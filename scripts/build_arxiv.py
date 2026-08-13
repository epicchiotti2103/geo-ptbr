#!/usr/bin/env python3
"""Monta e VALIDA o pacote-fonte para submissão ao arXiv.

Por que um script e não um `tar czf` na mão:

1. **O arXiv não roda BibTeX.** Ele compila o que você mandou; se o `.bbl` não
   estiver no pacote, o paper sai com `[?]` no lugar de toda citação. O
   `tectonic` (único engine desta máquina) roda o BibTeX sozinho e por padrão
   NÃO deixa o `.bbl` em disco — só com `--keep-intermediates`. Este script
   gera o `.bbl` a cada build, do `refs.bib` atual.

2. **`main.tex` inclui toda tabela por `\\IfFileExists`.** Um `.tex` que fique
   de fora do tarball não quebra a compilação: o paper sai com um `[TODO: ...]`
   vermelho no lugar da tabela. É a mesma classe de falha silenciosa do
   `.gitignore` que descartava o `main.pdf` do pacote público — o comando
   retorna 0 e o artefato sai errado. Por isso a validação abaixo não confia
   no `exit 0`: ela EXTRAI o tarball num diretório vazio, compila lá dentro, e
   confere página a página contra o PDF local.

Invariantes checados no PDF do clean-room (falha o build se algum quebrar):
  - mesmo número de páginas do `paper/draft/main.pdf` de referência;
  - zero ocorrências de `TODO:` no texto extraído;
  - zero ocorrências de `[?]` (citação não resolvida — o sintoma de `.bbl`
    ausente);
  - o texto extraído bate com o do PDF de referência.

Uso:
    .venv/bin/python scripts/build_arxiv.py
    .venv/bin/python scripts/build_arxiv.py --skip-validation   # escotilha

Saída: paper/arxiv/geo-ptbr-arxiv.tar.gz (+ src/ com o conteúdo, para inspeção).

NÃO submete nada. O tarball é para o humano subir em arxiv.org/submit.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "paper" / "draft"
# FORA de publish/: `scripts/build_publish.py` faz rmtree do publish/ INTEIRO
# (preservando só os .git de dentro), então um pacote do arXiv guardado lá é
# apagado em silêncio no próximo build_publish — aconteceu na primeira versão
# deste script. Aqui, ao lado do paper de onde ele sai, ninguém o remove.
OUT_DIR = ROOT / "paper" / "arxiv"
TARBALL = OUT_DIR / "geo-ptbr-arxiv.tar.gz"

# Engines LaTeX, na mesma ordem de preferência do paper/draft/Makefile.
TECTONIC = "/opt/homebrew/bin/tectonic"

# Pacotes que o main.tex carrega. Todos existem no TeX Live que o arXiv usa —
# a lista fica aqui para que uma eventual rejeição por pacote seja
# diagnosticável sem reabrir o .tex. O clean-room roda tectonic, que baixa o
# que precisa; ele prova que o PACOTE está completo, não que o TeX Live do
# arXiv tem tudo. Estes são os dois testes diferentes.
PACOTES = [
    "fontenc", "inputenc", "babel", "geometry", "times", "microtype",
    "amsmath", "amssymb", "booktabs", "longtable", "graphicx", "xcolor",
    "enumitem", "caption", "url", "pgfplots", "natbib", "hyperref",
]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _compilar(dir_: Path) -> None:
    """Compila main.tex em dir_ com tectonic, guardando os intermediários."""
    if not Path(TECTONIC).exists() and shutil.which("tectonic") is None:
        sys.exit(f"[arxiv] ERRO: tectonic não encontrado ({TECTONIC}).\n"
                 f"[arxiv]   brew install tectonic")
    exe = TECTONIC if Path(TECTONIC).exists() else "tectonic"
    r = _run([exe, "-X", "compile", "--keep-intermediates", "main.tex"], dir_)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        sys.exit(f"[arxiv] ERRO: compilação falhou em {dir_}")


def _pdf_paginas(pdf: Path) -> int:
    exe = shutil.which("pdfinfo")
    if exe is None:
        sys.exit("[arxiv] ERRO: pdfinfo ausente (brew install poppler) — "
                 "sem ele não dá para validar o pacote.")
    out = _run([exe, str(pdf)], pdf.parent).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not m:
        sys.exit(f"[arxiv] ERRO: pdfinfo não devolveu contagem de páginas de {pdf}")
    return int(m.group(1))


def _pdf_texto(pdf: Path) -> str:
    exe = shutil.which("pdftotext")
    if exe is None:
        sys.exit("[arxiv] ERRO: pdftotext ausente (brew install poppler).")
    return _run([exe, str(pdf), "-"], pdf.parent).stdout


def _fontes() -> list[Path]:
    """Arquivos que entram no tarball, relativos a paper/draft/.

    tables/ vai INTEIRO (todo .tex, nos dois níveis) em vez de só o que um
    grep de \\input encontra: grep não vê inclusão construída por macro, e o
    custo de mandar um .tex a mais é zero enquanto o de esquecer um é uma
    tabela virar [TODO] no paper publicado.
    """
    arquivos = [DRAFT / "main.tex", DRAFT / "refs.bib"]
    arquivos += sorted((DRAFT / "tables").rglob("*.tex"))
    faltando = [p for p in arquivos if not p.exists()]
    if faltando:
        sys.exit("[arxiv] ERRO: fonte ausente: "
                 + ", ".join(str(p.relative_to(ROOT)) for p in faltando))
    return arquivos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-validation", action="store_true",
                    help="não extrai nem recompila o tarball (não recomendado)")
    args = ap.parse_args()

    ref_pdf = DRAFT / "main.pdf"
    if not ref_pdf.exists():
        sys.exit("[arxiv] ERRO: paper/draft/main.pdf não existe — "
                 "rode `cd paper/draft && make` antes.")
    ref_paginas = _pdf_paginas(ref_pdf)
    ref_texto = _pdf_texto(ref_pdf)
    print(f"[arxiv] referência: paper/draft/main.pdf, {ref_paginas} páginas")

    fontes = _fontes()

    # --- .bbl: gerado agora, do refs.bib atual ------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        gen = Path(tmp)
        for p in fontes:
            dest = gen / p.relative_to(DRAFT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        print("[arxiv] gerando main.bbl (tectonic --keep-intermediates)…")
        _compilar(gen)
        bbl = gen / "main.bbl"
        if not bbl.exists() or bbl.stat().st_size == 0:
            sys.exit("[arxiv] ERRO: main.bbl não foi produzido — sem ele o "
                     "arXiv renderiza [?] no lugar de cada citação.")

        # --- staging: exatamente o que vai no tarball -----------------------
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        src = OUT_DIR / "src"
        src.mkdir(parents=True)
        for p in fontes:
            dest = src / p.relative_to(DRAFT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        shutil.copy2(bbl, src / "main.bbl")

    membros = sorted(p for p in src.rglob("*") if p.is_file())
    with tarfile.open(TARBALL, "w:gz") as tar:
        for p in membros:
            # sem diretório-raiz embrulhando: o arXiv espera main.tex na raiz
            tar.add(p, arcname=str(p.relative_to(src)))
    print(f"[arxiv] {TARBALL.relative_to(ROOT)} — {len(membros)} arquivos, "
          f"{TARBALL.stat().st_size / 1024:.0f} KiB")

    if args.skip_validation:
        print("[arxiv] validação PULADA (--skip-validation)")
        return 0

    # --- validação: extrair num diretório vazio e compilar LÁ ---------------
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        clean.mkdir()
        with tarfile.open(TARBALL) as tar:
            tar.extractall(clean)
        print(f"[arxiv] clean-room: compilando o tarball extraído em {clean}")
        _compilar(clean)
        pdf = clean / "main.pdf"

        paginas = _pdf_paginas(pdf)
        texto = _pdf_texto(pdf)
        erros = []
        if paginas != ref_paginas:
            erros.append(f"páginas: {paginas} no pacote vs {ref_paginas} na "
                         f"referência (tabela faltando no tarball?)")
        n_todo = texto.count("TODO:")
        if n_todo:
            erros.append(f"{n_todo} marcador(es) TODO no PDF — o \\IfFileExists "
                         f"engoliu um tables/*.tex que não entrou no pacote")
        n_cit = len(re.findall(r"\[\?\]", texto))
        if n_cit:
            erros.append(f"{n_cit} citação(ões) não resolvida(s) [?] — .bbl "
                         f"ausente ou desatualizado")
        if texto.split() != ref_texto.split():
            erros.append("o texto extraído do PDF do pacote difere do da "
                         "referência (compare os dois PDFs antes de submeter)")
        if erros:
            for e in erros:
                print(f"[arxiv] FALHA: {e}", file=sys.stderr)
            return 1

        print(f"[arxiv] OK: {paginas} páginas, 0 TODO, 0 citação órfã, "
              f"texto idêntico ao da referência")

    print(f"[arxiv] pacotes LaTeX exigidos: {', '.join(PACOTES)}")
    print(f"[arxiv] pronto para upload em https://arxiv.org/submit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
