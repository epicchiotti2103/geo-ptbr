# Makefile — paper/draft/ (GEO-PTBR)
#
# Targets:
#   make tables   — regenerate tables/*.tex from results/*.csv
#                   (results/*.csv itself comes from src/aggregate.py against
#                   eval/traces/*.jsonl — never hand-edited, see tables/README.md)
#   make pdf      — compile (DEFAULT: plain `make` does this, never `tables`)
#   make clean    — remove LaTeX build artifacts only (never touches tables/*.tex
#                   or refs.bib — those are source/generated inputs, not build output)
#
# NOTE: `make pdf` does NOT depend on `make tables`. main.tex guards every
# \input with \IfFileExists, so it compiles standalone (with \TODO markers)
# even before any table has been generated — run `make tables` explicitly
# once results/*.csv exists.
#
# TeX ENGINE: `make pdf` prefers the pdflatex+bibtex cycle this project's spec
# asked for, and falls back to `tectonic` (self-contained, `brew install
# tectonic`; runs BibTeX itself) when pdflatex is absent — which is the case on
# this machine. It prints which engine it used. Neither is bundled; if both are
# missing the target fails with install instructions rather than silently
# producing nothing.
#
# HISTÓRICO (2026-08-12): a primeira regra deste arquivo era `tables`, o que
# fazia `make` sozinho REGENERAR as tabelas — e foi assim que 6 .tex de dado
# provisório entraram em tables/ por acidente. Daí o .DEFAULT_GOAL abaixo, e o
# gate de PARCIAL dentro de scripts/csv_to_latex.py.

ROOT    := ../..
PYTHON  := .venv/bin/python
MAIN    := main

# `make` sozinho compila o PDF; NUNCA regenera tabelas. Antes, a primeira regra
# do arquivo era `tables`, então um `make` por reflexo disparava a operação mais
# perigosa do repositório (gerar tables/*.tex, que main.tex inclui por
# \IfFileExists sem marcar como provisório). Regenerar tabela é agora sempre
# explícito: `make tables`.
.DEFAULT_GOAL := pdf

.PHONY: tables pdf clean

# csv_to_latex.py recusa .csv marcado PARCIAL e sai != 0, então este alvo
# FALHA em vez de encher tables/ com número provisório. O gate vive no script,
# não aqui, para valer também quando alguém o chama direto.
tables:
	cd $(ROOT) && $(PYTHON) scripts/csv_to_latex.py

# O ciclo pdflatex+bibtex é o que o spec deste projeto pediu, e é mantido
# sempre que a ferramenta existir. Onde ela não existe (esta máquina não tem
# MacTeX/TeX Live), cai para o tectonic — que é autocontido, baixa os pacotes
# sozinho e já roda o BibTeX — em vez de simplesmente falhar. A regra imprime
# qual engine usou: o PDF nunca sai sem dizer como foi feito.
pdf:
	@if command -v pdflatex >/dev/null 2>&1; then \
	  echo "[make] engine: pdflatex + bibtex (ciclo do spec)"; \
	  pdflatex -interaction=nonstopmode -halt-on-error $(MAIN).tex && \
	  bibtex $(MAIN) && \
	  pdflatex -interaction=nonstopmode -halt-on-error $(MAIN).tex && \
	  pdflatex -interaction=nonstopmode -halt-on-error $(MAIN).tex; \
	elif command -v tectonic >/dev/null 2>&1; then \
	  echo "[make] engine: tectonic (pdflatex não encontrado; roda o BibTeX sozinho)"; \
	  tectonic -X compile $(MAIN).tex; \
	else \
	  echo "[make] ERRO: nenhum engine LaTeX encontrado."; \
	  echo "[make]   brew install tectonic        (autocontido, ~sem sudo)"; \
	  echo "[make]   brew install --cask basictex (dá pdflatex/bibtex)"; \
	  exit 1; \
	fi

clean:
	rm -f $(MAIN).aux $(MAIN).log $(MAIN).bbl $(MAIN).blg $(MAIN).out \
	      $(MAIN).toc $(MAIN).pdf $(MAIN).fls $(MAIN).fdb_latexmk \
	      $(MAIN).synctex.gz $(MAIN).bcf $(MAIN).run.xml
