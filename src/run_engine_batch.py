#!/usr/bin/env python3
"""LIMITE MEDIDO (OpenAI, ago/2026): a organização tem teto de 2.000.000 de
tokens ENFILEIRADOS por modelo (soma dos batches in_progress). Com ~2.700
tokens de entrada por request e 30 requests por query, cabem ~24 queries por
lote; usamos 20 (81% do limite) por segurança. Um lote maior falha com
BatchError(code="token_limit_exceeded") logo na validação — barato de
descobrir, mas o chunk-size default precisa respeitar isso.

Runner de batch para um SEGUNDO engine do estudo GEO-PTBR (validação entre
engines) — primeira implementação: OpenAI `gpt-5-nano` via Batch API.

DESENHO CIENTÍFICO (por que este módulo existe): a run do Gemini (engine
principal) já está completa — 525 queries, 30 chamadas/query, traces em
eval/traces/. Para comparar a DIREÇÃO do efeito de cada técnica entre engines
sem refazer as 9 transformações de texto por query (que já existem, fase=
"transform" nos traces do Gemini), este runner reaproveita
cross_validate.load_transformed_texts() — a MESMA função usada pela validação
cruzada com Claude — para ler os textos já transformados e só chamar o novo
engine na etapa de RESPOSTA (3 baseline + 9 técnicas × 3 reps = 30 chamadas/
query). Isso isola a variável "quem responde" e economiza as 9 chamadas de
transform/query que a Fase 3 do Gemini pagou por query (ela precisava gerar o
transform; este runner só paga as 30 chamadas de resposta) — 9 chamadas a
menos em 39 por query, ≈23%. NUNCA gera um transform novo — se faltar algum,
a QUERY INTEIRA é pulada e registrada (nunca se inventa medição, TASK.md
regra 4).

Uso:
    python src/run_engine_batch.py --all
    python src/run_engine_batch.py --queries s001,j002
    python src/run_engine_batch.py --all --chunk-size 250 --poll-interval 60
    python src/run_engine_batch.py --status
    python src/run_engine_batch.py --estimate --all
    MOCK_LLM=1 python src/run_engine_batch.py --queries s001,s002 --chunk-size 2 \\
        --out-dir eval/traces_mock_gpt --state-file eval/state_mock_gpt.json

ARQUITETURA PLUGÁVEL (EngineBatchProvider): este runner não sabe nada sobre a
API específica de um provedor — ele só fala com um objeto que implementa
`EngineBatchProvider` (create/get, MESMO padrão de RealBatchClient/
MockBatchClient em run_batch.py, o runner "modelo a seguir" citado no
contrato). `OpenAIBatchProvider` foi a primeira implementação real;
`AnthropicBatchProvider` (Message Batches API — client.messages.batches.
create/retrieve/results, vocabulário de status e formato de resultado
DIFERENTES da OpenAI — ver seção dedicada "PROVIDER ANTHROPIC" abaixo) é a
segunda, implementando a MESMA interface e entrando só como mais uma entrada
no dict `PROVIDERS` no fim do módulo — NENHUMA outra parte deste arquivo
mudou por causa dela, exceto o ajuste mínimo documentado em "AJUSTE MÍNIMO AO
RUNNER GENÉRICO" abaixo (default de --chunk-size por engine).

SDK `openai` VERIFICADO NESTA SESSÃO (openai==2.53.0, instalado em .venv;
nenhuma chamada de rede feita — só inspeção de assinaturas/tipos via
`inspect`/`typing.get_args`):
  - `OpenAI(api_key=..., timeout=<float|httpx.Timeout>, max_retries=int)` —
    timeout aceita float simples (segundos, ao contrário do http_options em
    ms do google-genai). Usado aqui com max_retries=0 e um `_retry` manual
    (mesma disciplina de RealBatchClient em run_batch.py) para logar cada
    tentativa e cobrir explicitamente 429/5xx/timeout — lição aprendida
    (docstring de run_batch.py): sem timeout explícito, uma conexão pendurada
    trava o polling para sempre.
  - `client.files.create(file=<tupla (nome, bytes, content_type)>,
    purpose="batch")` -> `FileObject` com `.id`. `purpose` é um Literal que
    inclui "batch" (confirmado via `typing.get_args(FilePurpose)`).
  - `client.batches.create(input_file_id=str, endpoint=Literal[...] (inclui
    "/v1/chat/completions" e "/v1/responses"), completion_window=Literal["24h"]
    (único valor aceito pelo tipo desta versão do SDK), metadata=dict[str,str]
    opcional)` -> `Batch`.
  - `Batch`: campos relevantes — `id`, `status` (Literal com 8 valores:
    "validating","failed","in_progress","finalizing","completed","expired",
    "cancelling","cancelled" — SEM um estado distinto de "sucesso parcial";
    `request_counts.{completed,failed,total}` é como se descobre que ALGUMAS
    respostas falharam dentro de um batch "completed"), `input_file_id`,
    `output_file_id` (Optional — respostas bem-sucedidas), `error_file_id`
    (Optional — respostas com erro por request), `errors` (erros de
    validação do arquivo inteiro, ex.: JSONL malformado).
  - `client.files.content(file_id)` -> `HttpxBinaryResponseContent` com
    `.text` (str) — cada linha é um objeto JSON
    `{"custom_id","response":{"status_code","body":{...chat completion...}},
    "error"}` (formato documentado da Batch API; `body` é o mesmo dict de uma
    resposta síncrona de `/v1/chat/completions`: `.model`, `.choices[0]
    .message.content`, `.choices[0].finish_reason`, `.usage.
    {prompt_tokens,completion_tokens}`) — parseado aqui via `json.loads` linha
    a linha, sem reconstruir o pydantic `ChatCompletion` (evita acoplamento
    a uma versão exata do SDK para um formato que é, em si, um contrato JSON
    estável da API).

LIMITES DA BATCH API DA OPENAI (verificados via busca na documentação oficial
nesta sessão — não há teste de rede local possível para confirmar na prática,
igual ao caveat já registrado em run_batch.py para os limites do Gemini):
  - até 50.000 requests por batch;
  - arquivo de entrada até 200 MB;
  - `completion_window` só aceita "24h" no momento (não há "1h"/"7d" para
    chat completions).
  Consequência de desenho: `--chunk-size` aqui é o número de QUERIES por job
  submetido (não o número de requests cru) — default 250 queries × 30
  chamadas/query = 7.500 requests/job, bem abaixo de 50.000, com folga grande
  mesmo em cenários com mais reps/técnicas. Tamanho de arquivo: MEDIDO
  offline nesta sessão (sem rede — só serializando o JSONL localmente com
  `OpenAIBatchProvider._to_jsonl_bytes` sobre as 250 primeiras queries reais
  de data/sources/): **90,8 MB para chunk-size=250** (7.500 requests; fontes
  de 150–400 palavras cada geram prompts de ~5 fontes citadas, maiores do que
  "poucas KB" — a estimativa inicial por extrapolação grosseira era
  otimista). Isso é ~45% do limite documentado (200MB) e deixa ~50% de folga
  sob `_MAX_FILE_BYTES = 180MB` — dentro do previsto, mas com MENOS margem
  do que se poderia supor sem medir; reduzir `--chunk-size` se o teor médio
  das fontes crescer no futuro. `_check_file_size` aplica essa margem de
  segurança e aborta com SystemExit pedindo `--chunk-size` menor se for
  excedida, mesma postura de `run_batch._check_inline_size`.

DECISÃO — TEMPERATURA: `config/study.yaml` (`engine.principal.temperatura:
0.7`) é explicitamente escopado ao engine PRINCIPAL (Gemini). Para
`gpt-5-nano` (família de modelos de raciocínio GPT-5), a Chat Completions API
REJEITA qualquer `temperature` diferente do default (erro documentado:
"Unsupported value: 'temperature' does not support 0.7 with this model. Only
the default (1) value is supported." — confirmado via busca na comunidade/
documentação OpenAI nesta sessão; só a família gpt-5.1 aceita temperature
customizado, e mesmo assim só com `reasoning_effort` omitido/"none"). Enviar
temperature=0.7 aqui faria TODO request do batch falhar. Decisão: o
`OpenAIBatchProvider` OMITE `temperature` do body (usa o default do modelo) —
documentado aqui explicitamente para não ser confundido com um bug silencioso
nem com uma tentativa de replicar a temperatura=0.7 do Gemini (que não é
replicável neste modelo).

DECISÃO — `max_completion_tokens` + `reasoning_effort`: modelos da família
GPT-5 consomem tokens de raciocínio (billados como output) antes do texto
visível; com um teto de tokens baixo, a resposta visível pode sair vazia
("finish_reason":"length" com conteúdo vazio). Este provider usa
`max_completion_tokens=3072` (folga generosa sobre respostas de algumas
centenas de palavras) e `reasoning_effort="minimal"` — a tarefa (responder
com citações, seguindo instruções explícitas do prompt) não exige raciocínio
profundo, e "minimal" reduz o risco de truncamento por raciocínio e o custo
por chamada (tokens de raciocínio contam no preço de output). Ambos os
parâmetros são aplicados uniformemente a TODAS as células (baseline e
técnicas) — não introduzem variável de confusão entre técnicas.

PROVIDER ANTHROPIC (`AnthropicBatchProvider`) — Message Batches API:

SDK `anthropic` VERIFICADO NESTA SESSÃO (anthropic==0.121.0, instalado em
.venv; nenhuma chamada de rede feita — só inspeção de assinaturas/tipos via
`inspect`/`typing.get_args` e instanciação OFFLINE de objetos pydantic reais
do SDK, mesma disciplina usada acima para o SDK `openai`):
  - `client.messages.batches.create(requests=[Request(custom_id=str,
    params=MessageCreateParamsNonStreaming(model=..., max_tokens=...,
    messages=[...], temperature=...))])` -> `MessageBatch`. `Request` e
    `MessageCreateParamsNonStreaming` são TypedDict, não classes com
    construtor especial (confirmado: `type(Request) is
    typing_extensions._TypedDictMeta`) — usados aqui como dict literal
    simples.
  - `MessageBatch`: `id`; `processing_status` (Literal com APENAS 3
    valores — "in_progress", "canceling", "ended" — SEM um estado
    "failed"/"completed" distinto do "ended" como o da OpenAI; confirmado
    via `MessageBatch.__annotations__`); `request_counts`
    (`{succeeded,errored,canceled,expired,processing}` — é aqui, não no
    `processing_status`, que se descobre que ALGUMAS respostas falharam
    dentro de um batch "ended"); `results_url` (Optional).
  - `client.messages.batches.retrieve(id)` -> `MessageBatch` (mesmo shape).
  - `client.messages.batches.results(id)` -> iterador `JSONLDecoder[
    MessageBatchIndividualResponse]` (streaming). CONFIRMADO via
    `inspect.getsource(Batches.results)` nesta sessão: o método chama
    `retrieve()` de novo internamente e lê `batch.results_url`; se
    `results_url` estiver vazio/None, levanta `anthropic.AnthropicError` —
    MESMO com `processing_status == "ended"` (ex.: batch cancelado ou
    expirado antes de processar qualquer request). `AnthropicBatchProvider.
    get()` guarda esse caso explicitamente (checa `batch.results_url` antes
    de chamar `.results()`) para nunca deixar essa exceção subir e derrubar
    a run com stack trace — em vez disso trata como 0 respostas coletáveis,
    que a lógica genérica já existente em `_process_chunk` ("menos respostas
    do que esperado") mantém o chunk `pending` para nova tentativa.
  - `MessageBatchIndividualResponse`: `custom_id` + `result`, união
    discriminada por `result.type` em succeeded/errored/canceled/expired
    (CONFIRMADO instanciando os 4 tipos reais via pydantic nesta sessão, não
    só lendo `__annotations__`): `succeeded.message` é um `Message` COMPLETO
    (mesmo schema de uma resposta síncrona — `.content` lista de blocks,
    filtrado aqui por `type=="text"`; `.model`; `.usage.
    {input_tokens,output_tokens}`); `errored.error` é um `ErrorResponse` com
    `.error.{type,message}`; `canceled`/`expired` não carregam payload além
    do `type`. NENHUM estado de batch inteiro "falhou" existe nesta API —
    por isso `AnthropicBatchProvider.terminal_failure` é um `set()` vazio
    (ver propriedade da classe): uma falha TOTAL de um batch aparece como
    `processing_status == "ended"` com 100% dos `result.type == "errored"`,
    capturada pela MESMA lógica genérica de "falha sistêmica" que já existe
    em `_process_chunk` (novas==0 and existentes==0 and falhas) — nenhum
    código novo precisou ser escrito no runner para esse caso.
  - `client.messages.batches.cancel(id)` existe mas não é usado por este
    provider (fora de escopo desta tarefa — o runner não cancela jobs).

LIMITES DA MESSAGE BATCHES API DA ANTHROPIC (fonte: documentação em cache da
skill `claude-api` deste ambiente, datada 2026-06-24 — "Up to 100,000
requests or 256 MB per batch. Most batches complete within 1 hour; maximum 24
hours. Results available for 29 days after creation."; SEM possibilidade de
chamada de rede local para confirmar em produção — mesmo caveat já registrado
acima para os limites da OpenAI e no módulo run_batch.py para os do Gemini).
DIFERENÇA MATERIAL em relação à OpenAI: a OpenAI tem um teto MEDIDO de
2.000.000 de tokens ENFILEIRADOS por modelo em nível de organização (ver
topo deste docstring), que forçou o `DEFAULT_CHUNK_SIZE` global a 20 queries.
Para a Anthropic, NENHUMA fonte disponível nesta sessão documenta um teto
análogo de tokens enfileirados por organização para a Message Batches API —
mas AUSÊNCIA DE DOCUMENTAÇÃO NÃO É PROVA DE AUSÊNCIA DO LIMITE; isso não foi
(e não pôde ser, por instrução desta tarefa: nenhuma chamada real à API
Anthropic) verificado empiricamente. Por isso o chunk-size sugerido abaixo
para claude-haiku-4-5 é uma escolha CONSERVADORA em relação ao teto de
100k requests/256MB (larga margem), não uma tentativa de maximizar o tamanho
do lote.

AJUSTE MÍNIMO AO RUNNER GENÉRICO — default de --chunk-size por engine: o
`DEFAULT_CHUNK_SIZE` global (20) existe especificamente por causa do teto
medido de tokens enfileirados da OpenAI — usá-lo também para
claude-haiku-4-5 seria excessivamente conservador sem motivo análogo
documentado (ver limites acima). Único ajuste feito ao runner genérico para
acomodar essa diferença: `DEFAULT_CHUNK_SIZE_POR_ENGINE` (dict engine_slug ->
chunk_size), consultado em `main()` SÓ quando o usuário não passa
`--chunk-size` explicitamente — mesmo padrão já usado por
`_out_dir_default`/`_state_file_default` para out-dir/state-file, que também
variam por engine_slug. Nenhuma outra linha da lógica de chunking, submissão,
polling, coleta ou estado mudou. Para claude-haiku-4-5: 150 queries/job
(150 × 30 chamadas/query = 4.500 requests/job, ~4,5% do limite de 100k
requests documentado; tamanho de arquivo não medido localmente para este
modelo, mas por extrapolação da métrica MEDIDA para a OpenAI nesta mesma
tarefa [~12,1KB/request serializado — ver seção da OpenAI acima; prompts de
mesma origem/tamanho, já que os dois providers reaproveitam os MESMOS textos
transformados do Gemini via `_build_pending`] ficaria em torno de ~54MB,
~21% da margem de 256MB documentada — folga grande). `--chunk-size` explícito
sempre tem prioridade e pode reduzir esse valor a qualquer momento.

TROCA CONSCIENTE nesse valor de 150: não é só o teto documentado da API que
importa aqui — `_process_chunk` (lógica genérica, herdada de run_batch.py)
marca um chunk "collected" mesmo com falhas ESPORÁDICAS dentro dele (só uma
falha SISTÊMICA, 100% do chunk, reabre o chunk como pending — ver docstring
acima "MENSAGEM BATCHES" e `_process_chunk`), e essas células falhas
esporádicas NÃO são reautomaticamente retentadas. Em 150 queries/job (4.500
requests) o "raio" de uma coleta malsucedida é maior do que em 20
(600 requests): mais células ficam sujeitas a essa limitação por job. 150 foi
escolhido mesmo assim porque (a) o teto de requests/tamanho tem folga muito
maior do que o necessário pra compensar, e (b) reduzir o número de jobs
reduz proporcionalmente o número de vezes que essa limitação pode ser
acionada por falha de rede/timeout na CRIAÇÃO do job (evento por job, não por
request) — mas é uma escolha, não a única defensável; `--chunk-size` menor
(ex. 50) é uma alternativa mais conservadora quanto a esse raio de falha, à
custa de mais jobs.

DECISÃO — TEMPERATURA (claude-haiku-4-5): AO CONTRÁRIO do gpt-5.6-luna
(família de raciocínio que rejeita temperature != default — ver decisão
acima), a Messages API da Anthropic para claude-haiku-4-5 ACEITA temperature
customizado normalmente. Decisão: usar temperature=0.7 — MESMO valor do
engine principal (Gemini, config/study.yaml) e do claude-sonnet-5 em
cross_validate.py (ENGINE_TEMPERATURE=0.7) — para reduzir a diferença
metodológica entre engines comparados no estudo (relevante para o paper: o
gpt-5.6-luna já introduz uma divergência inevitável nesse eixo por não
aceitar o parâmetro; claude-haiku-4-5 não tem essa limitação, então não há
razão para divergir aqui).

DECISÃO — max_tokens: 2048 — MESMO valor já usado e documentado por
cross_validate.py (MAX_TOKENS=2048) para claude-sonnet-5, reaproveitado aqui
por consistência entre os dois usos do SDK `anthropic` neste projeto; folga
generosa sobre as respostas observadas (~120-310 tokens, mesma faixa citada
no enunciado desta tarefa). `max_tokens` é campo OBRIGATÓRIO na Messages API
da Anthropic (ao contrário de outros parâmetros) — confirmado via
`MessageCreateParamsNonStreaming.__annotations__` (`Required[int]`).

DECISÃO — custom_id (chave <-> custom_id, reversível): a chave interna do
runner (`_make_key`/`_parse_key` de run_batch.py, reaproveitada sem
alteração) usa `|` como separador (`<qid>|<fase>|<tecnica ou '-'>|<rep ou
'-'>`) — a Message Batches API da Anthropic restringe `custom_id` a
caracteres alfanuméricos, `_` e `-`, até 64 caracteres (`|` não é aceito).
`_key_to_custom_id`/`_custom_id_to_key` (funções módulo-level, testáveis
isoladamente) fazem o mapeamento trocando `|` por `__` (duplo underscore):
`_key_to_custom_id` primeiro valida que NENHUM componente da chave já contém
`__` (o que quebraria a reversibilidade — nenhuma das 9 técnicas de
config/study.yaml, nenhum query_id no formato usado pelo projeto, nem
"baseline"/"tecnica" contêm `__` hoje, mas a validação levanta `ValueError`
explícito em vez de silenciosamente corromper o round-trip se isso mudar no
futuro) e então valida o resultado contra a regex de charset/tamanho da API
antes de devolvê-lo; `_custom_id_to_key` é a inversa exata
(`.replace("__", "|")`). Round-trip coberto por teste offline (ver relatório
da tarefa) para os dois casos exigidos: baseline (tecnica/rep nulos, ex.
"s001|baseline|-|0" -> "s001__baseline__-__0") e técnica com rep (ex.
"s001|tecnica|cite_sources|2" -> "s001__tecnica__cite_sources__2").

TRACES: eval/traces_<engine_slug>/<query_id>.jsonl — MESMO schema de
run_case.py (via run_case._make_record, reaproveitado sem alteração) + campos
"engine" (nome do modelo, ex. "gpt-5-nano") e "modo": "batch". Métricas
(metrics.impressions) calculadas na COLETA, a partir do texto retornado.

RESUMABILIDADE: eval/batch_state_<engine_slug>.json (mesmo desenho de
eval/batch_state.json do run_batch.py: por chunk, {"status":
"pending"|"submitted"|"collected", "job_id", "n_requests", "submitted_at",
"collected_at"}; um job "submitted" nunca é resubmetido, só reconsultado). O
pendente de cada chunk é recomputado a partir do que falta nos traces reais
(run_case._load_existing) toda vez que o chunk ainda não foi submetido —
mesmo princípio de run_batch.py: a run é resumível mesmo que a composição de
--all mude entre execuções. As chaves de request usam a MESMA convenção de
run_batch.py (`<qid>|<fase>|<tecnica ou '-'>|<rep ou '-'>`), reaproveitando
run_batch._make_key/_parse_key diretamente (nunca reimplementadas aqui) —
garante que a chave é auto-suficiente e idêntica entre os dois runners.
Queries puladas por falta de transform do Gemini são acumuladas em
`state["puladas"]` (qid -> motivo) e salvas junto do state file — nunca
tratado como erro fatal, só registrado. Um chunk cujo job veio 100% com erro
(nenhuma célula nova, nenhuma preexistente) NUNCA é marcado "collected" —
fica "pending" para nova tentativa numa execução futura (ver
_process_chunk); só falhas ESPORÁDICAS dentro de um chunk majoritariamente
bem-sucedido ficam sem retry automático (mesma limitação herdada, e
documentada, de run_batch.py). ISOLAMENTO MOCK/REAL no state file: a chave de
cada chunk leva um sufixo "__mock" quando MOCK_LLM=1 — um chunk_id de
CONTEÚDO idêntico (mesmos query_ids) nunca colide entre uma sessão mock e uma
real, mesmo compartilhando o mesmo --state-file (requisito 9: mock isolado da
resumabilidade real também no nível do state, não só dos traces).

GUARDA DE CUSTO — LEDGER PRÓPRIO: `CostGuardEngine` abaixo é uma
REIMPLEMENTAÇÃO deliberada (não reuso de run_case.CostGuard), seguindo o
MESMO precedente já estabelecido por cross_validate.CostGuardCrossval: ledger
escopado só a `--out-dir` deste engine, arquivo de abort próprio
(`ABORT_COST_<engine_slug>.md`) — NUNCA soma com o ledger do Gemini
(eval/traces/, ABORT_COST.md) nem escreve por cima dele. O teto US$ 40 do
estudo inteiro (config/study.yaml) é a SOMA de todos os ledgers dos engines
rodados (Gemini + validação cruzada Claude + este) — somar é responsabilidade
de quem orquestra o estudo, não deste script. Custo por resposta usa o
desconto de batch (config/prices.yaml: batch_desconto) — `_custo_usd_batch`
é uma extensão local do cálculo nominal de `llm.custo_usd`, parametrizada
pelo modelo (não hardcoded no ENGINE_MODEL do Gemini).

TRAVA DE VERSÃO (requisito 6): `ModelVersionTracker` (reimplementação local,
mesmo motivo do CostGuard acima — mensagem de erro escopada a este engine, em
vez de reaproveitar o texto "Fase 3"/Gemini de run_batch.ModelVersionTracker)
escaneia os traces reais já existentes em --out-dir; a cada resposta real
coletada (nunca em modo mock) cuja model_version ainda não foi vista, compara
contra o(s) já visto(s) — diverge => SystemExit imediato com os traces já
gravados preservados.

MODO MOCK (MOCK_LLM=1): `MockEngineBatchProvider` não toca rede — `create()`
já monta respostas sintéticas na hora (reaproveita `llm._mock_response`,
mesma função usada por todos os outros runners em modo mock) e `get()` já
retorna status "completed" de imediato, sem polling. model_version="mock" em
todas as respostas mock — nunca conta para ModelVersionTracker nem para o
teto real de custo (mesma regra de llm.py/run_case.py/run_batch.py).

CLI: --all | --queries id1,id2 | --status (mutuamente exclusivos entre os
dois primeiros e --status) | --estimate (só imprime custo estimado, não
submete nada — combina com --all/--queries). --chunk-size (queries por job;
default depende do engine — DEFAULT_CHUNK_SIZE_POR_ENGINE, com
DEFAULT_CHUNK_SIZE=20 como fallback, ver "AJUSTE MÍNIMO AO RUNNER GENÉRICO"
acima). --poll-interval (segundos, default 60). --no-wait (consulta jobs em
andamento 1x e sai). --engine (chave em PROVIDERS e em config/prices.yaml —
ex. "gpt-5.6-luna", "gpt-5-nano", "claude-haiku-4-5"). --out-dir (default
eval/traces_<engine_slug>). --state-file (default
eval/batch_state_<engine_slug>.json). --tecnicas, --reps (defaults de
config/study.yaml, mesmos nomes de run_batch.py).

CUIDADO OPERACIONAL (TASK.md E2): rodar sob `caffeinate` durante
submissão/coleta real — este processo bloqueia (time.sleep) enquanto aguarda
jobs em andamento, igual a run_batch.py.
"""
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import abc
import argparse
import json
import random
import re
import time
from datetime import datetime, timezone

