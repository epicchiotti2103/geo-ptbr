"""Cliente do engine do experimento — Gemini 2.5 Flash via API direta.

Contrato (TASK.md / PROMPT_GEO_PTBR.md): o engine SEMPRE é acessado via API direta
com temperatura controlada — nunca CLI/chat de plano pessoal. Toda chamada real
DEVE registrar a versão exata do modelo (response.model_version) — é obrigatório
no trace (a Fase 3 aborta se mais de uma versão aparecer nos traces).

Modo mock (MOCK_LLM=1): não toca a rede. Serve para testar o pipeline inteiro
offline. model_version="mock" nesse modo — funciona como marcador: o resto do
harness (run_case.py) usa esse marcador para nunca deixar um trace mock ser
confundido com um trace real (nem na resumabilidade, nem na guarda de custo).
"""
import os
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENGINE_MODEL = "gemini-3.5-flash-lite"

# Rate limit do free tier: intervalo mínimo entre chamadas reais (configurável).
# Default 6.5s => ~9 RPM, dentro da folga do limite free tier do gemini-2.5-flash.
MIN_INTERVAL_S_DEFAULT = 6.5
RETRY_DELAYS_S = (30, 60, 120)  # backoff exponencial em 429/RESOURCE_EXHAUSTED
MAX_RETRIES = len(RETRY_DELAYS_S)

_last_call_ts = 0.0  # relógio monotônico do processo, para o throttle entre chamadas


class QuotaExhausted(Exception):
    """Levantada quando o free tier fica esgotado: 429/RESOURCE_EXHAUSTED persiste
    após MAX_RETRIES tentativas com backoff. O runner (run_case.py / run_eval.py)
    trata esta exceção: salva o parcial e pausa de forma limpa."""


def _load_env_file(path=None):
    """Parser manual simples de .env (sem depender de python-dotenv).

    Formato aceito: KEY=VALUE por linha; linhas vazias e iniciadas com '#' são
    ignoradas; '#' após o valor é tratado como comentário; aspas simples/duplas
    ao redor do valor são removidas.
    """
    path = Path(path) if path else ROOT / ".env"
    env = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip("'\"")
        if key:
            env[key] = value
    return env


_ENV_FILE = _load_env_file()


def env(key, default=None):
    """Lê uma variável: ambiente real do processo tem prioridade sobre o .env,
    que tem prioridade sobre o default."""
    return os.environ.get(key, _ENV_FILE.get(key, default))


def _min_interval_s():
    return float(env("LLM_MIN_INTERVAL_S", MIN_INTERVAL_S_DEFAULT))


_PRICES = None


def _prices():
    global _PRICES
    if _PRICES is None:
        with open(ROOT / "config" / "prices.yaml", encoding="utf-8") as f:
            _PRICES = yaml.safe_load(f)
    return _PRICES


def custo_usd(input_tokens, output_tokens, model=ENGINE_MODEL):
    """Custo NOMINAL (o que custaria pago), calculado pelos preços de
    config/prices.yaml. Mesmo no free tier, o contrato exige contabilidade de
    custo por chamada (TASK.md regra 5) — free_tier não zera o custo logado."""
    p = _prices()["modelos"][model]
    return (input_tokens / 1_000_000 * p["input_por_1m"]) + (
        output_tokens / 1_000_000 * p["output_por_1m"]
    )


# Contador simples de chamadas reais de generate(), útil para verificar na prática
# que a resumabilidade de run_case.py está pulando o que deveria (0 chamadas novas
# numa segunda execução idêntica).
CALL_COUNT = 0


def _mock_response(prompt, temperature):
    """Resposta determinística sintética p/ testar o pipeline inteiro offline."""
    text = (
        "Segundo a primeira fonte consultada, este é um trecho de teste da resposta "
        "sintética [1]. Complementando o ponto anterior, uma segunda fonte reforça "
        "o mesmo argumento com outro ângulo [2]. Por fim, uma terceira fonte fecha "
        "o resumo do caso simulado [3]."
    )
    # tokens fictícios, só para exercitar o cálculo de custo — não vêm de API real.
    input_tokens = max(1, len(prompt) // 4)
    output_tokens = max(1, len(text) // 4)
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "custo_usd": custo_usd(input_tokens, output_tokens),
        "model_version": "mock",
    }


def _throttle():
    global _last_call_ts
    elapsed = time.monotonic() - _last_call_ts
    wait = _min_interval_s() - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.monotonic()


def generate(prompt, temperature=0.7):
    """Chama o engine do experimento (ENGINE_MODEL) com 1 prompt.

    Retorna dict: {"text", "input_tokens", "output_tokens", "custo_usd",
    "model_version"}. model_version vem de response.model_version (real) ou é
    "mock" em modo MOCK_LLM=1 — nunca inventado.

    Rate limit: intervalo mínimo configurável entre chamadas reais (free tier
    ~9 RPM por default) + retry com backoff exponencial (30s/60s/120s) em
    429/RESOURCE_EXHAUSTED. Após esgotar os retries, levanta QuotaExhausted.
    """
    global CALL_COUNT
    CALL_COUNT += 1

    if env("MOCK_LLM") == "1":
        return _mock_response(prompt, temperature)

    # Import tardio: o modo mock não deve depender do SDK estar instalado.
    from google.genai import Client, errors
    from google.genai.types import GenerateContentConfig

    api_key = env("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY não encontrada (defina em .env na raiz do projeto ou "
            "na variável de ambiente)."
        )
    client = Client(api_key=api_key)

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            response = client.models.generate_content(
                model=ENGINE_MODEL,
                contents=prompt,
                config=GenerateContentConfig(temperature=temperature),
            )
            usage = response.usage_metadata
            input_tokens = int(usage.prompt_token_count or 0) if usage else 0
            output_tokens = int(usage.candidates_token_count or 0) if usage else 0
            model_version = response.model_version
            if not model_version:
                raise RuntimeError(
                    "response.model_version ausente na resposta da API — o "
                    "contrato exige registrar a versão exata do modelo em todo "
                    "trace (TASK.md/PROMPT_GEO_PTBR.md, Fase 3)."
                )
            try:
                text = response.text or ""
            except Exception:
                text = ""  # resposta sem texto (ex.: bloqueada por segurança)
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "custo_usd": custo_usd(input_tokens, output_tokens),
                "model_version": model_version,
            }
        except errors.APIError as e:
            code = getattr(e, "code", None)
            status = (getattr(e, "status", "") or "").upper()
            is_quota = code == 429 or status == "RESOURCE_EXHAUSTED"
            # 5xx (503 UNAVAILABLE, 500 etc.): instabilidade do servidor —
            # transitório, mesma política de retry que quota
            is_server = (isinstance(code, int) and code >= 500) or status == "UNAVAILABLE"
            if not (is_quota or is_server):
                raise
            last_err = e
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS_S[attempt]
                rotulo = "429/RESOURCE_EXHAUSTED" if is_quota else f"{code or status} servidor"
                print(
                    f"  [llm] {rotulo} — retry em {delay}s "
                    f"(tentativa {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(delay)

    raise QuotaExhausted(
        f"Quota do free tier esgotada: {MAX_RETRIES} retries com backoff "
        f"(30s/60s/120s) falharam. Último erro: {last_err}. A run é resumível — "
        f"rode o mesmo comando novamente mais tarde para retomar de onde parou."
    )
