#!/usr/bin/env python3
"""csv_to_latex.py — GEO-PTBR, Fase 5 (Paper).

Converte os .csv gerados por src/aggregate.py (em results/) em tabelas LaTeX
com booktabs (uma tabela .tex por arquivo .csv), escritas em
paper/draft/tables/. Cada .tex gerado leva um comentário LaTeX com a versão do
experimento e a data de geração, extraídos das linhas de metadados (linhas
iniciadas com "#") do próprio .csv.

Uso:
    python scripts/csv_to_latex.py                          # converte as 7 tabelas conhecidas
    python scripts/csv_to_latex.py --only tabela_principal
    python scripts/csv_to_latex.py --only tabela_principal,tabela_custo
    python scripts/csv_to_latex.py --csv-dir results --tables-dir paper/draft/tables
    python scripts/csv_to_latex.py --only comparacao_engines  # lê results/cross_validation/comparacao_engines.csv
                                                                # (ver TABLE_SUBDIR, gerado por src/cross_validate.py)

NUNCA editar os .tex gerados à mão — ver paper/draft/tables/README.md.

FORMATO DE ENTRADA (ver src/aggregate.py::emit_table): cada .csv tem linhas de
metadados "# ..." ANTES da linha de cabeçalho de colunas, e — em algumas
tabelas (ex.: comparacao_paper) — outro bloco de linhas "# ..." DEPOIS das
linhas de dado (rodapé). Este script trata as duas posições: qualquer linha
que comece com "#" (ignorando espaços à esquerda) é metadado, nunca dado; as
linhas restantes, na ordem em que aparecem, são [cabeçalho, *dados] via
csv.reader padrão (vírgula, aspas).

Os nomes de coluna no .csv são as CHAVES internas em snake_case (não os
rótulos em português usados nos .md) — por conterem "_", são escapados como
qualquer outro conteúdo de célula antes de entrar no LaTeX.
"""
import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_DIR = ROOT / "results"
DEFAULT_TABLES_DIR = ROOT / "paper" / "draft" / "tables"

# Nomes conhecidos (== ALL_SECOES de src/aggregate.py, menos "findings", que
# produz só .md). Título/legenda em inglês (idioma do paper) — mapeados aqui
# porque o .csv não carrega o título "bonito" (só o .md faz).
KNOWN_TABLES = {
    # As quatro tabelas abaixo saem de src/aggregate.py e carregam a coluna
    # `conjunto`. A legenda TEM de dizer qual é o primário: sem isso o leitor vê
    # duas linhas por técnica com números diferentes e nenhuma indicação de qual
    # é o resultado e qual é a sensibilidade.
    "tabela_principal": (
        "Main results: position-adjusted word count ($\\mathrm{Imp}_{pwc}$) and "
        "word count ($\\mathrm{Imp}_{wc}$) of the target source, baseline vs. "
        "technique, with bootstrap 95\\% CI and relative improvement (mean and "
        "median, Eq.~4). Each technique appears twice, once per query set: "
        "\\texttt{baseline\\_pos} (\\textbf{primary}) restricts to queries whose "
        "target source has positive baseline visibility, and \\texttt{all} "
        "(sensitivity) adds the queries where the source was never cited, which "
        "enter Eq.~4 as an exact $0\\%$ and pull the median toward zero. Read "
        "the primary row as the result; see \\S\\ref{sec:stats}."
    ),
    "quebra_por_setor": (
        "Breakdown by sector (health / legal / real estate). Health is a "
        "YMYL (Your-Money-Your-Life) sector; sector-level behavior differences "
        "are a target finding of this study. Query sets as in "
        "Table~\\ref{tab:tabela_principal}: \\texttt{baseline\\_pos} is primary."
    ),
    "quebra_por_posicao": (
        "Breakdown by target-source position (rank 1--5), alongside the "
        "corresponding values from Table~2 of the original GEO paper "
        "\\citep{aggarwal2024geo}. Query sets as in "
        "Table~\\ref{tab:tabela_principal}: \\texttt{baseline\\_pos} is primary."
    ),
    "tabela_custo": (
        "API cost table: tokens and US\\$ per technique, aggregated directly "
        "from execution traces."
    ),
    "inducao_pegadinhas": (
        "Citation induction on pitfall queries (unanswerable-by-design): "
        "total $\\mathrm{Imp}_{wc}$/$\\mathrm{Imp}_{pwc}$ across all 5 sources, "
        "by technique. A value significantly above zero flags a technique that "
        "induced the engine to cite a source that does not answer the query."
    ),
    "comparacao_paper": (
        "Direction-of-effect comparison against the original paper's Table~1 "
        "(PAWC-Overall, \\citealt{aggarwal2024geo}) and Spearman rank "
        "correlation. Absolute scales are not comparable across studies "
        "(different engines/metrics normalization) --- only sign and "
        "ordering are. Reported for both query sets: the Spearman $\\rho$ "
        "differs between them because medians pinned at exactly $0\\%$ in the "
        "full set become ties and receive averaged ranks; "
        "\\texttt{baseline\\_pos} is primary."
    ),
    # --- Tabelas de src/compare_engines.py (§5.2 do main.tex) ------------------
    # O nome carrega a contagem REAL de engines: rodar só o par gemini×haiku
    # produz comparacao_2_engines, que não colide com comparacao_3_engines nem
    # mente sobre o que tem dentro. As duas entradas existem porque o par
    # fechado é o resultado de contingência caso o terceiro engine não termine.
    "comparacao_3_engines": (
        "Cross-engine comparison: relative improvement (Eq.~4) of the target "
        "source per technique and per engine, over the strictly paired query "
        "set (a query enters only if it is complete on every engine and the "
        "target source occupies the same position on all of them). Reported "
        "for both query sets: \\texttt{baseline\\_pos} (primary; queries whose "
        "target source has positive baseline visibility) and the full paired "
        "set (sensitivity) --- see \\S\\ref{sec:stats}."
    ),
    "comparacao_2_engines": (
        "Cross-engine comparison over the two engines that completed the full "
        "benchmark, in the same format and with the same paired-set and "
        "query-set conventions as Table~\\ref{tab:comparacao_3_engines}."
    ),
    "concordancia_engines": (
        "Direction-of-effect agreement across engines, per technique: the sign "
        "of the median relative improvement on each engine and whether all "
        "engines agree. The denominator is all nine techniques of the study "
        "and an indeterminate result counts as non-agreement --- the "
        "denominator is never reduced to the measurable subset. Disagreements "
        "are further split into \\emph{inversion} (opposite signs) and "
        "\\emph{attenuation} (effect present on one engine, null on another), "
        "since the two support different claims."
    ),
    "comprimento_transformacao": (
        "Length change of the transformed source per technique (median over "
        "the 525 queries, in words, against the original source), alongside "
        "the median visibility change each engine measures. The "
        "transformation is performed once and reused across engines, so the "
        "length column is engine-independent. Across the nine techniques, "
        "length change and visibility change are strongly rank-correlated: "
        "$\\rho = +0.80$ ($p = 0.014$) on gemini, $+0.73$ ($p = 0.031$) on "
        "haiku and $+0.67$ ($p = 0.059$) on luna, exact permutation $p$ with "
        "critical $|\\rho| = 0.700$. See \\S\\ref{sec:results-length} for what "
        "this does and does not confound."
    ),
    "abstencao_pegadinhas": (
        "Abstention on the 25 pitfall queries, by technique and engine: the "
        "share of generated answers in which the engine states that the "
        "provided sources do not answer the question. At baseline all three "
        "engines abstain in $100\\%$ of answers; every figure below that is "
        "erosion of a correct refusal. Detection is by lexical pattern over "
        "PT-BR refusal phrasings, hand-checked on a sample --- not a "
        "validated classifier (\\S\\ref{sec:limitations}); it is reliable here "
        "only because the baseline refusal is a near-verbatim fixed phrase."
    ),
    "spearman_engines": (
        "Pairwise Spearman rank correlation between engines over the "
        "nine-technique vector of median relative improvements. The $p$ is "
        "exact --- the permutation null over the $9!$ orderings is enumerated "
        "in full, since the asymptotic approximation is not valid at $n=9$. "
        "\\textbf{No pair reaches significance}: the critical $|\\rho|$ is "
        "$0.700$ (lower where ties in the ranks shrink the null), above every "
        "$\\rho$ observed here. These correlations are reported for "
        "completeness and support no claim about ordering; the "
        "per-technique effects and their intervals "
        "(Table~\\ref{tab:concordancia_engines}) are what this study leans on."
    ),
}

