# PROGRESS.md — Diário da run GEO-PTBR

Fonte da verdade do estado. Entradas em ordem cronológica inversa (mais recente no topo).
Checkpoints: só o humano escreve linhas iniciadas em `AUTORIZADO`.

---

## Sessão 2026-08-12 (cont. 5) — §5 escrito com números reais

Toda a prosa narrativa do §5 está escrita, mais Abstract, Conclusion e o
parágrafo do §3.5 sobre quanto o `baseline_pos` descarta. Paper em **19
páginas**, compila limpo, zero estouro de tabela.

**Delegação**: a extração dos números de setor/posição/pegadinhas/custo foi para
um subagente Sonnet (tarefa mecânica, sem juízo). A prosa NÃO foi delegada — ela
exige distinguir achado de ruído (5 inversões, só 1 sobrevive ao IC), e um erro
aí é exatamente o que o projeto inteiro se protege. O subagente pegou algo útil:
as 4 tabelas de `results/` na raiz são **só do gemini**, não dos 3 engines.

### Achados novos que entraram no paper (não estavam registrados aqui)
1. **Indução em pegadinhas — 5 das 9 técnicas induzem citação de fonte que não
   responde**, com IC excluindo zero: statistics_addition (+0,315),
   keyword_stuffing (+0,315), authoritative (+0,214), easy_to_understand
   (+0,208), quotation_addition (+0,197). Baseline exatamente 0 nas 25
   pegadinhas — o pipeline de medição não alucina; as técnicas é que induzem.
   Três delas (statistics_addition, authoritative, easy_to_understand) são
   inúteis ou daninhas para visibilidade legítima E das melhores em induzir
   citação indevida. Um terço do benchmark é saúde: isso é falha de segurança,
   não resultado de otimização.
2. **Saúde (YMYL) é o setor MENOS responsivo** — só 2 de 9 técnicas com efeito
   distinguível, contra 3 no jurídico e 4 no imobiliário. Contraria a intuição
   de que YMYL reagiria mais a sinais de autoridade: `authoritative` não é
   distinguível de zero em setor nenhum.
3. **A Tabela 2 do paper original NÃO replica.** O gradiente de posição do
   `cite_sources` (rank-1 −30,3% → rank-5 +115,1%) não aparece: nossas medianas
   são +0,0/+0,6/+2,8/+1,2/+3,5% e só o rank-3 exclui zero. O sinal "concorda"
   em 4 de 5 posições, mas com magnitude 1–2 ordens menor e IC cruzando zero em
   4 delas — por isso o paper não apoia nada nessa concordância de sinal.
4. **vs. paper original**: 5 de 9 direções replicam, ρ=0,62 (mediana) vs 0,80
   (média). Reportamos 0,62 como o número, com o 0,80 ao lado: a média infla a
   concordância por causa de baselines pequenos, exatamente o que o piloto
   previu.
5. **Custo entre engines varia 7×** para o mesmo benchmark e mesma faixa de
   modelo: US$ 15,93 / 44,66 / 6,10.

### O que falta no paper (tudo depende de você ou de literatura)
- `\TODO` de **autoria**: nome, afiliação, e-mail de correspondência, data.
- `\TODO` de **URLs**: dataset no Hugging Face e repositório GitHub.
- `\TODO` de **Related Work**: expansão da seção. **Não deleguei nem escrevi** —
  exigiria citar trabalhos que eu não posso verificar, e inventar referência é
  a única coisa pior que não ter a seção.
- Os outros 9 `\TODO` são ramos de `\IfFileExists` que **nunca renderizam** (as
  tabelas existem): são a rede de segurança, não pendência.

---

## Sessão 2026-08-12 (cont. 4) — ✅ tabelas legíveis: PAPER_VIEW + longtable

A pendência das tabelas ilegíveis está resolvida. Eram **dois** problemas, não um:
colunas demais (o `\resizebox` encolhia a fonte para caber na largura) **e**
`table`+`tabular` não quebrarem página (o `\resizebox` era forçado a espremer
180 linhas na altura de uma página). O segundo é o que colunas sozinhas não
resolveriam.

**`PAPER_VIEW` em `scripts/csv_to_latex.py`** — por tabela, um subconjunto de
colunas e um filtro de linhas. O **`.csv` continua completo**: ele é o dataset,
só a versão impressa é curada. Toda tabela recortada leva na legenda uma frase
automática dizendo o que foi recortado e onde está a completa — tabela curada
não pode se passar por completa. Falha ALTA (exceção) em coluna inexistente ou
filtro que não casa com linha nenhuma: emitir 6 de 8 colunas pedidas em silêncio
é a mesma classe de risco do PARCIAL sem marcação.

**`longtable` acima de `MAX_LINHAS_FLOAT = 40`** — quebra entre páginas com
cabeçalho repetido e **sem `\resizebox`**. `\usepackage{longtable}` no preâmbulo.

**Rótulos e precisão** (só na visão do paper; o `.csv` não muda):
`melhoria_mediana_pct__gemini-3.5-flash-lite` (42 caracteres) vira `gemini med.
%`; valores enumerados em português viram inglês por correspondência EXATA
(desconhecido passa intacto, nunca é adivinhado); e a precisão passa a
acompanhar a magnitude — `-74.563636` vira `-74.56`, mas visibilidade absoluta
(~0,001) mantém 4 casas.

**Medido a cada passo, não estimado:**
| passo | escala da fonte / estouro |
|---|---|
| início | escala 0,29–0,51 (fonte ~3pt) |
| + colunas curadas | 0,42–0,78 |
| + rótulos curtos | 0,58–0,78, mas **207pt e 130pt de estouro** nas longtables |
| + views enxutas e `\tabcolsep` 2pt | **0 estouros** |

Paper: **16 páginas** (eram 12 com as tabelas esmagadas). Zero referência
indefinida. Conferido *visualmente*, renderizando a página em PNG — não só pela
ausência de aviso.

