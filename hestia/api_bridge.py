# -*- coding: utf-8 -*-
"""Ponte HTTP do HESTIA (porta 8770) - mesmo padrão de `moirai/api_bridge.py`
(`BaseHTTPRequestHandler` simples, sem framework). Único consumidor: a GAIA
(`integrations/hestia_client.py`), tanto pelos 3 loops do Agendador Diário/
monitoramento (`run.py`) quanto pelas 4 tags sob demanda (`<STEAM>`/
`<LANCAMENTOS>`/`<CONQUISTAS:jogo>`/`<GUIA_CONQUISTA:jogo:conquista>`,
`core/agent/turno.py`/`core/tools/handlers.py`) - a GAIA decide QUANDO chamar e
O QUE DIZER (voz/Discord/persona); aqui só devolve o dado bruto.

`GET /conquistas/<appid>` só aceita appid NUMÉRICO - resolver por NOME é dado
LOCAL desta máquina (lista de jogos escaneados, `features/app_launcher/
apps_scanner.py` do lado da GAIA), não faz sentido virar chamada de rede pro
HESTIA (ver `core/agent/turno.py::_obter_conquistas_resolvendo_nome`)."""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from hestia.core import atividade, lancamentos, conquistas, familia

LOCAL_API_HOST = "127.0.0.1"
LOCAL_API_PORT = 8770


def _ler_corpo_json(handler):
    tamanho = int(handler.headers.get("Content-Length", 0))
    try:
        return json.loads(handler.rfile.read(tamanho)) if tamanho else {}
    except Exception:
        return {}


class _API(BaseHTTPRequestHandler):
    def _responder_json(self, dados):
        corpo = json.dumps(dados).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo)

    def _responder_ok(self):
        self.send_response(200)
        self.end_headers()

    def _responder_404(self):
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        caminho, _, query = self.path.partition("?")
        params = urllib.parse.parse_qs(query)

        if caminho == "/atividade/verificar":
            self._responder_json(atividade.verificar_novidades_steam())
        elif caminho == "/atividade/atual":
            limite = int((params.get("limite") or [10])[0])
            self._responder_json(atividade.obter_atividade_atual(limite))
        elif caminho == "/atividade/ultima_checagem_diaria":
            self._responder_json({"ultima_data": atividade.obter_ultima_checagem_diaria_resumo()})
        elif caminho == "/atividade/sessao_valida":
            self._responder_json(atividade.obter_status_sessao())
        elif caminho == "/lancamentos/verificar":
            self._responder_json(lancamentos.verificar_lancamentos())
        elif caminho == "/lancamentos/proximos":
            limite = int((params.get("limite") or [10])[0])
            self._responder_json(lancamentos.obter_proximos_lancamentos(limite))
        elif caminho == "/lancamentos/ultima_checagem_diaria":
            self._responder_json({"ultima_data": lancamentos.obter_ultima_checagem_diaria()})
        elif caminho.startswith("/conquistas/"):
            appid = caminho[len("/conquistas/"):]
            nome_conhecido = (params.get("nome_conhecido") or [None])[0]
            self._responder_json(conquistas.obter_progresso_conquistas(appid, nome_conhecido))
        elif caminho == "/guia_conquista":
            jogo = (params.get("jogo") or [""])[0]
            conquista_pedida = (params.get("conquista") or [""])[0]
            self._responder_json(conquistas.buscar_guia_conquista(jogo, conquista_pedida))
        elif caminho == "/familia":
            self._responder_json(familia.listar_familia())
        else:
            self._responder_404()

    def do_POST(self):
        caminho = self.path

        if caminho == "/atividade/ultima_checagem_diaria":
            atividade.salvar_ultima_checagem_diaria_resumo(_ler_corpo_json(self).get("data", ""))
            self._responder_ok()
        elif caminho == "/lancamentos/ultima_checagem_diaria":
            lancamentos.salvar_ultima_checagem_diaria(_ler_corpo_json(self).get("data", ""))
            self._responder_ok()
        elif caminho == "/atividade/renovar_sessao":
            self._responder_json(atividade.renovar_sessao_via_navegador())
        elif caminho == "/familia":
            self._responder_json(familia.adicionar_familia(_ler_corpo_json(self).get("perfil", "")))
        elif caminho == "/familia/remover":
            familia.remover_familia(_ler_corpo_json(self).get("accountid", ""))
            self._responder_ok()
        else:
            self._responder_404()

    def log_message(self, format, *args):
        return


def iniciar_servidor_api():
    servidor = HTTPServer((LOCAL_API_HOST, LOCAL_API_PORT), _API)
    servidor.serve_forever()
