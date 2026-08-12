> ⚠️ **DOCUMENTO HISTÓRICO — NÃO É MAIS O ESTADO ATUAL DO PROJETO.**
>
> Este é o contrato ORIGINAL do estudo, preservado para registro de proveniência.
> Várias decisões mudaram durante a execução. **Antes de agir com base neste
> arquivo, leia `TASK.md` (emendas ao contrato) e `PROGRESS.md` (estado atual).**
>
> Principais divergências entre este documento e o projeto real (2026-08-11):
> | Aqui está escrito | Na prática é |
> |---|---|
> | Engine: gemini-2.5-flash | **gemini-3.5-flash-lite** (o 2.5 saiu do ar para contas novas; o 3.6 era 5x mais caro) |
> | 1 engine + validação cruzada de 50 queries | **3 engines com as 525 queries**: gemini-3.5-flash-lite, gpt-5.6-luna, claude-haiku-4-5 |
> | Validação cruzada em claude-sonnet-4-6 | Substituída por runs completas nos 3 engines (`src/cross_validate.py` ficou obsoleto) |
> | Teto de custo US$ 40 | **US$ 70** (escopo triplicou) |
> | Pasta `~/geo-ptbr` | `/Volumes/SSD1/Projects/paper` |
> | Agente autônomo em tmux + scripts de babá | Claude orquestra, Grok executa, humano autoriza fases (ver TASK.md §E1) |
> | Fontes "coletadas ou adaptadas" | **Sintético-realistas** geradas pelo Grok, rotuladas no campo `origem` (aceito no checkpoint da Fase 1) |
>
> As fases, as 9 técnicas, as métricas e as regras inegociáveis (nunca inventar
> resultado, commit por etapa, checkpoint humano entre fases) continuam valendo.

---

# PROMPT-MESTRE — Projeto GEO-PTBR (estudo + paper)

> Cole este documento inteiro como instrução inicial do agente. Todas as decisões de escopo já estão tomadas — não há parâmetros abertos.

---

Você é um agente de engenharia autônomo trabalhando no projeto **GEO-PTBR**: a primeira replicação em português brasileiro do paper "GEO: Generative Engine Optimization" (Aggarwal et al., arXiv:2311.09735), incorporando as lições do C-SEO Bench. O objetivo final são DOIS entregáveis: (1) um dataset/benchmark público de queries brasileiras com resultados experimentais por técnica de otimização, e (2) um paper em LaTeX no formato do paper original, pronto para preprint.

## CONTEXTO CIENTÍFICO (leia antes de qualquer código)

O experimento reproduz EM LABORATÓRIO a etapa final de um motor de busca generativo: dado um conjunto de fontes já recuperadas, qual delas o modelo cita na resposta. O protocolo por caso é:

1. Cenário: 1 query em PT-BR + 5 fontes reais em PT-BR que a respondem.
2. Baseline: prompt de "motor de busca com IA" com as 5 fontes no contexto → resposta com citações [1]..[5] → medir visibilidade de cada fonte (métricas do paper original: word count atribuído e position-adjusted count).
3. Intervenção: aplicar UMA técnica a UMA fonte-alvo (as 9 do paper: cite sources, quotation addition, statistics addition, fluency optimization, easy-to-understand, authoritative, unique words, technical terms, keyword stuffing), mantendo todo o resto idêntico.
4. Re-rodar a MESMA chamada e medir o delta de visibilidade da fonte-alvo.
5. Agregar por técnica × setor × posição da fonte.

LINHA DE COMPARAÇÃO JUSTA: o paper original usa modelos via API com fontes em contexto fixo. Nós fazemos o mesmo paradigma (modelo promptado vs. modelo promptado). NUNCA comparar nossos números com resultados de modelos treinados/fine-tunados de trabalhos derivados. Registrar em paper/KEY_FACTS.md quais tabelas do paper original são o alvo de comparação.

HONESTIDADE DECLARADA (vai na seção de limitações do paper): este desenho mede o efeito na etapa de citação, condicionado à fonte já estar no contexto. Não mede descobribilidade orgânica (crawl/index/retrieval) nem efeito durável de tráfego.

## PARÂMETROS DO ESTUDO

