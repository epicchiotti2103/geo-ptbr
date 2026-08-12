#!/usr/bin/env python3
"""Runner da Fase 3 (batch pago) — GEO-PTBR, via Batch API do google-genai.

Uso:
    python src/run_batch.py --all                          # todas as queries com fontes em data/sources/
    python src/run_batch.py --queries s001,j002             # ids específicos
    python src/run_batch.py --all --chunk-size 25 --poll-interval 60
    python src/run_batch.py --status                        # mostra estado dos jobs, sem submeter nada
    MOCK_LLM=1 python src/run_batch.py --queries s001,s002 --out-dir eval/traces_mock_batch

DESENHO (duas etapas por chunk de N queries, default N=25):
  Etapa T (transform): 1 batch job com N × 9 técnicas requests (prompts de
      transform.py, temperatura 0). Ex.: N=25 => 225 requests.
  Etapa E (engine): só é submetida DEPOIS que a etapa T do mesmo chunk foi
      coletada (as fontes-alvo precisam do texto já transformado). N × (3
      baseline + 9 técnicas × 3 reps) requests (prompt de
      run_case.ENGINE_PROMPT_TEMPLATE, temperatura 0.7). Ex.: N=25 => 750.
  Cada request carrega metadata={"key": "<query_id>|<fase>|<tecnica ou '-'>|
  <rep ou '-'>"} — a chave é auto-suficiente: a coleta reconstrói fase/
  técnica/rep/query_id só a partir dela (não depende de nenhum estado
  adicional persistido além do nome do job), e target_pos é sempre
  recomputado via random.Random(query_id).randint(1, 5) (mesma regra
  determinística do run_case.py).

LIMITES DO SDK/API VERIFICADOS (google-genai 2.17.0, instalado em .venv;
Gemini Developer API, não Vertex):
  - client.batches.create(model=, src=<list[dict]>, config=CreateBatchJobConfig)
    aceita `src` como list[dict] com chaves "contents" (str), "config"
    (dict, ex.: {"temperature": 0.7}) e "metadata" (dict[str,str]) — testado
    localmente construindo google.genai.types.InlinedRequest(**d) e chamando
    o transformer interno google.genai._transformers.t_batch_job_source com
    uma lista de dicts nesse formato: converte sem erro para
    types.BatchJobSource(inlined_requests=[...]) (nenhuma chamada de rede
    feita nesse teste).
  - google.genai.types.InlinedRequest.config é Optional[GenerateContentConfig]
    POR REQUEST — ou seja, temperatura é configurável por request dentro do
    mesmo job, não só por job. Como cada etapa (T ou E) usa uma única
    temperatura fixa (0.0 ou 0.7), aqui ela é aplicada uniformemente a todos
    os requests da etapa, mas a via está disponível se um dia for preciso
    misturar temperaturas num único job.
  - Resposta: client.batches.get(name=...).dest.inlined_responses é
    list[InlinedResponse], cada um com .metadata (echo do que foi enviado),
    .response (GenerateContentResponse — mesmo objeto de generate_content,
    com .text/.usage_metadata/.model_version) e .error (JobError, quando
    aquele request específico falhou dentro de um job
    PARTIALLY_SUCCEEDED/SUCCEEDED).
  - types.JobState tem 12 valores; note que
    types.JOB_STATES_ENDED = ['JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED',
    'JOB_STATE_CANCELLED', 'JOB_STATE_EXPIRED', 'ACTIVE', 'FAILED'] NÃO
    inclui JOB_STATE_PARTIALLY_SUCCEEDED — por isso este módulo não usa
    job.done e define seus próprios conjuntos terminais (TERMINAL_SUCCESS /
    TERMINAL_FAILURE / IN_PROGRESS abaixo), tratando PARTIALLY_SUCCEEDED como
    sucesso parcial coletável (requests com erro individual viram "falha" e
    ficam pendentes para uma resubmissão futura, sem abortar o chunk).
  - Limite documentado (ai.google.dev/gemini-api/docs/batch-mode e
    /batch-api, consultados nesta sessão — não há teste de rede local
    possível para confirmar o número exato): requests INLINE (o modo usado
    aqui) devem manter o tamanho total do payload abaixo de ~20MB; acima
    disso a doc recomenda arquivo JSONL. A doc não define um limite explícito
    de QUANTIDADE de requests por job inline. Este módulo aplica uma margem
    de segurança: _MAX_INLINE_BYTES = 18MB, medida via
    len(json.dumps(...).encode()) do payload completo antes de submeter —
    é uma APROXIMAÇÃO do payload de fio (o SDK serializa para proto/JSON da
    API, não byte-a-byte igual ao json.dumps local); a margem de 2MB sob o
    limite de 20MB existe também por causa dessa imprecisão, não só como
    colchão de segurança contra erro de estimativa de tamanho de fonte.
    Estoura com SystemExit pedindo --chunk-size menor. Nas contas do
    contrato (chunk=25 → 225 requests na etapa T, 750 na etapa E, fontes de
    150–400 palavras), o payload fica na casa de poucos MB — folga grande.
  - Também documentado: job batch expira em 48h se ficar
    pendente/rodando além disso (JOB_STATE_EXPIRED) — dentro da janela-alvo
    de 72h do contrato (config/study.yaml: fase_3.fase_3), mas relevante para
    quem for depurar um job "sumido".

ESTADO RESUMÍVEL (eval/batch_state.json, escrita atômica via
arquivo .tmp + os.replace): por chunk (chave = conteúdo, não posição — ver
_chunk_id) e por etapa (T/E), guarda {"status": "pending"|"submitted"|
"collected", "job_name", "n_requests", "submitted_at", "collected_at"}. Um
job "submitted" NUNCA é resubmetido — é apenas reconsultado (client.get). Um
job "collected" nunca dispara nova submissão. A lista de requests pendentes
de cada etapa é recomputada a partir do que falta nos traces reais (mesma
checagem fase+tecnica+rep de run_case._load_existing) toda vez que a etapa
ainda não foi submetida — isso significa que a run é resumível mesmo que a
composição de --all mude entre execuções (novas fontes adicionadas): o pior
caso é um chunk "novo" (chunk_id diferente, calculado por hash do conteúdo)
cobrir outra vez alguma query já concluída, mas como o pending é sempre
calculado a partir do trace real (não do estado do chunk), nenhuma célula já
coletada é resubmetida — só o encadeamento chunk-id vira menos eficiente
(chunks podem sobrepor parcialmente). Traces gravados por run_case.py e por
este módulo são intercambiáveis para fins de resumabilidade (mesma chave).

GUARDA DE CUSTO: reusa run_case.CostGuard (não alterado) sem modificação —
mesmo teto (MAX_COST_USD_PER_RUN), mesmo ABORT_COST.md, mesma exclusão de
traces mock. Custo por resposta usa desconto de batch
(config/prices.yaml: batch_desconto) via _custo_usd_batch(), uma extensão
LOCAL do cálculo nominal de llm.custo_usd() — llm.py não é tocado. Ordem de
gravação idêntica à de run_case.py: o trace é gravado ANTES de guard.add()
verificar o teto. Consequência (herdada de run_case.py, não introduzida
aqui): se o teto estourar no meio da coleta de um job já pago no Google,
as respostas restantes desse job são descartadas nesta execução e a etapa
não é marcada collected — numa retomada futura (após revisão humana do
teto), o pending recomputado vai resubmeter essas células, pagando de novo
pelo que o job anterior já cobriu. Aceito por ora por consistência com o
comportamento já estabelecido de run_case.py.

CHECAGEM DE VERSÃO ÚNICA (regra da Fase 3): ModelVersionTracker escaneia os
traces reais já existentes em --out-dir na inicialização; a cada resposta
real coletada (nunca em modo mock) cuja model_version ainda não foi vista,
compara contra o conjunto já visto — se divergir, aborta com SystemExit e
mensagem clara, preservando tudo que já foi gravado nesta e em execuções
anteriores.

MODO MOCK (MOCK_LLM=1): MockBatchClient não toca rede; client.create() monta
respostas sintéticas na hora (reaproveita llm._mock_response(), mesma função
usada por llm.generate() em modo mock) e client.get() já retorna
JOB_STATE_SUCCEEDED de imediato — não há espera nem polling em modo mock,
para que o teste ponta a ponta seja rápido. model_version="mock" em todas as
respostas mock, nunca conta para ModelVersionTracker nem para o teto real de
custo (mesma regra de run_case.py/llm.py).

CLI: --all | --queries id1,id2 | --status (mutuamente exclusivos entre os
dois primeiros e --status). --chunk-size (default 25), --poll-interval
(segundos, default 60), --out-dir (default eval/traces), --state-file
(default eval/batch_state.json — use um caminho separado em testes para
nunca tocar o estado real da Fase 3), --tecnicas, --reps (defaults de
config/study.yaml), --no-wait (consulta os jobs em andamento uma vez e sai,
sem dormir poll-interval — útil para checar rapidamente sem bloquear a
sessão).

CUIDADO OPERACIONAL (TASK.md E2): rodar sob `caffeinate` durante
submissão/coleta real, porque este processo bloqueia (time.sleep) enquanto
aguarda jobs em andamento.
"""
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import argparse
import hashlib
import json
import random
import time
from datetime import datetime, timezone

