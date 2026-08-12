# tables/ — GERADO, não editar à mão

Todo arquivo `.tex` nesta pasta é **gerado por `scripts/csv_to_latex.py`** a
partir dos `.csv` em `results/` (que, por sua vez, são gerados por
`src/aggregate.py` a partir de `eval/traces/*.jsonl` — regra do TASK.md: "dado
sempre em JSONL... resultado só existe se saiu de execução real registrada em
trace").

**Nunca editar um `.tex` desta pasta diretamente.** Qualquer correção deve
acontecer na origem:

- Número errado / metodologia errada → corrigir `src/aggregate.py` (ou, se for
  a métrica em si, `src/metrics.py`) e regerar `results/*.csv`.
- Formatação da tabela (alinhamento, legenda, `\resizebox`, etc.) → corrigir
  `scripts/csv_to_latex.py`.
- Título/legenda de uma tabela específica → dicionário `KNOWN_TABLES` no topo
  de `scripts/csv_to_latex.py`.

Editar o `.tex` aqui diretamente cria um resultado que não bate com o trace de
origem — exatamente o tipo de número "inventado" que a regra 4 do TASK.md
proíbe. A próxima execução de `make tables` (ou `python
scripts/csv_to_latex.py`) sobrescreve qualquer edição manual sem aviso.

## Regenerar

Da raiz do projeto:

```bash
python src/aggregate.py                 # eval/traces/*.jsonl -> results/*.csv
python scripts/csv_to_latex.py           # results/*.csv -> paper/draft/tables/*.tex
```

Ou, de dentro de `paper/draft/`:

```bash
make tables
```

## Arquivos esperados

Um `.tex` por `.csv` de `results/` (ver `src/aggregate.py`, `ALL_SECOES`):

| `.tex` | Fonte (`.csv`) | Conteúdo |
|---|---|---|
| `tabela_principal.tex` | `results/tabela_principal.csv` | Imp_pwc / Imp_wc da fonte-alvo, baseline vs técnica |
| `quebra_por_setor.tex` | `results/quebra_por_setor.csv` | idem, por setor (saúde/jurídico/imobiliário) |
| `quebra_por_posicao.tex` | `results/quebra_por_posicao.csv` | idem, por posição (1..5) da fonte-alvo |
| `tabela_custo.tex` | `results/tabela_custo.csv` | tokens e US$ por técnica |
| `inducao_pegadinhas.tex` | `results/inducao_pegadinhas.csv` | indução de citação em queries-pegadinha |
| `comparacao_paper.tex` | `results/comparacao_paper.csv` | direção de efeito + Spearman vs. o paper original |
| `comparacao_engines.tex` | `results/cross_validation/comparacao_engines.csv` | direção de efeito Gemini vs Claude (validação cruzada, `src/cross_validate.py`, não `src/aggregate.py` — ver `TABLE_SUBDIR` em `scripts/csv_to_latex.py`) |

Se um `.csv` ainda não existir (antes da Fase 4 completa), o `.tex`
correspondente também não existe — `main.tex` trata isso com
`\IfFileExists{...}{\input{...}}{\TODO{...}}` em vez de quebrar a compilação.
