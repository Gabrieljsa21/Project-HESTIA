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


def _api_falsa(monkeypatch, bibliotecas, amigos=()):
    """bibliotecas: lista de {appid: nome}, uma por chamada (só a família).
    `amigos`: steamid64 de amigos fora da família, sem biblioteca pública."""
    respostas = iter(bibliotecas)
    monkeypatch.setattr(familia, "listar_familia", lambda: [{"steamid64": "765", "accountid": "42", "nome": "Ana"}])
    monkeypatch.setattr(atividade_api, "_jogos_da_pessoa", lambda s: next(respostas) if s == "765" else None)
    monkeypatch.setattr(atividade_api, "_anuncios_dos_meus_jogos", lambda estado: [])

    def _get_falso(url, **params):
        if url == atividade_api.URL_AMIGOS:
            return {"friendslist": {"friends": [{"steamid": a} for a in ("765", *amigos)]}}
        return {"players": [{"steamid": a, "personaname": f"Amigo {a[-2:]}"} for a in amigos]}
    monkeypatch.setattr(atividade_api, "_get", _get_falso)


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


def test_compra_de_amigo_fora_da_familia(monkeypatch):
    amigo = "76561197960265800"
    bibliotecas = {"765": iter([{"1": "A"}, {"1": "A"}]), amigo: iter([{"5": "X"}, {"5": "X", "6": "Y"}])}
    _api_falsa(monkeypatch, [], amigos=(amigo,))
    monkeypatch.setattr(atividade_api, "_jogos_da_pessoa", lambda s: next(bibliotecas[s]))
    assert atividade_api.coletar_eventos() == []
    eventos = atividade_api.coletar_eventos()
    assert [(e["texto"], e["familia"], e["autor"]) for e in eventos] == [("Amigo 00 comprou Y na Steam.", False, "72")]


def test_lista_de_amigos_privada_fica_so_a_familia(monkeypatch):
    monkeypatch.setattr(familia, "listar_familia", lambda: [{"steamid64": "765", "accountid": "42", "nome": "Ana"}])

    def _get_privado(url, **params):
        raise RuntimeError("401")
    monkeypatch.setattr(atividade_api, "_get", _get_privado)
    assert [p["steamid64"] for p in atividade_api._pessoas_acompanhadas()] == ["765"]


def test_pagina_que_volta_nao_despeja_o_passado(monkeypatch):
    _api_falsa(monkeypatch, [{"1": "A"}] * 3)
    monkeypatch.setattr(atividade, "_buscar_html", lambda: None)
    atividade.verificar_novidades_steam()  # linha de base, sem página
    atividade.verificar_novidades_steam()  # página ainda fora
    antigos = [{"chave": f"k{i}", "texto": f"antigo {i}", "familia": False} for i in range(5)]
    monkeypatch.setattr(atividade, "_buscar_html", lambda: "html")
    monkeypatch.setattr(atividade, "_extrair_eventos", lambda html: list(antigos))
    assert atividade.verificar_novidades_steam() == []
    antigos.insert(0, {"chave": "novo", "texto": "novo", "familia": False})
    assert [e["chave"] for e in atividade.verificar_novidades_steam()] == ["novo"]


def test_linha_de_conquista_traz_os_nomes(monkeypatch):
    monkeypatch.setattr(familia, "accountids_familia", lambda: set())
    html = (
        '<div class="blotter_daily_rollup_line"><span>'
        '<a data-miniprofile="7" href="x">Ana <span>(<span>Aninha</span>)</span></a> conquistou em '
        '<a href="https://steamcommunity.com/app/123">Jogo</a>:</span>'
        '<img title="Primeira&#10;Descrição"/><img title="Segunda&#10;Outra"/></div>'
    )
    evento = atividade._extrair_eventos(html)[0]
    assert evento["texto"] == "Ana (Aninha) conquistou em Jogo: Primeira, Segunda"
    assert (evento["tipo"], evento["autor"]) == ("conquista", "Ana (Aninha)")
    assert evento["link"] == "https://store.steampowered.com/app/123"


def test_feed_recente_junta_dias_e_compras_da_api(monkeypatch):
    monkeypatch.setattr(familia, "accountids_familia", lambda: set())
    linha = '<div class="blotter_daily_rollup_line"><span><a data-miniprofile="7" href="x">Ana</a> jogou <a href="https://steamcommunity.com/app/1">J</a> pela primeira vez.</span></div>'
    hoje = f'<div class="blotter_day">{linha}</div>' + "<script>g_BlotterNextLoadURL = 'https://x/ajaxgetusernews/?start=1';</script>"
    ontem = f'<div class="blotter_day"><div class="blotter_day_header_date">12 de nov.</div>{linha}</div>'
    monkeypatch.setattr(atividade, "_buscar_html", lambda: hoje)

    class Resp:
        def json(self):
            return {"blotter_html": ontem, "next_request": None}
    monkeypatch.setattr(atividade, "_get_logado", lambda url, cookie: Resp())
    historico.registrar("atividade", [{"texto": "Bia comprou X na Steam.", "familia": True}])
    itens = atividade.obter_atividade_recente(2)
    assert [i["dia"] for i in itens][1:] == ["Hoje", "12 de nov."]
    assert itens[0]["texto"] == "Bia comprou X na Steam." and itens[0]["familia"] is True
    assert [(i["tipo"], i["autor"]) for i in itens] == [("compra", "Bia"), ("primeira", "Ana"), ("primeira", "Ana")]


def test_tipo_pelo_texto():
    assert atividade._tipo_do_texto("Leo adicionou X à lista de desejos.") == "desejo"
    assert atividade._tipo_do_texto("Leo e Ana agora são amigos.") == "amizade"
    assert atividade._tipo_do_texto("Leo avaliou X.") == "outro"
