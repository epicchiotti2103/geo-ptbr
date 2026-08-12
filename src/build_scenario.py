#!/usr/bin/env python3
"""Monta e valida cenários query+fontes do estudo GEO-PTBR.

Uso:
    python src/build_scenario.py --validate            # valida tudo que existe
    python src/build_scenario.py --scenario q001       # imprime o cenário montado

Schemas (JSONL, um registro por linha):
    data/queries.jsonl:
        {"id": "q001", "setor": "saude|juridico|imobiliario",
         "query": "...", "tipo": "normal|pegadinha"}
    data/sources/<query_id>.jsonl (5 registros):
        {"id": "q001_s1", "query_id": "q001", "posicao": 1..5,
         "titulo": "...", "texto": "...", "origem": "..."}

Critério da Fase 1: --validate sai com código 0 e 100% dos cenários existentes OK.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES_PATH = ROOT / "data" / "queries.jsonl"
SOURCES_DIR = ROOT / "data" / "sources"

SETORES = {"saude", "juridico", "imobiliario"}
TIPOS = {"normal", "pegadinha"}
FONTES_POR_QUERY = 5
PALAVRAS_MIN, PALAVRAS_MAX = 150, 400

QUERY_FIELDS = {"id", "setor", "query", "tipo"}
SOURCE_FIELDS = {"id", "query_id", "posicao", "titulo", "texto", "origem"}


def load_jsonl(path):
    """Lê um JSONL tolerando linha corrompida: loga, pula, contabiliza (regra 8)."""
    records, corrupted = [], 0
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                corrupted += 1
                print(f"  [corrompida] {path.name}:{n} — {e}", file=sys.stderr)
    return records, corrupted


def validate_queries(errors):
    if not QUERIES_PATH.exists():
        errors.append("data/queries.jsonl não existe")
        return {}
    records, corrupted = load_jsonl(QUERIES_PATH)
    if corrupted:
        errors.append(f"queries.jsonl: {corrupted} linha(s) corrompida(s)")
    queries, seen = {}, set()
    for r in records:
        missing = QUERY_FIELDS - r.keys()
        extra = r.keys() - QUERY_FIELDS
        if missing:
            errors.append(f"query {r.get('id', '?')}: campos faltando {sorted(missing)}")
            continue
        if extra:
            errors.append(f"query {r['id']}: campos extras {sorted(extra)}")
        if r["id"] in seen:
            errors.append(f"query id duplicado: {r['id']}")
            continue
        seen.add(r["id"])
        if r["setor"] not in SETORES:
            errors.append(f"query {r['id']}: setor inválido '{r['setor']}'")
        if r["tipo"] not in TIPOS:
            errors.append(f"query {r['id']}: tipo inválido '{r['tipo']}'")
        if not isinstance(r["query"], str) or len(r["query"].strip()) < 10:
            errors.append(f"query {r['id']}: texto vazio ou curto demais")
        queries[r["id"]] = r
    return queries


def validate_sources(query_id, errors):
    path = SOURCES_DIR / f"{query_id}.jsonl"
    records, corrupted = load_jsonl(path)
    if corrupted:
        errors.append(f"{path.name}: {corrupted} linha(s) corrompida(s)")
    if len(records) != FONTES_POR_QUERY:
        errors.append(f"{query_id}: {len(records)} fontes (esperado {FONTES_POR_QUERY})")
    posicoes = set()
    for r in records:
        missing = SOURCE_FIELDS - r.keys()
        if missing:
            errors.append(f"fonte {r.get('id', '?')}: campos faltando {sorted(missing)}")
            continue
        if r["query_id"] != query_id:
            errors.append(f"fonte {r['id']}: query_id '{r['query_id']}' != '{query_id}'")
        if r["posicao"] not in range(1, FONTES_POR_QUERY + 1):
            errors.append(f"fonte {r['id']}: posicao inválida {r['posicao']}")
        elif r["posicao"] in posicoes:
            errors.append(f"{query_id}: posicao {r['posicao']} duplicada")
        posicoes.add(r["posicao"])
        n_palavras = len(r["texto"].split())
        if not PALAVRAS_MIN <= n_palavras <= PALAVRAS_MAX:
            errors.append(
                f"fonte {r['id']}: {n_palavras} palavras "
                f"(esperado {PALAVRAS_MIN}-{PALAVRAS_MAX})"
            )
        if not r["origem"].strip():
            errors.append(f"fonte {r['id']}: origem vazia")
    return records


def build_scenario(query_id):
    queries = {}
    errors = []
    queries = validate_queries(errors)
    if query_id not in queries:
        raise SystemExit(f"query '{query_id}' não encontrada")
    sources = validate_sources(query_id, errors)
    if errors:
        raise SystemExit("cenário inválido:\n" + "\n".join(f"  - {e}" for e in errors))
    return {"query": queries[query_id], "fontes": sorted(sources, key=lambda s: s["posicao"])}


def validate_all():
    errors = []
    queries = validate_queries(errors)
    com_fontes = 0
    for qid in queries:
        if (SOURCES_DIR / f"{qid}.jsonl").exists():
            com_fontes += 1
            validate_sources(qid, errors)

    por_setor = {}
    pegadinhas = 0
    for q in queries.values():
        por_setor[q["setor"]] = por_setor.get(q["setor"], 0) + 1
        if q["tipo"] == "pegadinha":
            pegadinhas += 1

    print(f"queries: {len(queries)}  (pegadinhas: {pegadinhas})")
    for setor, n in sorted(por_setor.items()):
        print(f"  {setor}: {n}")
    print(f"queries com fontes: {com_fontes}")

    if errors:
        print(f"\nFALHOU — {len(errors)} erro(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\nOK — 100% dos cenários existentes válidos")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--scenario", metavar="QUERY_ID")
    args = ap.parse_args()
    if args.validate:
        sys.exit(validate_all())
    if args.scenario:
        print(json.dumps(build_scenario(args.scenario), ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