# `comparacao_engines` (de src/cross_validate.py) foi REMOVIDA desta tabela em
# 2026-08-12: o cross_validate.py ficou obsoleto quando o estudo passou a rodar
# o benchmark completo em 3 engines, e o main.tex já não faz \IfFileExists nela.
# Mantê-la aqui deixaria aberto um caminho para números de um experimento que
# não existe mais entrarem no paper. Ver PROGRESS.md.

ALL_NAMES = list(KNOWN_TABLES.keys())

# Tabelas cujo .csv de origem não vive direto em --csv-dir, mas num
# subdiretório dele (ex.: results/cross_validation/comparacao_engines.csv,
# gerado por src/cross_validate.py, não por src/aggregate.py). convert_one()
# tenta csv_dir/SUBDIR/name.csv primeiro e cai para csv_dir/name.csv se não
# existir — assim tanto `--csv-dir results` (default) quanto `--csv-dir
# results/cross_validation` funcionam.
TABLE_SUBDIR = {
    # O par fechado gemini×haiku (525/525 nos dois, sem marcador PARCIAL) vive
    # em results/par_gemini_haiku/, não na raiz de results/ — a raiz guarda a
    # versão 3-engines. Sem esta entrada, `--only comparacao_2_engines` não
    # acharia o .csv.
    "comparacao_2_engines": "par_gemini_haiku",
}

# Marcador de resultado provisório, escrito por src/compare_engines.py nas linhas
# de metadado "#" do .csv quando algum engine ainda não terminou o dataset.
# Caixa alta e exata de propósito: não deve casar com a palavra "parcial" em
# prosa qualquer.
_PARCIAL_MARKER = "PARCIAL"


def csv_marcado_parcial(meta_lines):
    return any(_PARCIAL_MARKER in line for line in meta_lines)


