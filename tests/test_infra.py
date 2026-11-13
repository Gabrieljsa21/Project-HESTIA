# -*- coding: utf-8 -*-
"""Gravação segura, lista de vistos da atividade, cache de busca e logs."""
import datetime
import os

import pytest

from hestia import armazenamento, runtime_log
from hestia.core import atividade
from hestia.integrations import search_ddg


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_gravacao_segura_recupera_pelo_bak():
    armazenamento.gravar_json("data/x.json", {"v": 1})
    armazenamento.gravar_json("data/x.json", {"v": 2})
    with open("data/x.json", "w", encoding="utf-8") as f:
        f.write("{corrompido")
    assert armazenamento.ler_json("data/x.json", {}) == {"v": 1}
    assert not os.path.exists("data/x.json.tmp")


def test_vistos_cortam_os_mais_antigos(monkeypatch):
    monkeypatch.setattr(atividade, "MAX_VISTOS_GUARDADOS", 3)
    atividade._salvar_vistos(["a", "b", "c", "d"])
    assert atividade._carregar_vistos() == ["b", "c", "d"]


def test_evento_que_continua_na_pagina_nao_volta_como_novo(monkeypatch):
    monkeypatch.setattr(atividade, "MAX_VISTOS_GUARDADOS", 3)
    monkeypatch.setattr(atividade, "_buscar_html", lambda: "html")
    pagina = [{"chave": "velho", "texto": "x", "familia": False}]
    monkeypatch.setattr(atividade, "_extrair_eventos", lambda html: pagina)
    atividade.verificar_novidades_steam()  # primeira vez: linha de base
    for chave in ("n1", "n2", "n3"):
        pagina.insert(0, {"chave": chave, "texto": chave, "familia": False})
        pagina[:] = pagina[:3]
        novos = atividade.verificar_novidades_steam()
        assert [e["chave"] for e in novos] == [chave]


def test_cache_de_busca_devolve_resultados_estruturados(monkeypatch):
    class DDGSFalso:
        chamadas = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, **k):
            DDGSFalso.chamadas += 1
            return [{"title": "Guia Jogo", "body": "passo a passo", "href": "https://x"}]

    monkeypatch.setattr(search_ddg, "DDGS", DDGSFalso)
    primeira = search_ddg.search_ddg("jogo conquista", retornar_detalhes=True)
    segunda = search_ddg.search_ddg("jogo conquista", retornar_detalhes=True)
    assert DDGSFalso.chamadas == 1
    assert segunda == primeira and segunda[1][0]["link"] == "https://x"


def test_limpeza_apaga_so_logs_antigos(tmp_path):
    pasta = tmp_path / "logs"
    pasta.mkdir()
    hoje = datetime.date.today()
    antigo = pasta / f"{(hoje - datetime.timedelta(days=31)).isoformat()}.log"
    recente = pasta / f"{(hoje - datetime.timedelta(days=5)).isoformat()}.log"
    outro = pasta / "manual.log"
    for arquivo in (antigo, recente, outro):
        arquivo.write_text("x")
    assert runtime_log.limpar_logs_antigos(str(tmp_path)) == 1
    assert not antigo.exists() and recente.exists() and outro.exists()
