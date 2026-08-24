# Arquitetura do Project-HESTIA

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
(persona). Por isso o HESTIA fica parado esperando requisição: `GET
/lancamentos/verificar` (1x/dia, Agendador Diário), `GET /atividade/
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

## Contrato HTTP (`hestia/api_bridge.py`, porta 8770)

- `GET /lancamentos/verificar` - varre a wishlist inteira (minutos, não
  segundos), devolve eventos novos.
- `GET /lancamentos/proximos?limite=N` - lê o cache local, não refaz a
  varredura.
- `GET`/`POST /lancamentos/ultima_checagem_diaria` - catch-up persistido
  (mesmo padrão do MOIRAI).
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

## Dados migrados (2026-08-24, verificados por checksum antes de remover da GAIA)

`data/lancamentos_estado.json` (~230 itens de wishlist, renomeado de
`steam_lancamentos_estado.json`), `data/lancamentos_checagem_diaria.json`,
`data/atividade_vista.json` (renomeado de `steam_atividade_vista.json`),
`data/atividade_checagem_diaria.json` - prefixo `steam_` removido (dentro
do próprio repo do HESTIA já é redundante) - a GAIA não guarda mais cópia
nenhuma desses arquivos.
