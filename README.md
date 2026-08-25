# Project-HESTIA

Assistente de Steam da GAIA - acompanha a wishlist do usuário (avisa
lançamento do dia, saída de Acesso Antecipado, jogo que virou grátis, DLC
nova, lembretes antecipados), a página de atividade (compra/conquista/
anúncio de amigos) e o progresso de conquistas de um jogo específico
(incluindo busca de guia de "como destravar"). Processo próprio, **sem
interface gráfica** - só uma ponte HTTP; quem decide QUANDO checar e O QUE
FALAR sobre isso é sempre a [GAIA](../Project%20G.A.I.A) (assistente
pessoal do mesmo autor), consultando o HESTIA por HTTP.

Extraído da GAIA em 2026-08-24 - eram 3 features separadas
(`features/game_releases/steam_lancamentos.py`,
`features/steam_activity/steam_monitor.py`,
`features/achievements/steam_conquistas.py`, ver histórico completo em
`Project G.A.I.A/assistant/docs/FUNCIONALIDADES.md`/`CHANGELOG.md`).
Arquitetura completa e decisões de design em [`ARQUITETURA.md`](ARQUITETURA.md).

## A origem do nome

Héstia é a deusa grega da lareira, do fogo doméstico e do lar - a Steam
como o "lar" da biblioteca de jogos do usuário, a chama como o núcleo que
permanece ativo (identidade visual: fogo/chama/vapor, também conecta com
"Steam" literalmente). Escopo de longo prazo do projeto é mais amplo do
que o que existe em código hoje (biblioteca completa, Early Access →
lançamento, preços, tempo jogado, atualizações importantes) - o estado
atual cobre só wishlist/atividade/conquistas, a parte que já existia como
feature da GAIA antes da extração.

## Uso standalone

```bash
uv venv
uv pip install -e .
python -m hestia.main
```

Sem loop de manutenção próprio (diferente do Project-MOIRAI, que continua
baixando/sincronizando sozinho mesmo com a GAIA fechada) - o HESTIA fica
parado esperando requisição HTTP na porta 8770 (`hestia/api_bridge.py`).
As 3 checagens (lançamentos, atividade, conquistas) só rodam quando
alguém pergunta - normalmente a GAIA, pelo Agendador Diário ou por uma
tag sob demanda (`<STEAM>`/`<LANCAMENTOS>`/`<CONQUISTAS:jogo>`/
`<GUIA_CONQUISTA:jogo:conquista>`); sem a GAIA rodando, chame os
endpoints manualmente.

Variáveis de ambiente opcionais (`.env`, ver `.env.example`) - cada uma
liga um módulo independente:
- `STEAM_LOGIN_SECURE`/`STEAM_PERFIL_URL` - sessão logada da Steam, usada
  pelo monitoramento de atividade (compra/conquista/anúncio de amigos) e
  como fallback pra resolver o SteamID64 se ele não estiver configurado.
- `STEAM_ID64` - usado pelo Assistente de Lançamentos pra ler a wishlist
  via API oficial (sem chave nenhuma).
- `STEAM_WEBAPI_KEY` - usada pelo Assistente de Conquistas pra ler o
  progresso real de conquistas.
- `GAIA_WEBHOOK_URL` - onde avisar a GAIA pra sincronizar um lançamento
  com o Google Calendar dedicado "Lançamentos Steam" (padrão
  `http://127.0.0.1:8766/hestia/sincronizar_lancamento`) - o HESTIA nunca
  fala com o Google Calendar direto, evita duplicar credencial OAuth só
  pra isso (a GAIA já tem tudo configurado pra Agenda/Secretária).

## Integração com a GAIA

`integrations/hestia_client.py` (repo da GAIA) fala com a ponte HTTP
daqui - usado pelo Agendador Diário (avisos proativos de lançamento/
atividade), pelo monitoramento reativo de atividade (`_monitorar_steam_
loop`, a cada 20min) e pelas tags sob demanda `<STEAM>`/`<LANCAMENTOS>`/
`<CONQUISTAS:jogo>`/`<GUIA_CONQUISTA:jogo:conquista>`. A resolução de
NOME de jogo pra appid (`<CONQUISTAS:nome do jogo>`) fica do lado da
GAIA, não aqui - depende da lista de jogos escaneados LOCALMENTE naquela
máquina (`features/app_launcher/apps_scanner.py`), dado que não faz
sentido virar chamada de rede pro HESTIA; o HESTIA só aceita appid
numérico. Ver `hestia/api_bridge.py` pro contrato HTTP completo.

## Estado da extração (2026-08-24)

Completa - sem UI dedicada pra migrar (diferente do MOIRAI): os toggles
de Steam sempre moraram no Painel da GAIA (`ui/qt_modais/notificacoes.py`,
"quando/como avisar", não dado da Steam) e continuam lá sem mudança.
Validado de ponta a ponta com dados reais: wishlist de ~230 itens,
conquistas de um jogo real (percentuais/raridade), busca de guia de
conquista (DDG + conteúdo completo da página), e o webhook de
sincronização com o Google Calendar.
