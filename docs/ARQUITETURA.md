# Arquitetura do Project HESTIA

Extraído da GAIA em 2026-08-24 (ver `Project G.A.I.A/assistant/docs/TODO.md`
-> "Arquitetura do ecossistema", item "Steam → Project HESTIA") - mesmo
padrão já validado 2x antes (Argus, depois MOIRAI): repo próprio, processo
próprio, ponte HTTP, a GAIA consome por cliente HTTP
(`integrations/hestia_client.py`, no repo dela).

## Por que separar

Teste usado pra decidir (mesmo do MOIRAI): "a feature só tem valor por
causa da IA/persona, ou é infraestrutura que a GAIA hospeda por
conveniência?" As 3 checagens de Steam são dado 100% determinístico (Web
API oficial da Steam) - o texto do aviso já sai PRONTO do próprio módulo,
a LLM só copia (nunca cria), mais "limpo" até que o Modo Jornalista (que
exige resumo de verdade). Candidato mais limpo ainda que a maioria: tem
**relação dupla** com a GAIA, não só uma - além do poll agendado (Agendador
Diário), 2 dos 3 módulos (lançamentos, conquistas) também são ferramentas
chamadas EM TEMPO REAL durante a conversa (`<LANCAMENTOS>`/`<CONQUISTAS>`).

## Sem loop de manutenção próprio (diferente do MOIRAI)

O MOIRAI precisa de `_loop_manutencao` porque downloads/biblioteca/MAL têm
valor mesmo com a GAIA fechada (o usuário quer que o episódio termine de
baixar). As 3 checagens de Steam não têm esse valor independente - a única
razão de checar é AVISAR alguém, e quem decide isso é sempre a GAIA
(persona). Por isso o HESTIA fica parado esperando requisição: `POST
/lancamentos/varrer` (1x/dia, Agendador Diário, roda em segundo plano), `GET /atividade/
verificar` (a cada 20min, `_monitorar_steam_loop`) e `GET /conquistas/
<appid>`/`GET /guia_conquista` (sob demanda, tags `<CONQUISTAS>`/
`<GUIA_CONQUISTA>`) só rodam quando a GAIA pergunta.

## Google Calendar: webhook reverso, nunca acesso direto

`steam_lancamentos.py` (GAIA, antes da extração) chamava `google_calendar.
sincronizar_evento_lancamento`/`remover_evento_lancamento` DIRETO (mesmo
processo). Duplicar credencial OAuth do Google só pra isso no HESTIA
(2ª tela de consentimento, 2º arquivo de token) não compensa, já que a
GAIA já tem tudo isso configurado pra Agenda/Secretária. Solução: mesmo
padrão do webhook reverso já usado pelo MOIRAI (`POST /moirai/
episodio_assistido`) - `hestia/integrations/gaia_webhook.py` avisa a GAIA
(`POST /hestia/sincronizar_lancamento`/`POST /hestia/remover_lancamento`,
`integrations/iris_bridge.py` no repo dela) e é ELA quem chama
`google_calendar.py` de verdade, devolvendo o resultado (agendado ou não)
de volta na resposta HTTP. Validado ponta a ponta (script de teste
isolado, callback fake pra não sujar o calendário real durante o teste).

## Resolução de nome de jogo: fica na GAIA, não aqui

`steam_conquistas.py::_resolver_appid` (antes da extração) lia `features/
app_launcher/apps_scanner.py::carregar_apps_escaneados()` - lista de jogos
escaneados LOCALMENTE naquela máquina (mesma usada por `<APP:abrir>`).
Isso é dado da MÁQUINA, não da conta Steam - não faz sentido virar chamada
de rede pro HESTIA (que pode rodar numa máquina diferente, ou não ter
motivo nenhum pra conhecer o disco local de quem pergunta). Decisão: a
resolução por NOME fica inteira do lado da GAIA (`core/agent/turno.py::
_resolver_appid_steam`/`_obter_conquistas_resolvendo_nome`, chamada ANTES
de perguntar ao HESTIA) - `GET /conquistas/<appid>` só aceita appid
NUMÉRICO. `nome_conhecido` (query param opcional) deixa a GAIA repassar o
nome já resolvido, só como fallback de exibição se a API da Steam não
devolver `gameName`.