⚠️ **`comparacao_2_engines.tex` é gerado mas nenhum `\input` o inclui.**
Deliberado: é a tabela do par de contingência. Se alguém adicionar um `\input`
para ela agora que os números de 3 engines são o resultado real, o paper passa a
carregar **duas respostas diferentes** para a mesma pergunta. Não incluir.

---

## Sessão 2026-08-12 (cont. 3) — 🎉 RUN COMPLETA: 3 engines × 525, resultado final

### Fase 3 encerrada
**525/525 queries completas por CÉLULA nos três engines** (checado com
`compare_engines`, não por `ls`). Interseção pareada: 525. O luna não repetiu a
armadilha do haiku — zero recuperação necessária.

**Custo final: US$ 66,69** de um teto de US$ 70 (95,3%). gemini 15,93 · haiku
44,66 · luna 6,10. Projeção da manhã era ~66,9 — bateu.

### RESULTADO CENTRAL (conjunto primário `baseline_pos`, n efetivo = 402 IDÊNTICO nos 3, Imp_pwc)

| técnica | gemini | haiku | luna | concordam? | sig. nos 3? |
|---|---|---|---|---|---|
| cite_sources | +0,5% | −2,3% | −12,1% | inversão | não |
| quotation_addition | +0,0% | −2,1% | −9,6% | inversão | não |
| statistics_addition | −1,4% | +0,6% | **−81,5%** | inversão | não |
| fluency_optimization | +0,2% | +7,9% | −6,9% | inversão | não |
| easy_to_understand | −5,4% | −10,7% | −31,4% | **sim** | **sim** |
| authoritative | −3,1% | −8,1% | −48,7% | **sim** | **sim** |
| unique_words | −3,2% | −54,1% | −55,4% | **sim** | **sim** |
| **technical_terms** | **+1,9%** | **−4,4%** | **−12,4%** | **inversão** | **SIM** |
| keyword_stuffing | −9,1% | −28,6% | −45,3% | **sim** | **sim** |

1. **`technical_terms` é a inversão genuína, agora com 3 engines**: IC95 exclui
   zero nos TRÊS, com sinal positivo no gemini e negativo nos outros dois.
   Continua sendo a única técnica que inverte COM suporte estatístico em todos.
2. **Concordância de direção: 44,4% (4/9)** — contra 66,7% no par gemini×haiku.
   **Adicionar o terceiro engine derrubou a concordância**: quanto mais engines,
   menos o protocolo GEO transfere. É o argumento mais forte do paper.
3. As 4 que concordam são **todas negativas e significativas nos três**.
4. **O luna reage muito mais forte**: `statistics_addition` −81,5% (contra −1,4%
   e +0,6%), `authoritative` −48,7%. ⚠️ Mas como gemini e haiku cruzam zero em
   `statistics_addition`, isso **não** é inversão com suporte — a frase correta é
   "um engine reage catastroficamente onde os outros não mostram nada".
5. **Das 5 inversões, só `technical_terms` tem efeito ≠ 0 nos três.** As outras 4
   têm IC cruzando zero em pelo menos um engine — **não escrever como achado.**
6. Spearman: gemini×haiku ρ=0,67 · gemini×luna ρ=0,55 · haiku×luna ρ=0,48.
   Nenhum par correlaciona forte.

Por engine (`aggregate.py` com `baseline_pos`), a melhor técnica do gemini é
`technical_terms` (+2,6%, IC [+0,9%, +4,3%], n=497) — coerente com a inversão.

### Tabelas e paper
`results/` regerado com o `aggregate.py` portado; `results/por_engine/<slug>/`
para haiku e luna. `make tables` gerou **10/10** (o gate liberou sozinho: sem
`PARCIAL` em lugar nenhum). O paper compila em **12 páginas**.

### 🔴 CONFIRMADO COM DADO REAL: as tabelas são ilegíveis
As 10 tabelas juntas — uma delas com **180 linhas** (`quebra_por_posicao`), outra
com 108 (`quebra_por_setor` e `comparacao_3_engines`) — acrescentaram **apenas 1
página** (11 → 12). Não há aviso de "float too large" porque o
`\resizebox{\textwidth}` encolhe tudo até caber: a fonte fica na casa de 3 pt.

**"Compila" continua não sendo "está publicável".** Esta é agora a maior
pendência do paper, e é a próxima decisão de Fase 5 (ver recomendação na entrada
anterior: `--columns` + uma linha por técnica com engines em colunas).

---

## Sessão 2026-08-12 (cont. 2) — fiação do LaTeX fechada + tabelas largas demais

### ✅ PENDÊNCIA FECHADA: `KNOWN_TABLES`/`TABLE_SUBDIR`
`scripts/csv_to_latex.py` agora conhece as tabelas do `compare_engines.py`:
`comparacao_3_engines`, `comparacao_2_engines`, `concordancia_engines`,
`spearman_engines`, com legenda em inglês. O `comparacao_2_engines` (par
gemini×haiku) ganhou entrada em `TABLE_SUBDIR` apontando para
`results/par_gemini_haiku/` — é o resultado de contingência caso o luna não
feche, e sem a entrada o `.csv` não seria encontrado.

**`comparacao_engines` (do `cross_validate.py`) foi REMOVIDA** do `KNOWN_TABLES`.
O `main.tex` já não faz `\IfFileExists` nela; mantê-la registrada deixaria
aberto o último caminho por onde números de um experimento que não existe mais
poderiam entrar no paper.

As legendas das 4 tabelas do `aggregate.py` passaram a **declarar qual conjunto
é o primário** — sem isso o leitor veria duas linhas por técnica, com números
diferentes, e nenhuma indicação de qual é o resultado.

Testado contra dado real: o par congelado (não-PARCIAL) gera; as três tabelas
3-engines de `results/` **BLOQUEARAM de verdade** pelo marcador PARCIAL (exit 1)
— o gate disparou em dado real, não em teste sintético.

