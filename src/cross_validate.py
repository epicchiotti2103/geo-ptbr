#!/usr/bin/env python3
"""Fase 3 — Validação cruzada GEO-PTBR: re-executa 50 queries (baseline + 9
técnicas, 3 reps) num SEGUNDO engine (claude-sonnet-5, API Anthropic direta)
para verificar se a DIREÇÃO do efeito por técnica se mantém entre engines.

ISOLAMENTO DA VARIÁVEL "ENGINE": os cenários (query + fontes originais) e os
TEXTOS JÁ TRANSFORMADOS pelo Gemini (eval/traces/<qid>.jsonl, fase="transform")
são reaproveitados tal como estão — a transformação NUNCA é refeita aqui, só a
etapa de resposta do engine muda (Gemini -> Claude). Isso é o que isola a
variável "engine" na comparação (regra 4 do TASK.md: nunca inventar resultado
de avaliação — resultado só existe com trace real).

Uso:
    python src/cross_validate.py --estimate                       # só estimativa de custo
    python src/cross_validate.py --run                            # roda (exige --confirm se estimativa > US$ 5)
    python src/cross_validate.py --run --confirm
    python src/cross_validate.py --report                         # só regenera o relatório dos traces existentes
    python src/cross_validate.py --run --limit 2                  # teste com só 2 queries
    python src/cross_validate.py --reselect --estimate            # força recalcular a seleção antes
    MOCK_LLM=1 python src/cross_validate.py --run --limit 2 --out-dir eval/traces_crossval_mocktest

SELEÇÃO DAS 50 QUERIES (results/cross_validation/queries_selecionadas.json):
determinística e estratificada por setor. Alvo por setor = alocação
proporcional (método dos maiores restos) sobre os "alvo" de setor de
config/study.yaml (167/167/166 de 500), escalados para 50 — dá exatamente
17/17/16 (saude/juridico/imobiliario), o número citado no contrato. Dentro de
cada setor: candidatos = queries tipo="normal" daquele setor com trace REAL
(não-mock) completo no Gemini (baseline x reps + transform x9 + técnica x9x
reps, eval/traces/); UM único random.Random("geo-ptbr-crossval") é usado,
consultado setor a setor em ordem alfabética (imobiliario, juridico, saude),
`.sample(candidatos_ordenados, k)` com k = min(alvo, candidatos disponíveis).
Se o pool de candidatos completos for menor que o alvo (caso atual: só 8
queries normais têm trace Gemini completo, versus as 500 do desenho final),
a seleção é gravada mesmo assim (para permitir teste/execução parcial) mas
marcada "completo": false e um aviso é impresso — NÃO deve ser tratada como
final até o Gemini ter rodado a run completa da Fase 3. Rode com --reselect
para recalcular depois que mais traces existirem (a seleção é puramente
determinística a partir do pool atual — sem estado escondido).

LEITURA DOS TEXTOS TRANSFORMADOS: sempre de eval/traces/<qid>.jsonl,
fase="transform", filtrando SOMENTE registros reais (model_version !=
"mock") — isso é INDEPENDENTE do modo (MOCK_LLM) da sessão atual deste
módulo, ao contrário de run_case._load_existing (que filtra pelo modo da
sessão atual). Se qualquer uma das 9 técnicas não tiver transform real no
Gemini, a query inteira é pulada e registrada em
results/cross_validation/queries_puladas.json — NUNCA se gera uma
transformação nova aqui.

CHAMADAS AO ENGINE: SDK `anthropic` (import tardio — o modo mock não depende
do pacote estar instalado, mesma disciplina de llm.py), model
claude-sonnet-5, MESMO ENGINE_PROMPT_TEMPLATE de run_case.py (importado via
run_case._build_engine_prompt, nunca copiado), temperatura 0.7, 3 reps por
célula (baseline + 9 técnicas). Chave: ANTHROPIC_API_KEY lida via llm.env()
(.env na raiz ou variável de ambiente, mesmo parser de llm.py) — se ausente,
`--run` real sai com SystemExit(1) e mensagem clara, sem chamar a API e sem
stack trace.

TRACES: eval/traces_crossval/<qid>.jsonl (--out-dir configurável, default
esse), MESMO schema de run_case.py (via run_case._make_record) + campo
"engine": "claude-sonnet-5" (sempre presente, inclusive em modo mock — o
marcador de mock/real continua sendo model_version=="mock", nunca o campo
"engine"). Resumível: usa run_case._load_existing (fase+tecnica+rep já
presente NO MODO DA SESSÃO ATUAL => pula), a mesma lógica de run_case.py.

CUSTO: preços de claude-sonnet-5 em config/prices.yaml, SEM o
`batch_desconto` (essas chamadas são síncronas via Messages API, não via
Batch API — o desconto de 50% só se aplica a jobs em lote). Guarda de custo
PRÓPRIA (CostGuardCrossval abaixo) — reimplementação deliberada, não reuso de
run_case.CostGuard, porque contabiliza um ledger SEPARADO (eval/traces_
crossval/) e escreve seu próprio arquivo de abort (ABORT_COST_CROSSVAL.md),
para nunca ser confundido com o teto da run principal do Gemini (eval/
traces/, ABORT_COST.md). MAX_COST_USD_PER_RUN (mesma env/.env var do resto do
projeto) é o teto desta guarda; **o teto do estudo inteiro (US$ 40, config/
study.yaml) é a SOMA dos dois ledgers**, não cada um isoladamente — quem
revisar custo total do estudo deve somar os dois.

Antes de `--run` real, SEMPRE imprime a estimativa de custo (queries
selecionadas × 30 chamadas/query × tokens médios observados nos traces reais
do Gemini) e exige `--confirm` se ela passar de US$ 5 — sem --confirm nesse
caso, sai sem chamar a API.

RELATÓRIO: results/cross_validation/crossval_<stamp>.md — por técnica,
melhoria relativa média (Eq. 4 do paper, via metrics.relative_improvement)
do Imp_pwc da fonte-alvo, calculada por query e depois a média entre queries
(mesma convenção de eval/run_eval.py), separadamente para Gemini e para
Claude, SOMENTE sobre a interseção de queries com dado comparável nos dois
engines para aquela técnica (nunca compara colunas com denominadores
diferentes). "mesma direção?" = sim/não/indefinido (indefinido quando a
melhoria não pôde ser calculada em algum dos dois engines, ou quando a média
deu exatamente 0 num deles). No fim, "% de técnicas com mesma direção de
efeito nos dois engines" — o número exigido pelo contrato para a Fase 5 — é
definido como sim / 9 (as 9 técnicas do estudo; indefinido conta como "não
mesma direção", denominador sempre 9, nunca menor); uma linha secundária
mostra sim/(sim+não) só entre as técnicas com comparação determinada, para
contexto, mas NÃO é o número do contrato.

CSV IMPORTÁVEL PELO LATEX: results/cross_validation/comparacao_engines.csv
(+ .md par), emitido a partir do MESMO cálculo que alimenta o relatório
acima (write_report -> _compute_comparacao, reaproveitado por
_emit_comparacao_engines_csv, nunca recalculado à parte). Escrito via
aggregate.emit_table — mesma convenção de cabeçalho de metadados "#" (antes
das colunas) e rodapé "#" (com o número do contrato) usada por todo o resto
de results/*.csv; colunas: tecnica, melhoria_relativa_gemini_pct,
melhoria_relativa_sonnet_pct, mesma_direcao (sim/nao/indefinido — ASCII, ao
contrário do "não" acentuado usado no .md), n_queries. É esta tabela que
scripts/csv_to_latex.py converte em paper/draft/tables/comparacao_engines.tex
(ver §5.6 do paper, sec:results-crossval) — análoga a comparacao_paper.csv
de src/aggregate.py, mas sem duplicar a lógica de "mesma direção" aqui:
_compute_comparacao é a única definição.

MODO MOCK (MOCK_LLM=1): não toca rede; model_version="mock" (marcador
isolado, nunca conta para o teto real nem para a resumabilidade de uma sessão
real — mesma regra de llm.py/run_case.py). Use --out-dir separado em testes
para nunca tocar eval/traces_crossval/ real.
"""
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import argparse
import json
import random
from datetime import datetime, timezone

