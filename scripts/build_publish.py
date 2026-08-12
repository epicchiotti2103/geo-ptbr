#!/usr/bin/env python3
"""build_publish.py — monta o pacote público do GEO-PTBR em publish/.

Gera, a partir dos artefatos do repositório de trabalho, um diretório limpo
pronto para subir ao Hugging Face (dataset) e ao GitHub (código + paper).

Uso:
    python scripts/build_publish.py                # sem traces (rápido)
    python scripts/build_publish.py --com-traces   # inclui os traces brutos
    python scripts/build_publish.py --out publish

POR QUE UM SCRIPT E NÃO CÓPIA MANUAL: o pacote público é um artefato citável.
Montado à mão, ninguém consegue dizer depois de qual estado do repositório ele
saiu, nem regerá-lo idêntico. Aqui ele é reproduzível e as contagens do card
são MEDIDAS dos arquivos, nunca digitadas.

O QUE NÃO ENTRA, e por quê:
  - `.env`, chaves, qualquer credencial (o script recusa arquivo que case com
    padrão de segredo);
  - traces `mock` (regra 4 do TASK.md: não são resultado científico);
  - histórico do git de trabalho, `.venv`, caches;
  - `results/` intermediários de piloto (pilot_*.md), que não são o resultado
    final e confundiriam quem baixa.
"""
import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENGINES = [
    ("gemini-3.5-flash-lite", "eval/traces"),
    ("claude-haiku-4-5", "eval/traces_claude-haiku-4-5"),
    ("gpt-5.6-luna", "eval/traces_gpt-5.6-luna"),
]

# Tabelas finais que entram no pacote. Piloto e cross_validation obsoleto ficam
# de fora de propósito.
TABELAS_RAIZ = [
    "comparacao_3_engines", "concordancia_engines", "spearman_engines",
    "tabela_principal", "quebra_por_setor", "quebra_por_posicao",
    "tabela_custo", "inducao_pegadinhas", "comparacao_paper",
]

_SEGREDO_RE = re.compile(r"(^\.env$|api[_-]?key|secret|credential|token)", re.I)

LICENSE_DATASET = "cc-by-4.0"
LICENSE_CODIGO = "MIT"


def _guarda_segredo(nome):
    if _SEGREDO_RE.search(nome):
        raise RuntimeError(
            f"recusando incluir {nome!r} no pacote público: casa com padrão de "
            "segredo. Verifique antes de publicar."
        )


def copia(origem, destino):
    origem, destino = Path(origem), Path(destino)
    _guarda_segredo(origem.name)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)
    return destino