import build_scenario
import llm
import metrics
import run_case
import transform

ROOT = run_case.ROOT
DEFAULT_OUT_DIR = run_case.DEFAULT_OUT_DIR
DEFAULT_STATE_FILE = "eval/batch_state.json"
DEFAULT_CHUNK_SIZE = 25
DEFAULT_POLL_INTERVAL_S = 60

# Margem de segurança sob o limite documentado (~20MB) de payload inline da
# Gemini Developer API (ver docstring do módulo).
_MAX_INLINE_BYTES = 18 * 1024 * 1024

TERMINAL_SUCCESS = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
TERMINAL_FAILURE = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
IN_PROGRESS = {
    "JOB_STATE_UNSPECIFIED", "JOB_STATE_QUEUED", "JOB_STATE_PENDING",
    "JOB_STATE_RUNNING", "JOB_STATE_CANCELLING", "JOB_STATE_PAUSED",
    "JOB_STATE_UPDATING",
}


# --------------------------------------------------------------------------
# custo com desconto de batch — extensão LOCAL de llm.custo_usd(), llm.py
# não é alterado.
# --------------------------------------------------------------------------
def _custo_usd_batch(input_tokens, output_tokens, model=llm.ENGINE_MODEL):
    p = llm._prices()["modelos"][model]
    nominal = llm.custo_usd(input_tokens, output_tokens, model)
    return nominal * p.get("batch_desconto", 1.0)


