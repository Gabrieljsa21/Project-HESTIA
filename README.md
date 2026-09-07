<p align="center">
  <img src="assets/icone_hestia.png" alt="Project HESTIA" width="180">
</p>

# Project HESTIA

Serviço que acompanha a Steam, incluindo wishlist, lançamentos, atividade e conquistas.

## Recursos principais

- avisa sobre lançamentos, DLCs, jogos gratuitos e saída de Acesso Antecipado;
- acompanha compras, conquistas e anúncios na atividade da Steam;
- destaca pessoas marcadas como família;
- consulta o progresso de conquistas;
- procura guias para destravar conquistas.

O HESTIA recebe pedidos pela API local na porta `8770`. Ele não possui janela própria nem faz consultas em horário fixo por conta própria.

## Origem do nome

HESTIA vem de Héstia (Ἑστία), deusa grega da lareira, do fogo doméstico, da casa e do lar. Na Grécia antiga, a lareira ocupava o centro da casa e representava estabilidade, pertencimento e o lugar para onde as pessoas retornavam.

A Steam cumpre um papel parecido como lar da biblioteca de jogos: **Héstia → lareira → lar → biblioteca de jogos → Steam**.

### Identidade visual

A logo traz uma chama dourada no centro, referência direta ao fogo de Héstia. Ao redor dela, fluxos azuis e brancos lembram fumaça, vapor, chama azul e energia.

Essa combinação forma a sequência **fogo → calor → vapor → Steam**. Os pequenos cristais mantêm a linguagem visual do ecossistema sem tirar o destaque da chama.

## Requisitos

- Python 3.11 ou mais recente;
- conta da Steam;
- dados opcionais da Steam conforme o recurso usado.

## Instalação e uso

```powershell
uv venv
uv pip install -e .
Copy-Item .env.example .env
python -m hestia.main
```

O `.env.example` explica estas opções:

- `STEAM_ID64` para a wishlist;
- `STEAM_WEBAPI_KEY` para conquistas;
- `STEAM_LOGIN_SECURE` e `STEAM_PERFIL_URL` para a atividade.

Use `iniciar_hestia_oculto.vbs` para abrir sem terminal visível.

## Integrações com outros projetos

- **GAIA:** define quando consultar os dados, apresenta os avisos por texto ou voz e sincroniza lançamentos com o Google Calendar.

Use `GAIA_WEBHOOK_URL` no `.env` para ativar a sincronização com o calendário.

A API local permite que outros clientes façam as mesmas consultas.

## Documentação

- [Arquitetura](docs/ARQUITETURA.md)
- [Pendências](docs/TODO.md)
- [Histórico de versões](CHANGELOG.md)
- [Padrão de documentação](docs/PADRAO_DOCUMENTACAO.md)

## Situação atual

Wishlist, atividade, conquistas e busca de guias foram validadas com dados reais.
