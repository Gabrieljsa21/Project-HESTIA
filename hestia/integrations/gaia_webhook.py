# -*- coding: utf-8 -*-
"""Avisa a GAIA por HTTP quando um lançamento da wishlist precisa ser
sincronizado/removido do Google Calendar dedicado "Lançamentos Steam" -
extraído de `integrations/google_calendar/google_calendar.py::
sincronizar_evento_lancamento`/`remover_evento_lancamento` (GAIA, antes da
extração pro HESTIA, 2026-08-24). O HESTIA NUNCA fala com o Google Calendar
direto - duplicar a credencial OAuth só pra isso (2ª tela de consentimento)
não compensa, já que a GAIA já tem tudo isso configurado pra Agenda/
Secretária. Mesmo padrão do webhook reverso já usado pelo MOIRAI
(`POST /moirai/episodio_assistido`), só que na direção "sincronizar", não
"avisar que terminou de assistir".

Silencioso se a GAIA não estiver rodando (nunca trava a checagem de
lançamentos por causa de um aviso que ninguém vai ouvir) - devolve False,
igual a `sincronizar_evento_lancamento` original devolvia False em qualquer
falha (sem calendário configurado, API indisponível, etc.), então quem
chama (`hestia/core/lancamentos.py`) não precisa saber a diferença."""
import json
import os
import urllib.request

URL_BASE = os.environ.get("GAIA_WEBHOOK_URL", "http://127.0.0.1:8766/hestia/sincronizar_lancamento")
_URL_REMOVER = URL_BASE.replace("/sincronizar_lancamento", "/remover_lancamento")


def sincronizar_evento_lancamento(appid, nome_jogo, data_lancamento, link_steam=None):
    """Mesmo contrato de retorno do original (True se agendou/já estava
    agendado, False em qualquer falha) - `data_lancamento` é um `date` do
    Python aqui, mas vai serializado como ISO string no corpo HTTP."""
    try:
        corpo = json.dumps({
            "appid": appid,
            "nome": nome_jogo,
            "data": data_lancamento.isoformat(),
            "link": link_steam,
        }).encode("utf-8")
        req = urllib.request.Request(URL_BASE, data=corpo, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            resultado = json.loads(resp.read())
        return bool(resultado.get("agendado"))
    except Exception:
        return False


def remover_evento_lancamento(appid):
    try:
        corpo = json.dumps({"appid": appid}).encode("utf-8")
        req = urllib.request.Request(_URL_REMOVER, data=corpo, method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False
