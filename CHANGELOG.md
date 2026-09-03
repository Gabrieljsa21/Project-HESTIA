# Changelog

Histórico de alto nível do que muda no HESTIA, por versão. Ver
`ARQUITETURA.md` pro detalhe técnico completo.

## [Unreleased]

### Novidades
- **`iniciar_hestia.bat`/`iniciar_hestia_oculto.vbs` (2026-09-01)** - roda o HESTIA escondido via `pythonw.exe`, sem console. Usado pelo item "HESTIA" da categoria "Projects" do IRIS (ver `Project-IRIS/ARQUITETURA.md`). Ver `README.md`.
- **Destaque de "família" na Atividade da Steam (2026-09-01)** - pedido do usuário: "quero receber principalmente qnd alguem da familia compra algo novo". Nova lista configurável (`hestia/core/familia.py`, cadastro por link do perfil, resolvido pra SteamID64/accountid via API oficial) e novos endpoints `GET`/`POST /familia`, `POST /familia/remover`. Cada evento de `atividade.py` ganha um campo `familia: true/false` - o HESTIA continua notificando tudo (não filtra), só marca quem é família pra GAIA destacar na notificação. Ver `ARQUITETURA.md`.
- **Detecção + autocura de sessão da Steam expirada (2026-09-01)** - pedido do usuário: "vou ter que fazer isso toda hora? n da p automatizar?" (depois de eu diagnosticar - incorretamente, ver correção abaixo - que `STEAM_LOGIN_SECURE` tinha expirado). `_validar_sessao`/`obter_status_sessao` detectam de verdade (checa `g_steamID` no HTML, exige 2 falhas SEGUIDAS antes de declarar expirado de verdade - ver correção); `renovar_sessao_via_navegador` (novo, `browser_cookie3`) pega um cookie fresco direto do Edge/Chrome/Firefox já logado do usuário, sem pedir senha/2FA, e atualiza `.env` + processo atual na hora. Novos endpoints `GET /atividade/sessao_valida`, `POST /atividade/renovar_sessao`. Ver `ARQUITETURA.md`.

### Correções
- **Falso positivo de "sessão expirada" na detecção acima (mesmo dia, achado logo depois de implementar)** - um teste manual isolado leu a tela de login da Steam e eu reportei ao usuário como "confirmado, sessão expirada"; testando de novo minutos depois com o MESMO cookie (comparado por hash, idêntico byte a byte), a sessão leu como válida. Causa: a raspagem dessa página já tinha uma flakiness conhecida e documentada (`_SESSION_ID_FAKE`, ~1 em cada 3 tentativas volta vazia/errada mesmo com sessão boa) que eu não levei em conta ao tratar 1 leitura isolada como prova definitiva. Corrigido: `_marcar_status_sessao` só reporta `valida: false` depois de `LIMITE_FALHAS_CONSECUTIVAS_SESSAO = 2` falhas SEGUIDAS.

## [0.1.0] - 2026-08-24 a 2026-08-27: Extração completa - lançamentos, atividade e conquistas da Steam (PRs #1 a #6)

### Novidades
- **Repositório criado (extração completa, 2026-08-24)** - 3 módulos de
  Steam (lançamentos da wishlist, atividade de amigos, conquistas) movidos
  de `Project G.A.I.A/assistant/features/{game_releases,steam_activity,
  achievements}/`, rodando como processo próprio, sem interface gráfica.
  Ponte HTTP (porta 8770) pro Project G.A.I.A (`integrations/
  hestia_client.py`). Sem loop de manutenção próprio (diferente do
  MOIRAI) - as 3 checagens só rodam quando a GAIA pergunta. Dados reais
  migrados (wishlist de ~230 itens, catch-up de checagem diária),
  verificados por checksum antes de remover da GAIA.
- **Webhook reverso pro Google Calendar** - o HESTIA nunca fala com o
  Google Calendar direto (evita duplicar credencial OAuth só pra isso);
  avisa a GAIA por HTTP (`POST /hestia/sincronizar_lancamento`/`POST
  /hestia/remover_lancamento`) e é ela quem sincroniza o calendário
  dedicado "Lançamentos Steam" de verdade.

### Correções
- **Aviso de "lança HOJE" nunca disparava (2026-08-27)** - achado real, usuário: recebeu "Faltam 1 dia(s)" mas nunca o aviso de lançamento no dia seguinte, e 3 lançamentos do dia (Google Calendar) sem nenhuma notificação. `BRACKETS_LEMBRETE_DIAS` não tinha bracket pro dia `0` - o bracket `1` já era consumido no dia anterior (checagem diária normal), sobrando vazio no dia do lançamento mesmo com a data batendo certinho. Reproduzido com dado real de produção ("Resonance: A Plague Tale Legacy", lançamento no mesmo dia do relato). Corrigido: `BRACKETS_LEMBRETE_DIAS = [30, 7, 1, 0]`. Ver `ARQUITETURA.md`.
- **Lembrete de lançamento (30/7/1 dias antes) ficava mudo pra sempre depois de um jogo ser ADIADO** - achado real (2026-08-26, usuário: "esse My Party Is Grinding lança amanha, e n recebi anuncio hj") - `lembretes_enviados` (faixas já avisadas) nunca era resetado quando a data de lançamento mudava, então uma faixa já "gasta" contra a data ANTIGA continuava contando como "já avisado" mesmo a contagem regressiva reiniciando do zero pra data nova - o usuário nunca mais recebia aviso nenhum daquele jogo. Corrigido em `hestia/core/lancamentos.py::verificar_lancamentos` - reseta as faixas sempre que a data muda. Validado simulando um adiamento (jogo com [30,7,1] já gastos contra a data antiga corretamente voltou a avisar "Faltam 5 dia(s)" pra nova data).
- **`load_dotenv()` nunca era chamado** - nenhuma variável do `.env` era
  carregada de verdade (achado testando os endpoints logo depois da
  extração, com as 4 credenciais de Steam já preenchidas no arquivo, e
  mesmo assim voltando "sem_configuracao"). Corrigido com
  `load_dotenv(override=True)` em `hestia/main.py`, antes de subir a
  ponte HTTP.