import build_scenario
import cross_validate  # reaproveita load_transformed_texts (NUNCA reimplementado aqui)
import llm
import metrics
import run_batch  # reaproveita _make_key/_parse_key (convenção de chave idêntica)
import run_case

ROOT = run_case.ROOT
GEMINI_TRACES_DIR = cross_validate.GEMINI_TRACES_DIR
DEFAULT_CHUNK_SIZE = 20
DEFAULT_POLL_INTERVAL_S = 60
DEFAULT_ENGINE = "gpt-5.6-luna"

# Default de --chunk-size por engine, só usado quando o usuário não passa
# --chunk-size explicitamente (ver docstring do módulo, seção "AJUSTE MÍNIMO
# AO RUNNER GENÉRICO"). Engines não listados aqui caem em DEFAULT_CHUNK_SIZE.
DEFAULT_CHUNK_SIZE_POR_ENGINE = {
    "claude-haiku-4-5": 150,
}

_make_key = run_batch._make_key
_parse_key = run_batch._parse_key

# Margem de segurança sob o limite documentado (200MB) de arquivo de entrada
# da Batch API da OpenAI (ver docstring do módulo).
_MAX_FILE_BYTES = 180 * 1024 * 1024


# --------------------------------------------------------------------------
# custom_id <-> chave interna (`_make_key`/`_parse_key`) — reversível, exigido
# pela Message Batches API da Anthropic (ver docstring do módulo, seção
# "DECISÃO — custom_id"). Módulo-level (não método de classe) para ser
# testável isoladamente sem instanciar AnthropicBatchProvider (que exige
# ANTHROPIC_API_KEY no __init__).
# --------------------------------------------------------------------------
_CUSTOM_ID_SEP = "__"
_CUSTOM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _key_to_custom_id(key):
    """`<qid>|<fase>|<tecnica ou '-'>|<rep ou '-'>` -> custom_id válido pra
    Anthropic (alfanumérico/'_'/'-', 1-64 chars). Levanta ValueError (nunca
    corrompe silenciosamente) se algum componente já contiver '__' (quebraria
    a reversibilidade) ou se o resultado não bater com o charset/tamanho
    exigido pela API."""
    partes = key.split("|")
    if len(partes) != 4:
        raise ValueError(f"chave malformada (esperado 4 partes separadas por '|'): {key!r}")
    for p in partes:
        if _CUSTOM_ID_SEP in p:
            raise ValueError(
                f"componente {p!r} da chave {key!r} contém '{_CUSTOM_ID_SEP}' — colide "
                "com o separador usado para codificar '|' no custom_id da Anthropic "
                "(reversibilidade quebrada)."
            )
    custom_id = key.replace("|", _CUSTOM_ID_SEP)
    if not _CUSTOM_ID_RE.match(custom_id):
        raise ValueError(
            f"custom_id resultante inválido pra Message Batches API da Anthropic "
            f"(regex alfanumérico/'_'/'-', 1-64 chars): {custom_id!r} (chave original: {key!r})"
        )
    return custom_id


