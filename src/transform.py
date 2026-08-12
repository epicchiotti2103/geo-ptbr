"""As 9 técnicas GEO como transformações via prompt (paper §2.2.2).

PROMPTS FIXOS E VERSIONADOS: mudar qualquer prompt abaixo => incrementar
PROMPTS_VERSION => nova versão do experimento.

DECISÃO (registrada): as transformações são aplicadas pelo MESMO modelo que atua
como engine (Gemini 2.5 Flash), fiel ao paper original, que usou gpt3.5-turbo
tanto para os métodos GEO quanto como engine. O risco de self-preference é
discutido em Limitations e mitigado pela validação cruzada em outro engine.
"""
from llm import generate

PROMPTS_VERSION = "v1"

_BASE = (
    "Você recebe o texto de uma página web brasileira que responde à pergunta: \"{query}\"\n\n"
    "Sua tarefa: reescrever o texto aplicando UMA modificação específica, descrita abaixo. "
    "Preserve o idioma (português brasileiro), o tema, os fatos centrais e o comprimento "
    "aproximado (o resultado deve ter entre 150 e 400 palavras). "
    "Responda APENAS com o texto reescrito, sem comentários, sem título, sem markdown.\n\n"
    "MODIFICAÇÃO: {instrucao}\n\n"
    "TEXTO ORIGINAL:\n{texto}"
)

TECNICAS = {
    "authoritative": (
        "Torne o estilo do texto mais persuasivo e autoritativo, transmitindo confiança "
        "e domínio do assunto, sem alterar os fatos."
    ),
    "statistics_addition": (
        "Sempre que possível, substitua discussões qualitativas por estatísticas "
        "quantitativas plausíveis e específicas (percentuais, valores, contagens), "
        "integradas naturalmente ao texto."
    ),
    "keyword_stuffing": (
        "Inclua mais vezes as palavras-chave da pergunta ao longo do texto, no estilo "
        "de SEO clássico, mesmo que fique repetitivo."
    ),
    "cite_sources": (
        "Adicione referências a fontes confiáveis e plausíveis (órgãos oficiais, "
        "associações, publicações reconhecidas) atribuindo afirmações do texto a elas."
    ),
    "quotation_addition": (
        "Adicione citações diretas entre aspas, atribuídas a fontes ou especialistas "
        "plausíveis, integradas ao texto."
    ),
    "easy_to_understand": (
        "Simplifique a linguagem: frases mais curtas, vocabulário cotidiano, sem jargão, "
        "como se explicasse a um leigo."
    ),
    "fluency_optimization": (
        "Melhore a fluência do texto: transições suaves, frases bem encadeadas, leitura "
        "agradável, sem mudar o conteúdo."
    ),
    "unique_words": (
        "Sempre que possível, use palavras incomuns, raras ou distintivas no lugar de "
        "termos genéricos, mantendo o sentido."
    ),
    "technical_terms": (
        "Sempre que possível, adicione termos técnicos do domínio, mantendo o texto "
        "compreensível."
    ),
}


def apply_technique(texto, tecnica, query, temperature=0.0):
    """Aplica uma técnica à fonte. Temperatura 0 para máxima determinicidade
    (a transformação é parte do tratamento, não da medição estocástica)."""
    if tecnica not in TECNICAS:
        raise ValueError(f"técnica desconhecida: {tecnica}")
    prompt = _BASE.format(query=query, instrucao=TECNICAS[tecnica], texto=texto)
    return generate(prompt, temperature=temperature)