def flatten_sources(dir_sources, saida):
    """525 arquivos de 5 fontes viram um sources.jsonl. O Hugging Face carrega
    um único arquivo por split sem configuração; 525 arquivos exigiriam script
    de loading e afastariam quem só quer `load_dataset`."""
    n = 0
    with open(saida, "w", encoding="utf-8") as out:
        for path in sorted(Path(dir_sources).glob("*.jsonl")):
            with open(path, encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue
                    json.loads(linha)  # valida; linha corrompida estoura aqui
                    out.write(linha + "\n")
                    n += 1
    return n


def copia_traces(destino_raiz):
    """Traces brutos por engine, excluindo mock. São a evidência: o contrato do
    estudo diz que resultado só existe se saiu de execução registrada em trace,
    e publicá-los é a forma forte de sustentar isso."""
    total, mock = 0, 0
    for slug, rel in ENGINES:
        origem = ROOT / rel
        if not origem.exists():
            continue
        destino = destino_raiz / "traces" / slug
        destino.mkdir(parents=True, exist_ok=True)
        for path in sorted(origem.glob("*.jsonl")):
            linhas = []
            with open(path, encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        rec = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("model_version") == "mock":
                        mock += 1
                        continue
                    linhas.append(linha)
                    total += 1
            (destino / path.name).write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return total, mock


def conta_queries(path):
    setores, tipos = {}, {}
    n = 0
    with open(path, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            rec = json.loads(linha)
            n += 1
            setores[rec.get("setor")] = setores.get(rec.get("setor"), 0) + 1
            tipos[rec.get("tipo")] = tipos.get(rec.get("tipo"), 0) + 1
    return n, setores, tipos


def le_meta_csv(path):
    """versao_experimento e model_version das linhas '#' do .csv."""
    versao = modelo = None
    with open(path, encoding="utf-8") as f:
        for linha in f:
            if not linha.startswith("#"):
                break
            m = re.search(r"vers[aã]o do experimento:\s*`([^`]*)`", linha)
            if m:
                versao = m.group(1)
            m = re.search(r"model_version\(s\) nos traces:\s*`([^`]*)`", linha)
            if m:
                modelo = m.group(1)
    return versao, modelo


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def stats_origem(path):
    """(n estilos distintos, n fontes marcadas como pegadinha) medidos do
    sources.jsonl. O campo `origem` é a prova verificável de duas afirmações do
    paper — fontes sintéticas rotuladas como tais, e pegadinhas desenhadas para
    não responder — então o card cita números medidos, não digitados."""
    estilos, peg = set(), 0
    for linha in open(path, encoding='utf-8'):
        linha = linha.strip()
        if not linha:
            continue
        origem = json.loads(linha).get('origem') or ''
        for parte in origem.split(';'):
            if parte.startswith('estilo:'):
                estilos.add(parte.split(':', 1)[1])
        if 'pegadinha:' in origem:
            peg += 1
    return len(estilos), peg


def card(n_queries, setores, tipos, n_sources, versao, com_traces, n_traces,
          namespace, n_estilos, n_fontes_peg):
    """Dataset card do Hugging Face. O bloco YAML é lido pela plataforma; a
    prosa abaixo é o que a pessoa lê. Todos os números vêm medidos."""
    normais = tipos.get("normal", 0)
    pegadinhas = tipos.get("pegadinha", 0)
    linhas_setor = "\n".join(
        f"| {s} | {n} |" for s, n in sorted(setores.items()) if s
    )
    traces_secao = ""
    if com_traces:
        traces_secao = f"""
### `traces/` — raw execution traces

{n_traces:,} JSONL records, one per engine call, under `traces/<engine>/<query_id>.jsonl`.
Each record carries the full generated answer, the computed visibility metrics
per source, token counts, cost in USD, and the exact `model_version`.

These are published deliberately. The study's contract states that a result
exists only if it came from a recorded execution, and releasing the traces is
the strong form of that claim: every number in the paper can be recomputed
from this directory with the released code.
"""

    return f"""---
license: {LICENSE_DATASET}
language:
  - pt
pretty_name: GEO-PTBR
size_categories:
  - 1K<n<10K
task_categories:
  - text-generation
  - question-answering
tags:
  - generative-engine-optimization
  - geo
  - information-retrieval
  - citation
  - portuguese
  - brazilian-portuguese
  - llm-evaluation
configs:
  - config_name: queries
    data_files: data/queries.jsonl
  - config_name: sources
    data_files: data/sources.jsonl
---

# GEO-PTBR

The first Brazilian-Portuguese benchmark for **Generative Engine Optimization
(GEO)**: {n_queries} PT-BR queries with {n_sources:,} source documents, plus
per-technique citation-visibility results measured on **three generative
engines**.

Companion artifact to the paper *GEO-PTBR: A Brazilian-Portuguese Replication
of Generative Engine Optimization and the Engine-Dependence of Its Effects*.

Experiment version: `{versao or 'n/d'}`.

## What this measures

Given a query and five already-retrieved PT-BR sources, one designated target
source is rewritten with each of the nine GEO techniques from
[Aggarwal et al. (2024)](https://arxiv.org/abs/2311.09735), and we measure how
the engine's citation of that source changes. Everything else is held fixed.

The same queries and the **same transformed sources** were run against
`gemini-3.5-flash-lite`, `claude-haiku-4-5` and `gpt-5.6-luna`, so the only
variable across the three runs is which engine answers.

**Headline finding:** the three engines agree on the direction of the effect
for only four of the nine techniques, and all four are techniques that *hurt*.
One technique (Technical Terms) inverts sign across engines with bootstrap
confidence intervals excluding zero on all three.

## Contents

### `data/queries.jsonl` — {n_queries} queries

| field | description |
|---|---|
| `id` | query identifier (`s*` health, `j*` legal, `i*` real estate) |
| `setor` | sector: `saude`, `juridico`, `imobiliario` |
| `query` | the query, phrased as a real user would ask an AI assistant |
| `tipo` | `normal` ({normais}) or `pegadinha` ({pegadinhas}) |

| sector | queries |
|---|---|
{linhas_setor}

`pegadinha` ("pitfall") queries are **unanswerable by the sources given**, by
design. They are a control for measurement hallucination: baseline visibility
on them must be zero, and it is. They are excluded from all main results and
analyzed separately.

### `data/sources.jsonl` — {n_sources:,} sources

Five per query, 150--400 words each, in one of five website styles.

| field | description |
|---|---|
| `id` | source identifier (`<query_id>_s<position>`) |
| `query_id` | the query this source answers |
| `posicao` | position 1--5 in the context given to the engine |
| `titulo` | source title |
| `texto` | source body |
| `origem` | provenance string: generating model, website style, and pitfall marker |

`origem` is machine-readable and records how each source was produced, e.g.
`sintetico:grok-4.5;estilo:portal_juridico`. It spans **{n_estilos} distinct
website styles** (legal portal, clinic blog, bank FAQ, specialist column,
developer site, and so on), which is how the benchmark varies register without
varying the answer. Sources belonging to pitfall queries carry an explicit
`pegadinha:nao_responde` marker ({n_fontes_peg} sources), so the control set is
verifiable from the data alone rather than on our word.

⚠️ **The sources are synthetic-realistic, not scraped.** They were generated to
read like real PT-BR web content and are labelled as such. They have not been
verified by domain experts, and the health and legal texts in particular should
not be treated as accurate information. See the paper's Limitations.

### `results/` — measured results

Per-technique visibility, relative improvement (Eq. 4 of the original paper)
with bootstrap 95% confidence intervals, cross-engine agreement, and Spearman
correlations. `results/por_engine/<engine>/` holds the single-engine tables.

The Spearman table carries an exact permutation `p` (the 9! orderings are
enumerated in full — the asymptotic approximation is invalid at n=9). **No
correlation in this study is significant**: the critical |rho| at 5% is 0.700,
above every value measured. Read them as reported, not as evidence of ordering.

Every table reports **two query sets** side by side: `baseline_pos` (primary;
queries whose target source had positive baseline visibility) and the full set
(sensitivity). This matters — pooling them pins the median at exactly zero on
some engines and can make a real negative effect read as no effect.
{traces_secao}
## Loading

```python
from datasets import load_dataset

queries = load_dataset("{namespace}/geo-ptbr", "queries")
sources = load_dataset("{namespace}/geo-ptbr", "sources")
```

## Limitations

Read these before using the dataset:

- **Fixed context.** Results measure citation *given* that the source is already
  retrieved. They do not measure crawling, indexing, retrieval, or traffic.
  Content-side rewriting can improve one stage while harming another.
- **Synthetic sources**, as described above.
- **One transformation pass, reused across engines.** All three engines received
  sources transformed by one model, which isolates citation behavior but does
  not test whether another model would have rewritten them better.
- **`gpt-5.6-luna` does not accept a custom temperature**; the other two ran at
  0.7.

## License

`{LICENSE_DATASET}` — free to use with attribution.

## Citation

```bibtex
@misc{{picchiotti2026geoptbr,
  author = {{Picchiotti, Elio Suraci}},
  title  = {{GEO-PTBR: A Brazilian-Portuguese Replication of Generative Engine
            Optimization and the Engine-Dependence of Its Effects}},
  year   = {{2026}},
  note   = {{Dataset and code: AEO BR, Caracol Media --- https://aeobr.com.br}},
}}
```

Produced by [AEO BR / Caracol Media](https://aeobr.com.br).

Generated by `scripts/build_publish.py` on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.
"""



# ---------------------------------------------------------------------------
# Pacote do GitHub — código + paper. Sem os traces (vivem no Hugging Face) e
# sem o histórico do repositório de trabalho.
# ---------------------------------------------------------------------------

CODIGO_DIRS = ["src", "scripts", "config"]
DOCS = ["TASK.md", "PROGRESS.md", "PROMPT_GEO_PTBR.md"]
IGNORAR = {"__pycache__", ".DS_Store", ".pyc"}


def _copiavel(path):
    return not any(parte in IGNORAR or parte.endswith(".pyc")
                   for parte in path.parts)


def readme_github(n_queries, n_sources, versao, namespace):
    return f"""# GEO-PTBR

**The first Brazilian-Portuguese replication of Generative Engine Optimization
(GEO) --- and a measurement of how far its effects transfer between engines.**

Code and paper for *GEO-PTBR: A Brazilian-Portuguese Replication of Generative
Engine Optimization and the Engine-Dependence of Its Effects*.

- 📊 **Dataset:** https://huggingface.co/datasets/{namespace}/geo-ptbr (CC BY 4.0)
- 📄 **Paper:** `paper/draft/main.tex` (build instructions below)
- Experiment version: `{versao or 'n/d'}`

## What this measures

Given a PT-BR query and five already-retrieved sources, one designated target
source is rewritten with each of the nine GEO techniques from
[Aggarwal et al. (2024)](https://arxiv.org/abs/2311.09735), and we measure how
the engine's citation of that source changes. Everything else is held fixed.

The same {n_queries} queries and the **same transformed sources** were run
against three engines from three model families ---
`gemini-3.5-flash-lite`, `claude-haiku-4-5`, `gpt-5.6-luna` --- so the only
variable across runs is which engine answers.

## Findings

- The three engines agree on the direction of the effect for **4 of 9
  techniques (44.4%)**, and all four are techniques that **hurt**. What
  transfers across engines is which optimizations backfire, not which work.
- **Technical Terms inverts:** $+1.9\\%$ on one engine, $-4.4\\%$ and $-12.4\\%$
  on the others, with bootstrap CIs excluding zero on all three.
- Agreement drops from **66.7% with two engines to 44.4% with three** --- a
  two-engine cross-validation would have overstated transferability.
- **5 of 9 techniques induce citation of sources that cannot answer the
  query.** Baseline visibility on those control queries is exactly zero, so
  the pipeline is not hallucinating: the techniques are.
- Against the original English results, 5 of 9 directions replicate, but the
  level does not: the original's top techniques gain $+27$ to $+41\\%$; our
  largest positive effect is $+2.6\\%$.
- **No rank correlation in this study is statistically significant.** With
  $n = 9$ techniques the permutation null is enumerated in full ($9!$ orders),
  and the critical $|\\rho|$ at 5% is $0.700$ --- above every $\\rho$ we
  measure (engine pairs: $0.667$, $0.550$, $0.483$; against the original:
  $0.617$ by median). We report them and claim nothing from them, in either
  direction.

## Layout

```
src/                 measurement pipeline
  metrics.py           Imp_wc / Imp_pwc (Eqs. 2-4 of the original paper)
  transform.py         the nine GEO techniques, as versioned prompts
  run_case.py          one case: baseline + intervention + measurement
  run_engine_batch.py  full run against one engine, via batch APIs, resumable
  aggregate.py         per-engine tables (bootstrap CIs, no scipy/pandas)
  compare_engines.py   cross-engine comparison, agreement, Spearman
scripts/
  csv_to_latex.py      results/*.csv -> paper/draft/tables/*.tex
  build_publish.py     builds this package and the HF dataset
config/                study parameters and API prices
data/                  {n_queries} queries + {n_sources:,} sources
paper/draft/           the paper (LaTeX)
docs/                  research log and study contract (see below)
```

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # add your API keys

.venv/bin/python src/build_scenario.py --validate   # sanity-check the data
```

To recompute every table from traces, download `traces/` from the
[Hugging Face dataset]( https://huggingface.co/datasets/{namespace}/geo-ptbr )
into `eval/`, then:

```bash
.venv/bin/python src/aggregate.py --traces-dir eval/traces --out-dir results
.venv/bin/python src/compare_engines.py
cd paper/draft && make tables && make
```

**No number in the paper is hand-typed.** Every table is generated from the
traces by script, and `csv_to_latex.py` refuses to emit a LaTeX table from a
CSV still marked `PARCIAL`.

Re-running the full experiment against the engines costs roughly US\\$67 at the
prices in `config/prices.yaml` and requires batch API access on three
providers.

## `docs/` --- the research log

`docs/PROGRESS.md` is the unedited session-by-session log, including the
mistakes: a batch job that reported success while silently dropping 41 queries
in one contiguous block (which flipped one technique from non-significant to
significant), and a statistical convention that made a real negative effect
read as no effect on two of the three engines. Both are discussed in the
paper's Limitations. It is published because a replication study that hides its
own failure modes is worth less than one that does not.

`docs/TASK.md` is the study contract; `docs/PROMPT_GEO_PTBR.md` is the original
brief, superseded during execution and kept for provenance (it carries a header
listing what changed).

## Citation

```bibtex
@misc{{picchiotti2026geoptbr,
  author = {{Picchiotti, Elio Suraci}},
  title  = {{GEO-PTBR: A Brazilian-Portuguese Replication of Generative Engine
            Optimization and the Engine-Dependence of Its Effects}},
  year   = {{2026}},
}}
```

## License

Code: {LICENSE_CODIGO}. Dataset: {LICENSE_DATASET.upper()} (see the Hugging Face
repo). Produced by [AEO BR / Caracol Media](https://aeobr.com.br).
"""


LICENSE_MIT = """MIT License

Copyright (c) 2026 Elio Suraci Picchiotti, AEO BR / Caracol Media

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

GITIGNORE = """.env
.venv/
__pycache__/
*.pyc
.DS_Store
eval/traces*/
publish/
paper/draft/*.aux
paper/draft/*.log
paper/draft/*.out
paper/draft/*.pdf
paper/draft/*.synctex.gz
"""


# Data do release, em ISO. NÃO é `date.today()`: o Zenodo grava este campo no
# DOI, e um build rodado noutro dia mudaria o registro sem que nada no estudo
# tivesse mudado. Bump manual, junto da tag.
DATA_RELEASE = "2026-08-12"

# Versão CITÁVEL, que o Zenodo grava no DOI. Deliberadamente SEPARADA de
# `versao_experimento` (0.3.0 hoje, o mesmo número por coincidência): aquela
# marca o desenho do estudo e sobe quando o pipeline muda; esta marca o que foi
# publicado e sobe junto da tag. Acopladas, uma mudança interna do pipeline
# moveria a versão citada de um artefato já com DOI.
VERSAO_RELEASE = "0.3.0"


def citation_cff(versao, namespace, gh_namespace):
    """CITATION.cff — como citar o repositório.

    Existe por dois motivos: o GitHub passa a mostrar "Cite this repository",
    e a integração Zenodo↔GitHub lê este arquivo ao cunhar o DOI do release.
    Sem ele o DOI sai com autoria derivada do login do git, que não é o nome
    do autor.

    Não traz `preferred-citation` porque o preprint ainda não tem identificador
    — quando o arXiv atribuir um, é aqui que ele entra, e só então.
    """
    return f"""cff-version: 1.2.0
message: "If you use this dataset or code, please cite it as below."
title: "GEO-PTBR: a Brazilian-Portuguese replication of Generative Engine Optimization"
abstract: >-
  Replication of the nine GEO content-side optimization techniques
  (Aggarwal et al., arXiv:2311.09735) on a 525-query Brazilian-Portuguese
  benchmark, measured across three generative engines. Includes the
  benchmark, the measurement pipeline, and the per-engine and cross-engine
  results with bootstrap confidence intervals.
type: dataset
authors:
  - family-names: Picchiotti
    given-names: Elio Suraci
    affiliation: "AEO BR, Caracol Media"
    email: elio.picchiotti@aeobr.com.br
    orcid: "https://orcid.org/0009-0006-3058-4096"
version: "{VERSAO_RELEASE}"
date-released: "{DATA_RELEASE}"
license:
  - MIT
  - CC-BY-4.0
repository-code: "https://github.com/{gh_namespace}/geo-ptbr"
url: "https://huggingface.co/datasets/{namespace}/geo-ptbr"
keywords:
  - generative engine optimization
  - GEO
  - Brazilian Portuguese
  - information retrieval
  - LLM evaluation
  - replication study
references:
  - type: article
    title: "GEO: Generative Engine Optimization"
    authors:
      - family-names: Aggarwal
        given-names: Pranjal
      - family-names: Murahari
        given-names: Vishvak
      - family-names: Rajpurohit
        given-names: Tanmay
      - family-names: Kalyan
        given-names: Ashwin
      - family-names: Narasimhan
        given-names: Karthik
      - family-names: Deshpande
        given-names: Ameet
    year: 2024
    notes: "arXiv:2311.09735 — the study replicated here"
"""


def build_github(destino, n_queries, n_sources, versao, namespace,
                 gh_namespace):
    destino.mkdir(parents=True, exist_ok=True)

    for d in CODIGO_DIRS:
        for path in sorted((ROOT / d).rglob("*")):
            if path.is_file() and _copiavel(path):
                copia(path, destino / path.relative_to(ROOT))

    copia(ROOT / "eval" / "run_eval.py", destino / "eval" / "run_eval.py")
    for nome in ("requirements.txt", ".env.example"):
        copia(ROOT / nome, destino / nome)
    for nome in DOCS:
        if (ROOT / nome).exists():
            copia(ROOT / nome, destino / "docs" / nome)

    # dados: o mesmo benchmark do HF, para o repo ser executável sem download.
    # O HF continua sendo a cópia canônica (tem MANIFEST com sha256).
    copia(ROOT / "data" / "queries.jsonl", destino / "data" / "queries.jsonl")
    for path in sorted((ROOT / "data" / "sources").glob("*.jsonl")):
        copia(path, destino / "data" / "sources" / path.name)

    # paper: fonte LaTeX e tabelas geradas; sem PDF (saída de build)
    for path in sorted((ROOT / "paper" / "draft").rglob("*")):
        if path.is_file() and _copiavel(path) and path.suffix not in (
                ".pdf", ".aux", ".log", ".out", ".synctex.gz", ".bbl", ".blg"):
            copia(path, destino / path.relative_to(ROOT))

    (destino / "README.md").write_text(
        readme_github(n_queries, n_sources, versao, namespace), encoding="utf-8")
    (destino / "LICENSE").write_text(LICENSE_MIT, encoding="utf-8")
    (destino / "CITATION.cff").write_text(
        citation_cff(versao, namespace, gh_namespace), encoding="utf-8")
    (destino / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    # `.git` fica de fora da contagem: é o histórico local preservado entre
    # builds, não conteúdo do pacote — incluí-lo faria o número relatado
    # crescer sozinho a cada commit.
    arquivos = [p for p in destino.rglob("*")
                if p.is_file() and ".git" not in p.parts]
    return len(arquivos), sum(p.stat().st_size for p in arquivos) / 1e6


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="publish")
    ap.add_argument("--namespace", default="epicchi2103",
                    help="namespace do Hugging Face, usado no exemplo de "
                         "load_dataset do card (default: epicchi2103)")
    ap.add_argument("--gh-namespace", default="epicchiotti2103",
                    help="usuário do GitHub — NÃO é o mesmo do Hugging Face "
                         "(default: epicchiotti2103). Vai para o CITATION.cff, "
                         "que o Zenodo lê ao cunhar o DOI")
    ap.add_argument("--com-traces", action="store_true",
                    help="inclui os traces brutos (~100 MB, mas é a evidência)")
    args = ap.parse_args()

    saida = ROOT / args.out
    hf = saida / "huggingface"
    # O pacote é reconstruído do zero — mas PRESERVANDO qualquer .git dentro
    # dele. publish/github/ costuma ser um clone com remote configurado e
    # histórico próprio; um rmtree cego apaga o .git junto e o `git push`
    # seguinte falha com "repository does not exist" sem dizer por quê.
    # (Aconteceu em 2026-08-12: o repo público teve de ser reinicializado.)
    gits = [p for p in saida.rglob(".git") if p.is_dir()] if saida.exists() else []
    guardados = []
    for g in gits:
        tmp = ROOT / f".git_preservado_{g.parent.name}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.move(str(g), str(tmp))
        guardados.append((tmp, g))
    if saida.exists():
        shutil.rmtree(saida)
    (hf / "data").mkdir(parents=True)
    for tmp, destino_git in guardados:
        destino_git.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(destino_git))
        print(f"[publish] .git preservado em {destino_git.parent}")

    # --- dados -------------------------------------------------------------
    copia(ROOT / "data" / "queries.jsonl", hf / "data" / "queries.jsonl")
    n_queries, setores, tipos = conta_queries(hf / "data" / "queries.jsonl")
    n_sources = flatten_sources(ROOT / "data" / "sources", hf / "data" / "sources.jsonl")
    print(f"[publish] queries: {n_queries} | fontes: {n_sources}")

    # --- resultados --------------------------------------------------------
    versao = None
    for nome in TABELAS_RAIZ:
        for ext in ("csv", "md"):
            origem = ROOT / "results" / f"{nome}.{ext}"
            if origem.exists():
                copia(origem, hf / "results" / f"{nome}.{ext}")
                if ext == "csv" and versao is None:
                    versao, _ = le_meta_csv(origem)
    por_engine = ROOT / "results" / "por_engine"
    if por_engine.exists():
        for sub in sorted(por_engine.iterdir()):
            if sub.is_dir():
                for arq in sorted(sub.glob("*.*")):
                    copia(arq, hf / "results" / "por_engine" / sub.name / arq.name)
    print(f"[publish] tabelas copiadas | versão do experimento: {versao}")

    # --- traces ------------------------------------------------------------
    n_traces = 0
    if args.com_traces:
        n_traces, mock = copia_traces(hf)
        print(f"[publish] traces: {n_traces} registros ({mock} mock excluídos)")

    # --- card + licença ----------------------------------------------------
    (hf / "README.md").write_text(
        card(n_queries, setores, tipos, n_sources, versao, args.com_traces,
              n_traces, args.namespace, *stats_origem(hf / 'data' / 'sources.jsonl')),
        encoding="utf-8")
    (hf / "LICENSE").write_text(
        f"Dataset licensed under {LICENSE_DATASET.upper()} "
        "(Creative Commons Attribution 4.0 International).\n"
        "https://creativecommons.org/licenses/by/4.0/\n\n"
        "Attribution: Elio Suraci Picchiotti, AEO BR / Caracol Media "
        "(https://aeobr.com.br).\n", encoding="utf-8")

    # --- manifesto ---------------------------------------------------------
    arquivos = sorted(p for p in hf.rglob("*") if p.is_file())
    manifesto = [
        {"path": str(p.relative_to(hf)), "bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in arquivos if p.suffix in (".jsonl", ".csv")
    ]
    (hf / "MANIFEST.json").write_text(
        json.dumps({"gerado_em_utc": datetime.now(timezone.utc).isoformat(),
                     "versao_experimento": versao,
                     "n_queries": n_queries, "n_sources": n_sources,
                     "n_traces": n_traces, "arquivos": manifesto}, indent=2),
        encoding="utf-8")

    total_mb = sum(p.stat().st_size for p in arquivos) / 1e6
    print(f"[publish] HF: {len(arquivos)} arquivos, {total_mb:.1f} MB em {hf}")
    print("[publish] MANIFEST.json com sha256 de cada .jsonl/.csv")

    # --- pacote do GitHub --------------------------------------------------
    n_gh, mb_gh = build_github(saida / "github", n_queries, n_sources, versao,
                               namespace=args.namespace,
                               gh_namespace=args.gh_namespace)
    print(f"[publish] GitHub: {n_gh} arquivos, {mb_gh:.1f} MB em {saida / 'github'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