### ⚠️ ACHADO NOVO: as tabelas não cabem na página
Primeiro teste de renderização de uma tabela real dentro do `main.tex` (feito
com o par congelado, copiado temporariamente e removido em seguida): **compila,
mas é ilegível**. A `comparacao_2_engines` tem **25 colunas × 72 linhas de
dado** (2 conjuntos × 2 métricas × 9 técnicas × 2 engines), e o
`csv_to_latex.py` embrulha tudo em `\resizebox{\textwidth}`, que encolhe a
fonte até caber. Com 3 engines serão 108 linhas. A `tabela_principal` tem 36
linhas × ~20 colunas.

"Compila" ≠ "está publicável". **O CSV é o dataset e deve manter todas as
colunas; a tabela do paper precisa de um subconjunto curado.** Decisão de Fase 5
ainda não tomada — opções: (a) `csv_to_latex.py` ganha `--columns` para
selecionar; (b) uma linha por técnica com os engines em colunas, e os detalhes
(IC, n, citação zerada) só no CSV; (c) quebrar em tabelas por métrica.
Recomendação do orquestrador: (a) + (b), com a tabela do paper reportando
mediana + IC por engine e nada mais.

### ⚠️ Erro de operação registrado
Ao remover o `.tex` temporário do teste, o `rm` rodou de dentro de
`paper/draft/` por causa de um `cd` anterior no mesmo comando, então o caminho
relativo não bateu e **o arquivo ficou** — só saiu na verificação seguinte.
Lição: depois de qualquer teste que escreva em `paper/draft/tables/`, conferir
com `ls` a partir da raiz do projeto. O diretório correto tem **só o
`README.md`**.

---

## Sessão 2026-08-12 (cont.) — realinhamento estrutural do paper

O `main.tex` estava **uma mudança de escopo atrás do experimento**: descrevia,
em Abstract, Contribuições e §4 Setup, um desenho de "1 engine + validação
cruzada de 50 queries no claude-sonnet-5" — experimento que **não existe** (o
`cross_validate.py` ficou obsoleto e o sonnet nunca rodou nessa escala). Um
endossante do arXiv que abrisse o Setup e não achasse aquilo nos Results leria
como descuido. Corrigido antes de escrever qualquer prosa do §5, que é quando
sairia caro.

### 🔴 ERRO DE CORREÇÃO NA METODOLOGIA (o achado mais sério da sessão)
O §3.5 (Statistical treatment) afirmava:
> *"Eq. 4 is undefined when the baseline is exactly zero — that case is reported
> as 'new', never imputed with a numeric value."*

**Falso no código.** Só `antes=0 & depois>0` é indefinido; `antes=0 & depois=0`
retorna `0.0` e É imputado. Ou seja, o paper descrevia na Metodologia o oposto
do que o pipeline faz, e o que ele descrevia era justamente a ausência do
zero-injection. Reescrito: agora distingue o caso indefinido do caso
**degenerado**, e documenta `baseline_pos` como conjunto primário + conjunto
completo como sensibilidade, incluindo o argumento do n efetivo idêntico entre
engines. Sem números digitados à mão — a magnitude fica como `\TODO` a ser lida
das tabelas.

### O que mudou de estrutura
- **Abstract**: 3 engines × 525 como desenho; achado central reenquadrado como
  *efeito dependente de engine*, com `\TODO` para os números.
- **Contribuições**: item 3 vira a avaliação em 3 engines (com a transformação
  reusada, que é o que isola "quem responde"); **item novo** afirmando a
  dependência de engine como contribuição própria, não como robustez.
- **§4 Setup**: parágrafo "Cross-validation engine" → "The three evaluation
  engines"; tabela de setup corrigida (525 queries com as 25 pegadinhas
  explícitas; 3 engines; teto US$ 70, não 40; janela de coleta single-version
  **por engine**, não compartilhada — verificado: 1 `model_version` por
  diretório de traces).
- **§5**: a comparação entre engines sai de §5.6 ("Cross-engine validation",
  apêndice de robustez) e vira **§5.2**, logo após Main results, apontando para
  `comparacao_3_engines` / `concordancia_engines` / `spearman_engines`. O
  `\IfFileExists` do obsoleto `comparacao_engines.tex` foi **eliminado** — era
  um caminho por onde números do `cross_validate.py` podiam entrar no paper em
  silêncio.
- **Limitations**: 3 itens reescritos (o "engine único" deixou de ser limitação;
  virou "a transformação nunca é cross-engine", que é a limitação real) e **3
  fatos novos**: temperatura não-customizável do luna, janelas de coleta não
  compartilhadas, e o item de completude por célula que o PROGRESS já marcava
  como "vai para Limitations" (bloco contíguo faltante que invertia um achado).

Nenhuma prosa narrativa do §5 foi escrita — as tabelas não existem e o luna não
fechou. Todos os `\TODO{Narrative summary...}` continuam de pé.

### ⚠️ ARMADILHA NOVA: `make` no paper/draft GERA as tabelas
O bloqueio do `.tex` **não é sustentável por disciplina**: `make` no
`paper/draft/` roda `scripts/csv_to_latex.py` como primeira regra. Rodei `make`
só para compilar e ele gerou 6 `.tex` a partir dos CSVs antigos do gemini
(pré-`baseline_pos`, sem a coluna `conjunto`) — que o `\IfFileExists` teria
puxado para dentro do paper sem marcação nenhuma. Removidos na hora
(`paper/draft/tables/` voltou a ter só o README).

**RESOLVIDO no mesmo dia** — ver "Bloqueio do .tex agora é garantido por código"
abaixo. `make` já não regenera tabela.

### ✅ Bloqueio do `.tex` agora é garantido por código, não por disciplina
Três mudanças, em ordem de importância:

