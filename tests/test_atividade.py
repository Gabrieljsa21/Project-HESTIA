# -*- coding: utf-8 -*-
"""Atividade: detecção de sessão, Web API da família, chave comum entre as
duas fontes e histórico de avisos."""
import pytest

from hestia import historico
from hestia.core import atividade, atividade_api, familia, lancamentos


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STEAM_WEBAPI_KEY", "chave")
    monkeypatch.setenv("STEAM_ID64", "76561197960265729")


def test_tela_de_login_nao_conta_como_sessao_valida():
    assert atividade._validar_sessao('<script>g_steamID = false;</script>') is False
    assert atividade._validar_sessao('<script>g_steamID = "76561198000000000";</script>') is True


def _api_falsa(monkeypatch, bibliotecas):
    """bibliotecas: lista de {appid: nome}, uma por chamada."""
    respostas = iter(bibliotecas)
    monkeypatch.setattr(familia, "listar_familia", lambda: [{"steamid64": "765", "accountid": "42", "nome": "Ana"}])
    monkeypatch.setattr(atividade_api, "_jogos_da_pessoa", lambda s: next(respostas))
    monkeypatch.setattr(atividade_api, "_anuncios_dos_meus_jogos", lambda estado: [])


def test_compra_da_familia_pela_api(monkeypatch):
    _api_falsa(monkeypatch, [{"1": "Jogo A"}, {"1": "Jogo A", "2": "Jogo B"}])
    assert atividade_api.coletar_eventos() == []  # linha de base
    eventos = atividade_api.coletar_eventos()
    assert [e["texto"] for e in eventos] == ["Ana comprou Jogo B na Steam."]
    assert eventos[0]["familia"] is True


def test_mesma_compra_nas_duas_fontes_avisa_uma_vez(monkeypatch):
    _api_falsa(monkeypatch, [{"1": "Jogo A"}, {"1": "Jogo A"}, {"1": "Jogo A", "2": "Jogo B"}])
    monkeypatch.setattr(atividade, "_buscar_html", lambda: None)
    atividade.verificar_novidades_steam()  # linha de base da API
    pagina = []
    monkeypatch.setattr(atividade, "_buscar_html", lambda: "html")
    monkeypatch.setattr(atividade, "_extrair_eventos", lambda html: list(pagina))
    atividade.verificar_novidades_steam()  # primeira leitura dos vistos
    pagina.append({"chave": atividade._chave("compra", "42", "jogo b"), "texto": "Ana comprou Jogo B na Steam.", "familia": True})
    novos = atividade.verificar_novidades_steam()
    assert len(novos) == 1
    assert historico.listar(categoria="atividade")[0]["texto"] == "Ana comprou Jogo B na Steam."


def test_lancamento_confirmado_vai_para_o_historico(monkeypatch):
    monkeypatch.setattr(lancamentos, "verificar_lancamentos", lambda: ["X lança HOJE"])
    lancamentos._executar_varredura()
    pendente = lancamentos.obter_status_varredura()["eventos"][0]
    assert historico.listar() == []
    lancamentos.confirmar_eventos([pendente["id"]])
    assert historico.listar()[0]["texto"] == "X lança HOJE"
