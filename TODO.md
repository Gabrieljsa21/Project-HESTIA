# TODO - Project HESTIA

## Extração completa (2026-08-24)

3 módulos (lançamentos/atividade/conquistas) totalmente migrados da GAIA,
validados de ponta a ponta com dados reais (wishlist de ~230 itens,
conquistas de um jogo real, busca de guia, webhook do Google Calendar).
Ver `CHANGELOG.md`/`ARQUITETURA.md` pro detalhe completo. Nada bloqueado
no momento - próximos itens são melhorias, não pendências da extração:

- **`load_dotenv()` no MOIRAI** (achado durante esta extração, não é bug
  do HESTIA) - o repo irmão `Project-MOIRAI` também não chama
  `load_dotenv()` em lugar nenhum, então `MAL_CLIENT_ID`/
  `QBITTORRENT_*` do `.env` dele provavelmente nunca são carregados de
  verdade (mesmo sintoma corrigido aqui). Fora de escopo desta extração -
  registrado só pra não esquecer, quem for mexer no MOIRAI de novo deveria
  aplicar o mesmo fix (`load_dotenv(override=True)` em `moirai/main.py`).
- **Visão de longo prazo do HESTIA é mais ampla** (ver
  `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`) - biblioteca de
  jogos completa, transição Early Access → lançamento completo, jogo que
  virou grátis fora da wishlist, DLCs, tempo jogado, preços, atualizações
  importantes. Nenhum desses tem código ainda - o estado atual é só o que
  já existia como feature da GAIA antes da extração (wishlist/atividade/
  conquistas).
- **Sem interface própria (janela/bandeja)** - mesmo caso do MOIRAI, roda
  sem UI nenhuma. Só faria sentido se um dia alguém quiser gerenciar Steam
  sem a GAIA aberta - não é uma necessidade conhecida hoje.