# --------------------------------------------------------------------------
# chave auto-suficiente por request (metadata do batch)
# --------------------------------------------------------------------------
def _make_key(query_id, fase, tecnica, rep):
    return f"{query_id}|{fase}|{tecnica or '-'}|{'-' if rep is None else rep}"


def _parse_key(key):
    qid, fase, tecnica, rep = key.split("|")
    tecnica = None if tecnica == "-" else tecnica
    rep = None if rep == "-" else int(rep)
    return qid, fase, tecnica, rep


# --------------------------------------------------------------------------
# construção das listas de requests pendentes (pulando o que já está no trace)
# --------------------------------------------------------------------------
def _build_pending_transform(query_ids, tecnicas, out_dir):
    pending = []
    for qid in query_ids:
        cenario = build_scenario.build_scenario(qid)
        query_text = cenario["query"]["query"]
        fontes = cenario["fontes"]
        target_pos = random.Random(qid).randint(1, 5)
        target_fonte = next(f for f in fontes if f["posicao"] == target_pos)
        existing = run_case._load_existing(run_case._trace_path(qid, out_dir))
        for tecnica in tecnicas:
            if ("transform", tecnica, None) in existing:
                continue
            prompt = transform._BASE.format(
                query=query_text, instrucao=transform.TECNICAS[tecnica],
                texto=target_fonte["texto"],
            )
            pending.append({"key": _make_key(qid, "transform", tecnica, None), "prompt": prompt})
    return pending