- Queries: 500 no total, distribuídas em 3 setores (~165 cada): (a) SAÚDE — clínicas médicas, exames, procedimentos, especialidades ("quanto custa uma rinoplastia", "clínica de fertilização como escolher"); (b) JURÍDICO — direito do consumidor, trabalhista, família, do ponto de vista de quem busca advogado ("posso ser demitido por justa causa se..."); (c) IMOBILIÁRIO — compra, aluguel, financiamento, bairros ("vale a pena comprar na planta"). Queries no registro de usuário real perguntando a uma IA, não no registro de palavra-chave de SEO. Nota para análise: saúde é setor YMYL — reportar diferenças de comportamento entre setores é um dos achados-alvo do estudo.
- Fontes por query: 5, textos reais em PT-BR (coletados ou adaptados), 150–400 palavras cada.
- Técnicas: as 9 do paper original, implementadas como transformações determinísticas via prompt padronizado (o prompt de transformação é fixo e versionado — mudou o prompt, mudou a versão do experimento).
- Motor simulado: **Gemini 2.5 Flash via API** (modelo da família que alimenta as respostas de IA do Google — relevância máxima para o mercado brasileiro). OBRIGATÓRIO usar API direta com temperatura e prompts controlados — NUNCA interfaces de chat/terminal de plano pessoal, que injetam system prompt, memória e personalização não observáveis e invalidam o experimento.
- ESTRATÉGIA DE TIER (contratual): Fases 1 e 2 rodam no free tier da API, em chamadas síncronas, respeitando os limites de RPM/RPD com backoff — o piloto (~300 chamadas) cabe no free tier e custa zero. A Fase 3 (run completa) roda OBRIGATORIAMENTE no tier pago via modo batch (≈50% de desconto). É PROIBIDO executar a run completa no free tier: esticá-la por semanas cria risco de o modelo ser atualizado no meio da coleta, contaminando o dataset com duas versões de engine — dado da Fase 3 só é válido se coletado numa janela compacta (alvo: ≤72h), com o identificador exato da versão do modelo registrado em cada trace. Se os traces da Fase 3 reportarem mais de uma versão de modelo, PARAR e reportar antes de prosseguir.
- Validação cruzada: amostra de 50 queries re-executada em um segundo engine (claude-sonnet-4-6 ou gpt-4o-mini via API) para verificar se a direção dos efeitos se mantém entre modelos. Reportar concordância no paper.
- Repetições: cada célula (query × técnica) roda 3 vezes com temperatura 0.7 e reporta média ± desvio (engines são estocásticos; 1 amostra não é resultado).
- Fonte-alvo: rotacionar a posição da fonte-alvo entre os cenários para não confundir efeito da técnica com efeito de posição.

## REGRAS INEGOCIÁVEIS DE OPERAÇÃO

1. Trabalhe SOMENTE dentro da pasta do projeto (~/geo-ptbr). Nada fora dela.
2. Commit git ao final de cada etapa concluída, com mensagem descritiva. Nunca acumular trabalho sem commit por mais de 1 hora de sessão.
3. Manter PROGRESS.md atualizado a cada sessão: o que foi feito, o que falta, decisões tomadas, custo acumulado.
4. NUNCA, sob nenhuma circunstância, inventar/estimar/extrapolar resultado de avaliação. Resultado só existe se saiu de execução real registrada em trace. Se um eval falhou, o resultado é "FALHOU", não um número plausível.
5. CUSTO: preços de API ficam em config/prices.yaml como constantes. Todo script que chama API calcula e loga custo por execução em traces/. Teto global: US$ 40 para o estudo completo (o custo esperado com batch é US$ 12–20; o teto é linha de aborto, não orçamento). Ao atingir 80% do teto, pausar e reportar. Ao atingir 100%, ABORTAR a run e escrever ABORT_COST.md com o estado.
6. CHECKPOINTS: ao concluir cada fase, escreva no PROGRESS.md a linha "FASE N CONCLUÍDA — AGUARDANDO REVISÃO" e PARE. Só continue quando um humano escrever no PROGRESS.md uma linha iniciada em "AUTORIZADO FASE N+1:". Você está PROIBIDO de escrever qualquer linha iniciada com a palavra AUTORIZADO.
7. Perguntas-pegadinha: o benchmark inclui ~5% de queries não-respondíveis pelas fontes dadas. Elas existem para detectar se o pipeline de medição está alucinando atribuições. Se uma pegadinha retornar visibilidade alta, isso é bug de medição — investigar antes de prosseguir.
8. Dados sempre em JSONL com schema fixo e validado. Um registro corrompido não derruba a run: loga, pula, contabiliza.

## ESTRUTURA DO PROJETO (criar na Fase 1)

```
geo-ptbr/
├── README.md            # porta de entrada p/ qualquer IA: o que é, arquitetura,
│                        # mapa de arquivos, ordem de leitura, regras inegociáveis
├── TASK.md              # este contrato
├── PROGRESS.md          # diário por sessão + checkpoints
├── config/
│   ├── prices.yaml      # preços por modelo (input/output por 1M tokens)
│   └── study.yaml       # parâmetros do estudo (n queries, setores, modelo, reps)
├── paper/
│   ├── geo_original.pdf # baixar do arXiv
│   ├── KEY_FACTS.md     # tabelas-alvo do paper original + linha de comparação justa
│   └── draft/           # o paper em LaTeX (Fase 5)
├── data/
│   ├── queries.jsonl    # query, setor, tipo (normal|pegadinha)
│   └── sources/         # 5 fontes por query, com origem registrada
├── src/
│   ├── build_scenario.py    # monta cenário query+fontes
│   ├── transform.py         # aplica as 9 técnicas (prompts versionados)
│   ├── run_case.py          # baseline + intervenção + medição de 1 caso
│   ├── metrics.py           # word count / position-adjusted, do paper
│   └── aggregate.py         # tabelas finais por técnica×setor
├── eval/
│   ├── run_eval.py      # roda o estudo; inclui baseline ingênuo p/ comparação
│   └── traces/          # 1 arquivo por execução: inputs, outputs, tokens, custo
├── results/             # tabelas e gráficos gerados (nunca editados à mão)
└── scripts/
    ├── start_run.sh     # inicia em tmux
    ├── status.sh        # progresso, custo acumulado, último commit
    ├── run_loop.sh      # ressurreição: crash/quota → commit parcial, espera 30min,
    │                    # renasce e retoma pelo PROGRESS.md
    └── watchdog.sh      # alerta se 3h sem commit
```

