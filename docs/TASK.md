# TASK.md — Contrato da run GEO-PTBR

**O contrato-base é [`PROMPT_GEO_PTBR.md`](PROMPT_GEO_PTBR.md).** Tudo que está lá vale
— parâmetros do estudo, regras inegociáveis, fases e critérios de conclusão — **exceto
onde as emendas abaixo o modificam**. Em conflito, este arquivo manda.

## Emendas operacionais (decididas com o Du em 2026-08-07)

### E1 — Modelo de operação: Claude orquestra, Grok executa
Não há agente autônomo solto em tmux como no projeto agenticocr. A operação é:

- **Claude (Claude Code)** é o orquestrador e revisor: planeja, delega blocos de
  trabalho, revisa cada entrega, mantém PROGRESS.md e o estado da run.
- **Grok (grok-4.5, via subagente `grok`)** é o operário: gera queries, fontes e
  material do experimento. Motivo científico: o engine julgador é o Gemini — quem
  produz o material não pode ser da mesma família de quem julga (viés de
  self-preference). Claude também não gera fontes/queries, pois claude-sonnet-5 é
  o engine de validação cruzada.
- **Humano (Du)** revisa nos checkpoints de fase e é o único que escreve linhas
  `AUTORIZADO FASE N:` no PROGRESS.md.

Consequência: os scripts de babá do desenho original (`run_loop.sh`, `watchdog.sh`,
autosave via cron) **não existem neste projeto**. Quem mantém a run viva é a sessão
do orquestrador. `scripts/` contém apenas utilitários de operação direta.

### E2 — Execução local (não Hetzner)
O projeto roda no Mac do Du, em `/Volumes/SSD1/Projects/paper` (volume externo).
A Fase 3 usa o modo batch da API do Gemini — o processamento pesado acontece no
servidor do Google; a máquina local só submete lotes e coleta resultados. Cuidado
operacional: durante submissão/coleta de lotes, usar `caffeinate` para evitar sleep.

### E3 — Papéis de modelo (não confundir)
| Papel | Modelo | Via |
|---|---|---|
| Orquestrador/revisor | Claude | Sessão Claude Code |
| Operário (código, queries, fontes) | grok-4.5 | Subagente `grok` (Grok Build CLI) |
| Engine do experimento | gemini-3.5-flash-lite | **API direta** (GEMINI_API_KEY em .env) |
| Engine de validação cruzada | claude-sonnet-5 | API Anthropic |

A regra do contrato-base permanece: o engine do experimento é SEMPRE API direta com
temperatura controlada — nunca CLI/chat de plano pessoal.

### E4 — Credencial Gemini (resolvido na Fase 2)
Billing ativo (projeto `projetocaracol`, Nível 2, créditos pré-pagos) — o free tier
do modelo dava só 20 req/dia, inviável até para o piloto. Mini-batch de prontidão
da Fase 3 executado com sucesso em 2026-08-10.

### E6 — Trocas de engine (histórico)
gemini-2.5-flash (contrato original) → indisponível para contas novas →
gemini-3.6-flash (v0.2.0) → 5x mais caro, projeção acima do teto →
**gemini-3.5-flash-lite (v0.3.0, em uso)**. Validação cruzada: claude-sonnet-4-6
→ **claude-sonnet-5** (decisão do Du, 2026-08-11).

### E5 — Estrutura de pastas
Igual ao contrato-base, com a raiz sendo esta pasta (`paper/`), e sem os scripts de
babá (ver E1). `docs/referencia_agenticocr.md` guarda o README do projeto anterior
como referência de desenho — não é normativo aqui.

## Regras que continuam valendo na íntegra (resumo)
1. Trabalhar somente dentro desta pasta.
2. Commit ao final de cada etapa concluída.
3. PROGRESS.md atualizado a cada sessão.
4. NUNCA inventar resultado de avaliação — resultado só existe com trace real.
5. Teto de custo US$ 40; custo logado por execução em eval/traces/.
6. Checkpoint humano entre fases; só humano escreve AUTORIZADO.
7. ~5% de queries-pegadinha para detectar alucinação de medição.
8. Dados em JSONL com schema fixo e validado.
