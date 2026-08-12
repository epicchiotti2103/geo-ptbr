#!/usr/bin/env python3
"""aggregate.py — Fase 4 (Análise) do GEO-PTBR.

Lê eval/traces/*.jsonl e gera as tabelas obrigatórias da Fase 4 em results/
(.md + .csv correspondente para importação no LaTeX na Fase 5) e FINDINGS.md.

Uso:
    python src/aggregate.py                          # gera tudo
    python src/aggregate.py --only tabela_principal
    python src/aggregate.py --only tabela_principal,quebra_por_setor
    python src/aggregate.py --traces-dir eval/traces --out-dir results

Saídas (em --out-dir):
    tabela_principal.md/.csv      — Imp_pwc/Imp_wc da fonte-alvo, baseline vs
                                     técnica, com IC95% bootstrap e melhoria
                                     relativa (média E mediana, Eq. 4).
    quebra_por_setor.md/.csv      — idem, separado por saude/juridico/imobiliario.
    quebra_por_posicao.md/.csv    — idem, separado por posição 1..5 da fonte-alvo,
                                     com a Tabela 2 do paper original ao lado.
    tabela_custo.md/.csv          — tokens e US$ por técnica (dos traces reais).
    inducao_pegadinhas.md/.csv    — Imp_wc/Imp_pwc TOTAL nas pegadinhas, por técnica.
    comparacao_paper.md/.csv      — direção de efeito + correlação de Spearman
                                     vs a Tabela 1 do paper (paper/KEY_FACTS.md).
    FINDINGS.md                   — 5 achados, gerados por template a partir dos
                                     números acima (nunca texto fixo inventado).

DECISÕES DE IMPLEMENTAÇÃO (ver resposta final da tarefa para o detalhe completo):
  - Nenhuma biblioteca nova. scipy não está em requirements.txt: Spearman e
    bootstrap são implementados manualmente (stdlib: random, statistics, math).
    pandas está listado em requirements.txt mas NÃO está instalado no .venv
    deste projeto no momento em que este script foi escrito — para não quebrar
    a própria validação, este script também evita pandas e usa só stdlib
    (csv, json, yaml — yaml já é dependência usada por run_case.py/run_eval.py).
  - Bootstrap por query (não por rep): para cada (técnica, métrica, subconjunto),
    primeiro agregamos por query (média das reps daquela query), DEPOIS
    reamostramos entre queries (10.000 reamostragens, semente fixa) — evita
    pseudo-replicação das 3 reps. Uma única reamostragem por iteração alimenta
    as 4 estatísticas (baseline, técnica, melhoria média, melhoria mediana) —
    pareado, para não descompassar as listas quando há queries com baseline=0
    (Eq. 4 indefinida).
  - Custo: somado diretamente de custo_usd/input_tokens/output_tokens já
    gravados nos traces (não recalculado via config/prices.yaml) — os traces
    são o registro de verdade do que foi de fato gasto/gerado. NOTA: detectamos
    que eval/run_eval.py::_custo_section usa a chave fixa
    prices["modelos"]["gemini-2.5-flash"] para extrapolar custo, mas o
    model_version real nos traces do piloto é "gemini-3.5-flash-lite" — parece
    um bug latente naquele arquivo. Não alteramos eval/run_eval.py (regra da
    tarefa); reportado à parte na resposta final.
  - **Dois conjuntos de queries, sempre lado a lado** (coluna `conjunto`), na
    mesma convenção de src/compare_engines.py:
        `baseline_pos` (PRIMÁRIO) — só queries cujo baseline da fonte-alvo é
                        > 0 naquele engine, para aquela métrica.
        `todas`        (sensibilidade) — todas as queries normais.
    Motivo, medido e não suposto: `metrics.relative_improvement(0, 0)` retorna
    **0.0**, não None (só `antes=0 & depois>0` é indefinido). Então toda query
    em que a fonte-alvo não foi citada nem no baseline nem sob a técnica entra
    na distribuição como "0% de mudança". No claude-haiku-4-5 isso é 5–12% das
    queries por técnica (contra ~1% no gemini-3.5-flash-lite), o bastante para
    **pregar a mediana em exatamente 0** e fazer um efeito negativo real
    parecer ausência de efeito. Não é um número errado — é um número que
    responde a outra pergunta ("a fonte foi citada?"), misturado com a pergunta
    da Eq. 4 ("quanto mudou a citação?"). Sem esta separação, `tabela_principal`
    sobre os traces do haiku diria "sem efeito" onde há efeito forte.
    NOME: aqui o conjunto completo se chama `todas`, não `pareado` como no
    compare_engines.py — lá o pareamento entre engines é parte da definição, e
    neste script (um engine por vez) não há pareamento nenhum. A definição de
    `baseline_pos` é a MESMA nos dois, menos a interseção entre engines: aqui
    basta baseline > 0 no engine analisado. Implementação: filtrar os pares por
    `baseline > 0` é exatamente equivalente a `compare_engines.
    qids_baseline_positivo` restrito a um engine (os dois usam
    `_baseline_query_mean`), e aplica-se de graça aos subconjuntos (setor,
    posição).
    NÃO se aplica a `tabela_custo` (não tem baseline) nem a
    `inducao_pegadinhas` (baseline ~0 por desenho — o filtro esvaziaria a
    tabela, e a pergunta lá é justamente "citou o que não devia"): as duas
    declaram isso no cabeçalho em vez de omitir a coluna em silêncio.
  - Traces mock (model_version == "mock") são excluídos de toda a análise —
    não são resultado científico (regra 4 do TASK.md).
  - Constantes do paper original (Tabela 1 e Tabela 2) são copiadas literalmente
    de paper/KEY_FACTS.md §3.1 e §3.3, com a citação ao lado da constante no
    código — nunca recalculadas ou aproximadas.
  - CSVs carregam linhas de cabeçalho comentadas com "#" antes da linha de
    colunas (versão do experimento, model_version(s), n de queries, data de
    geração) — pandas.read_csv(..., comment="#") ou qualquer parser que ignore
    linhas "#" as pula; a linha de nomes de coluna usa as CHAVES internas
    (snake_case, estáveis), não os rótulos em português das tabelas .md.
"""
import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import yaml

import metrics  # reusa relative_improvement (Eq. 4) e METRICS_VERSION — não duplica

ROOT = _SRC_DIR.parent
DEFAULT_TRACES_DIR = ROOT / "eval" / "traces"
DEFAULT_OUT_DIR = ROOT / "results"

N_BOOT = 10000
BOOTSTRAP_SEED = 42          # semente fixa (regra da tarefa)
ALPHA = 0.05                 # IC 95%
MIN_BOOT_EFFETIVO = 100      # abaixo disso, IC da melhoria (%) é "n insuficiente"
                              # (pode acontecer quando quase todas as queries do
                              # subconjunto têm baseline=0 — a maioria das
                              # reamostragens fica sem nenhum valor de melhoria
                              # definido)

METRICAS = ("pwc", "wc")

SETORES = ("saude", "juridico", "imobiliario")

# Conjuntos de queries emitidos lado a lado em toda tabela que usa a Eq. 4.
# Ordem = ordem nas tabelas: o primário vem primeiro, para quem lê de cima.
# Ver o bloco "Dois conjuntos de queries" no docstring do módulo.
CONJUNTO_PRIMARIO = "baseline_pos"
CONJUNTOS = (CONJUNTO_PRIMARIO, "todas")

ALL_SECOES = [
    "tabela_principal",
    "quebra_por_setor",
    "quebra_por_posicao",
    "tabela_custo",
    "inducao_pegadinhas",
    "comparacao_paper",
    "findings",
]

# ---------------------------------------------------------------------------
# Constantes do paper original — copiadas literalmente de paper/KEY_FACTS.md.
# Nunca recalculadas: mudar aqui só é permitido se a fonte (KEY_FACTS.md) mudar.
# ---------------------------------------------------------------------------

