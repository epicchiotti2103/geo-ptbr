"""Métricas de visibilidade do paper GEO (Aggarwal et al.), Seção 2.2.1.

Implementa:
  - Imp_wc  (Word Count, Eq. 2)
  - Imp_pwc (Position-Adjusted Word Count, Eq. 3)

DECISÃO DE INTERPRETAÇÃO (registrada em paper/KEY_FACTS.md §1.2): o paper não
formaliza `pos(s)`. Implementamos a leitura consistente com a descrição
qualitativa ("sentenças no início pesam mais, decaimento exponencial") e com o
código do repositório oficial: peso = exp(-idx / n_sentencas), onde idx é o
índice 0-based da sentença na resposta. Esta escolha é fixa e versionada; mudá-la
muda a versão do experimento.

Regra do paper: sentença citada por múltiplas fontes divide as palavras
igualmente entre as citações.
"""
import math
import re

METRICS_VERSION = "v1"

# [1], [2] ... possivelmente aglutinadas: [1][3] ou [1, 3]
_CITATION_RE = re.compile(r"\[(\d(?:\s*,\s*\d)*)\]")
# quebra de sentenças: pontuação final seguida de espaço+maiúscula/fim.
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀ0-9\[])")


def split_sentences(text):
    text = text.strip()
    if not text:
        return []
    return [s for s in _SENTENCE_RE.split(text) if s.strip()]


def citations_of(sentence):
    """Conjunto de índices de fonte (int) citados na sentença."""
    cited = set()
    for m in _CITATION_RE.finditer(sentence):
        for part in m.group(1).split(","):
            cited.add(int(part.strip()))
    return cited


def word_count(sentence):
    """Palavras da sentença, excluindo os marcadores de citação."""
    return len(_CITATION_RE.sub(" ", sentence).split())


def impressions(answer, n_sources=5):
    """Imp_wc e Imp_pwc para cada fonte 1..n_sources.

    Retorna {"wc": {i: float}, "pwc": {i: float}, "n_sentencas": int,
             "sentencas_sem_citacao": int}.
    Fonte não citada tem impressão 0.0. Resposta vazia → tudo 0.
    """
    sentences = split_sentences(answer)
    n = len(sentences)
    wc = {i: 0.0 for i in range(1, n_sources + 1)}
    pwc = {i: 0.0 for i in range(1, n_sources + 1)}
    total_words = sum(word_count(s) for s in sentences)
    uncited = 0

    if total_words == 0:
        return {"wc": wc, "pwc": pwc, "n_sentencas": n, "sentencas_sem_citacao": 0}

    for idx, s in enumerate(sentences):
        cited = {c for c in citations_of(s) if 1 <= c <= n_sources}
        if not cited:
            uncited += 1
            continue
        words = word_count(s)
        share = words / len(cited)          # divide igualmente entre citações
        pos_weight = math.exp(-idx / n)     # decaimento pela posição da sentença
        for c in cited:
            wc[c] += share
            pwc[c] += share * pos_weight

    for c in wc:
        wc[c] /= total_words
        pwc[c] /= total_words
    return {"wc": wc, "pwc": pwc, "n_sentencas": n, "sentencas_sem_citacao": uncited}


def relative_improvement(imp_after, imp_before):
    """Eq. 4 do paper, em %. Se antes for 0 e depois >0, retorna None (indefinido
    — reportar como 'novo' em vez de inventar um número)."""
    if imp_before == 0:
        return None if imp_after > 0 else 0.0
    return (imp_after - imp_before) / imp_before * 100.0
