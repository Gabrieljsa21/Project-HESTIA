# -*- coding: utf-8 -*-
"""Gravação segura, lista de vistos da atividade, cache de busca e logs."""
import datetime
import os

import pytest

import logging

from hestia import armazenamento, registro
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


def test_pasta_de_logs_no_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert registro.pasta_logs("HESTIA") == tmp_path / "Ecossistema" / "HESTIA" / "Logs"


def test_limpeza_apaga_so_logs_antigos(tmp_path):
    hoje = datetime.date(2026, 11, 14)
    for nome in ("2026-10-01.log", "2026-11-01.log", "manual.log", "2026-13-99.log"):
        (tmp_path / nome).write_text("x")
    assert registro.limpar(tmp_path, dias=30, hoje=hoje) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-01.log", "2026-13-99.log", "manual.log"]


def test_log_no_arquivo_do_dia(tmp_path):
    manipulador = registro.ArquivoDoDia(tmp_path)
    manipulador.setFormatter(logging.Formatter(registro.FORMATO))
    log = logging.getLogger("teste.registro")
    log.addHandler(manipulador)
    log.propagate = False
    try:
        log.warning("algo aconteceu")
    finally:
        log.removeHandler(manipulador)
        manipulador.arquivo.close()
    texto = (tmp_path / f"{datetime.date.today().isoformat()}.log").read_text(encoding="utf-8")
    assert "WARNING teste.registro: algo aconteceu" in texto


def test_falha_do_log_nao_vira_laco(monkeypatch):
    """Se o log falhar ao escrever, o erro não pode voltar para o log."""
    import sys
    saida = registro._SaidaParaLog("teste.laco", logging.WARNING)
    chamadas = []

    class Quebrado(logging.Handler):
        def emit(self, registro_):
            chamadas.append(1)
            sys.stderr.write("erro ao escrever\n")   # como o logging.handleError faz

    log = logging.getLogger("teste.laco")
    quebrado = Quebrado()
    log.addHandler(quebrado)
    log.propagate = False
    monkeypatch.setattr(sys, "stderr", saida)
    try:
        saida.write("primeira linha\n")
    finally:
        log.removeHandler(quebrado)
    assert chamadas == [1]