1. **Gate de PARCIAL dentro do `scripts/csv_to_latex.py`** (não no Makefile).
   O conversor já lia as linhas `#` de metadado do `.csv`; agora recusa gerar
   `.tex` de qualquer CSV que carregue o marcador `PARCIAL`, e **sai com código
   1** para o `make tables` falhar em vez de passar batido. Fica no script, e
   não no Makefile, porque o Makefile é UM ponto de entrada — quem chama
   `python scripts/csv_to_latex.py` direto (como o próprio help ensina) pularia
   um gate no Makefile. Escotilha explícita: `--force`, que gera com aviso.
   Se já existir um `.tex` antigo daquela tabela, o bloqueio avisa nominalmente
   e manda removê-lo, porque o `\IfFileExists` o incluiria assim mesmo.
2. **`.DEFAULT_GOAL := pdf` no Makefile.** A primeira regra do arquivo era
   `tables`, então `make` sozinho disparava a operação mais perigosa do repo.
   Agora `make` compila; regenerar tabela é sempre explícito.
3. **`make pdf` detecta o engine**: usa `pdflatex`+`bibtex` (o ciclo que o spec
   pediu) quando existir, senão cai para o `tectonic`, imprimindo qual usou. Se
   faltarem os dois, falha com instrução de instalação. A decisão registrada no
   Makefile — manter o ciclo do spec — **não foi revogada**, só deixou de ser
   um alvo quebrado nesta máquina.

Testado: CSV com marcador → BLOQUEADO + exit 1, e a tabela limpa da mesma
execução é escrita normalmente; `--force` → gera com aviso, exit 0; `make`
sozinho → compila 11 páginas e `tables/` continua só com o README.

⚠️ **O que o gate NÃO cobre (honestidade sobre o alcance):** ele reage ao
marcador `PARCIAL`, que só o `compare_engines.py` escreve. As 6 tabelas do
`aggregate.py` hoje em `results/` são de gemini e **anteriores ao port do
`baseline_pos`** (sem a coluna `conjunto`) — velhas, mas não marcadas PARCIAL,
então um `make tables` explícito ainda as converteria. A correção disso não é
mais gate: é **regerar o `results/` com o `aggregate.py` novo** quando o luna
fechar. Note ainda que as três tabelas PARCIAL de hoje sequer estão em
`KNOWN_TABLES`, então o gate protege sobretudo a fiação futura.

### Verificação — COMPILA ✅
**Compilado com `tectonic -X compile main.tex`: 11 páginas, `main.pdf` gerado,
BibTeX sem citação indefinida.** Só avisos de `Overfull \hbox` (quebra de linha;
os maiores em §5.2 e §3.5, onde entraram nomes longos em `\texttt{}`) —
cosmético, não impede nada.

Não é preciso instalar MacTeX: o `tectonic` já está em `/opt/homebrew/bin` e
baixa os pacotes sozinho. **`make pdf` falha** porque chama `pdflatex`, que não
existe aqui — o próprio Makefile já documentava isso, e foi o que me levou a
registrar erradamente, antes, que a compilação não podia ser verificada.

Checagem estrutural também passou: nenhuma `\ref` órfã (todas as menções ao
label removido `sec:results-crossval` foram atualizadas), ambientes e chaves
balanceados. Ordem final do §5 confirmada no fonte: Main results → **Cross-engine
comparison** → setor → posição → comparação com o paper → pegadinhas → custo.

---

## Sessão 2026-08-12 — `baseline_pos` portado para o aggregate.py + luna retomado

### Retomada depois do notebook offline
Os dois runners estavam mortos (nenhum processo), como o CLAUDE.md previa.
Relançados com `./scripts/retomar_runs.sh`: o haiku saiu na hora (pending=0) e o
luna voltou a coletar. Completude por CÉLULA na volta: gemini 525, haiku 525,
**luna 282** (aqui 282 arquivos = 282 queries completas — sem a armadilha do
haiku). Ao longo da sessão o luna foi de 282 → 322.

**Custo real somado dos traces: US$ 63,90** (gemini 15,93 + haiku 44,66 + luna
3,31) de um teto de US$ 70. A taxa do luna subiu entre medições (US$ 0,0083/query
a n=142 → 0,0117 a n=282), então fechar as 525 deve custar ~US$ 3 → **projeção
~US$ 66,9**. A margem restante cobre terminar o luna e nada mais.

### ⚠️ O passo 1 do procedimento de retomada tem efeito colateral
`compare_engines.py` **não é diagnóstico read-only** — ele reescreve os seis
arquivos de `results/` a cada execução. Rodá-lo só para ler "N queries
completas" deixa o `results/` sujo com uma tabela PARCIAL nova. Não há dano
(ambas são PARCIAL e serão regeradas), mas quem for conferir completude deve
usar `--out-dir` para um diretório descartável, ou restaurar com
`git restore results/` depois.

### ✅ Metade não-verificada do bloqueio do `.tex`: limpa
`paper/draft/tables/` contém só o `README.md` — **nenhum `.tex` obsoleto**. O
`\IfFileExists` do `main.tex:628` cai no ramo TODO, então o paper não estava
puxando número velho do `cross_validate.py` sem marcação. O risco era real mas
não se materializou. A fiação do LaTeX continua aberta e bloqueada até o luna
fechar.

### ✅ PENDÊNCIA FECHADA: `aggregate.py` agora aplica o `baseline_pos`
Era a pendência que bloqueava qualquer tabela principal por engine. Toda tabela
que usa a Eq. 4 (`tabela_principal`, `quebra_por_setor`, `quebra_por_posicao`,
`comparacao_paper`) passa a ter a coluna **`conjunto`** com as duas linhas lado
a lado, na mesma convenção do `compare_engines.py`.

**Decisão de nomenclatura (nova convenção que o paper herda):** o conjunto
completo se chama **`todas`** no `aggregate.py` e **`pareado`** no
`compare_engines.py`. Não é inconsistência: lá o pareamento entre engines é
parte da definição do conjunto, aqui (um engine por vez) não há pareamento
nenhum, e chamar de "pareado" seria mentira. A definição de `baseline_pos` é a
MESMA nos dois — baseline > 0 —, menos a interseção entre engines, que só existe
no comparativo. Está documentado no docstring do módulo e no rodapé de toda
tabela afetada.