## `search_ddg.py`/`content_learner.py`: copiados, não compartilhados

Usados só por `buscar_guia_conquista` (busca de guia de conquista) - na
GAIA, esses 2 módulos são compartilhados com Jornalista/`<APRENDER:>`/
`<PESQUISAR:>`, então não podiam ser MOVIDOS (os outros consumidores
continuam lá). `hestia/integrations/search_ddg.py`/`content_learner.py`
são cópias mínimas, mesmo tratamento que o MOIRAI deu a `mal_client.py`/
`anilist_client.py` (copiados verbatim, não importados entre processos -
processos separados não compartilham módulo Python nenhum de qualquer
jeito).

## Bug real encontrado durante a extração: `load_dotenv()` faltando

Nem o HESTIA nem o MOIRAI (confirmado no repo dele) chamavam
`load_dotenv()` em lugar nenhum - variável nenhuma do `.env` era carregada
de verdade, `os.getenv`/`os.environ.get` sempre voltava vazio a não ser
que a variável já existisse no ambiente HERDADO do processo pai. Corrigido
aqui (`hestia/main.py`, `load_dotenv(override=True)` - mesmo `override`
usado na correção equivalente da GAIA no mesmo dia, ver `Project G.A.I.A/
assistant/docs/CORRECOES.md`) antes mesmo do primeiro teste real funcionar
("sem_configuracao" com as 4 credenciais já preenchidas no `.env` foi o
sintoma). **Mesmo bug ainda existe no MOIRAI** - fora de escopo desta
extração, registrado aqui só pra não esquecer.

## Bug real encontrado em produção: lembrete ficava mudo pra sempre após adiamento

2026-08-26, reportado pelo usuário: "esse My Party Is Grinding lança amanha, e
n recebi anuncio hj". `verificar_lancamentos` (`hestia/core/lancamentos.py`)
avisa em 3 faixas antes do lançamento (`BRACKETS_LEMBRETE_DIAS = [30, 7, 1]`
dias restantes), guardando quais já foram avisadas em `lembretes_enviados`
por appid, pra nunca repetir o mesmo aviso. Causa raiz: essa lista NUNCA era
resetada quando a data de lançamento MUDAVA (jogo adiado) - uma faixa já
"gasta" contra a data ANTIGA continuava contando como "já avisado" pra
sempre, mesmo a contagem regressiva reiniciando do zero contra a data nova.
Investigado com arqueologia de log real (`assistant/logs/2026-08-*.log`) -
o jogo teve "Faltam 5 dia(s)" avisado corretamente em 21/08, mas nunca mais
apareceu em log nenhum depois disso, apesar do estado local já mostrar as 3
faixas como "enviadas" - só fazia sentido se essas faixas tivessem sido
herdadas de um agendamento anterior à extração (antes de qualquer log
disponível), congeladas desde então.

Corrigido: `data_mudou = anterior.get("data") != data_iso` reseta
`lembretes_enviados` pra `[]` sempre que a data muda, antes de calcular
quais faixas cruzar. Validado simulando um adiamento com `unittest.mock`
(jogo com as 3 faixas já gastas contra a data antiga, adiado 5 dias -
corretamente voltou a avisar "Faltam 5 dia(s)" pra nova data, sem
recalcular as faixas 30/7 que ainda não deveriam cruzar). Registro
manualmente corrigido pro jogo real afetado (`data/lancamentos_estado.json`,
não versionado - dado de produção, não código).

## Limitação conhecida (não é bug): data de lançamento pode errar por 1 dia

Investigando o caso acima, o usuário trouxe print da própria loja da Steam
mostrando "My Party Is Grinding" com lançamento em 27/ago (~12h de
distância), enquanto a API que o HESTIA usa devolvia 26/ago pro MESMO jogo.
Conferido na hora - o JSON bruto da `appdetails` só tem
`{"coming_soon": true, "date": "26 ago. 2026"}`, uma STRING de data sem
fuso horário nenhum, sem timestamp preciso. A página da loja usa um widget
de contagem regressiva alimentado por um timestamp de verdade que essa API
pública/sem chave não expõe - o campo de texto provavelmente reflete o dia
num fuso de referência interno da Valve (Pacific, tipicamente), que pode
cair no dia anterior comparado ao fuso do usuário dependendo da hora exata
do lançamento.

