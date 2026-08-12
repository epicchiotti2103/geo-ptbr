#!/usr/bin/env python3
"""Roda UM caso completo (1 query): baseline + 9 técnicas, com medição.

Uso:
    python src/run_case.py --query s001
    python src/run_case.py --query s001 --tecnicas cite_sources,quotation_addition
    python src/run_case.py --query s001 --reps 3

Fluxo por caso (query_id):
  (a) baseline: `reps` chamadas ao engine (temperatura 0.7) com as 5 fontes
      originais no contexto; mede impressões (metrics.impressions) em cada
      resposta.
  (b) para cada técnica: transform.apply_technique aplicada UMA vez (temperatura
      0) sobre a fonte-alvo; o texto da fonte-alvo é substituído; `reps`
      chamadas ao engine (temperatura 0.7) com as fontes (4 originais + 1
      transformada); mede impressões em cada resposta.

Fonte-alvo: random.Random(query_id).randint(1, 5) — determinística por query,
constante entre técnicas (regra do paper, KEY_FACTS §4).

TRACE: 1 linha JSONL por chamada de engine E por transformação, em
eval/traces/<query_id>.jsonl.

RESUMABILIDADE: antes de cada chamada, verifica se o trace correspondente
(fase+tecnica+rep) já existe; se sim, pula. A checagem é sensível a modo mock
vs real (model_version == "mock" é o marcador) — um trace mock nunca é
confundido com um trace real, nem na resumabilidade nem na guarda de custo,
para que uma run mock de teste nunca "engula" chamadas reais de uma run
posterior (e vice-versa).

GUARDA DE CUSTO: acumula custo_usd nominal de todos os traces reais existentes
(em eval/traces/, todos os arquivos) + o que for gasto nesta sessão. Lê
MAX_COST_USD_PER_RUN do .env (default 40). A 80% imprime aviso e continua; a
100% escreve ABORT_COST.md na raiz com o estado e levanta SystemExit.
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

import yaml

import build_scenario
import llm
import metrics
import transform

ROOT = _SRC_DIR.parent
DEFAULT_OUT_DIR = "eval/traces"

# Adaptação PT-BR do Listing 1 do paper (ver paper/KEY_FACTS.md §4): instrui o
# engine a responder de forma concisa usando APENAS as fontes fornecidas, com
# citações inline [1]..[5] em cada afirmação; se as fontes não respondem, dizer
# isso explicitamente sem citar nenhuma. Prompt fixo e versionado — mudar o
# texto abaixo => incrementar ENGINE_PROMPT_VERSION => nova versão do experimento.
ENGINE_PROMPT_VERSION = "v1"

ENGINE_PROMPT_TEMPLATE = (
    "Você é um motor de busca com inteligência artificial. Responda à pergunta do "
    "usuário de forma concisa e direta, usando exclusivamente as informações "
    "contidas nas fontes numeradas abaixo — não utilize nenhum conhecimento "
    "externo a elas.\n\n"
    "Regras obrigatórias:\n"
    "- Cite a fonte de cada afirmação logo após a frase que ela sustenta, no "
    "formato [1], [2], [3], [4] ou [5] (use o número entre colchetes que "
    "identifica a fonte abaixo).\n"
    "- Se uma frase se apoia em mais de uma fonte, cite todas, por exemplo: "
    "[1][3].\n"
    "- Não inclua nenhuma afirmação sem citação de fonte.\n"
    "- Se as fontes fornecidas NÃO contiverem informação suficiente para "
    "responder à pergunta, diga isso explicitamente (por exemplo: \"As fontes "
    "fornecidas não respondem a esta pergunta.\") e, nesse caso, NÃO cite "
    "nenhuma fonte.\n\n"
    "PERGUNTA: {query}\n\n"
    "FONTES:\n{fontes_bloco}\n"
)

_STUDY_CONFIG = None


def load_study_config():
    global _STUDY_CONFIG
    if _STUDY_CONFIG is None:
        with open(ROOT / "config" / "study.yaml", encoding="utf-8") as f:
            _STUDY_CONFIG = yaml.safe_load(f)
    return _STUDY_CONFIG


def _build_engine_prompt(query_text, fontes):
    blocos = [
        f"[{f['posicao']}] {f['titulo']}\n{f['texto']}"
        for f in sorted(fontes, key=lambda x: x["posicao"])
    ]
    return ENGINE_PROMPT_TEMPLATE.format(
        query=query_text, fontes_bloco="\n\n".join(blocos)
    )


def _trace_path(query_id, out_dir):
    out_dir = Path(out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    return out_dir / f"{query_id}.jsonl"


def _is_mock_record(rec):
    return rec.get("model_version") == "mock"


def _current_mode_is_mock():
    return llm.env("MOCK_LLM") == "1"


def _load_existing(trace_path):
    """Retorna {(fase, tecnica, rep): record} dos traces já existentes que
    pertencem ao MESMO modo (mock/real) da sessão atual — um trace mock nunca
    conta como "já feito" para uma sessão real, e vice-versa."""
    existing = {}
    corrompidas = 0
    mock_atual = _current_mode_is_mock()
    if trace_path.exists():
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    corrompidas += 1
                    continue  # regra 8: linha corrompida não derruba a run
                if _is_mock_record(rec) != mock_atual:
                    continue
                key = (rec.get("fase"), rec.get("tecnica"), rec.get("rep"))
                existing[key] = rec
    if corrompidas:
        print(f"  [{trace_path.name}] {corrompidas} linha(s) de trace corrompida(s), ignoradas")
    return existing


def _append_trace(trace_path, record):
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with open(trace_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_record(query_id, fase, tecnica, rep, target_pos, resposta, metricas, resp, versao_experimento):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_id": query_id,
        "fase": fase,
        "tecnica": tecnica,
        "rep": rep,
        "target_pos": target_pos,
        "resposta": resposta,
        "metricas": metricas,
        "input_tokens": resp["input_tokens"],
        "output_tokens": resp["output_tokens"],
        "custo_usd": resp["custo_usd"],
        "model_version": resp["model_version"],
        "versao_experimento": versao_experimento,
        "metrics_version": metrics.METRICS_VERSION,
        "prompts_version": transform.PROMPTS_VERSION,
        "engine_prompt_version": ENGINE_PROMPT_VERSION,
    }


class CostGuard:
    """Guarda de custo: acumula custo_usd NOMINAL de todos os traces reais
    existentes em out_dir (todos os arquivos, todas as queries) + a sessão
    atual. Traces mock nunca contam para o teto real."""

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
                        if _is_mock_record(rec):
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
            print(
                f"  [custo] AVISO: {pct:.1f}% do teto atingido "
                f"(US$ {self.total:.4f} / US$ {self.max_cost:.2f})"
            )

    def _abort(self, contexto):
        conteudo = (
            "# ABORT_COST — teto de custo atingido\n\n"
            f"- Custo acumulado (nominal): US$ {self.total:.4f}\n"
            f"- Teto (MAX_COST_USD_PER_RUN): US$ {self.max_cost:.2f}\n"
            f"- Contexto da chamada que estourou o teto: {contexto}\n"
            f"- Timestamp: {datetime.now(timezone.utc).isoformat()}\n\n"
            "A run foi abortada (SystemExit). Os traces já gravados em "
            "eval/traces/ não foram perdidos — resumível ao retomar após "
            "revisão humana do teto/orçamento.\n"
        )
        (self.root / "ABORT_COST.md").write_text(conteudo, encoding="utf-8")
        raise SystemExit(
            f"ABORTADO POR CUSTO: US$ {self.total:.4f} atingiu/excedeu o teto "
            f"US$ {self.max_cost:.2f}. Ver ABORT_COST.md."
        )


def run_case(query_id, tecnicas=None, reps=3, out_dir=DEFAULT_OUT_DIR):
    """Roda baseline + as técnicas indicadas (default: as 9 de config/study.yaml)
    para 1 query, com `reps` repetições por célula. Resumível: pula o que já
    existe no trace. Retorna {"novas": int, "puladas": int} (contagem de
    chamadas de engine/transform desta execução, útil para auditar a
    resumabilidade)."""
    study = load_study_config()
    if tecnicas is None:
        tecnicas = list(study["tecnicas"])  # ordem canônica do contrato

    cenario = build_scenario.build_scenario(query_id)
    query_text = cenario["query"]["query"]
    fontes_originais = cenario["fontes"]
    target_pos = random.Random(query_id).randint(1, 5)
    versao_experimento = study["versao_experimento"]

    trace_path = _trace_path(query_id, out_dir)
    existing = _load_existing(trace_path)
    guard = CostGuard(out_dir)

    modo = "MOCK" if _current_mode_is_mock() else "REAL"
    print(f"[{query_id}] modo={modo} fonte-alvo=posição {target_pos} técnicas={len(tecnicas)}")

    novas = 0
    puladas = 0

    # (a) baseline
    prompt_baseline = _build_engine_prompt(query_text, fontes_originais)
    for rep in range(reps):
        key = ("baseline", None, rep)
        if key in existing:
            puladas += 1
            continue
        resp = llm.generate(prompt_baseline, temperature=0.7)
        metricas = metrics.impressions(resp["text"], n_sources=5)
        record = _make_record(
            query_id, "baseline", None, rep, target_pos, resp["text"], metricas,
            resp, versao_experimento,
        )
        _append_trace(trace_path, record)
        guard.add(resp["custo_usd"], contexto=f"{query_id} baseline rep{rep}")
        novas += 1

    # (b) técnicas
    for tecnica in tecnicas:
        target_fonte = next(f for f in fontes_originais if f["posicao"] == target_pos)

        transform_key = ("transform", tecnica, None)
        if transform_key in existing:
            texto_transformado = existing[transform_key]["resposta"]
            puladas += 1
        else:
            resp_t = transform.apply_technique(
                target_fonte["texto"], tecnica, query_text, temperature=0
            )
            texto_transformado = resp_t["text"]
            record_t = _make_record(
                query_id, "transform", tecnica, None, target_pos, texto_transformado,
                None, resp_t, versao_experimento,
            )
            _append_trace(trace_path, record_t)
            guard.add(resp_t["custo_usd"], contexto=f"{query_id} transform {tecnica}")
            existing[transform_key] = record_t
            novas += 1

        fontes_modificadas = [
            dict(f, texto=texto_transformado) if f["posicao"] == target_pos else f
            for f in fontes_originais
        ]
        prompt_tecnica = _build_engine_prompt(query_text, fontes_modificadas)
        for rep in range(reps):
            key = ("tecnica", tecnica, rep)
            if key in existing:
                puladas += 1
                continue
            resp = llm.generate(prompt_tecnica, temperature=0.7)
            metricas = metrics.impressions(resp["text"], n_sources=5)
            record = _make_record(
                query_id, "tecnica", tecnica, rep, target_pos, resp["text"], metricas,
                resp, versao_experimento,
            )
            _append_trace(trace_path, record)
            guard.add(resp["custo_usd"], contexto=f"{query_id} {tecnica} rep{rep}")
            novas += 1

    print(f"[{query_id}] concluído — chamadas novas: {novas} | puladas: {puladas}")
    return {"novas": novas, "puladas": puladas}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, metavar="QUERY_ID", help="ex.: s001")
    ap.add_argument("--tecnicas", default=None, help="lista separada por vírgula (default: as 9 de config/study.yaml)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    tecnicas = [t.strip() for t in args.tecnicas.split(",")] if args.tecnicas else None
    run_case(args.query, tecnicas=tecnicas, reps=args.reps, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