## FASES E CRITÉRIOS DE CONCLUSÃO

### FASE 1 — Infraestrutura e dados
- Estrutura acima criada; README.md e config/ completos.
- 500 queries geradas/coletadas nos 3 setores + ~25 pegadinhas, revisáveis em data/queries.jsonl.
- 5 fontes por query para as primeiras 50 queries (o restante é gerado na Fase 3, após validação do formato).
- CONCLUÍDA quando: `python src/build_scenario.py --validate` passa em 100% dos cenários existentes.
- → CHECKPOINT (humano revisa amostra de queries e fontes antes de autorizar).

### FASE 2 — Harness + piloto supervisionado (10 queries)
- run_case.py funcionando ponta a ponta com traces e custo real.
- Piloto: 10 queries × 9 técnicas × 3 reps. Gerar tabela piloto em results/.
- Sanidade obrigatória: (a) pegadinhas com visibilidade ~zero; (b) desvio entre reps reportado; (c) custo do piloto extrapolado para o estudo completo cabe no teto — senão, reportar e parar; (d) verificação de prontidão da Fase 3: billing ativo no projeto Google, submissão de um mini-batch de teste (5 chamadas) bem-sucedida, e versão do modelo registrada no trace.
- CONCLUÍDA quando: tabela piloto existe + os 4 checks de sanidade passam.
- → CHECKPOINT (humano valida números do piloto e custo projetado).

### FASE 3 — Run completa
- Gerar fontes das queries restantes; rodar 500 × 9 × 3 via batch pago do Gemini, orquestrado por run_loop.sh (submeter lotes, aguardar, coletar, validar, contabilizar custo). Janela de coleta alvo: ≤72h, versão do modelo idêntica em todos os traces.
- Progresso persistido: a run é retomável de onde parou (lotes já coletados nunca re-submetidos).
- Ao final: validação cruzada — as 50 queries designadas re-executadas no segundo engine, resultados em results/cross_validation/.
- CONCLUÍDA quando: ≥95% das células executadas com trace válido; falhas listadas; validação cruzada completa.
- → CHECKPOINT.

### FASE 4 — Análise
- aggregate.py gera: tabela principal (delta de visibilidade por técnica, com IC), quebra por setor, quebra por posição da fonte, e tabela de custo (tokens/US$ por técnica).
- Comparação lado a lado com as tabelas-alvo de paper/KEY_FACTS.md: onde replicamos a direção do efeito, onde divergimos.
- Cada ablation/variação medida separadamente contra o mesmo piloto baseline — nunca mudanças agregadas sem atribuição.
- CONCLUÍDA quando: results/ tem todas as tabelas + um FINDINGS.md em linguagem simples (5 achados principais, incluindo o que NÃO funcionou).
- → CHECKPOINT.

### FASE 5 — Paper + pacote de publicação
- paper/draft/: LaTeX no esqueleto do paper original (Abstract, Intro, Related Work, Methodology, Experiments, Results, Limitations, Conclusion), tabelas importadas de results/ por script (nunca digitadas).
- Seção de Limitations obrigatória: contexto fixo, não mede retrieval, engine principal único (mitigado pela validação cruzada em 50 queries), fontes parcialmente adaptadas, PT-BR.
- Resultados da validação cruzada reportados: % de técnicas com mesma direção de efeito nos dois engines.
- Pacote público: dataset limpo p/ Hugging Face (queries + fontes + resultados, com LICENSE e README citando aeobr.com.br), repo GitHub organizado.
- CONCLUÍDA quando: PDF compila + pacote HF/GitHub pronto em publish/.
- → CHECKPOINT FINAL (humano revisa o paper inteiro antes de qualquer publicação).

## PRIMEIRA AÇÃO

Leia este documento inteiro, escreva em PROGRESS.md seu plano de execução da Fase 1 em até 15 linhas (incluindo qualquer ambiguidade que encontrou), e comece. Não pule fases. Não otimize prematuramente. O estudo vale pelo rigor da medição, não pela sofisticação do código.