import aggregate  # reusa emit_table (mesma convenção de cabeçalho "#" do resto do pipeline)
import build_scenario
import llm
import metrics
import run_case

ROOT = run_case.ROOT
GEMINI_TRACES_DIR = ROOT / "eval" / "traces"
DEFAULT_OUT_DIR = "eval/traces_crossval"
RESULTS_DIR = ROOT / "results" / "cross_validation"
SELECTION_PATH = RESULTS_DIR / "queries_selecionadas.json"
PULADAS_PATH = RESULTS_DIR / "queries_puladas.json"

ENGINE_MODEL = "claude-sonnet-5"
ENGINE_TEMPERATURE = 0.7
MAX_TOKENS = 2048
SELECTION_SEED = "geo-ptbr-crossval"
N_QUERIES_ALVO = 50
CUSTO_CONFIRM_THRESHOLD_USD = 5.0

CALL_COUNT = 0  # contador de chamadas reais de _anthropic_generate(), útil p/ auditar resumabilidade


# --------------------------------------------------------------------------
# leitura dos dados de origem (queries.jsonl, traces do Gemini)
# --------------------------------------------------------------------------
def _load_queries():
    path = ROOT / "data" / "queries.jsonl"
    queries = {}
    if not path.exists():
        return queries
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            queries[rec["id"]] = rec
    return queries


def _read_gemini_records(qid, gemini_traces_dir=GEMINI_TRACES_DIR):
    """{(fase,tecnica,rep): record} de eval/traces/<qid>.jsonl, SOMENTE
    registros REAIS (model_version != "mock") — independe do modo (mock/real)
    da sessão ATUAL deste módulo, ao contrário de run_case._load_existing.
    Aqui sempre queremos o trace real do Gemini, nunca um mock."""
    path = Path(gemini_traces_dir) / f"{qid}.jsonl"
    index = {}
    if not path.exists():
        return index
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("model_version") == "mock":
                continue
            index[(rec.get("fase"), rec.get("tecnica"), rec.get("rep"))] = rec
    return index


def _gemini_completo(qid, tecnicas, reps, gemini_traces_dir=GEMINI_TRACES_DIR):
    index = _read_gemini_records(qid, gemini_traces_dir)
    for rep in range(reps):
        if ("baseline", None, rep) not in index:
            return False
    for tecnica in tecnicas:
        if ("transform", tecnica, None) not in index:
            return False
        for rep in range(reps):
            if ("tecnica", tecnica, rep) not in index:
                return False
    return True


def load_transformed_texts(qid, tecnicas, gemini_traces_dir=GEMINI_TRACES_DIR):
    """Lê os textos JÁ transformados pelo Gemini p/ `qid` (fase="transform",
    reais). Retorna (textos {tecnica: texto}, faltando [tecnica,...], index).
    NUNCA gera transformação nova — só lê o que já existe em eval/traces/."""
    index = _read_gemini_records(qid, gemini_traces_dir)
    textos, faltando = {}, []
    for tecnica in tecnicas:
        rec = index.get(("transform", tecnica, None))
        if rec is None:
            faltando.append(tecnica)
        else:
            textos[tecnica] = rec["resposta"]
    return textos, faltando, index