# ---------------------------------------------------------------------------
# PAPER_VIEW — a visão CURADA de cada tabela para o paper.
#
# O .csv é o dataset e continua completo: nada aqui o altera. O que se recorta é
# só o que vai impresso. Motivo, medido: com ~20 colunas o \resizebox encolhe a
# fonte para ~3pt e a tabela "cabe" na página sendo ilegível (as 10 tabelas
# somavam 1 página de aumento — ver PROGRESS.md 2026-08-12).
#
# `columns`: chaves na ordem em que devem sair. Chave inexistente é ERRO, nunca
#            omissão silenciosa — as colunas do aggregate.py vão mudar de novo, e
#            uma view que emite 6 de 8 colunas pedidas parece completa.
# `filter`:  {coluna: valor} para recortar linhas. Filtro que não casa com linha
#            nenhuma também é ERRO (tabela vazia parece "sem efeito").
# Toda tabela recortada leva na legenda uma frase dizendo o que foi recortado e
# onde está a versão completa — tabela curada não pode se passar por completa.
# ---------------------------------------------------------------------------

_CELL_ESSENCIAL = [
    "n_queries", "baseline_mean", "tecnica_mean",
    "melhoria_mediana_pct", "melhoria_mediana_ci_lo", "melhoria_mediana_ci_hi",
    "sig_mediana",
    # A média entra APESAR de a convenção do estudo ser "mediana lidera": o
    # paper promete que a média acompanha, e discute mediana vs média onde a
    # escolha muda a conclusão (§5.5). Se ela não aparecer em tabela nenhuma
    # do PDF, essa discussão fica sem o número que a sustenta.
    "melhoria_media_pct",
]

# Versão enxuta, para as tabelas que já são LONGAS: sem `longtable` não há
# \resizebox para corrigir a largura, então cada coluna a mais vira estouro de
# margem medido (207pt além, na primeira tentativa). Saem as médias absolutas
# de baseline/técnica — a Eq. 4 é a grandeza que essas tabelas discutem, e os
# absolutos continuam no .csv.
_CELL_ENXUTO = [
    "n_queries",
    "melhoria_mediana_pct", "melhoria_mediana_ci_lo", "melhoria_mediana_ci_hi",
    "sig_mediana",
]

PAPER_VIEW = {
    # Tabela principal: mantém os DOIS conjuntos e as DUAS métricas — é a tabela
    # em que o §3.5 promete `baseline_pos` e `todas` lado a lado. 36 linhas.
    "tabela_principal": {
        "columns": ["conjunto", "tecnica", "metrica"] + _CELL_ESSENCIAL
                   + ["sig_holm"],
    },
    # Comparação entre engines: os dois conjuntos, só a métrica primária (a wc
    # fica no .csv). Inclui a citação zerada, que é o mecanismo do achado.
    "comparacao_3_engines": {
        "filter": {"metrica": "pwc"},
        # sem `n_queries`: a coluna de Holm entrou e a 10a coluna estourou a
        # margem (longtable não tem \resizebox). O n por conjunto está no
        # cabeçalho do .csv e na legenda, e é o mesmo em toda linha do
        # conjunto — é a coluna mais barata de perder.
        # Sai também `sig_mediana` (o teste NÃO corrigido): com Holm e BH ao
        # lado, três colunas de significância para a mesma célula é redundância
        # que custa margem. O IC continua na tabela, então o leitor vê o teste
        # bruto — é exatamente "o intervalo exclui zero?".
        "columns": ["conjunto", "tecnica", "engine"]
                   + [c for c in _CELL_ENXUTO
                      if c not in ("n_queries", "sig_mediana")]
                   + ["sig_holm", "sig_bh", "pct_citacao_zerada"],
    },
    "comparacao_2_engines": {
        "filter": {"metrica": "pwc"},
        "columns": ["conjunto", "tecnica", "engine"] + _CELL_ENXUTO
                   + ["pct_citacao_zerada"],
    },
    # Concordância já vem na forma certa (uma linha por técnica, engines em
    # coluna): só se cortam as colunas auxiliares.
    "concordancia_engines": {
        "columns": None,  # preenchido em runtime: depende dos engines presentes
        "columns_prefix": ["conjunto", "metrica", "tecnica"],
        "columns_por_engine": ["melhoria_mediana_pct__", "sig__"],
        "columns_suffix": ["mesma_direcao", "tipo_divergencia",
                           "efeito_sig_em_todos", "n_efetivo_min"],
    },
    # Quebras: só o conjunto primário e a métrica primária — são análises de
    # apoio, e o cruzamento completo (2 conjuntos × 2 métricas) vive no .csv.
    "quebra_por_setor": {
        "filter": {"conjunto": "baseline_pos", "metrica": "pwc"},
        "columns": ["setor", "tecnica"] + _CELL_ESSENCIAL,
    },
    "quebra_por_posicao": {
        "filter": {"conjunto": "baseline_pos", "metrica": "pwc"},
        "columns": ["target_pos", "tecnica"] + _CELL_ENXUTO
                   + ["paper_valor_pct", "direcao_replica_pos"],
    },
    "comparacao_paper": {
        "columns": ["conjunto", "tecnica", "paper_pawc_overall", "paper_delta_pct",
                    "nosso_melhoria_mediana_pct", "nosso_melhoria_mediana_ci_lo",
                    "nosso_melhoria_mediana_ci_hi", "nosso_n_queries",
                    "sig_mediana", "direcao_replica"],
    },
    # Spearman: com as colunas de significância exata a tabela foi de 7 para 10
    # colunas e o \resizebox começou a encolher demais. Cortam-se as duas
    # constantes (n_tecnicas=9 em toda linha, tecnicas_excluidas vazio) — o n
    # está na legenda, e o .csv continua com tudo. As colunas que NÃO se cortam
    # são p_exato/rho_critico/sig_spearman: são o ponto da tabela.
    "spearman_engines": {
        "columns": ["conjunto", "metrica", "engine_a", "engine_b", "spearman",
                    "p_exato", "rho_critico", "sig_spearman"],
    },
    # tabela_custo (11 linhas) e inducao_pegadinhas (18) já cabem: sem view,
    # saem inteiras.
}