def _build_pending_engine(query_ids, tecnicas, reps, out_dir):
    """Retorna (pending, incompletas). `incompletas` lista (query_id, tecnica)
    cujo transform ainda não está no trace — a etapa E não pode ser montada
    para essas células até a etapa T terminar de fato."""
    pending = []
    incompletas = []
    for qid in query_ids:
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
            transform_rec = existing.get(("transform", tecnica, None))
            if transform_rec is None:
                incompletas.append((qid, tecnica))
                continue
            texto_transformado = transform_rec["resposta"]
            fontes_mod = [
                dict(f, texto=texto_transformado) if f["posicao"] == target_pos else f
                for f in fontes_originais
            ]
            prompt_tecnica = run_case._build_engine_prompt(query_text, fontes_mod)
            for rep in range(reps):
                if ("tecnica", tecnica, rep) in existing:
                    continue
                pending.append({"key": _make_key(qid, "tecnica", tecnica, rep), "prompt": prompt_tecnica})
    return pending, incompletas


def _to_inline(pending, temperature):
    return [
        {"contents": r["prompt"], "config": {"temperature": temperature},
         "metadata": {"key": r["key"]}}
        for r in pending
    ]


def _check_inline_size(inline_requests, stage, chunk_id):
    size = len(json.dumps(inline_requests, ensure_ascii=False).encode("utf-8"))
    if size > _MAX_INLINE_BYTES:
        raise SystemExit(
            f"Job inline da etapa {stage} do chunk {chunk_id} tem {size / 1e6:.1f}MB, "
            f"acima da margem de segurança ({_MAX_INLINE_BYTES / 1e6:.0f}MB; limite "
            "documentado ~20MB para requests inline da Gemini Developer API). "
            "Reduza --chunk-size e rode de novo (chunks já coletados não são afetados)."
        )


# --------------------------------------------------------------------------
# clients: real (google-genai Batch API) e mock (offline, determinístico)
# --------------------------------------------------------------------------
def _normalize_inlined(ir):
    key = (ir.metadata or {}).get("key")
    if ir.error is not None:
        return {"key": key, "error": str(ir.error)}
    resp = ir.response
    if resp is None:
        return {"key": key, "error": "resposta vazia (sem response nem error)"}
    usage = resp.usage_metadata
    input_tokens = int(usage.prompt_token_count or 0) if usage else 0
    output_tokens = int(usage.candidates_token_count or 0) if usage else 0
    model_version = resp.model_version
    try:
        text = resp.text or ""
    except Exception:
        text = ""  # bloqueada por segurança etc. — mesmo tratamento de llm.py
    return {
        "key": key, "text": text, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "model_version": model_version, "error": None,
    }


