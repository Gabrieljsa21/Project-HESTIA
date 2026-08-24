# -*- coding: utf-8 -*-
"""Entry point standalone do HESTIA (`python -m hestia.main`) - extraído da GAIA em
2026-08-24 (ver `Project G.A.I.A/assistant/docs/TODO.md` -> "Arquitetura do
ecossistema"). Diferente do MOIRAI, o HESTIA NÃO tem loop de manutenção próprio -
as 3 checagens (lançamentos 1x/dia, atividade a cada 20min, conquistas sob demanda)
são todas disparadas pela GAIA (ela decide QUANDO checar e O QUE FALAR sobre isso,
via Agendador Diário/`_monitorar_steam_loop`/tags `<STEAM>`/`<LANCAMENTOS>`/
`<CONQUISTAS>`) - o HESTIA só responde HTTP quando perguntado."""
import os
import socket
import sys

from dotenv import load_dotenv

# 🔥 override=True (2026-08-24, mesmo bug real corrigido na GAIA no mesmo dia,
# ver Project G.A.I.A/assistant/docs/CORRECOES.md) - sem isso, uma variável de
# ambiente herdada do processo que lançou o HESTIA (ex.: a própria GAIA, via
# `garantir_hestia_rodando`, que passa seu PRÓPRIO ambiente pro subprocesso
# por padrão) venceria o `.env` do HESTIA em silêncio, pra qualquer chave.
# Carregado ANTES de importar `api_bridge`/`hestia.core.*`, que leem
# `os.getenv` dentro das próprias funções (chamadas só depois do servidor
# subir, então a ordem de import aqui não importa pra elas - só precisa
# acontecer antes do primeiro request de verdade).
load_dotenv(override=True)

from hestia.api_bridge import iniciar_servidor_api  # noqa: E402

PORTA_INSTANCIA_UNICA = 8771

_socket_instancia_unica = None


def _garantir_instancia_unica():
    global _socket_instancia_unica
    _socket_instancia_unica = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _socket_instancia_unica.bind(("127.0.0.1", PORTA_INSTANCIA_UNICA))
    except OSError:
        print(
            " [SISTEMA] Já existe uma instância do HESTIA rodando "
            f"(porta {PORTA_INSTANCIA_UNICA} ocupada) - encerrando esta pra não rodar em duplicidade."
        )
        sys.exit(1)


def main():
    _garantir_instancia_unica()
    os.makedirs("data", exist_ok=True)

    print(" [SISTEMA] HESTIA pronto - ponte HTTP na porta 8770 (sem loop próprio, GAIA decide quando checar).")
    iniciar_servidor_api()  # bloqueia a thread principal


if __name__ == "__main__":
    main()