**Onde NÃO se aplica, declarado no cabeçalho em vez de omitido em silêncio:**
`tabela_custo` (não tem baseline; soma tokens/US$ de todas as chamadas) e
`inducao_pegadinhas` (o baseline ~0 é o desenho da pegadinha — filtrar por
baseline > 0 esvaziaria a tabela e apagaria a própria pergunta).

**Invariante verificada em execução, não assumida:** com baseline > 0 a Eq. 4
nunca é indefinida, então toda linha `baseline_pos` tem `n_baseline_zero=0` e
`n_indefinido=0`. `compute_cell_conjunto` levanta `RuntimeError` se isso não
valer — se o filtro parar de funcionar, o script para em vez de publicar uma
mediana contaminada. Passou em todas as células, inclusive nas fatias finas de
`quebra_por_posicao` (n pequeno por posição).

**FINDINGS.md** lê só o conjunto primário e diz qual é, nos 5 achados.

### Verificação do port (contra número calculado independentemente)
Rodado sobre os traces do **haiku** (onde o zero-injection é grande; no gemini
não provaria nada), saída em scratchpad para não sujar `results/`. O
`baseline_pos` do `aggregate.py` reproduz o que o `compare_engines.py` já tinha
calculado por outro caminho:

| técnica | compare_engines (n=431) | aggregate baseline_pos (n=433) |
|---|---|---|
| technical_terms | −5,3% | −5,30% |
| keyword_stuffing | −30,1% | −30,46% |
| easy_to_understand | −10,5% | −10,49% |
| authoritative | −8,3% | −8,18% |
| unique_words | −59,8% | −60,01% |
| fluency_optimization | +9,3% | +9,27% |

(n difere em 2 porque o `compare_engines` exige baseline > 0 nos DOIS engines.)

**O dano que isso evita, medido no haiku (Imp_pwc, mediana):** em `todas`,
`cite_sources`, `quotation_addition` e `statistics_addition` dão mediana
**exatamente 0,00** com IC hi = 0,00; `technical_terms` dá −0,77% com IC
cruzando zero — leria como "sem efeito" onde o efeito real é **−5,3%
significativo**. Os 67 zeros de 500 queries bastavam para isso.

**Não-regressão no gemini:** o conjunto `todas` reproduz os números commitados
em `results/tabela_principal.csv` **até a 6ª casa decimal** (prova de que a
estatística não mudou), e o `baseline_pos` difere só na 2ª casa — 3 queries de
500. Confirma o "inofensivo para o gemini, desastroso para o haiku" registrado
na sessão anterior. `compare_engines.py` (que importa a estatística deste
módulo) roda sem alteração de comportamento.

**Efeito colateral esperado no ρ de Spearman vs. o paper:** no conjunto `todas`
as medianas pregadas em 0,0 viram empates e recebem rank médio, o que muda o ρ
(haiku: +0,917 no `baseline_pos` vs +0,881 em `todas`). Os dois vão reportados
no rodapé — é a correção ficando visível, não um número trocado em silêncio.

### O que continua pendente
- Luna fechar as 525 (rodando).
- Fiação do LaTeX — inalterada e ainda bloqueada (`csv_to_latex.py` sem entrada
  para `comparacao_3_engines`/`concordancia_engines`/`spearman_engines`;
  `main.tex:628` ainda aponta para o obsoleto `comparacao_engines.tex`).
  **Não toquei no `csv_to_latex.py`** — é a área bloqueada. Nota para quando
  destravar: ele é genérico (converte quaisquer colunas do CSV), então a coluna
  `conjunto` entra sozinha no `.tex`; o que precisa de atenção é a legenda, que
  vem de `KNOWN_TABLES` e ainda não diz qual conjunto é o primário.
- `results/` não foi regerado com o `aggregate.py` novo de propósito: as tabelas
  por engine devem ser geradas depois que o luna fechar, junto com o resto.

---

## Sessão 2026-08-11 — ESTUDO EXPANDIDO PARA 3 ENGINES (estado anterior)

### Mudança de escopo (decisão do Du, autorizada no chat)
O estudo deixou de ser "1 engine + validação cruzada de 50 queries" e passou a ser
**3 engines com as 525 queries completas**. Motivo: o dataset e o harness já
estavam pagos; rodar mais engines é trocar o cliente de API, e a comparação entre
engines é o achado mais valioso (vira UM paper forte em vez de fatias).
Teto de custo: US$ 40 → 60 → **70** (medições reais foram subindo a projeção).

### Estado por engine (2026-08-11)
| Engine | Queries | Traces | Custo | Situação |
|---|---|---|---|---|
| gemini-3.5-flash-lite | **525/525** | 20.475 | US$ 15,93 | ✅ COMPLETO + analisado |
| claude-haiku-4-5 | **525/525** | 15.750 | US$ 44,65 | ✅ COMPLETO + analisado |
| gpt-5.6-luna | ~142/525 | 4.260 | US$ 1,18 | ⏳ rodando (~11 min por chunk de 20) |

**Total gasto: ~US$ 61,8** de um teto de 70. Projeção do luna até o fim: ~US$ 6.

**Armadilha resolvida (2026-08-11): 525 arquivos ≠ 525 queries completas.** O
haiku fechou com 525 `.jsonl` mas só **484 queries completas** — o primeiro
chunk coletou com `falhas=71` ("credit balance is too low") e MESMO ASSIM foi
marcado `collected` no state, então nenhum rerun recomputava aquelas células
(limitação herdada do run_batch.py, documentada no próprio run_engine_batch.py).
Recuperadas com state-file próprio (`--state-file ...recuperacao.json`), 71/71,
US$ 0,20. **Lição para o luna: ao final, conferir completude por CÉLULA, não por
arquivo** — `compare_engines.py` faz isso e imprime "N queries completas".