class RealBatchClient:
    """Client fino sobre google.genai Client().batches — só é instanciado
    fora de modo mock (import tardio, mesma disciplina de llm.generate())."""

    def __init__(self):
        from google.genai import Client, types
        api_key = llm.env("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY não encontrada (defina em .env na raiz do projeto ou "
                "na variável de ambiente)."
            )
        # Timeout explícito (ms): sem ele, uma conexão pendurada trava o polling
        # para sempre — observado 2x na run da Fase 3 (o log para de crescer e o
        # job já está SUCCEEDED do lado do Google). Com timeout, a exceção cai no
        # _retry e o polling continua.
        self._client = Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=120_000),
        )

    def _retry(self, fn, desc):
        from google.genai import errors
        import httpx
        delays = (10, 30, 60)
        last_err = None
        for attempt in range(len(delays) + 1):
            try:
                return fn()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                # Timeout/erro de transporte: com http_options.timeout definido, é
                # assim que uma conexão pendurada se manifesta — sempre transitório.
                last_err = e
                if attempt >= len(delays):
                    raise
                print(f"  [batch] {desc}: timeout/transporte ({type(e).__name__}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
                continue
            except errors.APIError as e:
                code = getattr(e, "code", None)
                status = (getattr(e, "status", "") or "").upper()
                transitorio = code == 429 or status == "RESOURCE_EXHAUSTED" or \
                    (isinstance(code, int) and code >= 500) or status == "UNAVAILABLE"
                if not transitorio or attempt >= len(delays):
                    raise
                last_err = e
                print(f"  [batch] {desc}: erro transitório ({code or status}) — retry em {delays[attempt]}s")
                time.sleep(delays[attempt])
        raise last_err

    def create(self, model, requests, display_name):
        from google.genai import types
        job = self._retry(
            lambda: self._client.batches.create(
                model=model, src=requests,
                config=types.CreateBatchJobConfig(display_name=display_name),
            ),
            f"create({display_name})",
        )
        return job.name

    def get(self, name):
        job = self._retry(lambda: self._client.batches.get(name=name), f"get({name})")
        state = job.state.name if job.state else "JOB_STATE_UNSPECIFIED"
        result = {"state": state, "responses": None, "error": None}
        if state in TERMINAL_SUCCESS:
            dest = job.dest
            raw = (dest.inlined_responses if dest else None) or []
            result["responses"] = [_normalize_inlined(ir) for ir in raw]
        elif state in TERMINAL_FAILURE:
            result["error"] = str(job.error) if job.error else state
        return result


class MockBatchClient:
    """Simula submit/poll/collect sem tocar rede: create() já gera as
    respostas sintéticas (via llm._mock_response, mesma função usada por
    llm.generate() em modo mock) e get() já devolve JOB_STATE_SUCCEEDED —
    não há estado "em andamento" simulado, para o teste ponta a ponta ser
    rápido. model_version="mock" sempre."""

    def __init__(self):
        self._jobs = {}
        self._counter = 0

    def create(self, model, requests, display_name):
        self._counter += 1
        name = f"mock-batches/{self._counter:04d}-{display_name}"
        responses = []
        for r in requests:
            prompt = r["contents"]
            temperature = (r.get("config") or {}).get("temperature", 0.0)
            key = (r.get("metadata") or {}).get("key")
            mock = llm._mock_response(prompt, temperature)
            responses.append({
                "key": key, "text": mock["text"], "input_tokens": mock["input_tokens"],
                "output_tokens": mock["output_tokens"], "model_version": mock["model_version"],
                "error": None,
            })
        self._jobs[name] = responses
        return name

    def get(self, name):
        return {"state": "JOB_STATE_SUCCEEDED", "responses": self._jobs.get(name, []), "error": None}


def _make_client():
    if llm.env("MOCK_LLM") == "1":
        return MockBatchClient()
    return RealBatchClient()


# --------------------------------------------------------------------------
# checagem de versão única de modelo (regra da Fase 3)
# --------------------------------------------------------------------------
class ModelVersionTracker:
    def __init__(self, out_dir, root=ROOT):
        self.out_dir = Path(out_dir)
        if not self.out_dir.is_absolute():
            self.out_dir = root / self.out_dir
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
                "ABORTADO: versão de modelo divergente detectada durante a coleta — "
                f"vista(s) anteriormente nos traces reais: {sorted(self.seen)}; agora: "
                f"'{model_version}'. A Fase 3 exige versão de modelo única entre todos "
                "os traces reais (TASK.md/config/study.yaml). Os traces já gravados "
                "nesta execução e em execuções anteriores permanecem intactos — revisão "
                "humana necessária antes de continuar."
            )