# Acima deste número de linhas, a tabela sai como `longtable` (quebra entre
# páginas, cabeçalho repetido) em vez de `table`+`\resizebox`. Um float NÃO
# quebra página: acima do limiar o \resizebox era forçado a espremer a tabela
# inteira na altura de uma página, que é como 180 linhas viravam fonte de ~3pt.
# ~40 linhas de corpo é o que cabe numa página a4, margem 1in, a 11pt com \small.
MAX_LINHAS_FLOAT = 40


# Rótulos curtos e em inglês para a visão do paper. As CHAVES do .csv são
# snake_case e longas de propósito (estáveis para parsing); impressas, elas são
# o que estoura a largura — `melhoria_mediana_pct__gemini-3.5-flash-lite` tem 42
# caracteres. Isto é troca de RÓTULO, não de dado: o .csv não muda.
_LABEL_COLUNA = {
    "conjunto": "set", "tecnica": "technique", "metrica": "metric",
    "engine": "engine", "setor": "sector", "target_pos": "rank",
    "n_queries": "n", "baseline_mean": "base.", "tecnica_mean": "tech.",
    "melhoria_mediana_pct": "median \\%",
    "melhoria_mediana_ci_lo": "CI lo", "melhoria_mediana_ci_hi": "CI hi",
    "sig_mediana": "CI excl.\\ 0", "pct_citacao_zerada": "\\% zeroed",
    "melhoria_media_pct": "mean \\%",
    "sig_holm": "sig.\\ (Holm)", "sig_bh": "sig.\\ (BH)",
    "p_bh_mediana": "$p$ (BH)", "p_boot_mediana": "$p$",
    "p_holm_mediana": "$p$ (Holm)",
    "mesma_direcao": "agree", "tipo_divergencia": "divergence",
    "efeito_sig_em_todos": "sig.\\ all", "n_efetivo_min": "n eff.",
    "paper_valor_pct": "paper \\%", "direcao_replica_pos": "replicates",
    "direcao_replica": "replicates", "sig_media": "CI excl.\\ 0 (mean)",
    "paper_pawc_overall": "paper PAWC", "paper_delta_pct": "paper $\\Delta$\\%",
    "nosso_melhoria_mediana_pct": "our median \\%",
    "nosso_melhoria_mediana_ci_lo": "CI lo",
    "nosso_melhoria_mediana_ci_hi": "CI hi",
    "nosso_n_queries": "n",
    "engine_a": "engine A", "engine_b": "engine B",
    "spearman": "$\\rho$", "p_exato": "exact $p$",
    "rho_critico": "crit.\\ $|\\rho|$", "sig_spearman": "$\\rho \\neq 0$",
    "n_tecnicas": "n tech.", "tecnicas_excluidas": "excluded",
}

# Engines: o slug completo como cabeçalho de coluna é impagável em largura.
_LABEL_ENGINE = {
    "gemini-3.5-flash-lite": "gemini",
    "claude-haiku-4-5": "haiku",
    "gpt-5.6-luna": "luna",
}

_LABEL_PREFIXO = {
    "melhoria_mediana_pct__": "{} med.\\ \\%",
    "sig__": "{} CI",
    "sinal__": "{} sign",
}

# Valores enumerados: o pipeline os escreve em português, e o paper é em inglês.
# Correspondência EXATA apenas — valor desconhecido passa intacto, nunca é
# adivinhado. Isto é rótulo de exibição, o .csv continua com o valor original.
_LABEL_VALOR = {
    "sim (efeito positivo)": "yes ($+$)",
    "sim (efeito negativo)": "yes ($-$)",
    "não (IC cruza zero)": "no",
    "n insuficiente": "n/a",
    "sim (induz citação)": "yes",
    "não (reduz citação — inesperado)": "no (reduces)",
    "não distinguível de zero": "no",
    "não comparável": "n/a",
    "indefinido": "undef.",
    # Rótulos da correção de multiplicidade. Sem estas entradas o valor sai em
    # português e longo ("não primário (exploratório)"), estourando a margem da
    # longtable — que não tem \resizebox para absorver.
    "não (Holm)": "no", "não primário (exploratório)": "expl.",
    # Valores de dado que o pipeline escreve em português. O paper é em inglês;
    # deixá-los crus fazia a tabela alternar de idioma célula a célula. As
    # CHAVES do .csv seguem em português — o dado publicado não muda de nome
    # por causa da tradução da tabela.
    "pareado": "paired", "todas": "all", "saude": "health",
    "juridico": "legal", "imobiliario": "real estate",
    "sensibilidade (não corrigido)": "sens.",
    "inversao": "inversion", "atenuacao": "attenuation",
    "sim": "yes", "nao": "no", "não": "no", "NAO": "NO",
    "positivo": "$+$", "negativo": "$-$", "nulo": "0",
    "não medido": "n/a",
}