**Decisão do usuário quando perguntado (2026-08-26)**: manter só fontes
OFICIAIS/SEM CHAVE (princípio já documentado abaixo em "Usa só APIs
OFICIAIS") em vez de fazer scraping do HTML da loja pra pegar o timestamp
preciso - aceita a margem de até 1 dia como limitação conhecida. Não
implementar scraping aqui sem decisão nova do usuário.

## Bug real encontrado em produção: aviso de "lança HOJE" nunca disparava

2026-08-27, reportado pelo usuário: recebeu "Faltam 1 dia(s) pro lançamento
de SeaColony" no dia 24, mas nunca recebeu o aviso de lançamento no dia
seguinte; no mesmo dia, o Google Calendar mostrava 3 lançamentos, mas
nenhuma notificação de voz/Discord chegou. Causa raiz: `BRACKETS_LEMBRETE_
DIAS = [30, 7, 1]` não tinha um bracket pro dia `0` (dia do lançamento em
si). A condição de cruzamento (`0 <= dias_restantes <= b`) fazia o bracket
`1` já casar com `dias_restantes == 0` também (`0 <= 0 <= 1`) - só que, com
a checagem diária rodando normalmente todo dia, o bracket `1` já tinha sido
consumido no dia ANTERIOR (quando `dias_restantes` era `1`), então no dia
do lançamento `cruzadas` ficava vazio (todos os brackets `[30,7,1]` já
"gastos") e NENHUM evento era gerado - mesmo com `dias_restantes`
calculando `0` corretamente. Reproduzido com dado real em produção:
"Resonance: A Plague Tale Legacy" (lançamento 27/08, o mesmo dia do
relato) com `coming_soon` ainda `True` e os 3 brackets já consumidos -
`cruzadas` vazio confirmado por simulação direta contra o estado real.

Esse bug é INDEPENDENTE do evento de "Hoje foi lançado" baseado na
transição de `coming_soon` (`True` -> `False`, seção acima do fluxo
principal) - aquele continua funcionando quando a Steam já atualizou a
flag a tempo da checagem diária; este cobre o caso (comum) de a checagem
rodar ANTES da flag mudar, quando só a DATA já indica que é hoje.

Corrigido: `BRACKETS_LEMBRETE_DIAS = [30, 7, 1, 0]` - o dia do lançamento
ganhou seu próprio bracket, que só é consumido no dia exato (`0 <=
dias_restantes <= 0` só é verdadeiro quando `dias_restantes == 0`),
independente do bracket `1` já ter disparado no dia anterior. Validado
simulando a contagem completa (30 -> 0): cada bracket dispara exatamente
uma vez, sem duplicar nem pular o dia 0. Sem suíte de testes automatizada (até a 0.3.1)
neste repo (nenhuma existe ainda) - validado só por simulação direta e
pelos dados reais de produção.

**Limitação residual (corrigida na 0.3.1)**: se a checagem diária fosse
pulada exatamente no dia do lançamento e a flag `coming_soon` não mudasse
até a checagem seguinte, `dias_restantes` negativo não casava faixa
nenhuma e o aviso se perdia. Agora, com `coming_soon` ainda verdadeiro e
data no passado, sai um aviso único de "tinha lançamento marcado para
dd/mm", que consome a faixa `0`.

## Varredura em segundo plano e fila confirmada (0.3.0, 2026-11-12)

Achado na análise do projeto: a varredura da wishlist leva uns 7 minutos
(274 itens x 1,5 s entre chamadas ao `appdetails`) e a GAIA esperava 300 s
pela resposta de `GET /lancamentos/verificar`. Ela desistia, recebia lista
vazia e marcava o dia como feito; o HESTIA terminava a varredura, gravava
as faixas de lembrete como enviadas e só então tentava responder a uma
conexão já fechada. Resultado: o aviso daquele dia sumia sem rastro (78
`ConnectionAbortedError` nesse endpoint em 58 dias de log). Aumentar o
timeout só adiaria o problema: a wishlist cresce.

- **Varredura numa thread**: `POST /lancamentos/varrer` liga
  `_executar_varredura` e volta na hora. Uma segunda chamada com a
  varredura em andamento não abre outra.
- **Fila em disco** (`data/lancamentos_pendentes.json`): cada aviso ganha
  um `id` e fica lá até a GAIA confirmar a entrega
  (`POST /lancamentos/confirmar`). GAIA fechada, Discord fora do ar ou
  conexão caída deixam o aviso na fila para a rodada seguinte.
- **Data da última varredura do lado do HESTIA**: gravada no fim de uma
  varredura sem exceção. Se ela cair no meio, a data não muda e a GAIA pede
  de novo na rodada seguinte do agendador (a cada 10 min).
- **A GAIA não espera mais**: a cada rodada do agendador ela entrega o que
  estiver na fila e, depois da hora configurada, pede a varredura se a de
  hoje ainda não foi concluída. Os avisos chegam numa rodada seguinte,
  minutos depois da hora configurada.

Junto: a ponte virou `ThreadingHTTPServer` (antes uma requisição lenta
travava as rápidas, mais de 160 conexões abortadas em sessão, família e
atividade), com `threading.Lock` nos trechos de leitura e regravação de
arquivo em `atividade.py`, `familia.py` e na fila. Erro num endpoint vira
HTTP 500; cliente que desistiu vira uma linha de log. Estado da wishlist,
fila e data passam por `hestia/armazenamento.py` (gravação atômica com
`.bak`), para uma queda de energia no meio da gravação não zerar a wishlist
e fazer tudo parecer "primeira vez".

## Pendências da análise de 2026-11-09 (0.3.1, 2026-11-13)

- **Transições independentes**: lançamento, Free to Play e saída do
  Acesso Antecipado deixaram de ser uma cadeia `elif` em
  `verificar_lancamentos`. A saída do Acesso Antecipado só fica de fora
  quando o jogo acabou de lançar, para não repetir o mesmo fato.
- **Vistos em ordem**: `atividade._carregar_vistos` devolve uma lista em
  ordem de chegada. Cada checagem move para o fim as chaves que ainda estão
  na página, então o corte em `MAX_VISTOS_GUARDADOS` só descarta o que
  saiu da página há mais tempo.
- **Gravação segura em todo `data/`**: atividade e família também passam
  por `hestia/armazenamento.py`.
- **Cache de busca**: `search_ddg` guarda `{"resposta", "resultados"}` e
  aceita o formato antigo (só texto). O cache já era apagado a cada
  inicialização; o ganho é dentro de uma mesma execução.
- **Logs**: `runtime_log.limpar_logs_antigos` apaga `logs/AAAA-MM-DD.log`
  com mais de 30 dias ao iniciar.
- **Testes**: `tests/` com pytest. Rede e calendário são trocados por
  dublês; cada teste roda numa pasta temporária, já que os caminhos de
  `data/` são relativos à pasta atual.

## Atividade pela Web API, histórico e status (0.4.0, 2026-11-13)

Achado real: o usuário não recebia atividade nenhuma havia semanas. O
cookie `STEAM_LOGIN_SECURE` tinha expirado, nenhum navegador tinha login
da Steam para a autocura, e `_validar_sessao` dava a sessão por válida
porque procurava só o texto `g_steamID`, presente também na tela de login
(`g_steamID = false`). Corrigido para exigir `g_steamID = "<número>"`.

Ler o cookie do cliente Steam (`%LOCALAPPDATA%\Steam\htmlcache`, formato
Chromium) foi tentado e descartado: o arquivo fica travado com a Steam
aberta e só sai com permissão de administrador.

Para não depender de login no que mais importa, `atividade_api.py` usa a
Web API com a chave que o HESTIA já tinha:

- **compras da família**: `IPlayerService/GetOwnedGames` de cada pessoa
  de `familia.py`; appid novo vira "Fulano comprou X". Exige biblioteca
  pública. Primeira leitura de cada pessoa só grava a linha de base
  (`data/atividade_api_estado.json`);
- **anúncios**: `ISteamNews/GetNewsForApp` (feed
  `steam_community_announcements`) dos até 10 jogos de
  `GetRecentlyPlayedGames` do usuário; jogo novo na lista só grava base.

Amigos fora da família ficam só com a página logada: a lista de amigos do
usuário responde 401 na API (privada).

As duas fontes geram a mesma chave para o mesmo fato (`_chave` normaliza
caixa e espaços; compra = accountid + nome do jogo; anúncio = nome do jogo
+ título), então um evento vindo das duas é avisado uma vez.

`historico.py` guarda o que já foi avisado (lançamentos no
`confirmar_eventos`, atividade no `verificar_novidades_steam`), e
`GET /status` junta o resumo da última varredura
(`data/lancamentos_ultima_varredura.json`), a fila e a última checagem de
atividade (`data/atividade_ultima_checagem.json`). Os dois alimentam a
tela Steam do Painel da GAIA.

## Contrato HTTP (`hestia/api_bridge.py`, porta 8770)

- `POST /lancamentos/varrer` - dispara a varredura da wishlist numa thread
  e volta na hora (`{"iniciada", "varrendo"}`); não abre outra se já houver
  uma rodando.
- `GET /lancamentos/pendentes` - `{"varrendo", "ultima_varredura_concluida",
  "ultimo_erro", "eventos": [{"id", "texto", "criado_em"}]}`.
- `POST /lancamentos/confirmar` (`{"ids": [...]}`) - tira da fila os avisos
  que a GAIA já entregou.
- `GET /lancamentos/proximos?limite=N` - lê o cache local, não refaz a
  varredura. Cada item: `nome`, `data`, `tipo_lancamento`, `appid`, `link`.
- `GET`/`POST /lancamentos/ultima_checagem_diaria` - data da última
  varredura concluída (desde a 0.3.0 gravada pelo próprio HESTIA no fim da
  varredura; o `POST` continua existindo, mas a GAIA não usa mais).
- `GET /atividade/verificar` - novidades da página de atividade desde a
  última checagem.
- `GET /atividade/atual?limite=N` - estado atual, sem alterar o "já visto".
- `GET`/`POST /atividade/ultima_checagem_diaria` - catch-up do resumo
  diário.
- `GET /conquistas/<appid>?nome_conhecido=X` - appid SEMPRE numérico (ver
  seção acima).
- `GET /guia_conquista?jogo=X&conquista=Y` - cadeia de fontes priorizadas
  (Steam Community Guides -> PowerPyx -> GameFAQs -> F95zone -> busca
  livre).
- `GET /familia` - lista de família cadastrada (`{steamid64, accountid,
  nome}` cada).
- `GET /status` - `{"lancamentos": {varrendo, ultima_varredura_concluida,
  ultima_varredura, ultimo_erro, pendentes}, "atividade": {sessao_valida,
  ultima_checagem, api_configurada, familia}}`.
- `GET /avisos/historico?limite=N&categoria=lancamento|atividade` - avisos
  já entregues, mais recentes primeiro.
- `POST /familia` (`{"perfil": "url ou vanity/steamid"}`) - resolve e
  adiciona; devolve a entrada criada ou `{"erro": "..."}`.
- `POST /familia/remover` (`{"accountid": "..."}`) - remove da lista.
- `GET /atividade/sessao_valida` - `{"valida": true/false/null}` (`null` =
  nenhuma checagem real rodou ainda).
- `POST /atividade/renovar_sessao` - tenta pegar um cookie fresco do
  navegador (ver seção abaixo); `{"sucesso": bool, "origem": navegador|null}`.

## Detecção + autocura de sessão expirada (2026-09-01)

Achado real: o usuário simplesmente parou de receber aviso nenhum de
atividade de amigos, sem erro visível em lugar algum. Investigando,
`_buscar_html` devolvia `status 200` normal, só que o HTML era a TELA DE
LOGIN da própria Steam (`<title>Iniciar sessão</title>`), não o feed -
`STEAM_LOGIN_SECURE` tinha expirado. Como esse cookie não tem refresh
token oficial (só existe pegando um novo, fazendo login de verdade),
perguntei ao usuário se dava pra automatizar - **decisão: não automatizar
login com senha/2FA** (Valve ativamente dificulta isso com captcha/
confirmação, e guardar senha no `.env` seria pior que guardar só um cookie
de sessão), mas SIM automatizar a detecção e a extração do cookie de uma
fonte que já existe: o navegador que o usuário já usa no dia a dia.

- **Detecção**: `_validar_sessao(html)` checa a presença de `g_steamID`
  (variável JS global que a Steam injeta em QUALQUER página autenticada da
  Community, independente de idioma) - ausência dela é o sinal mais forte
  de sessão morta, mas **não é confiável isolada**: a própria raspagem já
  era conhecida por voltar vazia/errada ~1 em cada 3 tentativas mesmo com
  sessão válida (ver docstring de `_SESSION_ID_FAKE`, achado antes desta
  extração) - confirmado batendo de novo, na prática (2026-09-01): um teste
  manual isolado leu a tela de login, mas a checagem seguinte, com o MESMO
  cookie (comparado por hash, idêntico), leu a sessão como válida. Por isso
  `_marcar_status_sessao` exige `LIMITE_FALHAS_CONSECUTIVAS_SESSAO = 2`
  falhas SEGUIDAS (2 checagens de 20min = 40min de sinal consistente) antes
  de reportar `valida: false` de verdade - 1 falha isolada não muda o status
  reportado. Marcado a cada `_buscar_html` bem-sucedido
  (`data/atividade_sessao_status.json`), sem gastar requisição extra.
- **Autocura**: `renovar_sessao_via_navegador` usa `browser_cookie3` pra ler
  o cookie `steamLoginSecure` direto do perfil já logado do usuário no
  Edge/Chrome/Firefox (nessa ordem, cada um best-effort - Brave exige admin
  nesse ambiente, Firefox exige perfil configurado, ambos ignorados em
  silêncio se falharem) - nunca pede senha nem 2FA, só lê uma sessão que já
  existe. Atualiza `os.environ` (efeito imediato no processo atual) E
  reescreve a linha no `.env` (sobrevive a reinício).
- **Quem decide avisar o usuário é a GAIA** (`run.py::_monitorar_steam_loop`,
  a cada 20min): só tenta a autocura quando detecta `valida: false`; se
  funcionar, segue em silêncio (a checagem seguinte já usa o cookie novo);
  se falhar (usuário não está logado em nenhum dos 3 navegadores), avisa 1x
  só (`steam_sessao_expirada_avisada` em `brain.json`, reseta quando a
  sessão volta a ficar válida) - nunca repete o aviso a cada ciclo. Botão
  manual "🔑 Checar/renovar sessão da Steam agora" no modal "👨‍👩‍👧 Família
  (Steam)" do Painel chama o mesmo endpoint sob demanda.

## Destaque de "família" na Atividade da Steam (2026-09-01)

Pedido do usuário: "quero receber principalmente qnd alguem da familia
compra algo novo" - hoje `atividade.py` trata todo mundo do feed de
atividade igual (qualquer amigo), sem prioridade nenhuma. Decisão (usuário
escolheu entre "destacar" e "filtrar", ver conversa): **destacar**, não
filtrar - continua notificando toda a atividade de amigos como antes, mas
eventos de família ganham um campo `familia: true` no evento (`hestia/core/
familia.py`), que a GAIA usa pra prefixar a notificação de forma diferente
(`run.py`, lado da GAIA) - nunca silencia o resto.

Cadastro é por LINK do perfil (`ui/qt_modais/steam_familia.py`, lado da
GAIA), não por accountid cru - o usuário não sabe de cabeça o accountid de
ninguém. `familia.py` resolve o link pra SteamID64 (via
`ISteamUser/ResolveVanityURL`, se for link customizado tipo `/id/apelido`)
e converte pra **accountid** (SteamID64 - 76561197960265728, os 32 bits
baixos) na hora de salvar - é esse número, não o SteamID64 inteiro, que a
página de atividade expõe em `data-miniprofile` pra cada autor de evento
(compra/rollup). Comparação em `_extrair_eventos` é sempre por accountid,
nunca por nome (que pode mudar).

## Dados migrados (2026-08-24, verificados por checksum antes de remover da GAIA)

`data/lancamentos_estado.json` (~230 itens de wishlist, renomeado de
`steam_lancamentos_estado.json`), `data/lancamentos_checagem_diaria.json`,
`data/atividade_vista.json` (renomeado de `steam_atividade_vista.json`),
`data/atividade_checagem_diaria.json` - prefixo `steam_` removido (dentro
do próprio repo do HESTIA já é redundante) - a GAIA não guarda mais cópia
nenhuma desses arquivos.