**→ Vai para Limitations (fato sobre o pipeline, não só bug corrigido):** as 41
queries incompletas **não faltavam ao acaso** — estavam todas em `i001–i143`, um
único chunk contíguo, porque o crédito acabou no meio dele. E a falta mudava uma
conclusão: `technical_terms` tinha IC cruzando zero a n=484 e virou significativa
nos dois engines a n=525. Ou seja, ausência sistemática de dados de batch pode
inverter um achado — justificativa concreta para a checagem de completude por
célula ser obrigatória antes de qualquer análise.

### Como retomar (UM comando)
```bash
./scripts/retomar_runs.sh
```
Relança os dois runners com `nohup` (sobrevivem ao fechamento do terminal).
Ambos são resumíveis: recomputam o pendente a partir dos traces; estado em
`eval/batch_state*.json`. Rodar o script duas vezes não duplica trabalho — o
que já existe é pulado — mas mata/relança processos, então cheque antes:
`ps aux | grep run_engine_batch`.

Ver progresso a qualquer momento:
```bash
for d in eval/traces eval/traces_claude-haiku-4-5 eval/traces_gpt-5.6-luna; do
  echo "$d: $(ls $d/*.jsonl 2>/dev/null | wc -l)/525"; done
```

### Decisão resolvida (2026-08-11)
Du recarregou crédito da Anthropic → **haiku vai até 525**, sem assimetria entre
engines. Os 3 engines terão as mesmas 525 queries.

### ⚠️ CORREÇÃO DO ACHADO PRELIMINAR (2026-08-11, n=484 pareadas, com IC)
O bloco "ACHADO PRELIMINAR" abaixo está **superado** — mantido por honestidade
de registro, mas **não use os números dele**. Com o haiku completo (484 queries
pareadas contra 152) e IC95 bootstrap, o quadro mudou, e a causa da mudança é
ela mesma um resultado metodológico:

**Causa: `metrics.relative_improvement(0, 0)` retorna 0.0, não None.** Só
`antes=0 & depois>0` é indefinido. Então toda query em que a fonte-alvo não foi
citada *nem no baseline nem sob a técnica* entra na distribuição como "0% de
mudança". No haiku isso é 5–12% das queries por técnica (contra ~1% no gemini,
que quase sempre cita a fonte-alvo) — o suficiente para **pregar a mediana em
exatamente 0** e fazer efeito negativo real parecer ausência de efeito. Por isso
`src/compare_engines.py` reporta sempre DOIS conjuntos lado a lado:
`pareado` (tudo) e `baseline_pos` (só queries com baseline > 0 em todos os
engines). Bônus: com baseline > 0 a Eq. 4 nunca é indefinida, então o n efetivo
fica IDÊNTICO entre engines — no conjunto `pareado` cada engine descarta um
conjunto diferente e a comparação se desemparelha *depois* do pareamento.

**RESULTADO FINAL DO PAR gemini × haiku** (525/525 queries nos dois, conjunto
`baseline_pos` com n efetivo 431 IDÊNTICO nos dois engines, mediana com IC95
bootstrap). As duas métricas (Imp_pwc e Imp_wc) concordam em tudo que segue —
robustez de graça, não precisa qualificar os achados com "sob Imp_pwc".

1. **Inversão genuína em `technical_terms`** — o achado central do estudo
   multi-engine. gemini **+1,9%** (IC exclui zero, positivo) vs haiku **−5,3%**
   (IC exclui zero, negativo); em Imp_wc, +2,0% vs −6,4%. É a única técnica em
   que os engines invertem COM suporte estatístico nos dois lados: adicionar
   termos técnicos ajuda no Gemini e atrapalha no Claude.
2. **4 técnicas negativas e significativas nos DOIS engines** (mesma direção):
   `keyword_stuffing` (−10,0% / −30,1%), `easy_to_understand` (−5,6% / −10,5%),
   `authoritative` (−3,2% / −8,3%), `unique_words` (−3,2% / **−59,8%**).
3. **Magnitude: o haiku reage 3–20x mais forte** que o gemini na mesma direção.
4. **Mecanismo por trás da magnitude** (coluna `n_citacao_zerada`): não é a
   citação encolhendo, é a fonte **sumindo da resposta**. Sob `unique_words` o
   haiku zera a citação de uma fonte que ERA citada em **28,5% das queries**
   (123 de 432); sob `keyword_stuffing`, 17,6%. O gemini: **0,0%** — nunca
   descarta a fonte por completo (máx. 0,2% em duas técnicas).
   ⚠️ Este é o número que substitui o "40% de 152 queries" do bloco superado.
5. `fluency_optimization`: positiva nos dois, significativa só no haiku (+9,3%).
6. **Sem suporte:** `cite_sources` e `quotation_addition` trocam de sinal, mas o
   IC cruza zero nos DOIS engines — inversão de ruído. Não escrever como achado.

Concordância de direção (regra do contrato: sinal da mediana, denominador = 9,
"indefinido" não concorda), todos de `results/par_gemini_haiku/concordancia_engines.md`:
- **primário — `baseline_pos`/pwc: 66,7% (6/9)**; não=3, todas inversões de
  sinal (só `technical_terms` com suporte estatístico), atenuação=0.
- sensibilidade — `pareado`/pwc: 55,6% (5/9); não=4 (inversão=1, atenuação=3).
  A diferença entre os dois é inteiramente o zero-injection descrito acima.
Spearman gemini×haiku sobre as 9 técnicas: ρ=0,58 (pwc) / 0,62 (wc).

**DECISÃO METODOLÓGICA NOVA — conjunto primário = `baseline_pos`.**
Distinta da convenção de denominador herdada do cross_validate.py (essa
continua valendo). Motivo: `baseline_pos` é o único conjunto em que o n efetivo
é idêntico entre engines — no `pareado` cada engine descarta um conjunto
diferente por Eq. 4 indefinida (a coluna `n_efetivo_igual` marca `NAO` nas 9
linhas). `pareado` fica como análise de sensibilidade reportada ao lado, nunca
como número principal. Sem isso o §5.6 herda dois números de contrato
(55,6% e 66,7%) e o revisor escolhe o que lhe convém.