# --------------------------------------------------------------------------
# seleção estratificada das 50 queries
# --------------------------------------------------------------------------
def _setor_targets(setores_config, n_total):
    """Alocação proporcional por setor (método dos maiores restos) a partir
    dos "alvo" de config/study.yaml (167/167/166 de 500), escalados para
    n_total. Para n_total=50 dá exatamente 17/17/16 (saude/juridico/
    imobiliario) — o número citado no contrato."""
    total_alvo = sum(s["alvo"] for s in setores_config)
    exato = {s["nome"]: n_total * s["alvo"] / total_alvo for s in setores_config}
    floors = {nome: int(v) for nome, v in exato.items()}
    resto = n_total - sum(floors.values())
    ordem = sorted(exato.keys(), key=lambda n: (-(exato[n] - floors[n]), n))
    for nome in ordem[:resto]:
        floors[nome] += 1
    return floors


def select_queries(n_total=N_QUERIES_ALVO, gemini_traces_dir=GEMINI_TRACES_DIR, seed=SELECTION_SEED):
    study = run_case.load_study_config()
    tecnicas = list(study["tecnicas"])
    reps = study["engine"]["principal"]["reps_por_celula"]
    queries = _load_queries()
    targets = _setor_targets(study["queries"]["setores"], n_total)

    por_setor = {}
    for qid, q in queries.items():
        if q.get("tipo") != "normal":
            continue
        por_setor.setdefault(q["setor"], []).append(qid)

    rng = random.Random(seed)
    setores_out = {}
    selecionadas = []
    for setor in sorted(targets):  # ordem alfabética fixa => determinismo entre setores
        candidatos = sorted(por_setor.get(setor, []))
        completos = [qid for qid in candidatos if _gemini_completo(qid, tecnicas, reps, gemini_traces_dir)]
        incompletos = [qid for qid in candidatos if qid not in completos]
        alvo = targets[setor]
        k = min(alvo, len(completos))
        escolhidas = sorted(rng.sample(completos, k)) if k else []
        setores_out[setor] = {
            "alvo": alvo,
            "candidatos_normais": len(candidatos),
            "candidatos_completos_gemini": len(completos),
            "candidatos_incompletos_gemini": len(incompletos),
            "selecionadas": escolhidas,
        }
        selecionadas.extend(escolhidas)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "n_alvo": n_total,
        "n_selecionadas": len(selecionadas),
        "completo": len(selecionadas) == n_total,
        "setores": setores_out,
        "selecionadas": selecionadas,
    }


def load_or_create_selection(force=False, gemini_traces_dir=GEMINI_TRACES_DIR):
    if SELECTION_PATH.exists() and not force:
        with open(SELECTION_PATH, encoding="utf-8") as f:
            return json.load(f)
    sel = select_queries(gemini_traces_dir=gemini_traces_dir)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SELECTION_PATH, "w", encoding="utf-8") as f:
        json.dump(sel, f, ensure_ascii=False, indent=2, sort_keys=True)
    if not sel["completo"]:
        print(
            f"  [seleção] AVISO: pool de queries normais com trace Gemini completo "
            f"insuficiente — {sel['n_selecionadas']}/{sel['n_alvo']} selecionadas. "
            f"{SELECTION_PATH.relative_to(ROOT)} foi gravado mesmo assim (permite "
            "teste/execução parcial), mas NÃO é a seleção final da Fase 5 — rode "
            "--reselect depois que a Fase 3 do Gemini tiver mais traces reais."
        )
    return sel


# --------------------------------------------------------------------------
# custo — preços claude-sonnet-5, SEM desconto de batch (chamada síncrona)
# --------------------------------------------------------------------------
def _custo_usd_claude(input_tokens, output_tokens):
    p = llm._prices()["modelos"][ENGINE_MODEL]
    return (input_tokens / 1_000_000 * p["input_por_1m"]) + (output_tokens / 1_000_000 * p["output_por_1m"])


def _avg_gemini_engine_tokens(query_ids, gemini_traces_dir=GEMINI_TRACES_DIR):
    """Tokens médios observados nos traces REAIS do Gemini (fases baseline +
    tecnica — a fase transform não é chamada aqui, é só lida)."""
    ins, outs = [], []
    for qid in query_ids:
        for (fase, _tecnica, _rep), rec in _read_gemini_records(qid, gemini_traces_dir).items():
            if fase in ("baseline", "tecnica"):
                ins.append(rec.get("input_tokens", 0) or 0)
                outs.append(rec.get("output_tokens", 0) or 0)
    avg_in = sum(ins) / len(ins) if ins else 0.0
    avg_out = sum(outs) / len(outs) if outs else 0.0
    return avg_in, avg_out, len(ins)


def estimate_cost(query_ids, gemini_traces_dir=GEMINI_TRACES_DIR):
    study = run_case.load_study_config()
    reps = study["engine"]["principal"]["reps_por_celula"]
    n_tecnicas = len(study["tecnicas"])
    chamadas_por_query = reps + n_tecnicas * reps  # baseline + técnicas×reps (transform reaproveitado, não conta)
    avg_in, avg_out, n_amostra = _avg_gemini_engine_tokens(query_ids, gemini_traces_dir)
    custo_por_chamada = _custo_usd_claude(avg_in, avg_out)
    n_queries = len(query_ids)
    total_chamadas = n_queries * chamadas_por_query
    return {
        "n_queries": n_queries,
        "chamadas_por_query": chamadas_por_query,
        "total_chamadas": total_chamadas,
        "avg_input_tokens": avg_in,
        "avg_output_tokens": avg_out,
        "n_amostra_tokens": n_amostra,
        "custo_por_chamada_usd": custo_por_chamada,
        "custo_total_usd": total_chamadas * custo_por_chamada,
    }