# KEY_FACTS.md §3.1 — Tabela 1 (p.7), PAWC-Overall, engine gpt3.5-turbo, GEO-bench
# test split completo (escala arbitrária normalizada do paper, NÃO comparável em
# valor absoluto com nossos números — só direção/ordenação, ver §6 do KEY_FACTS).
PAPER_TABELA1_PAWC_OVERALL = {
    "baseline": 19.3,
    "keyword_stuffing": 17.7,
    "unique_words": 20.5,
    "easy_to_understand": 22.0,
    "authoritative": 21.3,
    "technical_terms": 22.7,
    "fluency_optimization": 24.7,
    "cite_sources": 24.6,
    "quotation_addition": 27.2,
    "statistics_addition": 25.2,
}

# KEY_FACTS.md §3.3 — Tabela 2 (p.8), % de melhoria relativa por posição (rank)
# da fonte no SERP, rank-1..rank-5. Só 5 das 9 técnicas aparecem nessa tabela do
# paper original; as outras 4 são marcadas "não comparável" na quebra_por_posicao.
PAPER_TABELA2_POR_POSICAO = {
    "authoritative": [-6.0, 4.1, -0.6, 12.6, 6.1],
    "fluency_optimization": [-2.0, 5.2, 3.6, -4.4, 2.2],
    "cite_sources": [-30.3, 2.5, 20.4, 15.5, 115.1],
    "quotation_addition": [-22.9, -7.0, 3.5, 25.1, 99.7],
    "statistics_addition": [-20.6, -3.9, 8.1, 10.0, 97.9],
}


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