def _custom_id_to_key(custom_id):
    """Inversa exata de `_key_to_custom_id` (não revalida — validação já
    ocorreu na codificação; usada na coleta, onde o custom_id vem da API)."""
    return custom_id.replace(_CUSTOM_ID_SEP, "|")


def _out_dir_default(engine_slug):
    return f"eval/traces_{engine_slug}"


def _state_file_default(engine_slug):
    return f"eval/batch_state_{engine_slug}.json"


# --------------------------------------------------------------------------
# custo com desconto de batch — genérico por modelo (config/prices.yaml)
# --------------------------------------------------------------------------
def _custo_usd_batch(input_tokens, output_tokens, model):
    p = llm._prices()["modelos"][model]
    nominal = llm.custo_usd(input_tokens, output_tokens, model)
    return nominal * p.get("batch_desconto", 1.0)


# --------------------------------------------------------------------------
# EngineBatchProvider — contrato plugável (ver docstring do módulo)
# --------------------------------------------------------------------------
class EngineBatchProvider(abc.ABC):
    """Contrato mínimo que qualquer engine de batch precisa implementar para
    plugar neste runner — MESMO padrão de create()/get() de
    RealBatchClient/MockBatchClient em run_batch.py.

    Um `AnthropicBatchProvider` futuro (Message Batches API:
    client.messages.batches.create(requests=[...]) /
    client.messages.batches.results(batch_id) -> stream de
    MessageBatchIndividualResponse, com status
    "in_progress"/"canceling"/"ended" — vocabulário DIFERENTE do da OpenAI,
    por isso terminal_success/terminal_failure/in_progress são propriedades
    de CADA provider, não constantes globais do módulo) implementaria esta
    mesma interface. NÃO implementado nesta tarefa.
    """

    engine_slug: str
    model: str

    @property
    @abc.abstractmethod
    def terminal_success(self):
        """set[str] de status que significam "job terminou, dá pra coletar
        (mesmo que com falhas individuais dentro dele)"."""

    @property
    @abc.abstractmethod
    def terminal_failure(self):
        """set[str] de status que significam "job terminou sem nada
        coletável — reabrir para nova tentativa"."""

    @property
    @abc.abstractmethod
    def in_progress(self):
        """set[str] de status que significam "ainda rodando, continuar
        fazendo polling"."""

    @abc.abstractmethod
    def create(self, requests, display_name):
        """requests: [{"key": str, "prompt": str}, ...]. Submete o job e
        retorna um job_id (str) opaco — salvo no state file, NUNCA
        resubmetido, só reconsultado via get()."""

    @abc.abstractmethod
    def get(self, job_id):
        """Retorna {"state": str, "responses": list[dict]|None, "error":
        str|None}. `responses` (quando state in terminal_success):
        [{"key","text","input_tokens","output_tokens","model_version",
        "error"}, ...] — mesmo shape usado por run_batch.py, para
        reaproveitar run_case._make_record sem alteração."""