def print_estimate_block(est, selection):
    nominal_50x30 = N_QUERIES_ALVO * 30 * est["custo_por_chamada_usd"]
    print("\n=== Estimativa de custo — validação cruzada (claude-sonnet-5) ===")
    print(
        f"  seleção: {selection['n_selecionadas']}/{selection['n_alvo']} queries "
        f"({'completa' if selection['completo'] else 'INCOMPLETA — pool de traces Gemini insuficiente'})"
    )
    print(
        f"  tokens médios/chamada observados nos traces reais do Gemini "
        f"(amostra n={est['n_amostra_tokens']}): {est['avg_input_tokens']:.0f} in / "
        f"{est['avg_output_tokens']:.0f} out"
    )
    print(f"  custo nominal por chamada (claude-sonnet-5, sem desconto de batch): US$ {est['custo_por_chamada_usd']:.6f}")
    print(f"  --- estimativa NOMINAL do contrato (50 queries × 30 chamadas): US$ {nominal_50x30:.4f} ---")
    print(
        f"  --- estimativa PARA ESTA EXECUÇÃO ({est['n_queries']} queries × "
        f"{est['chamadas_por_query']} chamadas = {est['total_chamadas']} chamadas): "
        f"US$ {est['custo_total_usd']:.4f} ---"
    )


class CostGuardCrossval:
    """Guarda de custo PRÓPRIA da validação cruzada (reimplementação — não
    reuso de run_case.CostGuard, ver docstring do módulo): ledger separado
    (out_dir), preços claude-sonnet-5 sem desconto de batch, e seu próprio
    arquivo de abort (ABORT_COST_CROSSVAL.md), para nunca ser confundida com
    o teto/ABORT_COST.md da run principal do Gemini."""

    def __init__(self, out_dir, root=ROOT):
        self.out_dir = Path(out_dir)
        if not self.out_dir.is_absolute():
            self.out_dir = root / self.out_dir
        self.root = root
        self.max_cost = float(llm.env("MAX_COST_USD_PER_RUN", 40))
        self.total = self._scan_existing()
        self._warned_80 = False

    def _scan_existing(self):
        total = 0.0
        if self.out_dir.exists():
            for path in self.out_dir.glob("*.jsonl"):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("model_version") == "mock":
                            continue  # custo fictício de teste não conta p/ o teto real
                        total += float(rec.get("custo_usd", 0) or 0)
        return total

    def add(self, custo_usd_valor, contexto=""):
        self.total += custo_usd_valor or 0.0
        pct = (self.total / self.max_cost * 100) if self.max_cost else 0.0
        if pct >= 100:
            self._abort(contexto)
        elif pct >= 80 and not self._warned_80:
            self._warned_80 = True
            print(f"  [custo-crossval] AVISO: {pct:.1f}% do teto atingido (US$ {self.total:.4f} / US$ {self.max_cost:.2f})")

    def _abort(self, contexto):
        conteudo = (
            "# ABORT_COST_CROSSVAL — teto de custo da validação cruzada atingido\n\n"
            f"- Custo acumulado (nominal, ledger {self.out_dir}): US$ {self.total:.4f}\n"
            f"- Teto (MAX_COST_USD_PER_RUN): US$ {self.max_cost:.2f}\n"
            f"- Contexto da chamada que estourou o teto: {contexto}\n"
            f"- Timestamp: {datetime.now(timezone.utc).isoformat()}\n\n"
            "A validação cruzada foi abortada (SystemExit). Os traces já gravados\n"
            "não foram perdidos — resumível ao retomar após revisão humana do\n"
            "teto/orçamento. NOTA: este teto é contabilizado SEPARADAMENTE do\n"
            "ledger principal (eval/traces/, ABORT_COST.md) — o teto do estudo\n"
            "inteiro (config/study.yaml) é a soma dos dois.\n"
        )
        (self.root / "ABORT_COST_CROSSVAL.md").write_text(conteudo, encoding="utf-8")
        raise SystemExit(
            f"ABORTADO POR CUSTO (crossval): US$ {self.total:.4f} atingiu/excedeu o teto "
            f"US$ {self.max_cost:.2f}. Ver ABORT_COST_CROSSVAL.md."
        )


# --------------------------------------------------------------------------
# engine claude-sonnet-5 (API Anthropic direta) + modo mock
# --------------------------------------------------------------------------
def _mock_response(prompt):
    text = (
        "Segundo a primeira fonte consultada, este é um trecho de teste da "
        "resposta sintética do engine de validação cruzada [1]. Complementando "
        "o ponto anterior, uma segunda fonte reforça o mesmo argumento com "
        "outro ângulo [2]. Por fim, uma terceira fonte fecha o resumo do caso "
        "simulado [3]."
    )
    input_tokens = max(1, len(prompt) // 4)
    output_tokens = max(1, len(text) // 4)
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "custo_usd": _custo_usd_claude(input_tokens, output_tokens),
        "model_version": "mock",
    }


def _anthropic_generate(prompt, temperature=ENGINE_TEMPERATURE):
    """Chama claude-sonnet-5 via SDK `anthropic`. Retorna {"text",
    "input_tokens","output_tokens","custo_usd","model_version"} — mesmo shape
    de llm.generate(), para reaproveitar run_case._make_record sem alterá-lo.
    model_version vem de response.model (nunca inventado). Em MOCK_LLM=1
    retorna resposta sintética sem tocar rede (import do SDK é tardio — modo
    mock não depende do pacote estar instalado, mesma disciplina de llm.py)."""
    global CALL_COUNT
    CALL_COUNT += 1

    if llm.env("MOCK_LLM") == "1":
        return _mock_response(prompt)

    import anthropic  # import tardio

    api_key = llm.env("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY não encontrada (defina em .env na raiz do projeto "
            "ou na variável de ambiente)."
        )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ENGINE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    model_version = response.model
    if not model_version:
        raise RuntimeError(
            "response.model ausente na resposta da API Anthropic — o contrato "
            "exige registrar a versão exata do modelo em todo trace "
            "(TASK.md/PROMPT_GEO_PTBR.md)."
        )
    if response.stop_reason not in ("end_turn", "stop_sequence"):
        print(
            f"  [crossval] AVISO: stop_reason='{response.stop_reason}' — resposta "
            "pode estar truncada/incompleta (ex.: max_tokens ou refusal); "
            "medição registrada mesmo assim, mas revisar manualmente (TASK.md "
            "regra 4 — não inventar resultado, mas também não esconder anomalia)."
        )
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    input_tokens = response.usage.input_tokens or 0
    output_tokens = response.usage.output_tokens or 0
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "custo_usd": _custo_usd_claude(input_tokens, output_tokens),
        "model_version": model_version,
    }


