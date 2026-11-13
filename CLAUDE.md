# Project HESTIA

Serviço da Steam (wishlist, atividade, conquistas) sem interface, atrás de uma ponte HTTP em `127.0.0.1:8770`. O único cliente é a GAIA (`Project G.A.I.A/assistant/integrations/hestia_client.py`): ela decide quando consultar e o que dizer; o HESTIA só devolve dado.

## Ao mudar o código

- Contrato HTTP (rota, campo, formato) mudou: a PR da GAIA que acompanha sobe junto e os dois processos são reiniciados juntos. Um lado novo com o outro antigo perde os avisos daquele dia.
- Arquivo em `data/`: ler e gravar por `hestia/armazenamento.py` (`ler_json`/`gravar_json`). Leitura-e-regravação de um mesmo arquivo fica sob o lock do módulo: o servidor atende cada requisição numa thread.
- Caminhos de `data/`, `cache/` e `logs/` são relativos à pasta atual: rodar sempre da raiz do repositório.
- Fontes de dado da Steam: só API oficial, mais a página de atividade logada. Raspar a loja para corrigir a data de lançamento foi recusado pelo usuário (ver `docs/ARQUITETURA.md`, "Limitação conhecida").
- Testes: `.venv/Scripts/python.exe -m pytest -q tests`. Regra de aviso nova ou corrigida ganha teste em `tests/test_lancamentos.py`.

## Ao subir para o git

Cada PR leva, no mesmo commit:

- versão nova em `pyproject.toml` e entrada no `CHANGELOG.md` sob `## [X.Y.Z] - AAAA-MM-DD`; tag `vX.Y.Z` no commit mesclado;
- `docs/ARQUITETURA.md` quando a decisão técnica mudar (uma seção por leva, antes de "Contrato HTTP", e o contrato atualizado);
- `docs/FUNCIONALIDADES.md` quando mudar o que o usuário recebe;
- `docs/TODO.md` só com pendências: item feito sai do arquivo.

Estilo de texto em `docs/PADRAO_DOCUMENTACAO.md`.

## Reiniciar depois de mesclar

Python não recarrega código. Encerrar os dois processos `hestia.main` (o `pythonw.exe` do venv e o `python.exe` filho) e abrir `iniciar_hestia_oculto.vbs`. Conferir com `GET /lancamentos/pendentes`.
