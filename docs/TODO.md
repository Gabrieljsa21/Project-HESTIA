# TODO - Project HESTIA

Só pendências. Item feito sai do arquivo e vai para o `CHANGELOG.md`.

Cada item tem **Prioridade** (Alta/Média/Baixa), **Complexidade** (Alta/Média/Baixa) e **Status**.

## Funcionalidades

### Visão ampliada da Steam

- **Prioridade:** Média
- **Complexidade:** Alta
- **Status:** 💡 Ideia

Plano de longo prazo registrado em `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`: biblioteca de jogos completa, jogo que virou grátis fora da wishlist, tempo jogado, preços e atualizações importantes. Hoje o HESTIA cobre só wishlist, atividade e conquistas.

### Interface própria

- **Prioridade:** Baixa
- **Complexidade:** Média
- **Status:** 💡 Ideia

Janela ou ícone na bandeja para usar o HESTIA sem a GAIA aberta. Nenhuma necessidade conhecida hoje.

## Decisões em espera

### Data de lançamento pode ficar um dia antes

- **Prioridade:** Baixa
- **Complexidade:** Média
- **Status:** ⏸ Aguardando decisão do usuário

A API pública da Steam devolve só a data em texto, sem fuso; a loja mostra a data convertida para o fuso do usuário. Corrigir exige raspar o HTML da loja, o que o usuário decidiu não fazer em 2026-08-26 (ver `ARQUITETURA.md`, "Limitação conhecida"). Só mexer com pedido novo.