# --------------------------------------------------------------------------
# execução de UMA query (baseline + 9 técnicas, reaproveitando os textos do
# Gemini) — resumível via run_case._load_existing (mesma lógica de run_case.py)
# --------------------------------------------------------------------------
def run_query(qid, tecnicas, reps, out_dir, guard):
    study = run_case.load_study_config()
    versao_experimento = study["versao_experimento"]

    try:
        cenario = build_scenario.build_scenario(qid)
    except SystemExit as e:
        print(f"  [crossval] {qid}: cenário inválido, pulando — {e}")
        return {"novas": 0, "puladas": 0, "pulada_query": True, "motivo": f"cenário inválido: {e}"}

    query_text = cenario["query"]["query"]
    fontes_originais = cenario["fontes"]
    target_pos = random.Random(qid).randint(1, 5)

    textos_transformados, faltando, gemini_index = load_transformed_texts(qid, tecnicas)
    if faltando:
        motivo = f"transform Gemini faltando para técnica(s): {faltando}"
        print(f"  [crossval] {qid}: pulada — {motivo}")
        return {"novas": 0, "puladas": 0, "pulada_query": True, "motivo": motivo}

    gemini_baseline0 = gemini_index.get(("baseline", None, 0))
    if gemini_baseline0 is not None and gemini_baseline0.get("target_pos") != target_pos:
        print(
            f"  [crossval] AVISO: {qid} target_pos recomputado ({target_pos}) diverge "
            f"do trace Gemini ({gemini_baseline0.get('target_pos')}) — usando o "
            "recomputado (mesma fórmula determinística random.Random(query_id) de "
            "run_case.py); investigar se os dois traces referem-se ao mesmo cenário."
        )

    trace_path = run_case._trace_path(qid, out_dir)
    existing = run_case._load_existing(trace_path)
    modo = "MOCK" if llm.env("MOCK_LLM") == "1" else "REAL"
    print(f"[crossval:{qid}] modo={modo} engine={ENGINE_MODEL} fonte-alvo=posição {target_pos} técnicas={len(tecnicas)}")

    novas = puladas = 0

    prompt_baseline = run_case._build_engine_prompt(query_text, fontes_originais)
    for rep in range(reps):
        key = ("baseline", None, rep)
        if key in existing:
            puladas += 1
            continue
        resp = _anthropic_generate(prompt_baseline, temperature=ENGINE_TEMPERATURE)
        metricas = metrics.impressions(resp["text"], n_sources=5)
        record = run_case._make_record(
            qid, "baseline", None, rep, target_pos, resp["text"], metricas, resp, versao_experimento,
        )
        record["engine"] = ENGINE_MODEL
        run_case._append_trace(trace_path, record)
        guard.add(resp["custo_usd"], contexto=f"{qid} baseline rep{rep}")
        novas += 1

    for tecnica in tecnicas:
        texto_transformado = textos_transformados[tecnica]
        fontes_modificadas = [
            dict(f, texto=texto_transformado) if f["posicao"] == target_pos else f
            for f in fontes_originais
        ]
        prompt_tecnica = run_case._build_engine_prompt(query_text, fontes_modificadas)
        for rep in range(reps):
            key = ("tecnica", tecnica, rep)
            if key in existing:
                puladas += 1
                continue
            resp = _anthropic_generate(prompt_tecnica, temperature=ENGINE_TEMPERATURE)
            metricas = metrics.impressions(resp["text"], n_sources=5)
            record = run_case._make_record(
                qid, "tecnica", tecnica, rep, target_pos, resp["text"], metricas, resp, versao_experimento,
            )
            record["engine"] = ENGINE_MODEL
            run_case._append_trace(trace_path, record)
            guard.add(resp["custo_usd"], contexto=f"{qid} {tecnica} rep{rep}")
            novas += 1

    print(f"[crossval:{qid}] concluído — novas: {novas} | puladas: {puladas}")
    return {"novas": novas, "puladas": puladas, "pulada_query": False}


def _registrar_puladas(puladas, out_dir):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir),
        "puladas": puladas,
    }
    with open(PULADAS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"  {len(puladas)} query(ies) pulada(s) — registrado em {PULADAS_PATH.relative_to(ROOT)}")


# --------------------------------------------------------------------------
# relatório — direção do efeito por técnica, Gemini vs Claude
# --------------------------------------------------------------------------
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