# --------------------------------------------------------------------------
# estado resumível (eval/batch_state.json)
# --------------------------------------------------------------------------
def _state_full_path(state_file, root=ROOT):
    p = Path(state_file)
    return p if p.is_absolute() else root / p


def _load_state(state_file):
    path = _state_full_path(state_file)
    if not path.exists():
        return {"chunks": {}}
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
    return data


def _save_state(state_file, state):
    path = _state_full_path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)


def _make_chunks(query_ids, chunk_size):
    ids = sorted(set(query_ids))
    return [ids[i:i + chunk_size] for i in range(0, len(ids), chunk_size)]


def _chunk_id(query_ids):
    h = hashlib.sha1(",".join(query_ids).encode("utf-8")).hexdigest()[:8]
    return f"{query_ids[0]}_{query_ids[-1]}_{len(query_ids)}_{h}"


# --------------------------------------------------------------------------
# coleta: converte respostas normalizadas em traces (schema de run_case.py)
# --------------------------------------------------------------------------
def _collect_responses(responses, out_dir, versao_experimento, cost_guard,
                        version_tracker, modo_mock, job_name):
    novas = 0
    falhas = []
    existing_cache = {}
    for item in responses:
        key = item.get("key")
        if not key:
            falhas.append(("?", "resposta sem metadata.key"))
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
            continue  # célula já presente no trace (run_case.py ou coleta anterior) — pula

        text = item.get("text", "")
        input_tokens = item.get("input_tokens", 0)
        output_tokens = item.get("output_tokens", 0)
        custo = _custo_usd_batch(input_tokens, output_tokens)
        target_pos = random.Random(qid).randint(1, 5)
        metricas = None if fase == "transform" else metrics.impressions(text, n_sources=5)
        resp_like = {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "custo_usd": custo, "model_version": model_version,
        }
        record = run_case._make_record(
            qid, fase, tecnica, rep, target_pos, text, metricas, resp_like, versao_experimento,
        )
        record["batch_job"] = job_name
        record["modo"] = "batch"

        trace_path = run_case._trace_path(qid, out_dir)
        run_case._append_trace(trace_path, record)
        existing[(fase, tecnica, rep)] = record
        cost_guard.add(custo, contexto=f"{key} [batch:{job_name}]")
        novas += 1
    return novas, falhas