def label_coluna(chave):
    if chave in _LABEL_COLUNA:
        return _LABEL_COLUNA[chave]
    for prefixo, molde in _LABEL_PREFIXO.items():
        if chave.startswith(prefixo):
            slug = chave[len(prefixo):]
            return molde.format(_LABEL_ENGINE.get(slug, escape_latex(slug)))
    return escape_latex(chave)


def _resolve_columns(name, view, header):
    """Colunas da view, com as por-engine expandidas a partir do header real."""
    if view.get("columns") is not None:
        return list(view["columns"])
    cols = list(view.get("columns_prefix", []))
    for prefixo in view.get("columns_por_engine", []):
        cols.extend(h for h in header if h.startswith(prefixo))
    cols.extend(view.get("columns_suffix", []))
    return cols


def apply_paper_view(name, header, rows):
    """(header, rows, nota_legenda). Sem view registrada, devolve tudo intacto."""
    view = PAPER_VIEW.get(name)
    if not view or header is None:
        return header, rows, None

    filtro = view.get("filter") or {}
    idx = {h: i for i, h in enumerate(header)}
    for chave in filtro:
        if chave not in idx:
            raise KeyError(
                f"PAPER_VIEW[{name!r}]: coluna de filtro {chave!r} não existe no "
                f"CSV (colunas: {header}). Corrija a view — filtrar por coluna "
                "inexistente produziria uma tabela silenciosamente errada."
            )
    filtradas = [
        r for r in rows
        if all(idx[k] < len(r) and r[idx[k]].strip() == v for k, v in filtro.items())
    ]
    if filtro and not filtradas:
        raise ValueError(
            f"PAPER_VIEW[{name!r}]: o filtro {filtro} não casou com nenhuma linha "
            f"de {len(rows)} — tabela vazia parece 'sem efeito'. Corrija a view."
        )

    colunas = _resolve_columns(name, view, header)
    faltando = [c for c in colunas if c not in idx]
    if faltando:
        raise KeyError(
            f"PAPER_VIEW[{name!r}]: coluna(s) {faltando} não existe(m) no CSV "
            f"(colunas: {header}). Emitir só as encontradas produziria uma tabela "
            "que PARECE completa — corrija a view."
        )

    novo_header = list(colunas)
    novas_rows = [[r[idx[c]] if idx[c] < len(r) else "" for c in colunas]
                  for r in filtradas]

    # Tudo que vem de dado (chaves, valores, nome do arquivo) passa por
    # escape_latex antes de entrar na legenda: `baseline_pos` e
    # `tabela_principal` têm `_`, que é modo matemático em LaTeX e quebra a
    # compilação. Só a marcação fixa (\textbf, \texttt) é escrita literal.
    partes = []
    if filtro:
        partes.append("rows restricted to " + ", ".join(
            f"\\texttt{{{escape_latex(k)}={escape_latex(v)}}}"
            for k, v in filtro.items()))
    if len(colunas) < len(header):
        partes.append(f"{len(colunas)} of {len(header)} columns shown")
    nota = None
    if partes:
        nota = ("\\textbf{Paper view:} " + "; ".join(partes)
                + ". The complete table is released in "
                + f"\\texttt{{results/{escape_latex(name)}.csv}}.")
    return novo_header, novas_rows, nota


_META_RE_VERSION = re.compile(r"vers[aã]o do experimento:\s*`([^`]*)`", re.IGNORECASE)
_META_RE_MODEL = re.compile(r"model_version\(s\) nos traces:\s*`([^`]*)`", re.IGNORECASE)
_META_RE_DATE = re.compile(r"gerado em \(UTC\):\s*(.+)", re.IGNORECASE)

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    # Não-ASCII que o pipeline escreve nos DADOS. Sem estas entradas o caractere
    # simplesmente NÃO EXISTE na fonte (ptmr8t) e o pdflatex o descarta com um
    # aviso "Missing character" no meio de milhares de linhas de log: a célula
    # sai VAZIA no PDF, e vazio lê-se como dado faltando, não como "não se
    # aplica". Aconteceu com o travessão em `tipo_divergencia` e
    # `tecnicas_excluidas`. Foi encontrado à mão; se aparecer outro caractere,
    # o lugar de resolver é aqui.
    "\u2014": "---",   # travessão (marcador de "não se aplica" no .csv)
    "\u2013": "--",    # meia-risca
    "\u2192": r"$\rightarrow$",
    "\u00b1": r"$\pm$",
    "\u03c1": r"$\rho$",
}

_NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d+)?%?$")


def escape_latex(s):
    if s is None:
        return ""
    s = str(s)
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in s)


def _fmt_num_paper(txt):
    """Precisão de leitura para a visão do paper. O .csv guarda 6 casas
    (aggregate.py::_val_csv) porque é dado; impressas, viram ruído
    (`-74.563636`). A precisão acompanha a magnitude, de modo que percentuais
    saem com 1-2 casas e visibilidades absolutas (~0,001) mantêm 4. Devolve
    None se não for número — inteiros (n, rank) passam intactos por não terem
    ponto decimal."""
    if "." not in txt:
        return None
    try:
        v = float(txt)
    except ValueError:
        return None
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 100:
        return f"{v:.1f}"
    if a >= 10:
        return f"{v:.2f}"
    if a >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