def _read_crossval_records(qid, out_dir):
    """Leitura MODE-AGNÓSTICA (mock e real juntos) dos traces de validação
    cruzada de uma query — usada só para relatório. Diferente de
    run_case._load_existing (usado em run_query() para resumabilidade), que
    filtra pelo modo da sessão ATUAL: um `--report` standalone deve mostrar
    o que de fato está gravado em disco, independente do valor de MOCK_LLM
    no momento em que --report foi invocado."""
    path = run_case._trace_path(qid, out_dir)
    index = {}
    if not path.exists():
        return index
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            index[(rec.get("fase"), rec.get("tecnica"), rec.get("rep"))] = rec
    return index


def _melhoria_tecnica(index, tecnica, reps, target_pos):
    """Melhoria relativa (Eq. 4) do Imp_pwc da fonte-alvo p/ UMA query e UMA
    técnica, a partir de um índice (fase,tecnica,rep)->record. None se não
    houver dado suficiente (mesma convenção de metrics.relative_improvement:
    baseline=0 e técnica>0 também retorna None — "novo", não um número)."""
    baseline_vals = [
        v for v in (_pwc_for(index[("baseline", None, r)], target_pos) for r in range(reps) if ("baseline", None, r) in index)
        if v is not None
    ]
    if not baseline_vals:
        return None
    tecnica_vals = [
        v for v in (_pwc_for(index[("tecnica", tecnica, r)], target_pos) for r in range(reps) if ("tecnica", tecnica, r) in index)
        if v is not None
    ]
    if not tecnica_vals:
        return None
    baseline_mean = sum(baseline_vals) / len(baseline_vals)
    tecnica_mean = sum(tecnica_vals) / len(tecnica_vals)
    return metrics.relative_improvement(tecnica_mean, baseline_mean)


def _compute_comparacao(query_ids, out_dir, gemini_traces_dir=GEMINI_TRACES_DIR):
    """Cálculo COMPARTILHADO entre o relatório .md (write_report) e o .csv
    importável pelo LaTeX (write_comparacao_engines_csv) — feito UMA vez só,
    para os dois nunca poderem divergir sobre o que conta como "mesma
    direção". Retorna um dict com tudo que os dois consumidores precisam."""
    study = run_case.load_study_config()
    tecnicas = list(study["tecnicas"])
    reps = study["engine"]["principal"]["reps_por_celula"]

    linhas = []
    sim = nao = indef = 0
    contains_mock = False
    model_versions_claude = set()

    for tecnica in tecnicas:
        melhorias_gemini, melhorias_claude = [], []
        n_comp = 0
        for qid in query_ids:
            gemini_index = _read_gemini_records(qid, gemini_traces_dir)
            claude_index = _read_crossval_records(qid, out_dir)
            if not gemini_index or not claude_index:
                continue
            if ("baseline", None, 0) not in gemini_index or ("baseline", None, 0) not in claude_index:
                continue
            for rec in claude_index.values():
                mv = rec.get("model_version")
                if mv:
                    model_versions_claude.add(mv)
                if mv == "mock":
                    contains_mock = True
            pos_g = gemini_index[("baseline", None, 0)]["target_pos"]
            pos_c = claude_index[("baseline", None, 0)]["target_pos"]
            m_g = _melhoria_tecnica(gemini_index, tecnica, reps, pos_g)
            m_c = _melhoria_tecnica(claude_index, tecnica, reps, pos_c)
            if m_g is None or m_c is None:
                continue
            n_comp += 1
            melhorias_gemini.append(m_g)
            melhorias_claude.append(m_c)

        media_g = sum(melhorias_gemini) / len(melhorias_gemini) if melhorias_gemini else None
        media_c = sum(melhorias_claude) / len(melhorias_claude) if melhorias_claude else None

        if media_g is None or media_c is None:
            direcao = "indefinido"
            indef += 1
        else:
            sinal_g = (media_g > 0) - (media_g < 0)
            sinal_c = (media_c > 0) - (media_c < 0)
            if sinal_g == 0 or sinal_c == 0:
                direcao = "indefinido"
                indef += 1
            elif sinal_g == sinal_c:
                direcao = "sim"
                sim += 1
            else:
                direcao = "não"
                nao += 1

        linhas.append({"tecnica": tecnica, "n": n_comp, "gemini_pct": media_g, "claude_pct": media_c, "direcao": direcao})

    pct_contrato = sim / len(tecnicas) * 100
    denom_secundario = sim + nao
    pct_secundario = (sim / denom_secundario * 100) if denom_secundario else None

    return {
        "tecnicas": tecnicas,
        "linhas": linhas,
        "sim": sim,
        "nao": nao,
        "indef": indef,
        "pct_contrato": pct_contrato,
        "denom_secundario": denom_secundario,
        "pct_secundario": pct_secundario,
        "contains_mock": contains_mock,
        "model_versions_claude": model_versions_claude,
        "study": study,
    }


# --------------------------------------------------------------------------
# .csv importável pelo LaTeX (scripts/csv_to_latex.py) — análogo a
# comparacao_paper.csv, mesma convenção de cabeçalho "#" (via
# aggregate.emit_table, para nunca reimplementar essa convenção à parte).
# --------------------------------------------------------------------------
COLS_COMPARACAO_ENGINES = [
    ("tecnica", "técnica", "str"),
    ("melhoria_relativa_gemini_pct", "melhoria relativa — Gemini (%)", "pct"),
    ("melhoria_relativa_sonnet_pct", "melhoria relativa — Claude Sonnet (%)", "pct"),
    ("mesma_direcao", "mesma direção?", "str"),
    ("n_queries", "n queries comparáveis", "int"),
]

_DIRECAO_ASCII = {"sim": "sim", "não": "nao", "indefinido": "indefinido"}


