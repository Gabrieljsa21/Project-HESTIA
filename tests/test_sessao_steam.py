# -*- coding: utf-8 -*-
"""Login por QR: aprovação, QR expirado, renovação do acesso e tokens
cifrados em disco. A Steam é trocada por um dublê de `requests.post`."""
import base64
import json
import time

import pytest

from hestia.core import sessao_steam


def _jwt(exp, sub="76561198000000001"):
    def parte(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{parte({'alg': 'none'})}.{parte({'sub': sub, 'exp': exp})}.assinatura"


class Resposta:
    def __init__(self, dados, eresult="1"):
        self._dados = dados
        self.headers = {"x-eresult": eresult}

    def json(self):
        return {"response": self._dados}

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sessao_steam._login.clear()
    sessao_steam._login["estado"] = "nenhum"


def _steam_falsa(monkeypatch, consultas, renovacao=None):
    consultas = iter(consultas)
    chamadas = []

    def post(url, data=None, timeout=None):
        chamadas.append(url)
        if url == sessao_steam.URL_INICIAR:
            return Resposta({"client_id": "1", "request_id": "cmVx", "challenge_url": "https://s.team/q/1/1", "interval": 0})
        if url == sessao_steam.URL_CONSULTAR:
            return next(consultas)
        return renovacao
    monkeypatch.setattr(sessao_steam.requests, "post", post)
    monkeypatch.setattr(sessao_steam.time, "sleep", lambda s: None)
    return chamadas


def _esperar_estado(*estados):
    limite = time.time() + 5
    while sessao_steam.status_login_qr()["estado"] not in estados and time.time() < limite:
        time.sleep(0.02)
    return sessao_steam.status_login_qr()["estado"]


def test_aprovacao_grava_tokens_cifrados(monkeypatch):
    refresh, access = _jwt(time.time() + 10**7), _jwt(time.time() + 86400)
    _steam_falsa(monkeypatch, [
        Resposta({"had_remote_interaction": True}),
        Resposta({"refresh_token": refresh, "access_token": access, "account_name": "conta"}),
    ])
    qr = sessao_steam.iniciar_login_qr()
    assert base64.b64decode(qr["qr_png"]).startswith(b"\x89PNG")
    assert _esperar_estado("aprovado") == "aprovado"
    bruto = open("data/sessao_steam.json", encoding="utf-8").read()
    assert refresh not in bruto and access not in bruto
    assert sessao_steam.obter_cookie() == f"76561198000000001%7C%7C{access}"
    assert sessao_steam.situacao()["conta"] == "conta"


def test_qr_recusado_vira_expirado(monkeypatch):
    _steam_falsa(monkeypatch, [Resposta({}, eresult="9")])
    sessao_steam.iniciar_login_qr()
    assert _esperar_estado("expirado") == "expirado"
    assert sessao_steam.obter_cookie() is None


def test_acesso_perto_de_vencer_e_renovado(monkeypatch):
    refresh, velho, novo = _jwt(time.time() + 10**7), _jwt(time.time() + 60), _jwt(time.time() + 86400)
    sessao_steam._salvar_tokens("76561198000000001", "conta", refresh, velho)
    chamadas = []
    loja = _jwt(time.time() + 86400 + 1)
    monkeypatch.setattr(sessao_steam, "_renovar_acesso", lambda r: chamadas.append(r) or {"comunidade": novo, "loja": loja})
    assert sessao_steam.obter_cookie().endswith(novo)
    assert sessao_steam.obter_cookie().endswith(novo)  # já renovado: não chama de novo
    assert sessao_steam.obter_cookie(loja=True).endswith(loja)  # veio junto na renovação
    assert chamadas == [refresh]


def test_token_da_loja_sai_da_renovacao_quando_falta(monkeypatch):
    comunidade, loja = _jwt(time.time() + 86400), _jwt(time.time() + 86400 + 5)
    sessao_steam._salvar_tokens("76561198000000001", "conta", _jwt(time.time() + 10**7), comunidade)
    monkeypatch.setattr(sessao_steam, "_renovar_acesso", lambda r: {"comunidade": comunidade, "loja": loja})
    assert sessao_steam.obter_cookie(loja=True).endswith(loja)
    assert sessao_steam.obter_cookie().endswith(comunidade)


def test_renovacao_falha_usa_o_acesso_ate_vencer(monkeypatch):
    velho = _jwt(time.time() + 60)
    sessao_steam._salvar_tokens("76561198000000001", "conta", _jwt(time.time() + 10**7), velho)
    monkeypatch.setattr(sessao_steam, "_renovar_acesso", lambda r: {})
    assert sessao_steam.obter_cookie().endswith(velho)


def test_acesso_vencido_sem_renovacao_devolve_none(monkeypatch):
    sessao_steam._salvar_tokens("76561198000000001", "conta", _jwt(time.time() + 10**7), _jwt(time.time() - 10))
    monkeypatch.setattr(sessao_steam, "_renovar_acesso", lambda r: {})
    assert sessao_steam.obter_cookie() is None
