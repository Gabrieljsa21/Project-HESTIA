# -*- coding: utf-8 -*-
"""Capturas da nuvem: lista com total e detalhes, apagar confere na Steam,
limites de entrada e sessão ausente."""
import pytest

from hestia.core import capturas_nuvem as cn

GRADE = ('<script>g_steamID = "765";</script> Showing 1 - 50 of 1,669 '
         '<a data-publishedfileid="11"></a><a data-publishedfileid="22"></a><a data-publishedfileid="11"></a>')


class Resp:
    def __init__(self, texto="", status=200):
        self.text, self.status_code = texto, status


class SessaoFalsa:
    def __init__(self, paginas):
        self.paginas = list(paginas)
        self.cookies = type("Cookies", (), {"get": lambda self, nome, domain=None: "abc"})()
        self.posts = []

    def get(self, url, params=None, timeout=None):
        return Resp(self.paginas.pop(0))

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append((url, data))
        return Resp("ok")


def _detalhe(pid, resultado=1):
    return {"publishedfileid": pid, "result": resultado, "consumer_appid": 678960, "app_name": "CODE VEIN",
            "filename": "678960/screenshots/20200906133038_1.jpg", "file_size": "448865", "time_created": 1787706616,
            "image_width": 1360, "image_height": 768, "file_url": "https://u/1", "visibility": 2}


@pytest.fixture
def sessao(monkeypatch):
    def montar(paginas, detalhes):
        s = SessaoFalsa(paginas)
        monkeypatch.setattr(cn, "_sessao", lambda: (s, "765"))
        monkeypatch.setattr(cn, "_detalhes", lambda ids: {i: detalhes(i) for i in ids})
        monkeypatch.setattr(cn.time, "sleep", lambda s: None)
        return s
    return montar


def test_lista_sem_repetir_e_com_total(sessao):
    sessao([GRADE], lambda i: _detalhe(i))
    r = cn.listar(1)
    assert (r["total"], r["paginas"]) == (1669, 34)
    assert [i["id"] for i in r["itens"]] == ["11", "22"]
    item = r["itens"][0]
    assert (item["nome_arquivo"], item["bytes"], item["visibilidade"], item["jogo"]) == ("20200906133038_1.jpg", 448865, "privada", "CODE VEIN")


def test_pagina_sem_grade_tenta_de_novo(sessao):
    sessao(['<script>g_steamID = "765";</script>', GRADE], lambda i: _detalhe(i))
    assert cn.listar(1)["total"] == 1669


def test_pagina_de_login_vira_sem_sessao(sessao):
    sessao(['<script>g_steamID = false;</script>'], lambda i: _detalhe(i))
    with pytest.raises(cn.SemSessao):
        cn.listar(1)


def test_apagar_confere_cada_uma(sessao):
    s = sessao([], lambda i: _detalhe(i, resultado=9 if i == "11" else 1))
    r = cn.apagar(["11", "22"])
    assert r["apagadas"] == ["11"] and r["falhas"][0]["id"] == "22"
    _, dados = s.posts[0]
    assert dados["action"] == "delete" and "screenshots[11]" in dados and "screenshots[22]" in dados


def test_apagar_recusa_id_invalido_e_lote_grande(sessao):
    sessao([], lambda i: _detalhe(i))
    with pytest.raises(ValueError):
        cn.apagar(["11", "abc"])
    with pytest.raises(ValueError):
        cn.apagar([str(i) for i in range(cn.MAX_APAGAR_POR_CHAMADA + 1)])
    assert cn.apagar([]) == {"apagadas": [], "falhas": []}