def _fmt_cell(raw, rotular=False):
    """Célula vazia (None em Python, via aggregate.py::_val_csv) -> 'n/d',
    seguindo a mesma convenção usada nos .md (aggregate.py::_fmt_md).
    Com `rotular`, valores enumerados conhecidos viram o rótulo em inglês (já em
    LaTeX, por isso não passam por escape); qualquer outro valor é escapado
    normalmente e nunca adivinhado."""
    if raw is None or raw.strip() == "":
        return "n/d"
    if rotular and raw.strip() in _LABEL_VALOR:
        return _LABEL_VALOR[raw.strip()]
    if rotular:
        num = _fmt_num_paper(raw.strip())
        if num is not None:
            return num
    return escape_latex(raw)


def parse_csv_file(path):
    """Retorna (meta_lines, header, rows) — meta_lines em qualquer posição no
    arquivo (antes E/OU depois dos dados), header e rows só das linhas que não
    começam com '#'."""
    meta_lines = []
    data_lines = []
    with open(path, encoding="utf-8", newline="") as f:
        for raw_line in f:
            stripped = raw_line.lstrip()
            if stripped.startswith("#"):
                meta_lines.append(stripped[1:].strip("\n").strip())
            else:
                data_lines.append(raw_line)
    if not data_lines:
        return meta_lines, None, []
    reader = csv.reader(data_lines)
    rows = [r for r in reader if r]
    if not rows:
        return meta_lines, None, []
    header, *data = rows
    return meta_lines, header, data


def extract_meta(meta_lines):
    versao = model = data_geracao = None
    for line in meta_lines:
        m = _META_RE_VERSION.search(line)
        if m:
            versao = m.group(1).strip()
        m = _META_RE_MODEL.search(line)
        if m:
            model = m.group(1).strip()
        m = _META_RE_DATE.search(line)
        if m:
            data_geracao = m.group(1).strip()
    return versao, model, data_geracao


def _column_alignment(header, rows):
    aligns = []
    for i in range(len(header)):
        vals = [r[i] for r in rows if i < len(r) and r[i].strip()]
        if vals and all(_NUMERIC_RE.match(v.strip()) for v in vals):
            aligns.append("r")
        else:
            aligns.append("l")
    return aligns


# Colunas que identificam a LINHA: repetem-se em toda fatia, senão a fatia 2
# vira uma lista de números sem dizer de quê.
_COLS_CHAVE = ("conjunto", "metrica", "tecnica", "engine", "setor",
               "target_pos", "n_queries", "n_pegadinhas")
# Orçamento em CARACTERES por fatia, não em número de colunas: o que estoura a
# margem é a largura, e uma coluna de texto ("sensibilidade (não corrigido)")
# vale por três de número. Calibrado medindo o overfull em \tiny.
BUDGET_CHARS_FATIA = 190


def _largura_col(coluna, header, rows):
    i = header.index(coluna)
    return max([len(coluna)] + [len(str(r[i] if r[i] is not None else "")) for r in rows]) + 2


def _fatia_por_colunas(name, header, rows):
    """[(header_fatia, rows_fatia, sufixo_label, texto_extra_da_legenda)]."""
    chaves = [c for c in header if c in _COLS_CHAVE]
    resto = [c for c in header if c not in chaves]
    larg = {c: _largura_col(c, header, rows) for c in header}
    orcamento = max(20, BUDGET_CHARS_FATIA - sum(larg[c] for c in chaves))
    blocos, atual, usado = [], [], 0
    for c in resto:
        if atual and usado + larg[c] > orcamento:
            blocos.append(atual); atual, usado = [], 0
        atual.append(c); usado += larg[c]
    if atual:
        blocos.append(atual)
    blocos = blocos or [[]]
    saida = []
    for k, bloco in enumerate(blocos, 1):
        cols = chaves + bloco
        idx = [header.index(c) for c in cols]
        rs = [[r[i] for i in idx] for r in rows]
        extra = ("" if len(blocos) == 1 else
                 f" \\textbf{{Part {k} of {len(blocos)}}} of the complete table; "
                 f"the identifying columns repeat in every part.")
        saida.append((cols, rs, f"_full{k}" if len(blocos) > 1 else "_full", extra))
    return saida