# --------------------------------------------------------------------------
# processamento de UMA etapa (T ou E) de UM chunk
# --------------------------------------------------------------------------
def _run_stage(client, state, state_file, chunk_record, stage, temperature, pending,
               out_dir, poll_interval, versao_experimento, cost_guard, version_tracker,
               modo_mock, wait, display_name, chunk_id, counters):
    stages = chunk_record.setdefault("stages", {})
    st = stages.setdefault(stage, {"status": "pending"})

    if st["status"] == "collected":
        return True

    if st["status"] != "submitted":
        if not pending:
            st.update(status="collected", n_requests=0)
            _save_state(state_file, state)
            print(f"  etapa {stage}: nada pendente — marcada collected")
            return True
        inline = _to_inline(pending, temperature)
        _check_inline_size(inline, stage, chunk_id)
        job_name = client.create(model=llm.ENGINE_MODEL, requests=inline, display_name=display_name)
        st.update(
            status="submitted", job_name=job_name, n_requests=len(pending),
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_state(state_file, state)
        print(f"  etapa {stage}: submetido job={job_name} n_requests={len(pending)}")

    job_name = st["job_name"]
    while True:
        result = client.get(job_name)
        state_str = result["state"]
        if state_str in IN_PROGRESS:
            if not wait:
                print(f"  etapa {stage}: job {job_name} em {state_str} — --no-wait, encerrando checagem")
                return False
            print(f"  etapa {stage}: job {job_name} em {state_str} — aguardando {poll_interval}s")
            time.sleep(poll_interval)
            continue
        break

    if state_str in TERMINAL_FAILURE:
        print(f"  ERRO etapa {stage}: job {job_name} terminou em {state_str}: {result['error']}")
        st["status"] = "pending"
        st.pop("job_name", None)
        st.pop("n_requests", None)  # evita "--status" reportar contagem de um job abandonado
        _save_state(state_file, state)
        return False

    responses = result["responses"] or []
    novas, falhas = _collect_responses(
        responses, out_dir, versao_experimento, cost_guard, version_tracker, modo_mock, job_name,
    )
    counters["novas"] += novas
    n_esperado = st.get("n_requests", len(responses))
    print(
        f"  etapa {stage}: coletado job={job_name} respostas={len(responses)}/{n_esperado} "
        f"novas={novas} falhas={len(falhas)}"
    )
    for key, err in falhas[:10]:
        print(f"    falha (célula fica pendente p/ retry): {key}: {err}")
    if len(falhas) > 10:
        print(f"    ... e mais {len(falhas) - 10} falha(s)")

    if len(responses) < n_esperado:
        # A API reportou estado terminal de sucesso, mas devolveu MENOS respostas
        # do que foram submetidas (ex.: dest.inlined_responses truncado/ausente,
        # ou — em modo mock — um job_name que não bate mais com o registrado).
        # NÃO marcar collected: se marcássemos, as células que não vieram nesta
        # resposta ficariam pendentes para sempre, porque _run_stage nunca mais
        # olha para `pending` de uma etapa já "collected". Reabrir para pending
        # (sem job_name) faz a próxima execução recomputar o que falta a partir
        # dos traces reais e resubmeter só isso — o que já foi gravado agora
        # não é refeito (checagem de existing em _collect_responses).
        print(
            f"  AVISO etapa {stage}: só {len(responses)}/{n_esperado} respostas retornadas "
            f"pelo job {job_name} (estado {state_str}) — mantendo etapa como pendente para "
            "nova tentativa; o que já foi gravado no trace fica valendo."
        )
        st["status"] = "pending"
        st.pop("job_name", None)
        st.pop("n_requests", None)  # evita "--status" reportar contagem de um job abandonado
        _save_state(state_file, state)
        return False

    st.update(status="collected", collected_at=datetime.now(timezone.utc).isoformat())
    _save_state(state_file, state)
    return True


# --------------------------------------------------------------------------
# --status
# --------------------------------------------------------------------------
def cmd_status(state_file, out_dir):
    state = _load_state(state_file)
    chunks = state.get("chunks", {})
    if not chunks:
        print(f"nenhum chunk registrado em {state_file}")
        return
    client = None
    try:
        client = _make_client()
    except Exception as e:
        print(f"(aviso: não foi possível inicializar client p/ consultar estado remoto: {e})")

    for chunk_id in sorted(chunks):
        rec = chunks[chunk_id]
        qids = rec.get("query_ids", [])
        rotulo = f"{qids[0]}..{qids[-1]}" if qids else "?"
        print(f"chunk {chunk_id}  ({len(qids)} queries: {rotulo})")
        for stage in ("T", "E"):
            st = rec.get("stages", {}).get(stage)
            if not st:
                print(f"  {stage}: (não iniciada)")
                continue
            linha = (
                f"  {stage}: status={st.get('status')} job={st.get('job_name', '-')} "
                f"n_requests={st.get('n_requests', '?')}"
            )
            if client is not None and st.get("status") == "submitted" and st.get("job_name"):
                try:
                    result = client.get(st["job_name"])
                    linha += f" remoto={result['state']}"
                except Exception as e:
                    linha += f" (erro ao consultar: {e})"
            print(linha)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="todas as queries com fontes em data/sources/")
    ap.add_argument("--queries", default=None, help="ids específicos, separados por vírgula")
    ap.add_argument("--status", action="store_true", help="mostra estado dos jobs sem submeter nada")
    ap.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    ap.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_S)
    ap.add_argument("--tecnicas", default=None, help="lista separada por vírgula (default: as 9 de config/study.yaml)")
    ap.add_argument("--reps", type=int, default=None, help="default: engine.principal.reps_por_celula de study.yaml")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    ap.add_argument("--no-wait", action="store_true", help="consulta jobs em andamento 1x e sai, sem dormir poll-interval")
    args = ap.parse_args()

    if args.status:
        cmd_status(args.state_file, args.out_dir)
        return

    if args.queries:
        query_ids = sorted({q.strip() for q in args.queries.split(",") if q.strip()})
    elif args.all:
        sources_dir = ROOT / "data" / "sources"
        query_ids = sorted(p.stem for p in sources_dir.glob("*.jsonl"))
        if not query_ids:
            ap.error(f"nenhuma fonte encontrada em {sources_dir}")
    else:
        ap.error("especifique --all, --queries id1,id2, ou --status")
        return

    study = run_case.load_study_config()
    tecnicas = [t.strip() for t in args.tecnicas.split(",")] if args.tecnicas else list(study["tecnicas"])
    reps = args.reps or study["engine"]["principal"]["reps_por_celula"]
    versao_experimento = study["versao_experimento"]

    modo_mock = llm.env("MOCK_LLM") == "1"
    client = _make_client()
    cost_guard = run_case.CostGuard(args.out_dir)
    version_tracker = ModelVersionTracker(args.out_dir)

    state = _load_state(args.state_file)
    chunks = _make_chunks(query_ids, args.chunk_size)
    modo = "MOCK" if modo_mock else "REAL"
    print(f"modo={modo} queries={len(query_ids)} chunks={len(chunks)} chunk_size={args.chunk_size}")

    counters = {"novas": 0, "puladas": 0}

    for qids in chunks:
        chunk_id = _chunk_id(qids)
        chunk_record = state["chunks"].setdefault(chunk_id, {"query_ids": qids, "stages": {}})
        chunk_record["query_ids"] = qids
        print(f"=== chunk {chunk_id} ===")

        pending_T = _build_pending_transform(qids, tecnicas, args.out_dir)
        counters["puladas"] += len(qids) * len(tecnicas) - len(pending_T)
        ok_T = _run_stage(
            client, state, args.state_file, chunk_record, "T", 0.0, pending_T,
            args.out_dir, args.poll_interval, versao_experimento, cost_guard,
            version_tracker, modo_mock, not args.no_wait, f"geo-ptbr-{chunk_id}-T",
            chunk_id, counters,
        )
        if not ok_T:
            continue

        pending_E, incompletas = _build_pending_engine(qids, tecnicas, reps, args.out_dir)
        if incompletas:
            print(
                f"  {len(incompletas)} transform(s) ainda pendentes após etapa T reportar "
                "'collected' (provável falha parcial na coleta) — reabrindo etapa T p/ nova "
                "tentativa nesta ou numa próxima execução."
            )
            chunk_record["stages"]["T"]["status"] = "pending"
            chunk_record["stages"]["T"].pop("job_name", None)
            _save_state(args.state_file, state)
            continue

        counters["puladas"] += (
            len(qids) * (reps + len(tecnicas) * reps) - len(pending_E) - len(incompletas) * reps
        )
        _run_stage(
            client, state, args.state_file, chunk_record, "E", 0.7, pending_E,
            args.out_dir, args.poll_interval, versao_experimento, cost_guard,
            version_tracker, modo_mock, not args.no_wait, f"geo-ptbr-{chunk_id}-E",
            chunk_id, counters,
        )

    print(f"\ntotal — chamadas novas: {counters['novas']} | já existentes/puladas: {counters['puladas']}")
    print("concluído (ou pausado — reexecute o mesmo comando para retomar).")


if __name__ == "__main__":
    main()