def _emit_comparacao_engines_csv(comp, query_ids, out_dir, gemini_traces_dir, results_dir=None):
    """Emite o par comparacao_engines.md/.csv a partir de um `comp` JÁ
    calculado por _compute_comparacao() — não recalcula nada, para nunca
    divergir do relatório crossval_<stamp>.md que consome o mesmo `comp`.
    results_dir=None (default) resolve para o RESULTS_DIR do módulo NO
    MOMENTO DA CHAMADA (não em tempo de definição — mesma disciplina de
    write_report(), que também lê RESULTS_DIR dinamicamente), para que um
    teste isolado possa sobrescrever cross_validate.RESULTS_DIR antes de
    chamar e ser respeitado."""
    if results_dir is None:
        results_dir = RESULTS_DIR
    rows = [
        {
            "tecnica": linha["tecnica"],
            "melhoria_relativa_gemini_pct": linha["gemini_pct"],
            "melhoria_relativa_sonnet_pct": linha["claude_pct"],
            "mesma_direcao": _DIRECAO_ASCII.get(linha["direcao"], linha["direcao"]),
            "n_queries": linha["n"],
        }
        for linha in comp["linhas"]
    ]

    header_lines = [
        # wording de "versão do experimento" e "model_version(s) nos traces"
        # EXATA (mesma que aggregate.py::_header_base) — csv_to_latex.py
        # extrai essas duas linhas por regex (extract_meta) para o comentário
        # do .tex; qualquer outra redação cai em "n/d" lá.
        f"versão do experimento: `{comp['study']['versao_experimento']}`",
        f"model_version(s) nos traces: `{', '.join(sorted(comp['model_versions_claude'])) or 'n/d'}`",
        f"engine principal (Gemini): `{comp['study']['engine']['principal']['modelo']}` — traces em `{gemini_traces_dir}`",
        f"engine de validação cruzada (Claude): `{ENGINE_MODEL}` — traces em `{out_dir}`",
        f"queries no conjunto: {len(query_ids)} ({', '.join(query_ids)})",
        f"gerado em (UTC): {datetime.now(timezone.utc).isoformat()}",
    ]
    if comp["contains_mock"]:
        header_lines.append(
            "ATENÇÃO: contém traces gerados em MOCK_LLM=1 — não é resultado "
            "científico (TASK.md regra 4)."
        )

    footer_lines = [
        f"- % de técnicas com mesma direção de efeito nos dois engines (número do "
        f"contrato, Fase 5): {comp['pct_contrato']:.1f}% (sim={comp['sim']}/"
        f"{len(comp['tecnicas'])} técnicas — denominador = todas as 9 técnicas do "
        "estudo; \"indefinido\" conta como não-mesma-direção, denominador nunca "
        "reduzido)",
        f"- detalhamento: sim={comp['sim']}, não={comp['nao']}, indefinido={comp['indef']}",
    ]
    if comp["denom_secundario"]:
        footer_lines.append(
            f"- secundário, informativo (só entre técnicas com comparação "
            f"determinada, NÃO é o número do contrato): {comp['pct_secundario']:.1f}% "
            f"({comp['sim']}/{comp['denom_secundario']})"
        )

    return aggregate.emit_table(
        results_dir,
        "comparacao_engines",
        "Comparação entre engines — direção do efeito por técnica (validação cruzada Gemini vs Claude)",
        header_lines,
        COLS_COMPARACAO_ENGINES,
        rows,
        footer_lines=footer_lines,
    )


def write_comparacao_engines_csv(query_ids, out_dir, gemini_traces_dir=GEMINI_TRACES_DIR, results_dir=None):
    """results/cross_validation/comparacao_engines.csv (+ .md par, mesma
    convenção de todo par .md/.csv gerado por aggregate.emit_table) — a
    tabela "análoga a comparacao_paper.csv" citada no TODO de
    paper/draft/main.tex §5.6 (sec:results-crossval), consumível por
    scripts/csv_to_latex.py. Ponto de entrada standalone (ex.: testes); em
    write_report() abaixo, o `comp` já calculado é reaproveitado direto."""
    comp = _compute_comparacao(query_ids, out_dir, gemini_traces_dir)
    return _emit_comparacao_engines_csv(comp, query_ids, out_dir, gemini_traces_dir, results_dir=results_dir)