def build_latex_table(name, meta_lines, header, rows, caption_override=None,
                      compacto=False, sufixo_label=None, caption_extra='',
                       nota_view=None, rotular=False):
    versao, model, data_geracao = extract_meta(meta_lines)
    generated_now = datetime.now(timezone.utc).isoformat()

    lines = []
    lines.append(f"% Auto-generated by scripts/csv_to_latex.py from results/{name}.csv")
    lines.append("% DO NOT EDIT BY HAND — see paper/draft/tables/README.md")
    lines.append(f"% source experiment version (versao_experimento): {versao or 'n/d'}")
    lines.append(f"% model_version(s) in traces: {model or 'n/d'}")
    lines.append(f"% data aggregated (UTC, from results/{name}.csv header): {data_geracao or 'n/d'}")
    lines.append(f"% this .tex file generated (UTC): {generated_now}")
    lines.append("")

    if header is None or not rows:
        lines.append(f"% NOTE: results/{name}.csv had no data rows when this file was generated.")
        lines.append("\\begin{center}")
        lines.append(
            "\\TODO{Table `" + escape_latex(name) + "` has no data yet --- "
            "run \\texttt{python src/aggregate.py} against real traces and re-run \\texttt{make tables}.}"
        )
        lines.append("\\end{center}")
        return "\n".join(lines) + "\n"

    aligns = _column_alignment(header, rows)
    col_spec = "".join(aligns)
    caption = caption_override or KNOWN_TABLES.get(name, f"Table: {escape_latex(name)} (auto-generated).")
    if nota_view:
        caption = f"{caption} {nota_view}"
    if caption_extra:
        caption = f"{caption}{caption_extra}"
    label = f"tab:{name}{sufixo_label or ''}"
    n_col = len(header)
    _rot = label_coluna if rotular else escape_latex
    titulos = " & ".join(f"\\textbf{{{_rot(h)}}}" for h in header) + " \\\\"

    def linhas_de_dado():
        # Linhas mal formadas (menos colunas que o header) são preenchidas com
        # 'n/d' em vez de quebrar a tabela (mesma disciplina de robustez do
        # resto do pipeline — regra 8 do TASK.md: dado ruim não derruba a run).
        for row in rows:
            cells = [row[i] if i < len(row) else "" for i in range(n_col)]
            yield " & ".join(_fmt_cell(c, rotular) for c in cells) + " \\\\"

    if len(rows) > MAX_LINHAS_FLOAT:
        # longtable NÃO é float: não aceita [htbp], a legenda e o \label vão
        # DENTRO do ambiente, e o cabeçalho precisa de \endfirsthead/\endhead
        # para se repetir nas páginas de continuação. E sem \resizebox — é
        # justamente ele que esmagava a fonte para caber a tabela numa página.
        lines.append(f"% {len(rows)} linhas > MAX_LINHAS_FLOAT={MAX_LINHAS_FLOAT}:"
                     " emitida como longtable (quebra entre páginas).")
        # \small vai num GRUPO em volta, nunca dentro do ambiente: dentro do
        # longtable já se está em contexto de linha, e um comando de fonte ali
        # desalinha o \noalign do \toprule ("Misplaced \noalign").
        # No apêndice (tabela COMPLETA, até 26 colunas) o footnotesize/2pt não
        # basta: longtable não tem \resizebox para absorver o excesso, então a
        # única saída é fonte e espaçamento menores. No corpo continua
        # footnotesize, que é legível.
        tam, colsep = ("\\tiny", "1pt") if compacto else ("\\footnotesize", "2pt")
        lines.append("{" + tam + "\\setlength{\\tabcolsep}{" + colsep + "}")
        lines.append("\\begin{longtable}{" + col_spec + "}")
        lines.append(f"\\caption{{{caption}}}\\label{{{label}}}\\\\")
        lines.append("\\toprule")
        lines.append(titulos)
        lines.append("\\midrule")
        lines.append("\\endfirsthead")
        lines.append(f"\\multicolumn{{{n_col}}}{{l}}{{\\small\\itshape "
                     "Table \\thetable\\ -- continued from previous page}\\\\")
        lines.append("\\toprule")
        lines.append(titulos)
        lines.append("\\midrule")
        lines.append("\\endhead")
        lines.append("\\midrule")
        lines.append(f"\\multicolumn{{{n_col}}}{{r}}{{\\small\\itshape "
                     "continued on next page}\\\\")
        lines.append("\\endfoot")
        lines.append("\\bottomrule")
        lines.append("\\endlastfoot")
        lines.extend(linhas_de_dado())
        lines.append("\\end{longtable}")
        lines.append("}")
        return "\n".join(lines) + "\n"

    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\small")
    lines.append("\\resizebox{\\textwidth}{!}{%")
    lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
    lines.append("\\toprule")
    lines.append(titulos)
    lines.append("\\midrule")
    lines.extend(linhas_de_dado())
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}%")
    lines.append("}")
    lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append("\\end{table}")
    return "\n".join(lines) + "\n"


def _resolve_csv_path(name, csv_dir):
    """csv_dir/SUBDIR/name.csv se TABLE_SUBDIR[name] existir e o arquivo
    estiver lá; senão csv_dir/name.csv (caminho "direto", como as tabelas de
    src/aggregate.py, ou --csv-dir já apontando pro subdiretório)."""
    csv_dir = Path(csv_dir)
    subdir = TABLE_SUBDIR.get(name)
    if subdir:
        subdir_path = csv_dir / subdir / f"{name}.csv"
        if subdir_path.exists():
            return subdir_path
    return csv_dir / f"{name}.csv"