Tabelas: `results/comparacao_3_engines`, `concordancia_engines`,
`spearman_engines` (.md + .csv). Reexecutar quando o luna terminar.

### ACHADO PRELIMINAR — SUPERADO, ver correção acima (152 queries pareadas gemini × haiku, sem IC)
**Os engines discordam em 3 das 9 técnicas** — é o que justifica o estudo
multi-engine:
- `technical_terms`: **+3,1% no Gemini, −7,9% no Haiku** (inverte)
- `cite_sources`: +1,7% vs −2,6% (inverte)
- `quotation_addition`: +0,7% vs −0,8% (inverte)
- Concordam: `keyword_stuffing` é ruim nos dois (−9,8% / −27,6%);
  `fluency_optimization` é bom nos dois (+0,9% / +13,3%)
- **`unique_words` no Haiku: −63,2% de mediana; em 61 de 152 queries (40%) a
  fonte transformada deixou de ser citada por completo.** O Gemini tolera
  palavras raras, o Claude descarta a fonte.
- O Haiku reage muito mais forte que o Gemini (magnitudes 5-20x maiores).

### Achado secundário: aderência à instrução de citar difere por engine
haiku 100% > gemini 99,1% > gpt-5.6-luna 97% >> gpt-5-nano 65% (descartado por
isso). Medido em batches reais.

### Decisões metodológicas registradas (vão para o paper)
1. **Transformações NÃO são refeitas por engine** — os textos transformados pelo
   Gemini são reusados nos 3 engines. Isola a variável "quem responde" e evita
   confundir qualidade da transformação com comportamento de citação.
2. **Temperatura:** gemini e haiku a 0.7; **gpt-5.6-luna não aceita temperatura
   customizada** (limitação da família GPT-5, não escolha nossa) → Limitations.
3. Modelos pareados por faixa: todos são o "pequeno" da geração atual de cada
   provedor (ago/2026).
4. Pegadinhas mantidas sob técnicas como sub-experimento de indução (decisão do Du).

### Bugs encontrados e corrigidos nesta sessão
- `run_batch.py` travava para sempre no polling (cliente HTTP sem timeout) —
  corrigido com `http_options.timeout=120s` + retry de timeout. Causa raiz de 2
  travamentos que antes eu só reiniciava.
- Backoff estendido para ~18 min (outage de provedor em runs de horas).
- `run_eval.py` lia preço de modelo hardcoded (`gemini-2.5-flash`) — agora lê o
  modelo real dos traces.
- OpenAI: teto de 2M tokens enfileirados por organização → chunk 250 → 20.

### Pendências de código
- ✅ FEITO: análise comparativa entre engines — `src/compare_engines.py`
  (interseção pareada estrita + target_pos verificado, técnica × engine,
  concordância de direção com inversão/atenuação, Spearman, citação zerada).
  Resultado final do par gemini×haiku (525/525, sem marcador PARCIAL) em
  `results/par_gemini_haiku/`; a versão 3-engines em `results/` é PARCIAL até o
  luna terminar.
- ⚠️ **`aggregate.py` não aplica o `baseline_pos`** — a correção do zero-injection
  só existe no `compare_engines.py`. Para o gemini é inofensivo (zera citação em
  0–0,2% das queries), e por isso `comparacao_paper.md`/`FINDINGS.md` atuais são
  confiáveis. Mas rodar `aggregate.py` sobre os traces do **haiku** (zera em até
  28,5%) ou do luna vai produzir `tabela_principal` com a mediana **pregada em
  zero**, e a tabela vai parecer dizer "sem efeito" onde há efeito forte —
  contaminando o §5 inteiro. Antes de gerar tabelas principais por engine:
  portar o conjunto `baseline_pos` para o `aggregate.py` (ou declarar por que a
  tabela principal usa outra convenção que a comparativa — mas UMA das duas).
- **Fiação do LaTeX ainda ABERTA** (fazer só quando o luna fechar):
  `scripts/csv_to_latex.py` não tem entrada em `KNOWN_TABLES`/`TABLE_SUBDIR`
  para `comparacao_3_engines`, `concordancia_engines` nem `spearman_engines`, e
  `main.tex:628` ainda faz `\IfFileExists` no obsoleto `comparacao_engines.tex`
  (o do cross_validate). ⚠️ **NÃO gerar nenhum .tex enquanto houver PARCIAL** —
  `\IfFileExists` faz o arquivo existir bastar para os números entrarem no paper
  sem nenhuma marcação de que são provisórios.
- `cross_validate.py` (50 queries no sonnet) ficou **obsoleto** — foi substituído
  por runs completas nos outros engines. Manter no repo mas não usar.

---

## Sessão 2026-08-10 — Fase 2 concluída

**FASE 2 CONCLUÍDA — AGUARDANDO REVISÃO** (todos os checks de prontidão da Fase 3 verdes)

**Mudanças de engine (forçadas/decididas durante a fase):**
- gemini-2.5-flash → indisponível p/ contas novas (v0.2.0: gemini-3.6-flash)
- gemini-3.6-flash → 5x mais caro, projeção US$55 > teto (v0.3.0: **gemini-3.5-flash-lite**,
  decisão do Du; mesmo preço que o contrato assumia; fiel ao espírito do original,
  que usou o gpt-3.5-turbo, modelo barato da época)

**Piloto (results/pilot_20260810_2057.md):** 10 queries × 9 técnicas × 3 reps, 390
traces, custo real US$ 0,52.
- Check pegadinhas: PASS (0,02) — medição não alucina citações
- Desvio entre reps: ±0,013 (estável)
- Projeção run completa: **US$ 12,90 com batch** vs teto 40 — PASS, sem necessidade
  de mudar teto ou desenho