def write_report(query_ids, out_dir, gemini_traces_dir=GEMINI_TRACES_DIR):
    comp = _compute_comparacao(query_ids, out_dir, gemini_traces_dir)
    tecnicas = comp["tecnicas"]
    linhas = comp["linhas"]
    sim, nao, indef = comp["sim"], comp["nao"], comp["indef"]
    pct_contrato = comp["pct_contrato"]
    denom_secundario = comp["denom_secundario"]
    pct_secundario = comp["pct_secundario"]
    contains_mock = comp["contains_mock"]
    model_versions_claude = comp["model_versions_claude"]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = RESULTS_DIR / f"crossval_{stamp}.md"

    lines = []
    lines.append(f"# Validação cruzada GEO-PTBR — Gemini vs Claude ({ENGINE_MODEL}) — {stamp}")
    lines.append("")
    if contains_mock:
        lines.append(
            "> **ATENÇÃO: contém traces gerados em MOCK_LLM=1.** Os números abaixo "
            "validam o *pipeline* (harness ponta a ponta), não são resultado "
            "científico. Nenhum trace mock deve entrar na validação cruzada real "
            "(TASK.md regra 4)."
        )
        lines.append("")
    lines.append(f"- engine de validação cruzada: `{ENGINE_MODEL}`")
    lines.append(
        f"- model_version(s) observada(s) nos traces de validação cruzada: "
        f"`{', '.join(sorted(model_versions_claude)) or 'n/d'}`"
    )
    lines.append(f"- queries no conjunto deste relatório: {len(query_ids)} ({', '.join(query_ids)})")
    lines.append("")

    lines.append("## Direção do efeito por técnica — Gemini vs Claude (Imp_pwc da fonte-alvo)")
    lines.append("")
    lines.append(
        "_Melhoria relativa média (Eq. 4 do paper, metrics.relative_improvement) "
        "calculada por query e depois a média entre queries; SOMENTE queries com "
        "dado comparável nos dois engines para a técnica (interseção — nunca "
        "compara colunas com denominadores diferentes). \"indefinido\" = baseline "
        "Imp_pwc=0 em algum engine, ou nenhuma query comparável._"
    )
    lines.append("")
    lines.append("| técnica | n queries comparáveis | melhoria média — Gemini | melhoria média — Claude | mesma direção? |")
    lines.append("|---|---|---|---|---|")
    for linha in linhas:
        g_str = f"{linha['gemini_pct']:.1f}%" if linha["gemini_pct"] is not None else "indefinido"
        c_str = f"{linha['claude_pct']:.1f}%" if linha["claude_pct"] is not None else "indefinido"
        lines.append(f"| {linha['tecnica']} | {linha['n']} | {g_str} | {c_str} | {linha['direcao']} |")
    lines.append("")

    lines.append("## Resultado da Fase 5 (contrato)")
    lines.append("")
    lines.append(
        f"- **% de técnicas com mesma direção de efeito nos dois engines: "
        f"{pct_contrato:.1f}%** ({sim}/{len(tecnicas)} técnicas — denominador = "
        "todas as 9 técnicas do estudo; \"indefinido\" conta como não-mesma-"
        "direção, denominador nunca reduzido)"
    )
    lines.append(f"  - detalhamento: sim={sim}, não={nao}, indefinido={indef}")
    if denom_secundario:
        lines.append(
            f"  - secundário, informativo (só entre técnicas com comparação "
            f"determinada, NÃO é o número do contrato): {pct_secundario:.1f}% "
            f"({sim}/{denom_secundario})"
        )
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    _emit_comparacao_engines_csv(comp, query_ids, out_dir, gemini_traces_dir)

    return out_path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _query_ids_para_execucao(args):
    selection = load_or_create_selection(force=args.reselect)
    query_ids = list(selection["selecionadas"])
    if args.limit:
        query_ids = query_ids[: args.limit]
    return query_ids, selection


def cmd_estimate(args):
    query_ids, selection = _query_ids_para_execucao(args)
    est = estimate_cost(query_ids)
    print_estimate_block(est, selection)


def cmd_report(args):
    query_ids, _selection = _query_ids_para_execucao(args)
    report_path = write_report(query_ids, args.out_dir)
    print(f"relatório: {report_path}")
    print(f"csv (LaTeX): {RESULTS_DIR / 'comparacao_engines.csv'}")


def cmd_run(args):
    modo_mock = llm.env("MOCK_LLM") == "1"
    if not modo_mock and not llm.env("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY não encontrada (defina em .env na raiz do projeto "
            "ou na variável de ambiente) — abortando SEM chamar a API."
        )
        sys.exit(1)

    query_ids, selection = _query_ids_para_execucao(args)
    if not query_ids:
        print("nenhuma query selecionada — nada a fazer (ver results/cross_validation/queries_selecionadas.json)")
        return

    study = run_case.load_study_config()
    tecnicas = list(study["tecnicas"])
    reps = study["engine"]["principal"]["reps_por_celula"]

    est = estimate_cost(query_ids)
    print_estimate_block(est, selection)
    if est["custo_total_usd"] > CUSTO_CONFIRM_THRESHOLD_USD and not args.confirm:
        print(
            f"\nEstimativa desta execução (US$ {est['custo_total_usd']:.2f}) acima de "
            f"US$ {CUSTO_CONFIRM_THRESHOLD_USD:.2f} — rode novamente com --confirm "
            "para prosseguir com as chamadas reais. Nenhuma chamada foi feita."
        )
        sys.exit(1)

    guard = CostGuardCrossval(args.out_dir)
    total_novas = total_puladas = 0
    puladas_query = []
    for qid in query_ids:
        resultado = run_query(qid, tecnicas, reps, args.out_dir, guard)
        total_novas += resultado["novas"]
        total_puladas += resultado["puladas"]
        if resultado.get("pulada_query"):
            puladas_query.append({"query_id": qid, "motivo": resultado.get("motivo")})

    print(f"\ntotal — chamadas novas: {total_novas} | puladas: {total_puladas} | queries puladas: {len(puladas_query)}")
    if puladas_query:
        _registrar_puladas(puladas_query, args.out_dir)

    report_path = write_report(query_ids, args.out_dir)
    print(f"relatório: {report_path}")
    print(f"csv (LaTeX): {RESULTS_DIR / 'comparacao_engines.csv'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="executa as chamadas ao engine claude-sonnet-5 (real ou mock)")
    ap.add_argument("--estimate", action="store_true", help="só imprime a estimativa de custo, sem chamar nada")
    ap.add_argument("--report", action="store_true", help="só regenera o relatório a partir dos traces já existentes")
    ap.add_argument("--limit", type=int, default=None, help="limita às N primeiras queries selecionadas (teste)")
    ap.add_argument("--confirm", action="store_true", help="confirma execução real quando a estimativa > US$ 5")
    ap.add_argument("--reselect", action="store_true", help="força recomputar queries_selecionadas.json")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"default: {DEFAULT_OUT_DIR}")
    args = ap.parse_args()

    if sum(bool(x) for x in (args.run, args.estimate, args.report)) != 1:
        ap.error("especifique exatamente um de --run, --estimate, --report")

    if args.estimate:
        cmd_estimate(args)
    elif args.report:
        cmd_report(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
