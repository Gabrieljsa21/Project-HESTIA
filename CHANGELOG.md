# Changelog

Histórico de alto nível do que muda no HESTIA, por versão. Ver
`ARQUITETURA.md` pro detalhe técnico completo.

## [Unreleased]

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