# --------------------------------------------------------------------------
# OpenAIBatchProvider — primeira implementação real
# --------------------------------------------------------------------------
class OpenAIBatchProvider(EngineBatchProvider):
    MAX_COMPLETION_TOKENS = 3072
    # gpt-5.6-luna rejeita "minimal" (só "none"/"low"/...); gpt-5-nano rejeita "none".
    # Medido: com "none" o luna gasta 0 tokens de raciocínio e cita em 5/5.
    REASONING_EFFORT_POR_MODELO = {"gpt-5-nano": "minimal"}
    REASONING_EFFORT_PADRAO = "none"
    ENDPOINT = "/v1/chat/completions"
    COMPLETION_WINDOW = "24h"

    def __init__(self, model=DEFAULT_ENGINE, engine_slug=None):
        self.model = model
        self.engine_slug = engine_slug or model
        # Import tardio: modo mock não deve depender do SDK estar instalado
        # nem de rede (mesma disciplina de llm.generate() e de
        # run_batch.RealBatchClient).
        from openai import OpenAI

        api_key = llm.env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não encontrada (defina em .env na raiz do projeto "
                "ou na variável de ambiente)."
            )
        # Timeout explícito em segundos (não ms, ao contrário do google-genai) +
        # max_retries=0 no client porque o retry é feito manualmente em
        # self._retry (mesma disciplina/lição aprendida de RealBatchClient em
        # run_batch.py: sem timeout, uma conexão pendurada trava o polling
        # para sempre).
        self._client = OpenAI(api_key=api_key, timeout=120.0, max_retries=0)

    @property
    def terminal_success(self):
        return {"completed"}

    @property
    def terminal_failure(self):
        return {"failed", "expired", "cancelled"}

    @property
    def in_progress(self):
        return {"validating", "in_progress", "finalizing", "cancelling"}

    def _retry(self, fn, desc):
        import httpx
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        delays = (10, 30, 60, 120, 300, 600)  # runs de horas: tolera outage prolongado do provedor
        last_err = None
        for attempt in range(len(delays) + 1):
            try:
                return fn()
            except (APITimeoutError, APIConnectionError, httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
                if attempt >= len(delays):
                    raise
                print(f"  [openai-batch] {desc}: timeout/transporte ({type(e).__name__}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
            except APIStatusError as e:
                transitorio = e.status_code == 429 or e.status_code >= 500
                if not transitorio or attempt >= len(delays):
                    raise
                last_err = e
                print(f"  [openai-batch] {desc}: erro transitório ({e.status_code}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
        raise last_err

    def _build_body(self, prompt):
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": self.MAX_COMPLETION_TOKENS,
            "reasoning_effort": self.REASONING_EFFORT_POR_MODELO.get(self.model, self.REASONING_EFFORT_PADRAO),
            # SEM "temperature": gpt-5-nano rejeita valor != default (ver
            # docstring do módulo, seção "DECISÃO — TEMPERATURA").
        }
        return body

    def _to_jsonl_bytes(self, requests):
        lines = []
        for r in requests:
            line = {
                "custom_id": r["key"],
                "method": "POST",
                "url": self.ENDPOINT,
                "body": self._build_body(r["prompt"]),
            }
            lines.append(json.dumps(line, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def create(self, requests, display_name):
        data = self._to_jsonl_bytes(requests)
        if len(data) > _MAX_FILE_BYTES:
            raise SystemExit(
                f"Arquivo de batch '{display_name}' tem {len(data) / 1e6:.1f}MB, acima "
                f"da margem de segurança ({_MAX_FILE_BYTES / 1e6:.0f}MB; limite documentado "
                "~200MB para arquivos de entrada da Batch API da OpenAI). Reduza "
                "--chunk-size e rode de novo (chunks já coletados não são afetados)."
            )
        file_obj = self._retry(
            lambda: self._client.files.create(
                file=(f"{display_name}.jsonl", data, "application/jsonl"), purpose="batch",
            ),
            f"files.create({display_name})",
        )
        batch = self._retry(
            lambda: self._client.batches.create(
                input_file_id=file_obj.id,
                endpoint=self.ENDPOINT,
                completion_window=self.COMPLETION_WINDOW,
                metadata={"display_name": display_name[:512]},
            ),
            f"batches.create({display_name})",
        )
        return batch.id

    def _parse_output_lines(self, text):
        responses = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                responses.append({"key": None, "error": f"linha de output não é JSON válido: {line[:200]!r}"})
                continue
            key = obj.get("custom_id")
            if obj.get("error"):
                responses.append({"key": key, "error": str(obj["error"])})
                continue
            resp = obj.get("response") or {}
            status_code = resp.get("status_code")
            body = resp.get("body") or {}
            if status_code != 200:
                responses.append({"key": key, "error": f"status_code={status_code}: {body}"})
                continue
            choices = body.get("choices") or []
            if not choices:
                responses.append({"key": key, "error": "resposta sem choices"})
                continue
            message = choices[0].get("message") or {}
            text_out = message.get("content") or ""
            usage = body.get("usage") or {}
            model_version = body.get("model")
            if not model_version:
                responses.append({"key": key, "error": "resposta sem 'model' no body — versão do modelo não registrada"})
                continue
            responses.append({
                "key": key,
                "text": text_out,
                "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(usage.get("completion_tokens", 0) or 0),
                "model_version": model_version,
                "error": None,
            })
        return responses

    def get(self, job_id):
        batch = self._retry(lambda: self._client.batches.retrieve(job_id), f"batches.retrieve({job_id})")
        state = batch.status
        result = {"state": state, "responses": None, "error": None}
        if state in self.terminal_success:
            responses = []
            if batch.output_file_id:
                content = self._retry(
                    lambda: self._client.files.content(batch.output_file_id),
                    f"files.content(output:{batch.output_file_id})",
                )
                responses.extend(self._parse_output_lines(content.text))
            if batch.error_file_id:
                content = self._retry(
                    lambda: self._client.files.content(batch.error_file_id),
                    f"files.content(error:{batch.error_file_id})",
                )
                responses.extend(self._parse_output_lines(content.text))
            result["responses"] = responses
        elif state in self.terminal_failure:
            errs = batch.errors.data if batch.errors else None
            result["error"] = str(errs) if errs else state
        return result


# --------------------------------------------------------------------------
# AnthropicBatchProvider — Message Batches API (ver docstring do módulo,
# seção "PROVIDER ANTHROPIC" para o detalhamento completo do SDK verificado,
# limites, e decisões de temperatura/max_tokens/custom_id).
# --------------------------------------------------------------------------
class AnthropicBatchProvider(EngineBatchProvider):
    MAX_TOKENS = 2048
    TEMPERATURE = 0.7
    # Limites documentados da Message Batches API (ver docstring do módulo —
    # SEM chamada de rede pra confirmar em produção, mesmo caveat da OpenAI).
    MAX_REQUESTS_PER_BATCH = 100_000
    MAX_BODY_BYTES_DOCUMENTED = 256 * 1024 * 1024
    # Margem de segurança (mesma postura de _MAX_FILE_BYTES da OpenAI: 80%
    # do limite documentado, não medida localmente pra este provider — ver
    # docstring do módulo).
    _MAX_BODY_BYTES = int(MAX_BODY_BYTES_DOCUMENTED * 0.8)

    def __init__(self, model=DEFAULT_ENGINE, engine_slug=None):
        self.model = model
        self.engine_slug = engine_slug or model
        # Import tardio: modo mock não deve depender do SDK estar instalado
        # nem de rede (mesma disciplina de llm.generate(),
        # cross_validate._anthropic_generate() e OpenAIBatchProvider acima).
        import anthropic

        api_key = llm.env("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY não encontrada (defina em .env na raiz do projeto "
                "ou na variável de ambiente)."
            )
        # Timeout explícito em segundos + max_retries=0 no client porque o
        # retry é feito manualmente em self._retry (mesma disciplina de
        # OpenAIBatchProvider/RealBatchClient — lição aprendida documentada
        # na docstring de run_batch.py: sem timeout, uma conexão pendurada
        # trava o polling para sempre).
        self._client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=0)

    @property
    def terminal_success(self):
        return {"ended"}

    @property
    def terminal_failure(self):
        # A Message Batches API da Anthropic NÃO tem um estado de "batch
        # inteiro falhou" — processing_status só tem 3 valores (in_progress/
        # canceling/ended, ver docstring do módulo) e falha é sempre POR
        # request individual (result.type in errored/canceled/expired,
        # tratado em get()/_parse_result_item). Um batch 100% falho ainda
        # aparece como "ended" e é pego pela mesma lógica genérica de "falha
        # sistêmica" já existente em _process_chunk (novas==existentes==0 e
        # falhas>0) — por isso este set fica vazio, não é um descuido.
        return set()

    @property
    def in_progress(self):
        return {"in_progress", "canceling"}

    def _retry(self, fn, desc):
        import anthropic
        import httpx

        delays = (10, 30, 60, 120, 300, 600)  # runs de horas: tolera outage prolongado do provedor
        last_err = None
        for attempt in range(len(delays) + 1):
            try:
                return fn()
            except (anthropic.APITimeoutError, anthropic.APIConnectionError, httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
                if attempt >= len(delays):
                    raise
                print(f"  [anthropic-batch] {desc}: timeout/transporte ({type(e).__name__}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
            except anthropic.APIStatusError as e:
                transitorio = e.status_code == 429 or e.status_code >= 500
                if not transitorio or attempt >= len(delays):
                    raise
                last_err = e
                print(f"  [anthropic-batch] {desc}: erro transitório ({e.status_code}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
        raise last_err

    def _build_params(self, prompt):
        return {
            "model": self.model,
            "max_tokens": self.MAX_TOKENS,
            "temperature": self.TEMPERATURE,
            "messages": [{"role": "user", "content": prompt}],
        }

    def _build_requests(self, requests):
        out = []
        for r in requests:
            custom_id = _key_to_custom_id(r["key"])
            out.append({"custom_id": custom_id, "params": self._build_params(r["prompt"])})
        return out

    def create(self, requests, display_name):
        if len(requests) > self.MAX_REQUESTS_PER_BATCH:
            raise SystemExit(
                f"Batch '{display_name}' tem {len(requests)} requests, acima do limite "
                f"documentado da Message Batches API da Anthropic ({self.MAX_REQUESTS_PER_BATCH}). "
                "Reduza --chunk-size e rode de novo."
            )
        body = self._build_requests(requests)
        # Tamanho aproximado do corpo serializado — não medido em produção
        # pra este provider (ver docstring do módulo); serve só de guarda de
        # segurança grosseira antes de submeter.
        approx_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if approx_bytes > self._MAX_BODY_BYTES:
            raise SystemExit(
                f"Batch '{display_name}' tem corpo serializado de ~{approx_bytes / 1e6:.1f}MB, "
                f"acima da margem de segurança ({self._MAX_BODY_BYTES / 1e6:.0f}MB; limite "
                f"documentado ~{self.MAX_BODY_BYTES_DOCUMENTED / 1e6:.0f}MB). Reduza --chunk-size "
                "e rode de novo (chunks já coletados não são afetados)."
            )
        batch = self._retry(
            lambda: self._client.messages.batches.create(requests=body),
            f"messages.batches.create({display_name})",
        )
        return batch.id

    def _parse_result_item(self, item):
        try:
            key = _custom_id_to_key(item.custom_id)
        except Exception as e:
            return {"key": None, "error": f"custom_id não decodificável ({item.custom_id!r}): {e}"}

        result = item.result
        tipo = getattr(result, "type", None)
        if tipo == "succeeded":
            msg = result.message
            model_version = msg.model
            if not model_version:
                return {"key": key, "error": "resposta sem 'model' no Message — versão do modelo não registrada"}
            if msg.stop_reason not in ("end_turn", "stop_sequence"):
                # Mesma disciplina de cross_validate._anthropic_generate: não
                # esconder a anomalia (TASK.md regra 4), mas também não
                # tratar como erro fatal — a medição é registrada mesmo
                # assim (pode ser max_tokens/refusal), só sinalizada.
                print(
                    f"  [anthropic-batch] AVISO: {key} stop_reason='{msg.stop_reason}' — resposta "
                    "pode estar truncada/incompleta; medição registrada mesmo assim."
                )
            text = "".join(b.text for b in (msg.content or []) if getattr(b, "type", None) == "text")
            usage = msg.usage
            return {
                "key": key,
                "text": text,
                "input_tokens": int(usage.input_tokens or 0) if usage else 0,
                "output_tokens": int(usage.output_tokens or 0) if usage else 0,
                "model_version": model_version,
                "error": None,
            }
        elif tipo == "errored":
            err = result.error.error
            return {"key": key, "error": f"{getattr(err, 'type', '?')}: {getattr(err, 'message', '')}"}
        elif tipo == "canceled":
            return {"key": key, "error": "resultado cancelado (batch cancelado antes de terminar este request)"}
        elif tipo == "expired":
            return {"key": key, "error": "resultado expirado (batch não terminou a tempo — resubmeter)"}
        else:
            return {"key": key, "error": f"tipo de resultado desconhecido: {tipo!r}"}

    def get(self, job_id):
        batch = self._retry(
            lambda: self._client.messages.batches.retrieve(job_id),
            f"messages.batches.retrieve({job_id})",
        )
        state = batch.processing_status
        result = {"state": state, "responses": None, "error": None}
        if state in self.terminal_success:
            if not batch.results_url:
                # Confirmado via inspect.getsource(Batches.results) nesta
                # sessão: .results() levanta anthropic.AnthropicError se
                # results_url estiver vazio, mesmo com processing_status ==
                # "ended" (ex.: batch cancelado/expirado antes de processar
                # qualquer request). Tratamos como 0 respostas coletáveis em
                # vez de deixar a exceção subir — _process_chunk já mantém o
                # chunk "pending" quando len(responses) < n_esperado.
                print(
                    f"  [anthropic-batch] AVISO: job {job_id} status='ended' sem results_url "
                    "— nenhum resultado coletável; chunk permanecerá pendente para nova tentativa."
                )
                result["responses"] = []
                return result
            items = self._retry(
                lambda: list(self._client.messages.batches.results(job_id)),
                f"messages.batches.results({job_id})",
            )
            result["responses"] = [self._parse_result_item(item) for item in items]
        return result


# --------------------------------------------------------------------------
# MockEngineBatchProvider — genérico, reusável por qualquer engine_slug/model
# --------------------------------------------------------------------------
class MockEngineBatchProvider(EngineBatchProvider):
    """Simula submit/poll/collect sem tocar rede: create() já gera as
    respostas sintéticas (via llm._mock_response, mesma função usada por
    llm.generate() em modo mock) e get() já devolve status "completed" — não
    há estado "em andamento" simulado, para o teste ponta a ponta ser rápido.
    model_version="mock" sempre. Genérico o bastante para servir de mock a
    QUALQUER provider (não só o da OpenAI) — nenhuma lógica específica de
    OpenAI aqui."""

    def __init__(self, model=DEFAULT_ENGINE, engine_slug=None):
        self.model = model
        self.engine_slug = engine_slug or model
        self._jobs = {}
        self._counter = 0

    @property
    def terminal_success(self):
        return {"completed"}

    @property
    def terminal_failure(self):
        return {"failed"}

    @property
    def in_progress(self):
        return set()

    def create(self, requests, display_name):
        self._counter += 1
        name = f"mock-batches/{self._counter:04d}-{display_name}"
        responses = []
        for r in requests:
            mock = llm._mock_response(r["prompt"], temperature=1.0)
            responses.append({
                "key": r["key"], "text": mock["text"], "input_tokens": mock["input_tokens"],
                "output_tokens": mock["output_tokens"], "model_version": mock["model_version"],
                "error": None,
            })
        self._jobs[name] = responses
        return name

    def get(self, job_id):
        return {"state": "completed", "responses": self._jobs.get(job_id, []), "error": None}


PROVIDERS = {
    # gpt-5.6-luna: modelo pequeno da geração atual da OpenAI (ago/2026) —
    # pareado em faixa com gemini-3.5-flash-lite e claude-haiku-4-5.
    "gpt-5.6-luna": lambda: OpenAIBatchProvider(model="gpt-5.6-luna"),
    "gpt-5-nano": lambda: OpenAIBatchProvider(model="gpt-5-nano"),
    "claude-haiku-4-5": lambda: AnthropicBatchProvider(model="claude-haiku-4-5"),
}


def _make_provider(engine_slug):
    if llm.env("MOCK_LLM") == "1":
        return MockEngineBatchProvider(model=engine_slug, engine_slug=engine_slug)
    if engine_slug not in PROVIDERS:
        raise SystemExit(
            f"engine '{engine_slug}' desconhecido — providers disponíveis: "
            f"{sorted(PROVIDERS)}. Para adicionar um novo, implemente "
            "EngineBatchProvider e registre em PROVIDERS (ver docstring do módulo)."
        )
    return PROVIDERS[engine_slug]()


# --------------------------------------------------------------------------
# guarda de custo — ledger PRÓPRIO deste engine (reimplementação deliberada,
# mesmo precedente de cross_validate.CostGuardCrossval — ver docstring)
# --------------------------------------------------------------------------
class CostGuardEngine:
    def __init__(self, out_dir, engine_slug, root=ROOT):
        self.out_dir = Path(out_dir)
        if not self.out_dir.is_absolute():
            self.out_dir = root / self.out_dir
        self.engine_slug = engine_slug
        self.root = root
        self.max_cost = float(llm.env("MAX_COST_USD_PER_RUN", 40))
        self.total = self._scan_existing()
        self._warned_80 = False

    def _scan_existing(self):
        total = 0.0
        if self.out_dir.exists():
            for path in self.out_dir.glob("*.jsonl"):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("model_version") == "mock":
                            continue
                        total += float(rec.get("custo_usd", 0) or 0)
        return total

    def add(self, custo_usd_valor, contexto=""):
        self.total += custo_usd_valor or 0.0
        pct = (self.total / self.max_cost * 100) if self.max_cost else 0.0
        if pct >= 100:
            self._abort(contexto)
        elif pct >= 80 and not self._warned_80:
            self._warned_80 = True
            print(f"  [custo-{self.engine_slug}] AVISO: {pct:.1f}% do teto atingido (US$ {self.total:.4f} / US$ {self.max_cost:.2f})")

    def _abort(self, contexto):
        abort_path = self.root / f"ABORT_COST_{self.engine_slug}.md"
        conteudo = (
            f"# ABORT_COST_{self.engine_slug} — teto de custo do engine '{self.engine_slug}' atingido\n\n"
            f"- Custo acumulado (nominal, ledger {self.out_dir}): US$ {self.total:.4f}\n"
            f"- Teto (MAX_COST_USD_PER_RUN): US$ {self.max_cost:.2f}\n"
            f"- Contexto da chamada que estourou o teto: {contexto}\n"
            f"- Timestamp: {datetime.now(timezone.utc).isoformat()}\n\n"
            "A run foi abortada (SystemExit). Os traces já gravados não foram\n"
            "perdidos — resumível ao retomar após revisão humana do teto/orçamento.\n"
            "NOTA: este teto é contabilizado SEPARADAMENTE do ledger do Gemini\n"
            "(eval/traces/, ABORT_COST.md) e de qualquer outro engine — o teto do\n"
            "estudo inteiro (config/study.yaml) é a SOMA de todos os ledgers; somar\n"
            "é responsabilidade de quem orquestra o estudo, não deste script.\n"
        )
        abort_path.write_text(conteudo, encoding="utf-8")
        raise SystemExit(
            f"ABORTADO POR CUSTO ({self.engine_slug}): US$ {self.total:.4f} atingiu/excedeu "
            f"o teto US$ {self.max_cost:.2f}. Ver {abort_path.name}."
        )


# --------------------------------------------------------------------------
# trava de versão — reimplementação local (mesmo motivo do CostGuard acima)
# --------------------------------------------------------------------------
class ModelVersionTracker:
    def __init__(self, out_dir, engine_slug, root=ROOT):
        self.out_dir = Path(out_dir)
        if not self.out_dir.is_absolute():
            self.out_dir = root / self.out_dir
        self.engine_slug = engine_slug
        self.seen = self._scan_existing()

    def _scan_existing(self):
        seen = set()
        if self.out_dir.exists():
            for path in self.out_dir.glob("*.jsonl"):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        mv = rec.get("model_version")
                        if mv and mv != "mock":
                            seen.add(mv)
        return seen

    def check(self, model_version):
        if not self.seen:
            self.seen.add(model_version)
            return
        if model_version not in self.seen:
            raise SystemExit(
                f"ABORTADO: versão de modelo divergente detectada durante a coleta do "
                f"engine '{self.engine_slug}' — vista(s) anteriormente nos traces reais: "
                f"{sorted(self.seen)}; agora: '{model_version}'. O contrato exige versão "
                "de modelo única entre todos os traces reais de um mesmo engine "
                "(TASK.md/config/study.yaml, requisito 6 desta tarefa). Os traces já "
                "gravados nesta e em execuções anteriores permanecem intactos — revisão "
                "humana necessária antes de continuar."
            )


# --------------------------------------------------------------------------
# construção da lista de requests pendentes (reaproveitando os transforms do
# Gemini via cross_validate.load_transformed_texts — NUNCA gera transform novo)
# --------------------------------------------------------------------------
def _build_pending(query_ids, tecnicas, reps, out_dir, gemini_traces_dir=GEMINI_TRACES_DIR):
    """Retorna (pending, puladas). `puladas`: [{"query_id","motivo"}] — query
    inteira pulada quando falta QUALQUER transform real do Gemini para ela
    (nunca se gera um transform novo aqui, nunca se roda a query
    parcialmente)."""
    pending = []
    puladas = []
    for qid in query_ids:
        textos_transformados, faltando, _idx = cross_validate.load_transformed_texts(
            qid, tecnicas, gemini_traces_dir,
        )
        if faltando:
            motivo = f"transform Gemini faltando para técnica(s): {faltando}"
            puladas.append({"query_id": qid, "motivo": motivo})
            continue

        cenario = build_scenario.build_scenario(qid)
        query_text = cenario["query"]["query"]
        fontes_originais = cenario["fontes"]
        target_pos = random.Random(qid).randint(1, 5)
        existing = run_case._load_existing(run_case._trace_path(qid, out_dir))

        prompt_baseline = run_case._build_engine_prompt(query_text, fontes_originais)
        for rep in range(reps):
            if ("baseline", None, rep) in existing:
                continue
            pending.append({"key": _make_key(qid, "baseline", None, rep), "prompt": prompt_baseline})

        for tecnica in tecnicas:
            texto_transformado = textos_transformados[tecnica]
            fontes_mod = [
                dict(f, texto=texto_transformado) if f["posicao"] == target_pos else f
                for f in fontes_originais
            ]
            prompt_tecnica = run_case._build_engine_prompt(query_text, fontes_mod)
            for rep in range(reps):
                if ("tecnica", tecnica, rep) in existing:
                    continue
                pending.append({"key": _make_key(qid, "tecnica", tecnica, rep), "prompt": prompt_tecnica})
    return pending, puladas


# --------------------------------------------------------------------------
# coleta: converte respostas normalizadas em traces (schema de run_case.py)
# --------------------------------------------------------------------------
def _collect_responses(responses, out_dir, engine_model, versao_experimento, cost_guard,
                        version_tracker, modo_mock, job_id):
    """Retorna (novas, existentes, falhas). `existentes` conta respostas cuja
    célula (fase,tecnica,rep) já estava gravada no trace ANTES desta coleta
    (célula "reaproveitável", não é uma falha nem uma novidade) — usado por
    _process_chunk para distinguir uma falha SISTÊMICA (nada gravável, nada
    preexistente, só erro — ex.: parâmetro do body rejeitado pela API em
    100% dos requests) de falhas esporádicas dentro de um chunk majoritamente
    bem-sucedido."""
    novas = 0
    existentes = 0
    falhas = []
    existing_cache = {}
    for item in responses:
        key = item.get("key")
        if not key:
            falhas.append(("?", item.get("error", "resposta sem custom_id/key")))
            continue
        try:
            qid, fase, tecnica, rep = _parse_key(key)
        except ValueError:
            falhas.append((key, "key malformada"))
            continue
        if item.get("error"):
            falhas.append((key, item["error"]))
            continue
        model_version = item.get("model_version")
        if not model_version:
            falhas.append((key, "model_version ausente na resposta"))
            continue
        if not modo_mock:
            version_tracker.check(model_version)  # pode levantar SystemExit

        if qid not in existing_cache:
            existing_cache[qid] = run_case._load_existing(run_case._trace_path(qid, out_dir))
        existing = existing_cache[qid]
        if (fase, tecnica, rep) in existing:
            existentes += 1
            continue  # célula já presente no trace — pula

        text = item.get("text", "")
        input_tokens = item.get("input_tokens", 0)
        output_tokens = item.get("output_tokens", 0)
        custo = _custo_usd_batch(input_tokens, output_tokens, engine_model)
        target_pos = random.Random(qid).randint(1, 5)
        metricas = metrics.impressions(text, n_sources=5)
        resp_like = {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "custo_usd": custo, "model_version": model_version,
        }
        record = run_case._make_record(
            qid, fase, tecnica, rep, target_pos, text, metricas, resp_like, versao_experimento,
        )
        record["engine"] = engine_model
        record["modo"] = "batch"
        record["batch_job"] = job_id

        trace_path = run_case._trace_path(qid, out_dir)
        run_case._append_trace(trace_path, record)
        existing[(fase, tecnica, rep)] = record
        cost_guard.add(custo, contexto=f"{key} [batch:{job_id}]")
        novas += 1
    return novas, existentes, falhas


# --------------------------------------------------------------------------
# estado resumível
# --------------------------------------------------------------------------
def _state_full_path(state_file, root=ROOT):
    p = Path(state_file)
    return p if p.is_absolute() else root / p


def _load_state(state_file):
    path = _state_full_path(state_file)
    if not path.exists():
        return {"chunks": {}, "puladas": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"{path} corrompido ({e}) — corrija ou remova manualmente antes de "
            "continuar (não sobrescrevo automaticamente para não perder o estado de "
            "jobs em andamento)."
        )
    data.setdefault("chunks", {})
    data.setdefault("puladas", {})
    return data


def _save_state(state_file, state):
    path = _state_full_path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)


def _chunk_id(query_ids):
    import hashlib
    h = hashlib.sha1(",".join(query_ids).encode("utf-8")).hexdigest()[:8]
    return f"{query_ids[0]}_{query_ids[-1]}_{len(query_ids)}_{h}"


def _make_chunks(query_ids, chunk_size):
    ids = sorted(set(query_ids))
    return [ids[i:i + chunk_size] for i in range(0, len(ids), chunk_size)]


# --------------------------------------------------------------------------
# processamento de um chunk (etapa única: resposta do engine — o transform já
# existe, reaproveitado do Gemini)
# --------------------------------------------------------------------------
def _process_chunk(provider, state, state_file, chunk_record, pending, out_dir, poll_interval,
                    versao_experimento, cost_guard, version_tracker, modo_mock, wait, display_name,
                    chunk_id, counters):
    if chunk_record.get("status") == "collected":
        return True

    if chunk_record.get("status") != "submitted":
        if not pending:
            chunk_record.update(status="collected", n_requests=0)
            _save_state(state_file, state)
            print("  nada pendente neste chunk — marcado collected")
            return True
        job_id = provider.create(pending, display_name)
        chunk_record.update(
            status="submitted", job_id=job_id, n_requests=len(pending),
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_state(state_file, state)
        print(f"  submetido job={job_id} n_requests={len(pending)}")

    job_id = chunk_record["job_id"]
    while True:
        result = provider.get(job_id)
        state_str = result["state"]
        if state_str in provider.in_progress:
            if not wait:
                print(f"  job {job_id} em '{state_str}' — --no-wait, encerrando checagem")
                return False
            print(f"  job {job_id} em '{state_str}' — aguardando {poll_interval}s")
            time.sleep(poll_interval)
            continue
        break

    if state_str in provider.terminal_failure:
        print(f"  ERRO: job {job_id} terminou em '{state_str}': {result['error']}")
        chunk_record["status"] = "pending"
        chunk_record.pop("job_id", None)
        chunk_record.pop("n_requests", None)
        _save_state(state_file, state)
        return False

    responses = result["responses"] or []
    novas, existentes, falhas = _collect_responses(
        responses, out_dir, provider.model, versao_experimento, cost_guard,
        version_tracker, modo_mock, job_id,
    )
    counters["novas"] += novas
    n_esperado = chunk_record.get("n_requests", len(responses))
    print(
        f"  coletado job={job_id} respostas={len(responses)}/{n_esperado} novas={novas} "
        f"existentes={existentes} falhas={len(falhas)}"
    )
    for key, err in falhas[:10]:
        print(f"    falha: {key}: {err}")
    if len(falhas) > 10:
        print(f"    ... e mais {len(falhas) - 10} falha(s)")

    if novas == 0 and existentes == 0 and falhas:
        # FALHA SISTÊMICA: nenhuma célula nova gravada, nenhuma já existia —
        # ou seja, TUDO que veio do job é erro (ex.: parâmetro do body
        # rejeitado pela API em 100% dos requests, como reasoning_effort/
        # max_completion_tokens com um valor inválido). Marcar "collected"
        # aqui perderia essas células para sempre (um chunk "collected" nunca
        # mais recomputa `pending`) — reabrir para nova tentativa numa
        # próxima execução (útil ex.: depois de corrigir o body do request).
        print(
            f"  ERRO: TODAS as {len(falhas)} resposta(s) deste job falharam e nada foi "
            "gravado (nem novo, nem preexistente) — reabrindo chunk como pendente em vez "
            f"de marcar collected. Primeiro erro: {falhas[0][1]}"
        )
        chunk_record["status"] = "pending"
        chunk_record.pop("job_id", None)
        chunk_record.pop("n_requests", None)
        _save_state(state_file, state)
        return False

    if len(responses) < n_esperado:
        print(
            f"  AVISO: só {len(responses)}/{n_esperado} respostas retornadas pelo job {job_id} "
            f"(estado '{state_str}') — mantendo chunk como pendente para nova tentativa; o que "
            "já foi gravado no trace fica valendo."
        )
        chunk_record["status"] = "pending"
        chunk_record.pop("job_id", None)
        chunk_record.pop("n_requests", None)
        _save_state(state_file, state)
        return False

    if falhas:
        print(
            f"  AVISO: {len(falhas)} célula(s) falharam dentro de um chunk majoritariamente "
            "bem-sucedido e NÃO serão retentadas automaticamente (chunk marcado collected — "
            "mesma limitação herdada de run_batch.py: um chunk collected nunca recomputa "
            "pending). Revisar manualmente e, se preciso, rodar --queries só com os ids "
            "afetados sob um --state-file novo para forçar nova tentativa dessas células."
        )

    chunk_record.update(status="collected", collected_at=datetime.now(timezone.utc).isoformat())
    _save_state(state_file, state)
    return True


# --------------------------------------------------------------------------
# --status
# --------------------------------------------------------------------------
def cmd_status(state_file, out_dir, engine_slug):
    state = _load_state(state_file)
    chunks = state.get("chunks", {})
    if not chunks:
        print(f"nenhum chunk registrado em {state_file}")
    else:
        provider = None
        try:
            provider = _make_provider(engine_slug)
        except Exception as e:
            print(f"(aviso: não foi possível inicializar provider p/ consultar estado remoto: {e})")

        for chunk_id in sorted(chunks):
            rec = chunks[chunk_id]
            qids = rec.get("query_ids", [])
            rotulo = f"{qids[0]}..{qids[-1]}" if qids else "?"
            linha = (
                f"chunk {chunk_id}  ({len(qids)} queries: {rotulo})  status={rec.get('status')} "
                f"job={rec.get('job_id', '-')} n_requests={rec.get('n_requests', '?')}"
            )
            if provider is not None and rec.get("status") == "submitted" and rec.get("job_id"):
                try:
                    result = provider.get(rec["job_id"])
                    linha += f" remoto={result['state']}"
                except Exception as e:
                    linha += f" (erro ao consultar: {e})"
            print(linha)

    puladas = state.get("puladas", {})
    if puladas:
        print(f"\n{len(puladas)} query(ies) pulada(s) por falta de transform do Gemini:")
        for qid, motivo in sorted(puladas.items()):
            print(f"  {qid}: {motivo}")


# --------------------------------------------------------------------------
# --estimate — custo estimado a partir dos tokens médios reais do Gemini
# --------------------------------------------------------------------------
def cmd_estimate(query_ids, engine_slug, model, gemini_traces_dir=GEMINI_TRACES_DIR):
    study = run_case.load_study_config()
    tecnicas = list(study["tecnicas"])
    reps = study["engine"]["principal"]["reps_por_celula"]
    chamadas_por_query = reps + len(tecnicas) * reps  # 3 + 9*3 = 30

    elegiveis, puladas = [], []
    for qid in query_ids:
        _textos, faltando, _idx = cross_validate.load_transformed_texts(qid, tecnicas, gemini_traces_dir)
        (puladas if faltando else elegiveis).append(qid)

    amostra_tokens = elegiveis or query_ids
    avg_in, avg_out, n_amostra = cross_validate._avg_gemini_engine_tokens(amostra_tokens, gemini_traces_dir)
    custo_por_chamada = _custo_usd_batch(avg_in, avg_out, model)
    total_chamadas = len(elegiveis) * chamadas_por_query
    custo_total = total_chamadas * custo_por_chamada

    print(f"\n=== Estimativa de custo — batch engine '{engine_slug}' (modelo {model}) ===")
    print(f"  queries solicitadas: {len(query_ids)}  |  elegíveis (transform Gemini completo): {len(elegiveis)}  |  puladas: {len(puladas)}")
    print(
        f"  tokens médios/chamada observados nos traces reais do Gemini "
        f"(amostra n={n_amostra}): {avg_in:.0f} in / {avg_out:.0f} out"
    )
    print(f"  custo por chamada (com desconto de batch, config/prices.yaml): US$ {custo_por_chamada:.6f}")
    print(
        f"  --- estimativa ({len(elegiveis)} queries × {chamadas_por_query} chamadas = "
        f"{total_chamadas} chamadas): US$ {custo_total:.4f} ---"
    )
    if puladas:
        print(f"  ({len(puladas)} query(ies) seriam puladas por falta de transform do Gemini — não entram na estimativa)")
    caveat = (
        "  CAVEAT: este número é um PISO, não um teto. avg_input/output_tokens vêm dos "
        f"traces do Gemini (tokenizer/estilo diferentes de {model})"
    )
    # Reasoning tokens (family GPT-5) são billados como output mesmo com
    # reasoning_effort mínimo — específico dessa família, não generalizável a
    # outros engines (ex.: claude-haiku-4-5 não tem esse comportamento).
    if model.startswith("gpt-5"):
        caveat += (
            "; e para a família GPT-5, completion_tokens inclui tokens de raciocínio "
            "(billados como output) mesmo com reasoning_effort mínimo"
        )
    caveat += (
        " — o custo real por chamada deste engine tende a divergir do extrapolado a "
        "partir do Gemini. Não use este número sozinho contra o teto de US$40 do "
        "estudo sem margem de segurança."
    )
    print(caveat)
    return {
        "n_queries": len(query_ids), "n_elegiveis": len(elegiveis), "n_puladas": len(puladas),
        "avg_input_tokens": avg_in, "avg_output_tokens": avg_out, "n_amostra_tokens": n_amostra,
        "custo_por_chamada_usd": custo_por_chamada, "total_chamadas": total_chamadas,
        "custo_total_usd": custo_total,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="todas as queries com fontes em data/sources/")
    ap.add_argument("--queries", default=None, help="ids específicos, separados por vírgula")
    ap.add_argument("--status", action="store_true", help="mostra estado dos jobs sem submeter nada")
    ap.add_argument("--estimate", action="store_true", help="só imprime custo estimado, sem submeter nada")
    ap.add_argument(
        "--chunk-size", type=int, default=None,
        help=(
            f"queries por job submetido (default depende do engine — "
            f"{DEFAULT_CHUNK_SIZE_POR_ENGINE}, ou {DEFAULT_CHUNK_SIZE} para engines não listados)"
        ),
    )
    ap.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_S)
    ap.add_argument("--tecnicas", default=None, help="lista separada por vírgula (default: as 9 de config/study.yaml)")
    ap.add_argument("--reps", type=int, default=None, help="default: engine.principal.reps_por_celula de study.yaml")
    ap.add_argument("--engine", default=DEFAULT_ENGINE, help=f"default: {DEFAULT_ENGINE}")
    ap.add_argument("--out-dir", default=None, help="default: eval/traces_<engine>")
    ap.add_argument("--state-file", default=None, help="default: eval/batch_state_<engine>.json")
    ap.add_argument("--no-wait", action="store_true", help="consulta jobs em andamento 1x e sai, sem dormir poll-interval")
    args = ap.parse_args()

    engine_slug = args.engine
    out_dir = args.out_dir or _out_dir_default(engine_slug)
    state_file = args.state_file or _state_file_default(engine_slug)
    # default por engine (ver docstring do módulo, "AJUSTE MÍNIMO AO RUNNER
    # GENÉRICO") — só entra em jogo quando o usuário não passa --chunk-size.
    chunk_size = args.chunk_size if args.chunk_size is not None else DEFAULT_CHUNK_SIZE_POR_ENGINE.get(engine_slug, DEFAULT_CHUNK_SIZE)

    if sum(bool(x) for x in (args.status, args.estimate)) > 1:
        ap.error("--status e --estimate são mutuamente exclusivos")

    if args.queries:
        query_ids = sorted({q.strip() for q in args.queries.split(",") if q.strip()})
    elif args.all:
        sources_dir = ROOT / "data" / "sources"
        query_ids = sorted(p.stem for p in sources_dir.glob("*.jsonl"))
        if not query_ids:
            ap.error(f"nenhuma fonte encontrada em {sources_dir}")
    elif args.status:
        query_ids = []
    else:
        ap.error("especifique --all, --queries id1,id2, ou --status")
        return

    if args.status:
        cmd_status(state_file, out_dir, engine_slug)
        return

    study = run_case.load_study_config()
    tecnicas = [t.strip() for t in args.tecnicas.split(",")] if args.tecnicas else list(study["tecnicas"])
    reps = args.reps or study["engine"]["principal"]["reps_por_celula"]
    versao_experimento = study["versao_experimento"]
    model = engine_slug  # slug == model id para o provider atual (gpt-5-nano)

    if args.estimate:
        cmd_estimate(query_ids, engine_slug, model)
        return

    modo_mock = llm.env("MOCK_LLM") == "1"
    try:
        provider = _make_provider(engine_slug)
    except RuntimeError as e:
        # Mensagem clara, sem stack trace, quando falta a chave de API do
        # provider (ex.: ANTHROPIC_API_KEY/OPENAI_API_KEY ausente em modo
        # real) — genérico o bastante pra qualquer EngineBatchProvider que
        # levante RuntimeError no __init__ por credencial ausente, não só o
        # Anthropic (mesmo padrão de mensagem-limpa já usado por
        # cross_validate.cmd_run() para o caso análogo).
        print(f"{e} Abortando SEM chamar a API.")
        sys.exit(1)
    cost_guard = CostGuardEngine(out_dir, engine_slug)
    version_tracker = ModelVersionTracker(out_dir, engine_slug)

    state = _load_state(state_file)
    chunks = _make_chunks(query_ids, chunk_size)
    modo = "MOCK" if modo_mock else "REAL"
    print(f"modo={modo} engine={engine_slug} queries={len(query_ids)} chunks={len(chunks)} chunk_size={chunk_size}")

    counters = {"novas": 0}
    total_puladas_query = {}

    for qids in chunks:
        # Sufixo "__mock" isola COMPLETAMENTE as entradas de chunk de uma sessão
        # mock das de uma sessão real, ainda que rodem com o MESMO --state-file
        # (requisito 9: modo mock isolado da resumabilidade real). Sem isso, um
        # chunk "collected" por uma run MOCK_LLM=1 seria lido como "já feito"
        # por uma run real subsequente com os mesmos query_ids (mesmo chunk_id
        # de conteúdo) — 0 chamadas reais, 0 traces, sem erro visível. Com o
        # sufixo, os dois modos nunca colidem na mesma chave de state["chunks"].
        base_chunk_id = _chunk_id(qids)
        chunk_id = base_chunk_id + ("__mock" if modo_mock else "")
        chunk_record = state["chunks"].setdefault(chunk_id, {"query_ids": qids, "status": "pending", "mock": modo_mock})
        chunk_record["query_ids"] = qids
        chunk_record["mock"] = modo_mock
        print(f"=== chunk {chunk_id} ===")

        pending, puladas = _build_pending(qids, tecnicas, reps, out_dir)
        for p in puladas:
            total_puladas_query[p["query_id"]] = p["motivo"]
            state["puladas"][p["query_id"]] = p["motivo"]
        if puladas:
            print(f"  {len(puladas)} query(ies) pulada(s) nesta seleção por falta de transform do Gemini")
        _save_state(state_file, state)

        _process_chunk(
            provider, state, state_file, chunk_record, pending, out_dir, args.poll_interval,
            versao_experimento, cost_guard, version_tracker, modo_mock, not args.no_wait,
            f"geo-ptbr-{engine_slug}-{chunk_id}", chunk_id, counters,
        )

    print(f"\ntotal — chamadas novas: {counters['novas']} | queries puladas (falta de transform): {len(total_puladas_query)}")
    print("concluído (ou pausado — reexecute o mesmo comando para retomar).")


if __name__ == "__main__":
    main()