def load_study_config():
    with open(ROOT / "config" / "study.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_queries_meta():
    """{query_id: {"setor":..., "tipo":...}} de data/queries.jsonl."""
    path = ROOT / "data" / "queries.jsonl"
    meta = {}
    if not path.exists():
        return meta
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta[rec.get("id")] = {"setor": rec.get("setor"), "tipo": rec.get("tipo")}
    return meta


def load_traces(traces_dir):
    """Carrega todos os *.jsonl de traces_dir. Linha corrompida: loga, pula,
    contabiliza (regra 8 do TASK.md). Registros mock são excluídos (não são
    resultado científico — regra 4)."""
    traces_dir = Path(traces_dir)
    records = []
    n_corrompidas = 0
    n_mock = 0
    if not traces_dir.exists():
        print(f"[aggregate] AVISO: traces-dir não existe: {traces_dir}")
        return records
    for path in sorted(traces_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    n_corrompidas += 1
                    continue
                if rec.get("model_version") == "mock":
                    n_mock += 1
                    continue
                records.append(rec)
    if n_corrompidas:
        print(f"[aggregate] {n_corrompidas} linha(s) de trace corrompida(s), ignorada(s)")
    if n_mock:
        print(f"[aggregate] {n_mock} registro(s) mock excluído(s) (MOCK_LLM=1 — não é resultado científico)")
    return records


def group_by_query(records):
    by_query = defaultdict(list)
    for r in records:
        by_query[r["query_id"]].append(r)
    return dict(by_query)


# ---------------------------------------------------------------------------
# Estatística: agregação por query, bootstrap pareado, Spearman manual
# ---------------------------------------------------------------------------

def _metric_val(rec, metrica, pos):
    m = rec.get("metricas")
    if not m:
        return None
    return m.get(metrica, {}).get(str(pos))


def _baseline_query_mean(recs, metrica):
    """Média (entre reps) do valor da métrica na posição-alvo, fase baseline.
    Retorna (media, target_pos) ou (None, None)."""
    b = [r for r in recs if r.get("fase") == "baseline"]
    if not b:
        return None, None
    pos = b[0].get("target_pos")
    vals = [v for v in (_metric_val(r, metrica, pos) for r in b) if v is not None]
    if not vals:
        return None, pos
    return statistics.fmean(vals), pos


def _tecnica_query_mean(recs, tecnica, metrica, pos):
    t = [r for r in recs if r.get("fase") == "tecnica" and r.get("tecnica") == tecnica]
    if not t:
        return None
    vals = [v for v in (_metric_val(r, metrica, pos) for r in t) if v is not None]
    if not vals:
        return None
    return statistics.fmean(vals)


def collect_pairs(by_query, queries_meta, tecnica, metrica, setor=None, target_pos=None,
                   apenas_pegadinha=False):
    """Lista de (query_id, baseline_mean_q, tecnica_mean_q) — 1 valor por query
    já agregado sobre as reps (agregação por query primeiro, regra da tarefa)."""
    pairs = []
    for qid, recs in by_query.items():
        meta = queries_meta.get(qid, {})
        tipo = meta.get("tipo")
        if apenas_pegadinha:
            if tipo != "pegadinha":
                continue
        else:
            if tipo == "pegadinha":
                continue
        if setor is not None and meta.get("setor") != setor:
            continue
        b_mean, pos = _baseline_query_mean(recs, metrica)
        if b_mean is None:
            continue
        if target_pos is not None and pos != target_pos:
            continue
        t_mean = _tecnica_query_mean(recs, tecnica, metrica, pos)
        if t_mean is None:
            continue
        pairs.append((qid, b_mean, t_mean))
    return pairs


def aplica_conjunto(pairs, conjunto):
    """Recorta a lista de pares (query_id, baseline, tecnica) para o conjunto
    pedido. `baseline_pos` mantém só queries com baseline > 0 — ver o bloco
    "Dois conjuntos de queries" no docstring do módulo. Como a Eq. 4 é definida
    para todo baseline > 0, as linhas de `baseline_pos` têm, por construção,
    n_baseline_zero = 0 E n_indefinido = 0 (invariante checada em
    compute_cell)."""
    if conjunto == "baseline_pos":
        return [p for p in pairs if p[1] > 0]
    if conjunto == "todas":
        return list(pairs)
    raise ValueError(f"conjunto desconhecido: {conjunto!r} (válidos: {CONJUNTOS})")


def conta_baseline_pos(by_query, queries_meta, metrica):
    """(n_normais_com_baseline, n_com_baseline_pos) para o cabeçalho: quantas
    queries o conjunto primário descarta e por quê. Só queries normais —
    pegadinha nunca entra na Eq. 4 (tem tabela própria)."""
    n_total = n_pos = 0
    for qid, recs in by_query.items():
        if queries_meta.get(qid, {}).get("tipo") == "pegadinha":
            continue
        b_mean, _pos = _baseline_query_mean(recs, metrica)
        if b_mean is None:
            continue
        n_total += 1
        if b_mean > 0:
            n_pos += 1
    return n_total, n_pos


def _percentile_ci(vals, alpha=ALPHA):
    """IC (1-alpha) por percentil sobre uma distribuição bootstrap já
    calculada. Convenção fixa: índices floor(alpha/2 * n) e
    floor((1-alpha/2) * n) - 1 sobre a lista ordenada."""
    if not vals:
        return (None, None)
    s = sorted(vals)
    n = len(s)
    lo_idx = max(0, min(int(alpha / 2 * n), n - 1))
    hi_idx = max(0, min(int((1 - alpha / 2) * n) - 1, n - 1))
    return (s[lo_idx], s[hi_idx])


def compute_cell(pairs, n_boot=N_BOOT, seed=BOOTSTRAP_SEED):
    """Bootstrap por query, pareado: cada reamostragem sorteia queries (com
    reposição) e calcula, DA MESMA reamostragem, a média baseline, a média
    técnica, a melhoria média e a melhoria mediana (Eq. 4 sobre as queries com
    baseline>0 daquela reamostragem). Evita descompasso entre as séries."""
    n = len(pairs)
    if n == 0:
        return {"n_queries": 0}

    baseline_vals = [p[1] for p in pairs]
    tecnica_vals = [p[2] for p in pairs]
    melhorias = []
    n_baseline_zero = 0
    n_indefinido = 0
    for _, b, t in pairs:
        if b == 0:
            n_baseline_zero += 1
        m = metrics.relative_improvement(t, b)
        if m is None:
            n_indefinido += 1
        else:
            melhorias.append(m)

    result = {
        "n_queries": n,
        "n_baseline_zero": n_baseline_zero,
        "n_indefinido": n_indefinido,
        "baseline_mean": statistics.fmean(baseline_vals),
        "tecnica_mean": statistics.fmean(tecnica_vals),
        "melhoria_media_pct": statistics.fmean(melhorias) if melhorias else None,
        "melhoria_mediana_pct": statistics.median(melhorias) if melhorias else None,
    }

    if n < 2:
        result["baseline_ci"] = (None, None)
        result["tecnica_ci"] = (None, None)
        result["melhoria_media_ci"] = (None, None)
        result["melhoria_mediana_ci"] = (None, None)
        return result

    rng = random.Random(seed)
    boot_baseline, boot_tecnica = [], []
    boot_melhoria_media, boot_melhoria_mediana = [], []
    for _ in range(n_boot):
        sample = rng.choices(pairs, k=n)
        boot_baseline.append(statistics.fmean(p[1] for p in sample))
        boot_tecnica.append(statistics.fmean(p[2] for p in sample))
        m_s = []
        for _, b, t in sample:
            m = metrics.relative_improvement(t, b)
            if m is not None:
                m_s.append(m)
        if m_s:
            boot_melhoria_media.append(statistics.fmean(m_s))
            boot_melhoria_mediana.append(statistics.median(m_s))

    result["baseline_ci"] = _percentile_ci(boot_baseline)
    result["tecnica_ci"] = _percentile_ci(boot_tecnica)
    if len(boot_melhoria_media) >= MIN_BOOT_EFFETIVO:
        result["melhoria_media_ci"] = _percentile_ci(boot_melhoria_media)
        result["melhoria_mediana_ci"] = _percentile_ci(boot_melhoria_mediana)
    else:
        result["melhoria_media_ci"] = (None, None)
        result["melhoria_mediana_ci"] = (None, None)
    return result


def compute_cell_conjunto(pairs, conjunto, **kwargs):
    """compute_cell sobre o recorte do conjunto, com a invariante do
    `baseline_pos` verificada em vez de assumida: com baseline > 0 a Eq. 4 é
    sempre definida, então n_baseline_zero e n_indefinido TÊM de ser 0. Se não
    forem, o filtro não está fazendo o que se pensa e a tabela sairia com a
    mediana contaminada de novo — parar é melhor que publicar o número."""
    cell = compute_cell(aplica_conjunto(pairs, conjunto), **kwargs)
    if conjunto == "baseline_pos" and cell.get("n_queries", 0) > 0:
        if cell.get("n_baseline_zero") or cell.get("n_indefinido"):
            raise RuntimeError(
                "invariante do conjunto baseline_pos violada: "
                f"n_baseline_zero={cell.get('n_baseline_zero')}, "
                f"n_indefinido={cell.get('n_indefinido')} (esperado 0 e 0)"
            )
    return cell


def _sig_from_ci(ci):
    lo, hi = ci
    if lo is None or hi is None:
        return "n insuficiente"
    if lo > 0 and hi > 0:
        return "sim (efeito positivo)"
    if lo < 0 and hi < 0:
        return "sim (efeito negativo)"
    return "não (IC cruza zero)"


def _sign(v):
    if v is None:
        return None
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _ranks(seq):
    """Ranks médios (1-based), com empates recebendo o rank médio — método
    padrão para correlação de Spearman com empates."""
    order = sorted(range(len(seq)), key=lambda i: seq[i])
    ranks = [0.0] * len(seq)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and seq[order[j + 1]] == seq[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x, y):
    """Correlação de Spearman manual (Pearson sobre os ranks, com empates pelo
    rank médio) — scipy não está em requirements.txt."""
    n = len(x)
    if n < 2 or len(y) != n:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _cell_to_row(extra, cell):
    row = dict(extra)
    if cell.get("n_queries", 0) == 0:
        row.update({
            "n_queries": 0, "n_baseline_zero": None, "n_indefinido": None,
            "baseline_mean": None, "baseline_ci_lo": None, "baseline_ci_hi": None,
            "tecnica_mean": None, "tecnica_ci_lo": None, "tecnica_ci_hi": None,
            "melhoria_media_pct": None, "melhoria_media_ci_lo": None, "melhoria_media_ci_hi": None,
            "melhoria_mediana_pct": None, "melhoria_mediana_ci_lo": None, "melhoria_mediana_ci_hi": None,
            "sig_media": "n insuficiente", "sig_mediana": "n insuficiente",
        })
        return row
    b_lo, b_hi = cell["baseline_ci"]
    t_lo, t_hi = cell["tecnica_ci"]
    mm_lo, mm_hi = cell["melhoria_media_ci"]
    md_lo, md_hi = cell["melhoria_mediana_ci"]
    row.update({
        "n_queries": cell["n_queries"],
        "n_baseline_zero": cell["n_baseline_zero"],
        "n_indefinido": cell["n_indefinido"],
        "baseline_mean": cell["baseline_mean"], "baseline_ci_lo": b_lo, "baseline_ci_hi": b_hi,
        "tecnica_mean": cell["tecnica_mean"], "tecnica_ci_lo": t_lo, "tecnica_ci_hi": t_hi,
        "melhoria_media_pct": cell["melhoria_media_pct"],
        "melhoria_media_ci_lo": mm_lo, "melhoria_media_ci_hi": mm_hi,
        "melhoria_mediana_pct": cell["melhoria_mediana_pct"],
        "melhoria_mediana_ci_lo": md_lo, "melhoria_mediana_ci_hi": md_hi,
        "sig_media": _sig_from_ci((mm_lo, mm_hi)),
        "sig_mediana": _sig_from_ci((md_lo, md_hi)),
    })
    return row


COLS_PRINCIPAL_EXTRA = []  # preenchido por chamador (tecnica/metrica, ou +setor, ou +target_pos)

COLS_CELL = [
    ("n_queries", "n queries", "int"),
    ("n_baseline_zero", "baseline=0", "int"),
    ("n_indefinido", "melhoria indefinida (\"novo\")", "int"),
    ("baseline_mean", "baseline (média)", "float4"),
    ("baseline_ci_lo", "IC95 lo", "float4"),
    ("baseline_ci_hi", "IC95 hi", "float4"),
    ("tecnica_mean", "técnica (média)", "float4"),
    ("tecnica_ci_lo", "IC95 lo", "float4"),
    ("tecnica_ci_hi", "IC95 hi", "float4"),
    ("melhoria_media_pct", "melhoria média %", "pct"),
    ("melhoria_media_ci_lo", "IC95 lo %", "pct"),
    ("melhoria_media_ci_hi", "IC95 hi %", "pct"),
    ("melhoria_mediana_pct", "melhoria mediana %", "pct"),
    ("melhoria_mediana_ci_lo", "IC95 lo %", "pct"),
    ("melhoria_mediana_ci_hi", "IC95 hi %", "pct"),
    ("sig_media", "sig. (média)", "str"),
    ("sig_mediana", "sig. (mediana)", "str"),
]


# ---------------------------------------------------------------------------
# 1. tabela_principal
# ---------------------------------------------------------------------------

def build_tabela_principal(by_query, queries_meta, tecnicas):
    rows = []
    for tecnica in tecnicas:
        for metrica in METRICAS:
            pairs = collect_pairs(by_query, queries_meta, tecnica, metrica)
            for conjunto in CONJUNTOS:
                cell = compute_cell_conjunto(pairs, conjunto)
                rows.append(_cell_to_row(
                    {"conjunto": conjunto, "tecnica": tecnica, "metrica": metrica}, cell
                ))
    return rows


COLS_TABELA_PRINCIPAL = [
    ("conjunto", "conjunto", "str"),
    ("tecnica", "técnica", "str"),
    ("metrica", "métrica", "str"),
] + COLS_CELL


# ---------------------------------------------------------------------------
# 2. quebra_por_setor
# ---------------------------------------------------------------------------

def build_quebra_setor(by_query, queries_meta, tecnicas):
    rows = []
    for setor in SETORES:
        for tecnica in tecnicas:
            for metrica in METRICAS:
                pairs = collect_pairs(by_query, queries_meta, tecnica, metrica, setor=setor)
                for conjunto in CONJUNTOS:
                    cell = compute_cell_conjunto(pairs, conjunto)
                    rows.append(_cell_to_row(
                        {"conjunto": conjunto, "setor": setor,
                         "tecnica": tecnica, "metrica": metrica}, cell
                    ))
    return rows


COLS_QUEBRA_SETOR = [
    ("conjunto", "conjunto", "str"),
    ("setor", "setor", "str"),
    ("tecnica", "técnica", "str"),
    ("metrica", "métrica", "str"),
] + COLS_CELL


# ---------------------------------------------------------------------------
# 3. quebra_por_posicao (dobra como comparação com a Tabela 2 do paper)
# ---------------------------------------------------------------------------

def build_quebra_posicao(by_query, queries_meta, tecnicas):
    rows = []
    for pos in range(1, 6):
        for tecnica in tecnicas:
            for metrica in METRICAS:
                pairs = collect_pairs(by_query, queries_meta, tecnica, metrica, target_pos=pos)
                # As colunas do paper são atribuídas DENTRO do laço de conjunto:
                # a comparação de direção com a Tabela 2 tem de ser feita para os
                # dois conjuntos, senão metade das linhas sairia "não comparável"
                # por acidente de implementação, e não por falta de dado.
                for conjunto in CONJUNTOS:
                    cell = compute_cell_conjunto(pairs, conjunto)
                    row = _cell_to_row(
                        {"conjunto": conjunto, "target_pos": pos,
                         "tecnica": tecnica, "metrica": metrica}, cell
                    )
                    paper_vals = PAPER_TABELA2_POR_POSICAO.get(tecnica)
                    if metrica == "pwc" and paper_vals is not None:
                        paper_val = paper_vals[pos - 1]
                        row["paper_valor_pct"] = paper_val
                        nossa_mediana = row.get("melhoria_mediana_pct")
                        # Gate no IC (não no ponto): com n=1 o ponto existe mas o IC é
                        # (None, None) (compute_cell exige n>=2 p/ bootstrap) — usar o
                        # ponto aqui declararia uma "direção" testável a partir de 1
                        # única query, o mesmo defeito que motivou o IC bootstrap.
                        if row.get("melhoria_mediana_ci_lo") is None:
                            row["direcao_replica_pos"] = "n insuficiente"
                        else:
                            row["direcao_replica_pos"] = "sim" if _sign(nossa_mediana) == _sign(paper_val) else "não"
                    else:
                        row["paper_valor_pct"] = None
                        row["direcao_replica_pos"] = "não comparável"
                    rows.append(row)
    return rows


COLS_QUEBRA_POSICAO = (
    [("conjunto", "conjunto", "str"), ("target_pos", "posição", "int"),
     ("tecnica", "técnica", "str"), ("metrica", "métrica", "str")]
    + COLS_CELL
    + [("paper_valor_pct", "paper Tabela 2 (%)", "pct"), ("direcao_replica_pos", "direção replica?", "str")]
)


# ---------------------------------------------------------------------------
# 4. tabela_custo
# ---------------------------------------------------------------------------

def _agg_custo(recs):
    n = len(recs)
    if n == 0:
        return {"n": 0, "tok_in": None, "tok_out": None, "custo_total": 0.0, "custo_medio": None}
    tok_in = statistics.fmean(r.get("input_tokens", 0) or 0 for r in recs)
    tok_out = statistics.fmean(r.get("output_tokens", 0) or 0 for r in recs)
    custo_total = sum(r.get("custo_usd", 0) or 0 for r in recs)
    return {"n": n, "tok_in": tok_in, "tok_out": tok_out, "custo_total": custo_total, "custo_medio": custo_total / n}


def build_tabela_custo(records, tecnicas):
    rows = []
    total_geral = 0.0
    total_chamadas_engine = 0
    total_chamadas_transform = 0

    baseline_recs = [r for r in records if r.get("fase") == "baseline"]
    b = _agg_custo(baseline_recs)
    rows.append({
        "categoria": "baseline",
        "n_chamadas_engine": b["n"], "tokens_input_medio": b["tok_in"], "tokens_output_medio": b["tok_out"],
        "custo_usd_total_engine": b["custo_total"], "custo_usd_medio_chamada": b["custo_medio"],
        "n_chamadas_transform": 0, "tokens_input_medio_transform": None, "tokens_output_medio_transform": None,
        "custo_usd_total_transform": 0.0,
        "custo_usd_total": b["custo_total"],
    })
    total_geral += b["custo_total"]
    total_chamadas_engine += b["n"]

    for tecnica in tecnicas:
        eng_recs = [r for r in records if r.get("fase") == "tecnica" and r.get("tecnica") == tecnica]
        tr_recs = [r for r in records if r.get("fase") == "transform" and r.get("tecnica") == tecnica]
        e = _agg_custo(eng_recs)
        t = _agg_custo(tr_recs)
        custo_total_tecnica = e["custo_total"] + t["custo_total"]
        rows.append({
            "categoria": tecnica,
            "n_chamadas_engine": e["n"], "tokens_input_medio": e["tok_in"], "tokens_output_medio": e["tok_out"],
            "custo_usd_total_engine": e["custo_total"], "custo_usd_medio_chamada": e["custo_medio"],
            "n_chamadas_transform": t["n"], "tokens_input_medio_transform": t["tok_in"],
            "tokens_output_medio_transform": t["tok_out"], "custo_usd_total_transform": t["custo_total"],
            "custo_usd_total": custo_total_tecnica,
        })
        total_geral += custo_total_tecnica
        total_chamadas_engine += e["n"]
        total_chamadas_transform += t["n"]

    rows.append({
        "categoria": "TOTAL",
        "n_chamadas_engine": total_chamadas_engine, "tokens_input_medio": None, "tokens_output_medio": None,
        "custo_usd_total_engine": None, "custo_usd_medio_chamada": None,
        "n_chamadas_transform": total_chamadas_transform, "tokens_input_medio_transform": None,
        "tokens_output_medio_transform": None, "custo_usd_total_transform": None,
        "custo_usd_total": total_geral,
    })
    return rows


COLS_TABELA_CUSTO = [
    ("categoria", "categoria", "str"),
    ("n_chamadas_engine", "n chamadas engine", "int"),
    ("tokens_input_medio", "tokens in/chamada (média)", "float1"),
    ("tokens_output_medio", "tokens out/chamada (média)", "float1"),
    ("custo_usd_total_engine", "custo US$ engine (total)", "float6"),
    ("custo_usd_medio_chamada", "custo US$ / chamada engine", "float6"),
    ("n_chamadas_transform", "n chamadas transform", "int"),
    ("tokens_input_medio_transform", "tokens in transform (média)", "float1"),
    ("tokens_output_medio_transform", "tokens out transform (média)", "float1"),
    ("custo_usd_total_transform", "custo US$ transform (total)", "float6"),
    ("custo_usd_total", "custo US$ total (engine+transform)", "float6"),
]


# ---------------------------------------------------------------------------
# 5. inducao_pegadinhas
# ---------------------------------------------------------------------------

def _collect_pegadinha_pairs(by_query, queries_meta, tecnica, metrica):
    pairs = []
    for qid, recs in by_query.items():
        if queries_meta.get(qid, {}).get("tipo") != "pegadinha":
            continue
        b = [r for r in recs if r.get("fase") == "baseline"]
        t = [r for r in recs if r.get("fase") == "tecnica" and r.get("tecnica") == tecnica]
        if not b or not t:
            continue
        b_tot = [sum(r["metricas"][metrica].values()) for r in b if r.get("metricas")]
        t_tot = [sum(r["metricas"][metrica].values()) for r in t if r.get("metricas")]
        if not b_tot or not t_tot:
            continue
        pairs.append((qid, statistics.fmean(b_tot), statistics.fmean(t_tot)))
    return pairs


def _compute_pegadinha_cell(pairs, n_boot=N_BOOT, seed=BOOTSTRAP_SEED):
    n = len(pairs)
    if n == 0:
        return {"n_queries": 0}
    b_vals = [p[1] for p in pairs]
    t_vals = [p[2] for p in pairs]
    result = {
        "n_queries": n,
        "baseline_total_mean": statistics.fmean(b_vals),
        "tecnica_total_mean": statistics.fmean(t_vals),
        "delta_mean": statistics.fmean(t - b for _, b, t in pairs),
    }
    if n < 2:
        result["baseline_ci"] = (None, None)
        result["tecnica_ci"] = (None, None)
        result["delta_ci"] = (None, None)
        return result
    rng = random.Random(seed)
    boot_b, boot_t, boot_d = [], [], []
    for _ in range(n_boot):
        sample = rng.choices(pairs, k=n)
        boot_b.append(statistics.fmean(p[1] for p in sample))
        boot_t.append(statistics.fmean(p[2] for p in sample))
        boot_d.append(statistics.fmean(t - b for _, b, t in sample))
    result["baseline_ci"] = _percentile_ci(boot_b)
    result["tecnica_ci"] = _percentile_ci(boot_t)
    result["delta_ci"] = _percentile_ci(boot_d)
    return result


def _inducao_flag(cell):
    if cell.get("n_queries", 0) < 2:
        return "n insuficiente"
    lo, hi = cell["delta_ci"]
    if lo is None:
        return "n insuficiente"
    if lo > 0:
        return "sim (induz citação)"
    if hi < 0:
        return "não (reduz citação — inesperado)"
    return "não distinguível de zero"


def build_inducao_pegadinhas(by_query, queries_meta, tecnicas):
    rows = []
    for tecnica in tecnicas:
        for metrica in METRICAS:
            pairs = _collect_pegadinha_pairs(by_query, queries_meta, tecnica, metrica)
            cell = _compute_pegadinha_cell(pairs)
            if cell.get("n_queries", 0) == 0:
                rows.append({
                    "tecnica": tecnica, "metrica": metrica, "n_pegadinhas": 0,
                    "baseline_total_mean": None, "baseline_ci_lo": None, "baseline_ci_hi": None,
                    "tecnica_total_mean": None, "tecnica_ci_lo": None, "tecnica_ci_hi": None,
                    "delta_mean": None, "delta_ci_lo": None, "delta_ci_hi": None,
                    "inducao": "n insuficiente",
                })
                continue
            b_lo, b_hi = cell["baseline_ci"]
            t_lo, t_hi = cell["tecnica_ci"]
            d_lo, d_hi = cell["delta_ci"]
            rows.append({
                "tecnica": tecnica, "metrica": metrica, "n_pegadinhas": cell["n_queries"],
                "baseline_total_mean": cell["baseline_total_mean"], "baseline_ci_lo": b_lo, "baseline_ci_hi": b_hi,
                "tecnica_total_mean": cell["tecnica_total_mean"], "tecnica_ci_lo": t_lo, "tecnica_ci_hi": t_hi,
                "delta_mean": cell["delta_mean"], "delta_ci_lo": d_lo, "delta_ci_hi": d_hi,
                "inducao": _inducao_flag(cell),
            })
    return rows


COLS_INDUCAO = [
    ("tecnica", "técnica", "str"), ("metrica", "métrica", "str"),
    ("n_pegadinhas", "n pegadinhas", "int"),
    ("baseline_total_mean", "baseline Imp total (média)", "float4"),
    ("baseline_ci_lo", "IC95 lo", "float4"), ("baseline_ci_hi", "IC95 hi", "float4"),
    ("tecnica_total_mean", "técnica Imp total (média)", "float4"),
    ("tecnica_ci_lo", "IC95 lo", "float4"), ("tecnica_ci_hi", "IC95 hi", "float4"),
    ("delta_mean", "delta (técnica - baseline)", "float4"),
    ("delta_ci_lo", "IC95 lo", "float4"), ("delta_ci_hi", "IC95 hi", "float4"),
    ("inducao", "induz citação?", "str"),
]


# ---------------------------------------------------------------------------
# 6. comparacao_paper
# ---------------------------------------------------------------------------

def build_comparacao_paper(tabela_principal_rows, tecnicas):
    """Retorna (rows, summaries) — summaries[conjunto] = {...}.

    Roda para os DOIS conjuntos: o ρ de Spearman é calculado sobre as 9 medianas
    por técnica, e é exatamente o número que mais muda com o `baseline_pos` —
    tirar as queries de baseline zero desprega as medianas do 0.0 e desfaz
    empates que estavam recebendo rank médio. Reportar os dois lado a lado
    deixa a correção visível em vez de substituir o número em silêncio."""
    baseline_paper = PAPER_TABELA1_PAWC_OVERALL["baseline"]
    rows, summaries = [], {}

    for conjunto in CONJUNTOS:
        pwc_rows = {
            r["tecnica"]: r for r in tabela_principal_rows
            if r["metrica"] == "pwc" and r["conjunto"] == conjunto
        }
        paper_para_mediana, nossos_mediana = [], []
        paper_para_media, nossos_media = [], []
        n_sim = n_nao = n_naomedido = 0

        for tecnica in tecnicas:
            paper_val = PAPER_TABELA1_PAWC_OVERALL.get(tecnica)
            paper_delta_pct = (paper_val - baseline_paper) / baseline_paper * 100 if paper_val is not None else None
            paper_sign = _sign(paper_delta_pct)

            our = pwc_rows.get(tecnica, {})
            our_mediana = our.get("melhoria_mediana_pct")
            our_media = our.get("melhoria_media_pct")
            our_sign = _sign(our_mediana)

            if our_sign is None or paper_sign is None:
                direcao = "não medido"
                n_naomedido += 1
            elif our_sign == paper_sign:
                direcao = "sim"
                n_sim += 1
            else:
                direcao = "não"
                n_nao += 1

            rows.append({
                "conjunto": conjunto,
                "tecnica": tecnica,
                "paper_pawc_overall": paper_val,
                "paper_delta_pct": paper_delta_pct,
                "nosso_melhoria_mediana_pct": our_mediana,
                "nosso_melhoria_mediana_ci_lo": our.get("melhoria_mediana_ci_lo"),
                "nosso_melhoria_mediana_ci_hi": our.get("melhoria_mediana_ci_hi"),
                "nosso_melhoria_media_pct": our_media,
                "nosso_n_queries": our.get("n_queries", 0),
                "sig_mediana": our.get("sig_mediana", "n insuficiente"),
                "direcao_replica": direcao,
            })

            if our_mediana is not None and paper_val is not None:
                paper_para_mediana.append(paper_val)
                nossos_mediana.append(our_mediana)
            if our_media is not None and paper_val is not None:
                paper_para_media.append(paper_val)
                nossos_media.append(our_media)

        summaries[conjunto] = {
            "rho_spearman_mediana": spearman(paper_para_mediana, nossos_mediana),
            "n_tecnicas_corr_mediana": len(nossos_mediana),
            "rho_spearman_media": spearman(paper_para_media, nossos_media),
            "n_tecnicas_corr_media": len(nossos_media),
            "n_direcao_sim": n_sim, "n_direcao_nao": n_nao, "n_direcao_naomedido": n_naomedido,
        }
    return rows, summaries


COLS_COMPARACAO_PAPER = [
    ("conjunto", "conjunto", "str"),
    ("tecnica", "técnica", "str"),
    ("paper_pawc_overall", "paper PAWC-Overall (Tab.1)", "float1"),
    ("paper_delta_pct", "paper delta vs baseline (%)", "pct"),
    ("nosso_melhoria_mediana_pct", "nosso melhoria mediana (%)", "pct"),
    ("nosso_melhoria_mediana_ci_lo", "IC95 lo %", "pct"),
    ("nosso_melhoria_mediana_ci_hi", "IC95 hi %", "pct"),
    ("nosso_melhoria_media_pct", "nosso melhoria média (%)", "pct"),
    ("nosso_n_queries", "n queries", "int"),
    ("sig_mediana", "sig. (mediana)", "str"),
    ("direcao_replica", "direção replica?", "str"),
]


# ---------------------------------------------------------------------------
# Escrita de tabelas (.md + .csv)
# ---------------------------------------------------------------------------

def _fmt_md(v, tipo):
    if v is None:
        return "n/d"
    if tipo == "int":
        return str(int(v))
    if tipo == "pct":
        return f"{v:+.1f}%"
    if tipo.startswith("float"):
        casas = int(tipo[5:]) if len(tipo) > 5 else 4
        return f"{v:.{casas}f}"
    return str(v)


def _val_csv(v, tipo):
    if v is None:
        return ""
    if tipo == "int":
        return int(v)
    if tipo == "str":
        return v
    return round(float(v), 6)


def emit_table(out_dir, name, title, header_lines, columns, rows, footer_lines=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{name}.md"
    csv_path = out_dir / f"{name}.csv"

    lines = [f"# {title}", ""]
    for hl in header_lines:
        lines.append(f"- {hl}")
    lines.append("")
    lines.append("| " + " | ".join(label for _, label, _ in columns) + " |")
    lines.append("|" + "|".join("---" for _ in columns) + "|")
    if not rows:
        lines.append("| " + " | ".join("_sem dados_" for _ in columns) + " |")
    for row in rows:
        cells = [_fmt_md(row.get(key), tipo) for key, _, tipo in columns]
        lines.append("| " + " | ".join(cells) + " |")
    if footer_lines:
        lines.append("")
        lines.extend(footer_lines)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        for hl in header_lines:
            f.write(f"# {hl}\n")
        writer = csv.writer(f)
        writer.writerow([key for key, _, _ in columns])
        for row in rows:
            writer.writerow([_val_csv(row.get(key), tipo) for key, _, tipo in columns])
        if footer_lines:
            for fl in footer_lines:
                f.write(f"# {fl}\n")

    return md_path, csv_path


def _header_base(records, by_query, extra=None):
    versoes_exp = sorted({r.get("versao_experimento") for r in records if r.get("versao_experimento")})
    model_versions = sorted({r.get("model_version") for r in records if r.get("model_version")})
    metrics_versions = sorted({r.get("metrics_version") for r in records if r.get("metrics_version")})
    n_total = len(by_query)
    gerado_em = datetime.now(timezone.utc).isoformat()
    lines = [
        f"versão do experimento: `{', '.join(versoes_exp) or 'n/d'}`",
        f"model_version(s) nos traces: `{', '.join(model_versions) or 'n/d'}`",
        f"metrics_version: `{', '.join(metrics_versions) or 'n/d'}`",
        f"n de queries nos traces carregados: {n_total}",
        f"gerado em (UTC): {gerado_em}",
    ]
    if len(model_versions) > 1:
        lines.append(
            "**ALERTA: mais de uma versão de modelo nos traces reais — pode misturar "
            "engines diferentes na mesma célula (regra da Fase 3, PROMPT_GEO_PTBR.md).**"
        )
    if extra:
        lines.extend(extra)
    return lines


# ---------------------------------------------------------------------------
# FINDINGS.md
# ---------------------------------------------------------------------------

def _fmt_pct_or_none(v):
    return f"{v:+.1f}%" if v is not None else "n/d"


# Abaixo deste n de queries por célula, um ponto estimado é só "indicativo" —
# achados setoriais/posicionais não afirmam direção com base nele. É uma
# escolha metodológica documentada aqui (não um valor extraído de dado nenhum).
N_MIN_INTERPRETAVEL = 5


def build_findings(tp_rows, qs_rows, qp_rows, ip_rows, cp_rows, cp_summaries):
    """Os achados leem SEMPRE o conjunto primário (`baseline_pos`). Misturar
    conjuntos aqui produziria um FINDINGS que troca de convenção entre achados
    sem dizer — por isso todo filtro por métrica leva junto o filtro por
    conjunto, e o texto declara qual conjunto está lendo.
    Exceção: `inducao_pegadinhas` (ip_rows) não tem conjunto — a Eq. 4 não é
    usada lá e o baseline é ~0 por desenho (ver docstring do módulo)."""
    partes = []

    # Achado 1 — melhor técnica. Só chama uma técnica de "melhor" se o IC95%
    # da mediana NÃO cruzar zero E for positivo — senão, o máximo é só o maior
    # PONTO estimado, e o texto precisa deixar isso explícito (não afirmar que
    # "funciona").
    pwc_tp = [
        r for r in tp_rows
        if r["metrica"] == "pwc" and r["conjunto"] == CONJUNTO_PRIMARIO
        and r["melhoria_mediana_pct"] is not None
    ]
    positivas_sig = [r for r in pwc_tp if r["sig_mediana"] == "sim (efeito positivo)"]
    if positivas_sig:
        melhor = max(positivas_sig, key=lambda r: r["melhoria_mediana_pct"])
        achado1 = (
            f"**1. Melhor técnica no conjunto atual (Imp_pwc, mediana da melhoria relativa, Eq. 4):** "
            f"**{melhor['tecnica']}**, {_fmt_pct_or_none(melhor['melhoria_mediana_pct'])} "
            f"(IC95% [{_fmt_pct_or_none(melhor['melhoria_mediana_ci_lo'])}, "
            f"{_fmt_pct_or_none(melhor['melhoria_mediana_ci_hi'])}], n={melhor['n_queries']} queries) — "
            "efeito distinguível de zero (positivo)."
        )
    elif pwc_tp:
        melhor = max(pwc_tp, key=lambda r: r["melhoria_mediana_pct"])
        achado1 = (
            "**1. Melhor técnica:** **nenhuma técnica teve efeito positivo distinguível de zero** no "
            "conjunto atual (todos os IC95% cruzam zero ou são negativos). A maior mediana PONTUAL foi "
            f"**{melhor['tecnica']}** ({_fmt_pct_or_none(melhor['melhoria_mediana_pct'])}, IC95% "
            f"[{_fmt_pct_or_none(melhor['melhoria_mediana_ci_lo'])}, "
            f"{_fmt_pct_or_none(melhor['melhoria_mediana_ci_hi'])}], n={melhor['n_queries']} queries) — "
            "não deve ser lida como \"a técnica funciona\", só como o maior valor observado."
        )
    else:
        achado1 = "**1. Melhor técnica:** não medido — n insuficiente em todas as técnicas do conjunto atual."
    partes.append(achado1)

    # Achado 2 — o que não funcionou (+ nota de indução de pegadinha)
    negativas = sorted([r for r in pwc_tp if r["melhoria_mediana_pct"] < 0], key=lambda r: r["melhoria_mediana_pct"])
    if pwc_tp:
        if negativas:
            piores = "; ".join(
                f"{r['tecnica']} ({_fmt_pct_or_none(r['melhoria_mediana_pct'])}, {r['sig_mediana']})"
                for r in negativas
            )
            achado2 = (
                f"**2. O que NÃO funcionou:** de {len(pwc_tp)} técnicas com dado suficiente, "
                f"{len(negativas)} tiveram melhoria mediana negativa: {piores}."
            )
        else:
            achado2 = (
                f"**2. O que NÃO funcionou:** nenhuma das {len(pwc_tp)} técnicas com dado suficiente "
                "mostrou melhoria mediana negativa no conjunto atual."
            )
    else:
        achado2 = "**2. O que NÃO funcionou:** não medido — n insuficiente."
    inducao_ativa = [r for r in ip_rows if r.get("metrica") == "pwc" and r.get("inducao") == "sim (induz citação)"]
    if inducao_ativa:
        nomes = ", ".join(r["tecnica"] for r in inducao_ativa)
        achado2 += (
            f" Nota adicional (sub-experimento de indução): {nomes} induziram o engine a citar fontes que, "
            "por desenho, não respondem à pergunta (queries-pegadinha) — ver inducao_pegadinhas."
        )
    partes.append(achado2)

    # Achado 3 — quebra setorial (YMYL). Um setor só é reportado com "melhor
    # técnica" se a maior mediana tiver n >= N_MIN_INTERPRETAVEL queries;
    # abaixo disso é ponto indicativo, não conclusão (evita manufaturar o
    # achado-alvo a partir de 2-3 queries).
    partes_setor = []
    algum_interpretavel = False
    for setor in SETORES:
        sub = [
            r for r in qs_rows
            if r["setor"] == setor and r["metrica"] == "pwc"
            and r["conjunto"] == CONJUNTO_PRIMARIO
            and r["melhoria_mediana_pct"] is not None
        ]
        if not sub:
            partes_setor.append(f"{setor}: n insuficiente")
            continue
        melhor_s = max(sub, key=lambda r: r["melhoria_mediana_pct"])
        if melhor_s["n_queries"] < N_MIN_INTERPRETAVEL:
            partes_setor.append(
                f"{setor}: n insuficiente para conclusão (maior n disponível={melhor_s['n_queries']} "
                f"< {N_MIN_INTERPRETAVEL}; ponto indicativo apenas: {melhor_s['tecnica']} "
                f"{_fmt_pct_or_none(melhor_s['melhoria_mediana_pct'])})"
            )
            continue
        algum_interpretavel = True
        partes_setor.append(
            f"{setor}: melhor técnica {melhor_s['tecnica']} "
            f"({_fmt_pct_or_none(melhor_s['melhoria_mediana_pct'])}, n={melhor_s['n_queries']}, {melhor_s['sig_mediana']})"
        )
    achado3 = "**3. Quebra por setor (achado-alvo: saúde é YMYL):** " + "; ".join(partes_setor) + "."
    if not algum_interpretavel:
        achado3 += (
            f" Com o volume atual de queries por setor (< {N_MIN_INTERPRETAVEL} por técnica em todos os "
            "setores), a comparação setorial não pode ser feita com confiança — n insuficiente. "
            "Aguardar a run completa (Fase 3, ~165 queries/setor)."
        )
    partes.append(achado3)

    # Achado 4 — posição vs Tabela 2 do paper (cite_sources). direcao_replica_pos
    # já é "n insuficiente" para qualquer posição com n<2 (IC não calculável) —
    # ver build_quebra_posicao — então a contagem abaixo é honesta.
    cs_pos = sorted(
        [r for r in qp_rows if r["tecnica"] == "cite_sources" and r["metrica"] == "pwc"
         and r["conjunto"] == CONJUNTO_PRIMARIO],
        key=lambda r: r["target_pos"],
    )
    if cs_pos:
        linhas_pos = []
        for r in cs_pos:
            nosso = _fmt_pct_or_none(r["melhoria_mediana_pct"]) if r["melhoria_mediana_pct"] is not None else "n insuficiente"
            paper_v = f"{r['paper_valor_pct']:+.1f}%" if r.get("paper_valor_pct") is not None else "n/d"
            linhas_pos.append(f"rank-{r['target_pos']}: nosso={nosso} (n={r['n_queries']}) vs paper={paper_v}")
        n_sim_pos = sum(1 for r in cs_pos if r["direcao_replica_pos"] == "sim")
        n_nao_pos = sum(1 for r in cs_pos if r["direcao_replica_pos"] == "não")
        n_ins_pos = sum(1 for r in cs_pos if r["direcao_replica_pos"] not in ("sim", "não"))
        achado4 = (
            "**4. Efeito por posição — Cite Sources vs Tabela 2 do paper** "
            "(paper: rank-1 −30.3%, rank-5 +115.1%): " + "; ".join(linhas_pos) + ". "
            f"Direção replicada em {n_sim_pos}/5 posições, divergente em {n_nao_pos}/5, "
            f"não testável em {n_ins_pos}/5 (IC não calculável — n<2 — ou métrica não comparável)."
        )
        testaveis = [r for r in cs_pos if r["direcao_replica_pos"] in ("sim", "não")]
        if testaveis and min(r["n_queries"] for r in testaveis) < N_MIN_INTERPRETAVEL:
            achado4 += (
                f" Atenção: mesmo as posições \"testáveis\" têm n muito pequeno (mínimo "
                f"{min(r['n_queries'] for r in testaveis)} query/queries) — interpretar com cautela, "
                "não como confirmação do padrão do paper."
            )
    else:
        achado4 = "**4. Efeito por posição:** não medido — sem dados de cite_sources por posição no conjunto atual."
    partes.append(achado4)

    # Achado 5 — direção geral / Spearman vs paper. Reporta as DUAS correlações
    # (ranking por mediana e por média) — não escolhe uma: a divergência entre
    # elas é, em si, o achado sobre instabilidade da Eq. 4 com baseline pequeno
    # que motivou o piloto a pedir mediana além de média.
    cp_summary = cp_summaries[CONJUNTO_PRIMARIO]
    rho_med = cp_summary["rho_spearman_mediana"]
    rho_media = cp_summary["rho_spearman_media"]
    rho_med_str = f"{rho_med:+.3f}" if rho_med is not None else "não calculável"
    rho_media_str = f"{rho_media:+.3f}" if rho_media is not None else "não calculável"
    achado5 = (
        f"**5. Direção geral de replicação vs. o paper original (Tabela 1, PAWC-Overall):** "
        f"das 9 técnicas, {cp_summary['n_direcao_sim']} replicaram a direção do efeito (mesmo sinal "
        f"de melhoria/piora vs. baseline, usando a mediana), {cp_summary['n_direcao_nao']} divergiram, e "
        f"{cp_summary['n_direcao_naomedido']} não puderam ser medidas (n insuficiente). "
        f"Correlação de Spearman entre nosso ranking de técnicas e o ranking do paper: "
        f"rho (ranking por MEDIANA)={rho_med_str} (n={cp_summary['n_tecnicas_corr_mediana']}), "
        f"rho (ranking por MÉDIA)={rho_media_str} (n={cp_summary['n_tecnicas_corr_media']})."
    )
    if rho_med is not None and rho_media is not None and abs(rho_med - rho_media) > 0.2:
        achado5 += (
            " A diferença grande entre as duas correlações mostra que a ordenação das técnicas no "
            "conjunto atual NÃO é robusta à escolha de estatística (média vs. mediana) — reforça o "
            "alerta do piloto de que a melhoria média (Eq. 4) é instável com baseline pequeno; a mediana "
            "é a leitura mais confiável, e mesmo ela deve ser tratada com cautela dado o n atual."
        )
    partes.append(achado5)

    return partes


def write_findings(out_dir, header_lines, tp_rows, qs_rows, qp_rows, ip_rows, cp_rows, cp_summaries):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "FINDINGS.md"
    partes = build_findings(tp_rows, qs_rows, qp_rows, ip_rows, cp_rows, cp_summaries)

    lines = ["# FINDINGS — GEO-PTBR, Fase 4", ""]
    lines.extend(f"- {hl}" for hl in header_lines)
    lines.append("")
    lines.append(
        "Gerado por código a partir dos números de tabela_principal.csv, quebra_por_setor.csv, "
        "quebra_por_posicao.csv, inducao_pegadinhas.csv e comparacao_paper.csv — nenhum número "
        "abaixo foi digitado manualmente. Onde o dado é insuficiente, o achado diz isso "
        "explicitamente em vez de estimar um valor."
    )
    lines.append("")
    lines.append(
        f"**Conjunto de queries: `{CONJUNTO_PRIMARIO}` (primário)** — todos os achados abaixo "
        "leem só as queries em que a fonte-alvo foi citada no baseline. As queries de baseline "
        "zero entram na Eq. 4 como \"0% de mudança\" (`relative_improvement(0,0)` = 0.0) e "
        "pregam a mediana em zero; o conjunto `todas`, com elas, está nos .csv das tabelas como "
        "análise de sensibilidade — nunca como número principal. `inducao_pegadinhas` é a "
        "exceção: não usa a Eq. 4."
    )
    lines.append("")
    for p in partes:
        lines.append(p)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="all", help=f"lista separada por vírgula entre {ALL_SECOES}, ou 'all'")
    ap.add_argument("--traces-dir", default=str(DEFAULT_TRACES_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    secoes = set(ALL_SECOES) if args.only == "all" else {s.strip() for s in args.only.split(",") if s.strip()}
    desconhecidas = secoes - set(ALL_SECOES)
    if desconhecidas:
        ap.error(f"seção(ões) desconhecida(s): {sorted(desconhecidas)} — válidas: {ALL_SECOES}")

    study = load_study_config()
    tecnicas = list(study["tecnicas"])
    queries_meta = load_queries_meta()
    records = load_traces(args.traces_dir)
    by_query = group_by_query(records)

    n_normais = len({qid for qid in by_query if queries_meta.get(qid, {}).get("tipo") != "pegadinha"})
    n_pegadinhas = len(by_query) - n_normais
    extra_header = [
        f"queries normais: {n_normais} | queries-pegadinha: {n_pegadinhas}",
        f"traces-dir: `{args.traces_dir}`",
    ]
    # Quanto o conjunto primário descarta, por métrica — e por quê. Sem esta
    # linha o leitor vê dois n diferentes na mesma tabela sem explicação.
    for metrica in METRICAS:
        n_tot, n_pos = conta_baseline_pos(by_query, queries_meta, metrica)
        extra_header.append(
            f"conjunto `baseline_pos` [{metrica}]: {n_pos} queries normais com baseline > 0 "
            f"(de {n_tot} com baseline medido) — nas outras {n_tot - n_pos} a fonte-alvo não "
            "foi citada no baseline e a Eq. 4 vale 0 por convenção "
            "(relative_improvement(0,0)=0.0), o que puxa a mediana para zero"
        )
    header = _header_base(records, by_query, extra=extra_header)

    # Rodapé comum às tabelas que usam a Eq. 4 (não vai em tabela_custo nem em
    # inducao_pegadinhas — ver docstring do módulo).
    rodape_conjunto = [
        f"- **Conjunto primário: `{CONJUNTO_PRIMARIO}`.** As linhas `conjunto=todas` são "
        "análise de SENSIBILIDADE, não o número do paper: incluem queries cuja fonte-alvo não "
        "foi citada no baseline, que entram na Eq. 4 como \"0% de mudança\" e pregam a mediana "
        "em zero. Onde os dois conjuntos discordam, a diferença é sobre CITAR a fonte, não "
        "sobre o tamanho do efeito — ler as duas linhas juntas.",
        "- Mesma convenção de `src/compare_engines.py` (lá o conjunto completo se chama "
        "`pareado`, porque inclui o pareamento entre engines; aqui, um engine por vez, "
        "chama-se `todas`). A definição de `baseline_pos` é a mesma nos dois.",
        "- Nas linhas `conjunto=baseline_pos`, `baseline=0` e `melhoria indefinida` são 0 por "
        "construção (com baseline > 0 a Eq. 4 é sempre definida) — verificado em execução, "
        "não assumido.",
    ]

    out_dir = args.out_dir

    _cache = {}

    def get_tp():
        if "tp" not in _cache:
            _cache["tp"] = build_tabela_principal(by_query, queries_meta, tecnicas)
        return _cache["tp"]

    def get_qs():
        if "qs" not in _cache:
            _cache["qs"] = build_quebra_setor(by_query, queries_meta, tecnicas)
        return _cache["qs"]

    def get_qp():
        if "qp" not in _cache:
            _cache["qp"] = build_quebra_posicao(by_query, queries_meta, tecnicas)
        return _cache["qp"]

    def get_ip():
        if "ip" not in _cache:
            _cache["ip"] = build_inducao_pegadinhas(by_query, queries_meta, tecnicas)
        return _cache["ip"]

    def get_cp():
        if "cp" not in _cache:
            _cache["cp"] = build_comparacao_paper(get_tp(), tecnicas)
        return _cache["cp"]

    if "tabela_principal" in secoes:
        rows = get_tp()
        emit_table(
            out_dir, "tabela_principal",
            "Tabela principal — Imp_pwc / Imp_wc da fonte-alvo (baseline vs técnica)",
            header + ["queries-pegadinha EXCLUÍDAS (baseline~0 por desenho — ver inducao_pegadinhas)."],
            COLS_TABELA_PRINCIPAL, rows, footer_lines=rodape_conjunto,
        )
        print(f"[aggregate] tabela_principal: {len(rows)} linhas")

    if "quebra_por_setor" in secoes:
        rows = get_qs()
        emit_table(
            out_dir, "quebra_por_setor",
            "Quebra por setor — saúde (YMYL) / jurídico / imobiliário",
            header + ["queries-pegadinha EXCLUÍDAS."],
            COLS_QUEBRA_SETOR, rows, footer_lines=rodape_conjunto,
        )
        print(f"[aggregate] quebra_por_setor: {len(rows)} linhas")

    if "quebra_por_posicao" in secoes:
        rows = get_qp()
        emit_table(
            out_dir, "quebra_por_posicao",
            "Quebra por posição da fonte-alvo (1..5) — comparação com a Tabela 2 do paper original",
            header + [
                "queries-pegadinha EXCLUÍDAS.",
                "paper_valor_pct só existe para as 5 técnicas da Tabela 2 (paper/KEY_FACTS.md §3.3) "
                "e só na métrica pwc; nas demais linhas: \"não comparável\".",
            ],
            COLS_QUEBRA_POSICAO, rows, footer_lines=rodape_conjunto,
        )
        print(f"[aggregate] quebra_por_posicao: {len(rows)} linhas")

    if "tabela_custo" in secoes:
        rows = build_tabela_custo(records, tecnicas)
        emit_table(
            out_dir, "tabela_custo",
            "Tabela de custo — tokens e US$ por técnica (dos traces reais, custo já gravado por chamada)",
            header + [
                "SEM coluna `conjunto`: esta tabela não usa a Eq. 4 nem baseline de citação — "
                "soma tokens e US$ de TODAS as chamadas registradas (inclusive pegadinhas e "
                "transformações). O recorte `baseline_pos` não se aplica.",
            ],
            COLS_TABELA_CUSTO, rows,
        )
        print(f"[aggregate] tabela_custo: {len(rows)} linhas")

    if "inducao_pegadinhas" in secoes:
        rows = get_ip()
        emit_table(
            out_dir, "inducao_pegadinhas",
            "Indução de citação em pegadinhas — Imp_wc / Imp_pwc TOTAL (soma das 5 fontes) por técnica",
            header + [
                f"queries-pegadinha no conjunto: {n_pegadinhas}. Baseline deve ser ~0 por desenho.",
                "SEM coluna `conjunto`: aqui a métrica é o Imp TOTAL (delta absoluto), não a "
                "Eq. 4, e o baseline ser ~0 é justamente o desenho da pegadinha — filtrar por "
                "`baseline > 0` esvaziaria a tabela e apagaria a pergunta ('a técnica induziu "
                "citação onde não havia?'). O recorte `baseline_pos` não se aplica.",
            ],
            COLS_INDUCAO, rows,
        )
        print(f"[aggregate] inducao_pegadinhas: {len(rows)} linhas")

    if "comparacao_paper" in secoes:
        rows, summaries = get_cp()
        footer = []
        for conjunto in CONJUNTOS:
            summary = summaries[conjunto]
            rho_med = summary["rho_spearman_mediana"]
            rho_media = summary["rho_spearman_media"]
            footer.append(
                f"- [{conjunto}] Correlação de Spearman (nosso ranking por MEDIANA da melhoria "
                f"vs. paper PAWC-Overall): rho={rho_med:+.3f}" if rho_med is not None
                else f"- [{conjunto}] Correlação de Spearman (mediana): não calculável "
                     "(menos de 2 técnicas com dado suficiente)."
            )
            footer.append(
                f"- [{conjunto}] Correlação de Spearman (nosso ranking por MÉDIA da melhoria "
                f"vs. paper PAWC-Overall): rho={rho_media:+.3f}" if rho_media is not None
                else f"- [{conjunto}] Correlação de Spearman (média): não calculável "
                     "(menos de 2 técnicas com dado suficiente)."
            )
            footer.append(
                f"- [{conjunto}] n técnicas usadas na correlação: "
                f"mediana={summary['n_tecnicas_corr_mediana']}, média={summary['n_tecnicas_corr_media']}"
            )
            footer.append(
                f"- [{conjunto}] direção replica: sim={summary['n_direcao_sim']}, "
                f"não={summary['n_direcao_nao']}, não medido={summary['n_direcao_naomedido']}"
            )
        footer.extend(rodape_conjunto)
        footer.append(
            "- O ρ é calculado sobre as 9 medianas por técnica: no conjunto `todas`, medianas "
            "pregadas em 0.0 viram EMPATES e recebem rank médio, o que altera o ρ. A diferença "
            "de ρ entre os dois conjuntos é efeito do zero-injection, não instabilidade do "
            "método — por isso os dois vão reportados."
        )
        footer.append(
            "- Escalas diferem entre estudos (ver paper/KEY_FACTS.md §6) — comparar só direção/ordenação, "
            "nunca valor absoluto."
        )
        emit_table(
            out_dir, "comparacao_paper",
            "Comparação com o paper original — direção do efeito e correlação de Spearman (Tabela 1, PAWC-Overall)",
            header,
            COLS_COMPARACAO_PAPER, rows,
            footer_lines=footer,
        )
        print(f"[aggregate] comparacao_paper: {len(rows)} linhas")

    if "findings" in secoes:
        path = write_findings(out_dir, header, get_tp(), get_qs(), get_qp(), get_ip(), *get_cp())
        print(f"[aggregate] FINDINGS: {path}")

    print(f"[aggregate] concluído — seções: {sorted(secoes)} | out-dir: {out_dir}")


if __name__ == "__main__":
    main()
