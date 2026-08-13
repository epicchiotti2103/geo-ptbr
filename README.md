# GEO-PTBR

**The first Brazilian-Portuguese replication of Generative Engine Optimization
(GEO) --- and a measurement of how far its effects transfer between engines.**

Code and paper for *GEO-PTBR: A Brazilian-Portuguese Replication of Generative
Engine Optimization and the Engine-Dependence of Its Effects*.

- 📊 **Dataset:** https://huggingface.co/datasets/epicchi2103/geo-ptbr (CC BY 4.0)
- 📄 **Paper:** [`paper/draft/main.pdf`](paper/draft/main.pdf) --- compiled, 47 pages (body to p. 26, complete-tables appendix from p. 27). Source: `paper/draft/main.tex`, build instructions below
- Experiment version: `0.3.0`

## What this measures

Given a PT-BR query and five already-retrieved sources, one designated target
source is rewritten with each of the nine GEO techniques from
[Aggarwal et al. (2024)](https://arxiv.org/abs/2311.09735), and we measure how
the engine's citation of that source changes. Everything else is held fixed.

The same 525 queries and the **same transformed sources** were run
against three engines from three model families ---
`gemini-3.5-flash-lite`, `claude-haiku-4-5`, `gpt-5.6-luna` --- so the only
variable across runs is which engine answers.

## Findings

- The three engines agree on the direction of the effect for **4 of 9
  techniques (44.4%)**, and all four are techniques that **hurt**. What
  transfers across engines is which optimizations backfire, not which work.
- **Technical Terms inverts:** $+1.9\%$ on one engine, $-4.4\%$ and $-12.4\%$
  on the others, with bootstrap CIs excluding zero on all three.
- Agreement drops from **66.7% with two engines to 44.4% with three** --- a
  two-engine cross-validation would have overstated transferability.
- **5 of 9 techniques induce citation of sources that cannot answer the
  query.** Baseline visibility on those control queries is exactly zero, so
  the pipeline is not hallucinating: the techniques are.
- Against the original English results, 5 of 9 directions replicate, but the
  level does not: the original's top techniques gain $+27$ to $+41\%$; our
  largest positive effect is $+2.6\%$.
- **No rank correlation in this study is statistically significant.** With
  $n = 9$ techniques the permutation null is enumerated in full ($9!$ orders),
  and the critical $|\rho|$ at 5% is $0.700$ --- above every $\rho$ we
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
data/                  525 queries + 2,625 sources
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
[Hugging Face dataset]( https://huggingface.co/datasets/epicchi2103/geo-ptbr )
into `eval/`, then:

```bash
.venv/bin/python src/aggregate.py --traces-dir eval/traces --out-dir results
.venv/bin/python src/compare_engines.py
cd paper/draft && make tables && make
```

**No number in the paper is hand-typed.** Every table is generated from the
traces by script, and `csv_to_latex.py` refuses to emit a LaTeX table from a
CSV still marked `PARCIAL`.

Re-running the full experiment against the engines costs roughly US\$67 at the
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
@misc{picchiotti2026geoptbr,
  author = {Picchiotti, Elio Suraci},
  title  = {GEO-PTBR: A Brazilian-Portuguese Replication of Generative Engine
            Optimization and the Engine-Dependence of Its Effects},
  year   = {2026},
}
```

## License

Code: MIT. Dataset: CC-BY-4.0 (see the Hugging Face
repo). Produced by [AEO BR / Caracol Media](https://aeobr.com.br).