- Versão de modelo única: PASS
- Prontidão Fase 3 (check d): billing ativo ✅; mini-batch de 5 chamadas SUCEDIDO ✅
  (batches/03cm..., 5/5 respostas corretas recuperadas — batch ponta a ponta OK)

**Nota científica:** com n=8 normais, efeitos por técnica dentro do ruído (−13% a
+3%); sem sinal ainda da direção do paper original. Não-bloqueante (piloto valida
pipeline, não achados). Para a Fase 4: média da Eq.4 por query é instável com
baseline pequeno — usar também mediana e agregado (registrado para a análise).

**Achado do piloto (revisão do Du, 2026-08-10):** técnicas podem INDUZIR citação
em pegadinhas — statistics_addition fabricou estatística sobre a entidade da
pergunta (fonte que não respondia passou a "responder"); keyword_stuffing fez o
engine citar fonte irrelevante. Correções: (1) relatório separa pegadinhas das
médias principais (seção 2b "indução de citação"); (2) check oficial restrito ao
baseline (0.0000, PASS). Decisão do Du: MANTER pegadinhas sob técnicas na run
completa como sub-experimento de indução de alucinação. Queries de preço (~10%)
mantidas (estão no escopo do contrato; README do dataset declarará valores
sintéticos).

**Decisão pendente do checkpoint da Fase 1 (fontes sintéticas):** manter sintéticas
foi aceito para o piloto; decidir agora se vale para a run completa (recomendação
do orquestrador: manter e declarar em Limitations).

Falhas e correções da fase: free tier do 3.6-flash era 20 req/dia (descoberto na
prática); crédito pré-pago zerado no projeto novo (resolvido pelo Du); 503 do
Google derrubou o runner (corrigido: retry em 5xx).

Para autorizar: `AUTORIZADO FASE 3: <comentário>` (após mini-batch OK).

> Registro do orquestrador (2026-08-10): Du revisou o piloto (páginas de revisão
> + investigações p010/j003), decidiu manter pegadinhas sob técnica e queries de
> preço, e autorizou a Fase 3 no chat ("E depois disso pode avancar, aprovado")
> — gasto de ~US$ 13 aprovado, fontes sintéticas mantidas com declaração no
> dataset. (Regra 6: orquestrador não escreve AUTORIZADO; esta nota documenta.)

---

## Sessão 2026-08-07 (cont.) — Fase 1 concluída

**FASE 1 CONCLUÍDA — AGUARDANDO REVISÃO**

Critério do contrato atingido: `python3 src/build_scenario.py --validate` → OK,
100% dos cenários existentes válidos.

**Entregue:**
- `data/queries.jsonl`: 525 queries (500 normais + 25 pegadinhas; 176 saúde /
  175 jurídico / 174 imobiliário). Geradas pelo Grok em 4 lotes; revisão por
  amostragem e correção de menções datadas pelo orquestrador.
- `data/sources/`: 250 fontes (50 queries × 5), 150–400 palavras, 5 estilos de
  site por query. Inclui 6 pegadinhas com fontes que por design NÃO respondem
  (verificado: nenhuma menciona a entidade específica da pergunta).
- `paper/KEY_FACTS.md`: extraído do PDF pelo subagente Sonnet — métricas, 9
  técnicas, tabelas-alvo (Tab. 1, 2, 5/7), discrepância interna do paper anotada.

**Pontos para o revisor humano decidir no checkpoint:**
1. **Fontes sintéticas vs coletadas.** O contrato-base fala em textos "coletados
   ou adaptados"; o que foi gerado é sintético-realista (rotulado no campo
   `origem`). Manter (e declarar em Limitations) ou substituir por coleta real
   antes da Fase 3?
2. Amostragem de qualidade: revisar algumas queries e fontes (sugestão: 1 arquivo
   por setor + 1 pegadinha). Mérito jurídico/médico dos textos não foi verificado
   por especialista.
3. Observações menores registradas pelos agentes: 4 pegadinhas reutilizam nomes
   fictícios dos exemplos do enunciado; construtora fictícia "Residencial Aurora"
   repete em i002/i006/i009; assinaturas fictícias completas em artigos de
   especialista (s001–s010, posição 5).

Para autorizar: escrever abaixo uma linha `AUTORIZADO FASE 2: <comentário>`.

> Registro do orquestrador (2026-08-07): Du autorizou a Fase 2 diretamente no chat
> ("vai"), após abrir a página docs/revisao_fase1.html. Fontes sintético-realistas
> aceitas para o piloto; reavaliar no checkpoint da Fase 2. (Pela regra 6 o
> orquestrador não escreve linhas AUTORIZADO — esta nota documenta a decisão humana.)

---

## Sessão 2026-08-07 — Setup + início da Fase 1

**Decisões operacionais (com o Du):**
- Operário = Grok (grok-4.5 via subagente); orquestração = Claude; humano autoriza fases.
- Execução local (Mac), não Hetzner — Fase 3 usa batch API do Gemini (pesado roda no Google).
- GEMINI_API_KEY existe sem billing → cobre Fases 1–2; billing é gate da Fase 3.
- Tarefas mecânicas delegadas a subagentes Sonnet (economia de tokens do orquestrador).
- Justificativa científica da separação: quem gera material (Grok) ≠ quem julga
  (Gemini) ≠ quem valida cruzado (claude-sonnet-4-6) ≠ quem orquestra (Claude).

**Feito:**
- git init, estrutura de pastas, TASK.md (emendas), README.md, configs, .gitignore
- paper/geo_original.pdf baixado do arXiv (12 págs)
- src/build_scenario.py com --validate (critério de conclusão da Fase 1)

**Em andamento:**
- paper/KEY_FACTS.md (subagente Sonnet extraindo do PDF)
- Smoke test do agente Grok
- Próximo: geração das 500 queries + 25 pegadinhas via Grok

**Custo acumulado de API do experimento:** US$ 0,00 (nenhuma chamada ao engine ainda)