def convert_one(name, csv_dir, tables_dir, force=False, full=False):
    """Retorna o Path do .tex escrito, None se pulado por CSV ausente, ou
    False se BLOQUEADO por marcador PARCIAL (o chamador distingue: ausente é
    esperado antes da Fase 4; bloqueado é uma parada que o humano precisa ver)."""
    csv_path = _resolve_csv_path(name, csv_dir)
    tables_dir = Path(tables_dir)
    # As tabelas completas vão para um subdiretório em vez de sobrescrever a
    # versão do corpo do paper: as duas convivem, e o apêndice inclui estas.
    # Sem isso, `--full` destruía a tabela recortada e o paper passava a
    # embutir a tabela inteira no meio do texto.
    if full:
        tables_dir = tables_dir / "full"
    tables_dir.mkdir(parents=True, exist_ok=True)
    tex_path = tables_dir / f"{name}.tex"

    if not csv_path.exists():
        print(f"[csv_to_latex] AVISO: {csv_path} não existe — pulando "
              f"(rode src/aggregate.py ou src/cross_validate.py primeiro). "
              f"Nenhum .tex escrito para '{name}'.")
        return None

    meta_lines, header, rows = parse_csv_file(csv_path)

    # GATE DO PARCIAL. main.tex inclui as tabelas com \IfFileExists: o arquivo
    # EXISTIR já basta para os números entrarem no paper, sem nenhuma marcação
    # de que são provisórios. Por isso o bloqueio vive aqui, no conversor, e não
    # no Makefile: assim vale para todo caminho de chamada (make, execução
    # direta do script, sessão futura que não leu o CLAUDE.md).
    if csv_marcado_parcial(meta_lines) and not force:
        print(f"[csv_to_latex] BLOQUEADO: {csv_path} está marcado {_PARCIAL_MARKER} "
              f"(nem todos os engines terminaram o dataset). Nenhum .tex escrito "
              f"para '{name}' — números provisórios entrariam no paper sem marcação, "
              f"porque main.tex usa \\IfFileExists. Regenere o .csv quando a run "
              f"fechar, ou use --force se souber exatamente o que está fazendo.")
        if tex_path.exists():
            print(f"[csv_to_latex]   ⚠️  ATENÇÃO: já existe {tex_path} de uma geração "
                  f"anterior, e o main.tex VAI incluí-lo. Se ele não veio de dado "
                  f"final, remova-o: rm {tex_path}")
        return False

    if csv_marcado_parcial(meta_lines) and force:
        print(f"[csv_to_latex] AVISO: {csv_path} está marcado {_PARCIAL_MARKER} e "
              f"--force foi passado — gerando .tex PROVISÓRIO para '{name}'.")

    n_bruto = len(rows)
    nota_view = None
    if not full:
        header, rows, nota_view = apply_paper_view(name, header, rows)

    if full:
        # As tabelas completas chegam a 26 colunas. Não cabem na página nem em
        # paisagem (medido: pdflscape não alarga o bloco de texto, e
        # \newgeometry ignora `landscape` dentro do documento). A saída correta
        # é FATIAR POR COLUNAS, repetindo as colunas-chave em cada fatia, de
        # modo que qualquer linha possa ser lida inteira juntando as partes.
        tex = "\n".join(
            # rotular=True também no apêndice: o que a tabela completa entrega
            # é o DADO completo, não rótulo cru. Deixar "sensibilidade (não
            # corrigido)" por extenso fazia o apêndice trocar de idioma em
            # relação ao corpo — e, de quebra, era o que mais gastava largura.
            build_latex_table(name, meta_lines, h, rs, rotular=True,
                              compacto=True, sufixo_label=suf,
                              caption_extra=extra)
            for h, rs, suf, extra in _fatia_por_colunas(name, header, rows)
        )
    else:
        tex = build_latex_table(name, meta_lines, header, rows,
                                 nota_view=nota_view, rotular=True)
    tex_path.write_text(tex, encoding="utf-8")
    recorte = "" if n_bruto == len(rows) else f", recortado de {n_bruto}"
    forma = "longtable" if len(rows) > MAX_LINHAS_FLOAT else "table"
    print(f"[csv_to_latex] {csv_path} -> {tex_path} "
          f"({len(rows)} linha(s){recorte}, {len(header or [])} col, {forma})")
    return tex_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="all",
                     help=f"nome (ou lista separada por vírgula) entre {ALL_NAMES}, ou 'all'")
    ap.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR),
                     help="diretório com os .csv de entrada (default: results/)")
    ap.add_argument("--tables-dir", default=str(DEFAULT_TABLES_DIR),
                     help="diretório de saída dos .tex (default: paper/draft/tables/)")
    ap.add_argument("--full", action="store_true",
                     help="ignora PAPER_VIEW e emite o .csv inteiro (todas as "
                          "colunas e linhas) — útil para conferência, não para o paper")
    ap.add_argument("--force", action="store_true",
                     help="gera o .tex mesmo se o .csv estiver marcado PARCIAL "
                          "(números provisórios entram no paper sem marcação — "
                          "só use deliberadamente)")
    args = ap.parse_args()

    if args.only == "all":
        names = ALL_NAMES
    else:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        desconhecidos = [n for n in names if n not in ALL_NAMES]
        if desconhecidos:
            ap.error(f"tabela(s) desconhecida(s): {desconhecidos} — válidas: {ALL_NAMES}")

    written, bloqueadas = [], []
    for name in names:
        path = convert_one(name, args.csv_dir, args.tables_dir,
                            force=args.force, full=args.full)
        if path:
            written.append(path)
        elif path is False:
            bloqueadas.append(name)

    print(f"[csv_to_latex] concluído — {len(written)}/{len(names)} tabela(s) escrita(s) em {args.tables_dir}")
    if bloqueadas:
        # Saída não-zero de propósito: `make tables` tem de FALHAR, não passar
        # em silêncio. Um bloqueio despercebido é o mesmo que não ter bloqueio.
        print(f"[csv_to_latex] ERRO: {len(bloqueadas)} tabela(s) bloqueada(s) por "
              f"marcador {_PARCIAL_MARKER}: {', '.join(bloqueadas)}")
        sys.exit(1)
    if len(written) < len(names):
        print("[csv_to_latex] NOTA: tabelas ausentes ficam sem .tex — main.tex deve usar "
              "\\IfFileExists para não quebrar a compilação (ver paper/draft/main.tex).")
        sys.exit(0)  # ausência de CSV não é erro fatal do conversor — é esperado antes da Fase 4


if __name__ == "__main__":
    main()
