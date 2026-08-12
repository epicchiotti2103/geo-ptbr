#!/usr/bin/env python3
"""Runner do piloto (e futuro runner geral) do estudo GEO-PTBR.

Uso:
    python eval/run_eval.py --pilot                     # as 10 queries do piloto
    python eval/run_eval.py --pilot --limit 2            # corta p/ as N primeiras
    python eval/run_eval.py --queries s001,j002           # ids específicos

Chama src/run_case.run_case para cada query. Em QuotaExhausted: salva o parcial
(os traces já gravados por run_case não são perdidos), imprime "PAUSADO POR
QUOTA — retomar rodando o mesmo comando" e sai limpo com código 0 — a
resumabilidade do run_case garante a retomada no dia seguinte.

Ao final (ou no que tiver): gera results/pilot_<YYYYMMDD_HHMM>.md com a tabela
por técnica, o check de pegadinhas, o desvio entre reps e a projeção de custo
para a run completa (500 queries × 9 técnicas × 3 reps).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import argparse
import json
from datetime import datetime, timezone

import yaml

import build_scenario  # noqa: F401  (garante que src/ está no path e importável)
import llm
import metrics
import run_case

PILOT_QUERIES = ["s001", "s002", "s003", "j001", "j002", "j003", "i001", "i002", "p001", "p010"]
RESULTS_DIR = ROOT / "results"


def _load_prices():
    with open(ROOT / "config" / "prices.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_tipos_queries():
    """{query_id: tipo} de data/queries.jsonl (para achar as pegadinhas)."""
    tipos = {}
    path = ROOT / "data" / "queries.jsonl"
    if not path.exists():
        return tipos
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tipos[rec.get("id")] = rec.get("tipo")
    return tipos


def _load_traces(query_ids, out_dir):
    out_dir = Path(out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    records = []
    for qid in query_ids:
        path = out_dir / f"{qid}.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # regra 8: linha corrompida não derruba a run
    return records


def _mean_std(vals):
    n = len(vals)
    if n == 0:
        return None, None
    mean = sum(vals) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return mean, var ** 0.5


def _pwc_for(rec, pos):
    m = rec.get("metricas")
    if not m:
        return None
    return m.get("pwc", {}).get(str(pos))


def _group_by_query(records):
    by_query = {}
    for r in records:
        by_query.setdefault(r["query_id"], []).append(r)
    return by_query


def _tabela_tecnicas(by_query, tecnicas_ordem, tipos=None):
    """(1) Tabela por técnica: média±desvio do Imp_pwc da fonte-alvo no baseline
    vs com técnica (pooled sobre reps das queries onde ambos existem), e
    melhoria relativa média (Eq. 4, metrics.relative_improvement) — None
    ("indefinido, baseline=0") é reportado como "novo", não descartado nem
    forçado a número.

    EXCLUI queries-pegadinha (tipos[qid] == "pegadinha"): elas têm baseline ~0
    por desenho e contaminariam as médias. O comportamento delas sob técnica é
    reportado à parte por _pegadinhas_sob_tecnica (achado do piloto 2026-08-10:
    statistics_addition/keyword_stuffing induzem citação de fonte que não
    responde)."""
    tipos = tipos or {}
    linhas = []
    for tecnica in tecnicas_ordem:
        baseline_pool, tecnica_pool, melhorias = [], [], []
        n_novo = 0
        n_queries = 0
        for qid, recs in by_query.items():
            if tipos.get(qid) == "pegadinha":
                continue
            baseline_recs = [r for r in recs if r["fase"] == "baseline"]
            tecnica_recs = [r for r in recs if r["fase"] == "tecnica" and r["tecnica"] == tecnica]
            if not baseline_recs or not tecnica_recs:
                continue
            pos = baseline_recs[0]["target_pos"]
            b_vals = [v for v in (_pwc_for(r, pos) for r in baseline_recs) if v is not None]
            t_vals = [v for v in (_pwc_for(r, pos) for r in tecnica_recs) if v is not None]
            if not b_vals or not t_vals:
                continue
            n_queries += 1
            baseline_pool.extend(b_vals)
            tecnica_pool.extend(t_vals)
            b_mean_q = sum(b_vals) / len(b_vals)
            t_mean_q = sum(t_vals) / len(t_vals)
            melhoria = metrics.relative_improvement(t_mean_q, b_mean_q)
            if melhoria is None:
                n_novo += 1
            else:
                melhorias.append(melhoria)
        if n_queries == 0:
            continue
        b_mean, b_std = _mean_std(baseline_pool)
        t_mean, t_std = _mean_std(tecnica_pool)
        melhoria_media = sum(melhorias) / len(melhorias) if melhorias else None
        linhas.append({
            "tecnica": tecnica,
            "n_queries": n_queries,
            "baseline_mean": b_mean, "baseline_std": b_std,
            "tecnica_mean": t_mean, "tecnica_std": t_std,
            "melhoria_media_pct": melhoria_media,
            "n_novo": n_novo,
        })
    return linhas


def _check_pegadinhas(by_query, tipos):
    """Check OFICIAL de sanidade da medição: no BASELINE, pegadinhas devem ter
    visibilidade ~0 (fontes não respondem => engine não cita => medição que
    acusar citação está alucinando atribuição). Fases de técnica ficam de fora
    do check — indução de citação por técnica é achado, não bug de medição
    (ver _pegadinhas_sob_tecnica)."""
    vals = []
    n_pegadinhas = 0
    for qid, recs in by_query.items():
        if tipos.get(qid) != "pegadinha":
            continue
        n_pegadinhas += 1
        for r in recs:
            if r.get("fase") != "baseline":
                continue
            m = r.get("metricas")
            if not m:
                continue
            for v in m.get("pwc", {}).values():
                vals.append(v)
    if n_pegadinhas == 0:
        return {"n_pegadinhas": 0, "media": None, "status": "N/A — nenhuma pegadinha no conjunto executado"}
    media, _ = _mean_std(vals) if vals else (None, None)
    if media is None:
        return {"n_pegadinhas": n_pegadinhas, "media": None, "status": "N/A — sem métricas registradas"}
    status = "PASS" if media <= 0.05 else "FAIL"
    return {"n_pegadinhas": n_pegadinhas, "media": media, "status": status}


def _pegadinhas_sob_tecnica(by_query, tipos, tecnicas_ordem):
    """(2b) Sub-experimento de indução: para cada técnica, o Imp_pwc TOTAL
    (soma das 5 fontes) médio nas queries-pegadinha. >0 significa que a técnica
    fez o engine citar fontes que por desenho não respondem a pergunta —
    indução de alucinação de citação."""
    linhas = []
    for tecnica in tecnicas_ordem:
        vals = []
        n = 0
        for qid, recs in by_query.items():
            if tipos.get(qid) != "pegadinha":
                continue
            rs = [r for r in recs if r.get("fase") == "tecnica" and r.get("tecnica") == tecnica]
            if not rs:
                continue
            n += 1
            for r in rs:
                m = r.get("metricas")
                if m:
                    vals.append(sum(m.get("pwc", {}).values()))
        if n:
            media, std = _mean_std(vals)
            linhas.append({"tecnica": tecnica, "n_pegadinhas": n, "total_medio": media, "std": std})
    return linhas


def _desvio_reps(by_query):
    """(3) Desvio entre reps: média do desvio-padrão da fonte-alvo entre as
    reps de baseline, e entre as reps de cada técnica, ao longo das queries."""
    baseline_stds, tecnica_stds = [], []
    for qid, recs in by_query.items():
        baseline_recs = [r for r in recs if r["fase"] == "baseline"]
        if baseline_recs:
            pos = baseline_recs[0]["target_pos"]
            vals = [v for v in (_pwc_for(r, pos) for r in baseline_recs) if v is not None]
            if len(vals) >= 2:
                _, std = _mean_std(vals)
                baseline_stds.append(std)
        tecnicas_no_query = {r["tecnica"] for r in recs if r["fase"] == "tecnica"}
        for tecnica in tecnicas_no_query:
            trecs = [r for r in recs if r["fase"] == "tecnica" and r["tecnica"] == tecnica]
            if not trecs:
                continue
            pos = trecs[0]["target_pos"]
            vals = [v for v in (_pwc_for(r, pos) for r in trecs) if v is not None]
            if len(vals) >= 2:
                _, std = _mean_std(vals)
                tecnica_stds.append(std)
    return {
        "baseline_std_medio": sum(baseline_stds) / len(baseline_stds) if baseline_stds else None,
        "tecnica_std_medio": sum(tecnica_stds) / len(tecnica_stds) if tecnica_stds else None,
    }


def _custo_section(records, prices, study):
    total_piloto = sum(r.get("custo_usd", 0) or 0 for r in records)
    engine_records = [r for r in records if r["fase"] in ("baseline", "tecnica")]
    transform_records = [r for r in records if r["fase"] == "transform"]

    def _avg_tokens(recs):
        if not recs:
            return 0.0, 0.0
        it = sum(r.get("input_tokens", 0) or 0 for r in recs) / len(recs)
        ot = sum(r.get("output_tokens", 0) or 0 for r in recs) / len(recs)
        return it, ot

    avg_in_engine, avg_out_engine = _avg_tokens(engine_records)
    avg_in_transform, avg_out_transform = _avg_tokens(transform_records)

    # Preço do modelo REALMENTE usado nos traces (não hardcode: o engine mudou
    # de 2.5-flash -> 3.6-flash -> 3.5-flash-lite ao longo do projeto).
    modelos_traces = {r.get("model_version") for r in records if r.get("model_version")}
    modelos_traces.discard("mock")
    modelo_preco = next((m for m in sorted(modelos_traces) if m in prices["modelos"]), None)
    if modelo_preco is None:
        modelo_preco = study["engine"]["principal"]["modelo"]
    if modelo_preco not in prices["modelos"]:
        raise SystemExit(
            f"sem preço em config/prices.yaml para o modelo dos traces: {sorted(modelos_traces)}"
        )
    p = prices["modelos"][modelo_preco]
    desconto = p["batch_desconto"]
    custo_engine_call = (
        avg_in_engine / 1e6 * p["input_por_1m"] + avg_out_engine / 1e6 * p["output_por_1m"]
    ) * desconto
    custo_transform_call = (
        avg_in_transform / 1e6 * p["input_por_1m"] + avg_out_transform / 1e6 * p["output_por_1m"]
    ) * desconto

    n_queries_full = study["queries"]["total"]
    n_tecnicas_full = len(study["tecnicas"])
    reps_full = study["engine"]["principal"]["reps_por_celula"]

    # Fórmula literal do contrato: 500 queries × 9 técnicas × 3 reps de engine
    # + 500×9 transforms, com desconto batch.
    n_engine_calls_formula = n_queries_full * n_tecnicas_full * reps_full
    n_transform_calls = n_queries_full * n_tecnicas_full
    custo_formula = n_engine_calls_formula * custo_engine_call + n_transform_calls * custo_transform_call

    # Decisão de implementação: a fórmula do contrato não inclui as chamadas de
    # baseline (500 queries × 3 reps, feitas 1x por query, não por técnica).
    # Reportamos as duas: a fórmula literal (headline) e o total mais completo
    # incluindo baseline, e o PASS/FAIL é julgado contra o total mais completo
    # (mais conservador / mais realista).
    n_baseline_calls = n_queries_full * reps_full
    custo_com_baseline = custo_formula + n_baseline_calls * custo_engine_call

    teto = study["custo"]["teto_usd"]
    status = "PASS" if custo_com_baseline <= teto else "FAIL"

    return {
        "total_piloto": total_piloto,
        "avg_in_engine": avg_in_engine, "avg_out_engine": avg_out_engine,
        "avg_in_transform": avg_in_transform, "avg_out_transform": avg_out_transform,
        "custo_engine_call_batch": custo_engine_call,
        "custo_transform_call_batch": custo_transform_call,
        "n_engine_calls_formula": n_engine_calls_formula,
        "n_transform_calls": n_transform_calls,
        "n_baseline_calls": n_baseline_calls,
        "custo_extrapolado_formula": custo_formula,
        "custo_extrapolado_com_baseline": custo_com_baseline,
        "teto": teto,
        "status": status,
    }


def _fmt(v, casas=4, sufixo=""):
    if v is None:
        return "novo"
    return f"{v:.{casas}f}{sufixo}"


def _write_report(query_ids, out_dir, contains_mock):
    records = _load_traces(query_ids, out_dir)
    study = run_case.load_study_config()
    prices = _load_prices()
    tipos = _load_tipos_queries()
    by_query = _group_by_query(records)

    tecnicas_presentes = list(study["tecnicas"])
    tabela = _tabela_tecnicas(by_query, tecnicas_presentes, tipos)
    pegadinhas = _check_pegadinhas(by_query, tipos)
    inducao = _pegadinhas_sob_tecnica(by_query, tipos, tecnicas_presentes)
    reps_dev = _desvio_reps(by_query)
    custo = _custo_section(records, prices, study)

    versoes_exp = sorted({r.get("versao_experimento") for r in records if r.get("versao_experimento")})
    metrics_versions = sorted({r.get("metrics_version") for r in records if r.get("metrics_version")})
    prompts_versions = sorted({r.get("prompts_version") for r in records if r.get("prompts_version")})
    engine_prompt_versions = sorted({r.get("engine_prompt_version") for r in records if r.get("engine_prompt_version")})
    model_versions = sorted({r.get("model_version") for r in records if r.get("model_version")})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = RESULTS_DIR / f"pilot_{stamp}.md"

    lines = []
    lines.append(f"# Resultado do piloto GEO-PTBR — {stamp}")
    lines.append("")
    if contains_mock:
        lines.append(
            "> **ATENÇÃO: contém traces gerados em MOCK_LLM=1.** Os números abaixo "
            "validam o *pipeline* (harness ponta a ponta), não são resultado "
            "científico. Nenhum trace mock deve entrar no piloto real (regra 4 do "
            "TASK.md)."
        )
        lines.append("")
    lines.append(f"- versão do experimento: `{', '.join(versoes_exp) or 'n/d'}`")
    lines.append(f"- METRICS_VERSION: `{', '.join(metrics_versions) or 'n/d'}`")
    lines.append(f"- PROMPTS_VERSION (técnicas): `{', '.join(prompts_versions) or 'n/d'}`")
    lines.append(f"- ENGINE_PROMPT_VERSION (Listing 1 PT-BR): `{', '.join(engine_prompt_versions) or 'n/d'}`")
    lines.append(f"- model_version(s) observada(s) nos traces: `{', '.join(model_versions) or 'n/d'}`")
    if len(model_versions) > 1 and not contains_mock:
        lines.append(
            "  - **ALERTA**: mais de uma versão de modelo nos traces reais — "
            "isso contamina a comparação entre células (regra da Fase 3). Investigar."
        )
    lines.append(f"- queries no conjunto: {', '.join(query_ids)}")
    lines.append("")

    lines.append("## 1. Tabela por técnica — Imp_pwc da fonte-alvo (baseline vs técnica)")
    lines.append("")
    lines.append("_Somente queries normais (pegadinhas reportadas nas seções 2 e 2b)._")
    lines.append("")
    lines.append("| técnica | n queries | baseline (média±dp) | com técnica (média±dp) | melhoria relativa média (Eq. 4) | \"novo\" (baseline=0) |")
    lines.append("|---|---|---|---|---|---|")
    if not tabela:
        lines.append("| _sem dados (nenhuma célula baseline+técnica completa ainda)_ | | | | | |")
    for linha in tabela:
        base_str = f"{_fmt(linha['baseline_mean'])} ± {_fmt(linha['baseline_std'])}"
        tec_str = f"{_fmt(linha['tecnica_mean'])} ± {_fmt(linha['tecnica_std'])}"
        melhoria_str = _fmt(linha["melhoria_media_pct"], casas=1, sufixo="%") if linha["melhoria_media_pct"] is not None else "novo"
        lines.append(
            f"| {linha['tecnica']} | {linha['n_queries']} | {base_str} | {tec_str} | "
            f"{melhoria_str} | {linha['n_novo']} |"
        )
    lines.append("")

    lines.append("## 2. Check pegadinhas (esperado Imp ~0)")
    lines.append("")
    lines.append(f"- queries-pegadinha no conjunto executado: {pegadinhas['n_pegadinhas']}")
    if pegadinhas["media"] is not None:
        lines.append(f"- Imp_pwc médio (todas as fontes, todas as fases) nas pegadinhas: {pegadinhas['media']:.4f}")
    lines.append(f"- **status: {pegadinhas['status']}** (fail se média > 0.05; check restrito ao BASELINE)")
    lines.append("")

    lines.append("## 2b. Pegadinhas sob técnica — indução de citação (achado, não check)")
    lines.append("")
    lines.append("Imp_pwc TOTAL (soma das 5 fontes) nas pegadinhas após aplicar cada técnica.")
    lines.append("Valores > 0 = a técnica induziu o engine a citar fontes que não respondem.")
    lines.append("")
    lines.append("| técnica | n pegadinhas | Imp_pwc total (média±dp) |")
    lines.append("|---|---|---|")
    for linha in inducao:
        lines.append(
            f"| {linha['tecnica']} | {linha['n_pegadinhas']} | "
            f"{_fmt(linha['total_medio'])} ± {_fmt(linha['std'])} |"
        )
    if not inducao:
        lines.append("| _sem pegadinhas com fases de técnica no conjunto_ | | |")
    lines.append("")

    lines.append("## 3. Desvio entre reps (fonte-alvo)")
    lines.append("")
    b_std = reps_dev["baseline_std_medio"]
    t_std = reps_dev["tecnica_std_medio"]
    lines.append(f"- desvio-padrão médio entre reps — baseline: {_fmt(b_std) if b_std is not None else 'n/d'}")
    lines.append(f"- desvio-padrão médio entre reps — com técnica: {_fmt(t_std) if t_std is not None else 'n/d'}")
    lines.append("")

    lines.append("## 4. Custo")
    lines.append("")
    lines.append(f"- custo nominal total do piloto (traces carregados): US$ {custo['total_piloto']:.6f}")
    lines.append(
        f"- tokens médios/chamada de engine (baseline+técnica): "
        f"{custo['avg_in_engine']:.0f} in / {custo['avg_out_engine']:.0f} out"
    )
    lines.append(
        f"- tokens médios/chamada de transform: "
        f"{custo['avg_in_transform']:.0f} in / {custo['avg_out_transform']:.0f} out"
    )
    lines.append(
        f"- extrapolação (fórmula do contrato: {custo['n_engine_calls_formula']} chamadas de "
        f"engine + {custo['n_transform_calls']} transforms, batch −50%): "
        f"US$ {custo['custo_extrapolado_formula']:.4f}"
    )
    lines.append(
        f"- + baseline global (adicional, {custo['n_baseline_calls']} chamadas, não incluído na "
        f"fórmula literal do contrato mas contabilizado por completude): "
        f"total US$ {custo['custo_extrapolado_com_baseline']:.4f}"
    )
    lines.append(f"- teto (config/study.yaml): US$ {custo['teto']:.2f}")
    lines.append(f"- **status: {custo['status']}** (julgado contra o total com baseline incluída)")
    if contains_mock:
        lines.append(
            "- (mock: tokens/custo acima são sintéticos — a extrapolação é estrutural, "
            "não é uma projeção de custo real)"
        )
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", action="store_true", help="roda as 10 queries do piloto")
    ap.add_argument("--limit", type=int, default=None, help="corta para as N primeiras queries")
    ap.add_argument("--queries", default=None, help="ids específicos, separados por vírgula")
    ap.add_argument("--reps", type=int, default=None, help="default: engine.principal.reps_por_celula de study.yaml")
    ap.add_argument("--out-dir", default=run_case.DEFAULT_OUT_DIR)
    args = ap.parse_args()

    if args.queries:
        query_ids = [q.strip() for q in args.queries.split(",") if q.strip()]
    elif args.pilot:
        query_ids = list(PILOT_QUERIES)
    else:
        ap.error("especifique --pilot ou --queries id1,id2")
        return

    if args.limit:
        query_ids = query_ids[: args.limit]

    study = run_case.load_study_config()
    reps = args.reps or study["engine"]["principal"]["reps_por_celula"]

    total_novas, total_puladas = 0, 0
    quota_paused = False
    for qid in query_ids:
        print(f"=== {qid} ===")
        try:
            resumo = run_case.run_case(qid, reps=reps, out_dir=args.out_dir)
            total_novas += resumo["novas"]
            total_puladas += resumo["puladas"]
        except llm.QuotaExhausted as e:
            print("PAUSADO POR QUOTA — retomar rodando o mesmo comando")
            print(f"  detalhe: {e}")
            quota_paused = True
            break

    print(f"\ntotal — chamadas novas: {total_novas} | puladas: {total_puladas}")

    contains_mock = llm.env("MOCK_LLM") == "1"
    report_path = _write_report(query_ids, args.out_dir, contains_mock)
    print(f"relatório: {report_path}")

    if quota_paused:
        sys.exit(0)


if __name__ == "__main__":
    main()
