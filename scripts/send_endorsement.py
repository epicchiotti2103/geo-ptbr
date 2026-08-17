#!/usr/bin/env python3
"""Envia os pedidos de endorsement da fila B pelo Resend, um a um.

Fonte da verdade dos textos é `docs/endorsement_fila_b.md`: este script PARSEIA
aquele arquivo em vez de manter uma segunda cópia das mensagens, porque duas
cópias divergem (foi assim que o README público ficou afirmando um resultado
retratado, ver CLAUDE.md). Editar o .md, rodar aqui.

Sem dependência nova: só stdlib (regra do projeto, ver requirements.txt).

    RESEND_API_KEY=... RESEND_FROM='Nome <caixa@dominio-verificado>' \
        .venv/bin/python scripts/send_endorsement.py --dry-run
    RESEND_API_KEY=... RESEND_FROM='...' \
        .venv/bin/python scripts/send_endorsement.py --send

A chave vem só do ambiente e nunca é escrita em disco nem impressa. `--dry-run`
é o padrão: sem `--send` o script não toca a rede.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "docs" / "endorsement_fila_b.md"
API = "https://api.resend.com/emails"

# Regra do Du: e-mail de contato não leva travessão nem hífen duplo, "fica na
# cara que é IA". O guard roda antes de qualquer envio.
PROIBIDOS = ("—", "–", "--")

CABECALHO = re.compile(r"^###\s+\d+\.\s+(.+?)\s+\(`([^`]+)`\)\s*$")
ASSUNTO = re.compile(r"^\*\*Assunto:\*\*\s+(.+?)\s*$")
# O código de endosso NÃO fica escrito aqui: `scripts/` inteiro é copiado para
# o pacote público por build_publish.py (CODIGO_DIRS), então um literal neste
# arquivo publicaria o código. Ele é extraído dos textos e conferido entre si.
ENDOSSO = re.compile(r"arxiv\.org/auth/endorse\?x=([A-Z0-9]+)")


@dataclass
class Mensagem:
    nome: str
    email: str
    assunto: str
    corpo: str


def carregar(caminho: Path) -> list[Mensagem]:
    """Lê os blocos '### N. Nome (`email`)' + '**Assunto:**' + ``` corpo ```."""
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    mensagens: list[Mensagem] = []
    nome = email = assunto = None
    corpo: list[str] | None = None

    for linha in linhas:
        if corpo is not None:
            if linha.strip() == "```":
                if not (nome and email and assunto):
                    raise SystemExit(f"bloco de corpo sem cabeçalho/assunto em {caminho}")
                mensagens.append(
                    Mensagem(nome, email, assunto, "\n".join(corpo).strip() + "\n")
                )
                nome = email = assunto = None
                corpo = None
            else:
                corpo.append(linha)
            continue

        cabecalho = CABECALHO.match(linha)
        if cabecalho:
            nome, email = cabecalho.group(1), cabecalho.group(2)
            assunto = None
            continue

        achou_assunto = ASSUNTO.match(linha)
        if achou_assunto and nome:
            assunto = achou_assunto.group(1)
            continue

        if linha.strip() == "```" and nome and assunto:
            corpo = []

    if corpo is not None:
        raise SystemExit(f"bloco de corpo não fechado em {caminho}")
    return mensagens


def validar(mensagens: list[Mensagem]) -> None:
    if not mensagens:
        raise SystemExit(f"nenhuma mensagem encontrada em {DRAFTS}")

    destinos = [m.email for m in mensagens]
    if len(set(destinos)) != len(destinos):
        raise SystemExit(f"destinatário repetido: {destinos}")

    for m in mensagens:
        for proibido in PROIBIDOS:
            if proibido in m.corpo or proibido in m.assunto:
                raise SystemExit(
                    f"{m.email}: travessão/hífen duplo ({proibido!r}) no texto. "
                    "Reescrever com vírgula ou ponto."
                )
        if "10.5281/zenodo.21936792" not in m.corpo:
            raise SystemExit(f"{m.email}: o corpo não traz o DOI")
        if "@" not in m.email:
            raise SystemExit(f"destinatário inválido: {m.email!r}")

    codigos = {tuple(ENDOSSO.findall(m.corpo)) for m in mensagens}
    if len(codigos) != 1 or not next(iter(codigos)):
        raise SystemExit(
            "os corpos não trazem o mesmo link de endosso: "
            f"{sorted(len(c) for c in codigos)} ocorrências por mensagem"
        )


def enviar(m: Mensagem, chave: str, remetente: str) -> str:
    """POST no Resend, preferindo `requests` quando ele existe no ambiente.

    A API do Resend fica atrás do Cloudflare, e o `urllib` puro leva 403 com
    "error code: 1010" (assinatura de cliente banida). Medido em 2026-08-17:
    seis de seis tentativas. O `requests`, que é o que o robo prospect usa em
    produção, passa. O caminho urllib fica como reserva, com User-Agent
    próprio, para o caso de rodar num ambiente sem requests.
    """
    corpo = {
        "from": remetente,
        "to": [m.email],
        "subject": m.assunto,
        "text": m.corpo,
        "reply_to": "elio.picchiotti@aeobr.com.br",
    }
    cabecalhos = {
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json",
        "User-Agent": "geo-ptbr-endorsement/1.0 (+https://github.com/epicchiotti2103/geo-ptbr)",
    }

    try:
        import requests  # noqa: PLC0415 (opcional de propósito, ver docstring)
    except ImportError:
        requests = None

    if requests is not None:
        resposta = requests.post(API, json=corpo, headers=cabecalhos, timeout=30)
        if resposta.status_code >= 400:
            raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:300]}")
        return resposta.json().get("id", "(sem id)")

    req = urllib.request.Request(
        API, data=json.dumps(corpo).encode("utf-8"), headers=cabecalhos, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resposta:
        return json.loads(resposta.read().decode("utf-8")).get("id", "(sem id)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--send", action="store_true", help="envia de verdade")
    grupo.add_argument("--dry-run", action="store_true", help="padrão: só mostra")
    parser.add_argument("--only", help="manda só para este e-mail")
    args = parser.parse_args()

    mensagens = carregar(DRAFTS)
    validar(mensagens)
    if args.only:
        mensagens = [m for m in mensagens if m.email == args.only]
        if not mensagens:
            raise SystemExit(f"nenhuma mensagem para {args.only}")

    print(f"{len(mensagens)} mensagens carregadas de {DRAFTS.relative_to(ROOT)}")
    for m in mensagens:
        print(f"  {m.nome} <{m.email}>: {m.assunto} ({len(m.corpo)} caracteres)")

    if not args.send:
        print("\n--dry-run (padrão). Nada foi enviado. Use --send para mandar.")
        return 0

    chave = os.environ.get("RESEND_API_KEY", "").strip()
    remetente = os.environ.get("RESEND_FROM", "").strip()
    if not chave:
        raise SystemExit("RESEND_API_KEY não está no ambiente")
    if not remetente:
        raise SystemExit(
            "RESEND_FROM não está no ambiente "
            "(ex.: 'Elio Picchiotti <elio.picchiotti@aeobr.com.br>')"
        )

    print(f"\nEnviando de {remetente}\n")
    falhas = 0
    for m in mensagens:
        try:
            ident = enviar(m, chave, remetente)
            print(f"  ok   {m.email}  id={ident}")
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")[:300]
            print(f"  FALHA {m.email}  HTTP {erro.code}: {detalhe}")
            falhas += 1
        except urllib.error.URLError as erro:
            print(f"  FALHA {m.email}  rede: {erro.reason}")
            falhas += 1
        except RuntimeError as erro:
            print(f"  FALHA {m.email}  {erro}")
            falhas += 1
        time.sleep(1)  # o Resend limita a 2 req/s

    print(f"\n{len(mensagens) - falhas} enviadas, {falhas} falhas")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
