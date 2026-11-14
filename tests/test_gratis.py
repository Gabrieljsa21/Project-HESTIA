# -*- coding: utf-8 -*-
"""Jogos grátis: ignora o que já está na conta, resgata o da loja e confere,
avisa os sorteios com link e respeita o intervalo entre consultas."""
import pytest

from hestia.core import gratis


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HESTIA_GRATIS_RESGATAR", "1")


class SessaoFalsa:
    def __init__(self):
        self.cookies = self
        self.resgates = []

    def get(self, nome, domain=None):
        return "abc"


def _cenario(monkeypatch, ofertas, posse, sorteios=(), meus=(), resgate_entra=True):
    sessao = SessaoFalsa()
    estado = {"apps": set(posse), "subs": set()}
    monkeypatch.setattr(gratis, "_sessao_loja", lambda: sessao)
    monkeypatch.setattr(gratis, "_posse_na_loja", lambda s: (set(estado["apps"]), set(estado["subs"])))
    monkeypatch.setattr(gratis, "_ofertas_da_steam", lambda: list(ofertas))
    monkeypatch.setattr(gratis, "_detalhes_da_oferta", lambda appid: (appid * 10, "Promoção termina em 17 de novembro"))

    def _resgatar(s, subid):
        s.resgates.append(subid)
        if resgate_entra:
            estado["subs"].add(subid)
        return 200
    monkeypatch.setattr(gratis, "_resgatar", _resgatar)
    monkeypatch.setattr(gratis, "_sorteios_gamerpower", lambda: list(sorteios))
    monkeypatch.setattr(gratis, "_nomes_dos_meus_jogos", lambda: set(meus))
    return sessao


def test_resgata_o_que_nao_tem_e_ignora_o_que_tem(monkeypatch):
    sessao = _cenario(monkeypatch, [{"appid": 1, "nome": "Tenho"}, {"appid": 2, "nome": "Novo"}], posse={1})
    eventos = gratis.coletar_eventos()
    assert sessao.resgates == [20]
    assert [e["texto"] for e in eventos] == ["Novo estava grátis na Steam e já está na sua conta."]
    assert gratis.listar()["itens"] == []  # resgatado não fica na lista


def test_resgate_que_nao_entra_vira_link(monkeypatch):
    _cenario(monkeypatch, [{"appid": 2, "nome": "Novo"}], posse=set(), resgate_entra=False)
    eventos = gratis.coletar_eventos()
    assert eventos[0]["texto"] == "Novo está grátis na Steam (promoção termina em 17 de novembro). Resgate pelo link."
    assert gratis.listar()["itens"][0]["nome"] == "Novo"


def test_sem_resgate_quando_desligado(monkeypatch):
    monkeypatch.setenv("HESTIA_GRATIS_RESGATAR", "0")
    sessao = _cenario(monkeypatch, [{"appid": 2, "nome": "Novo"}], posse=set())
    gratis.coletar_eventos()
    assert sessao.resgates == []


def test_sorteio_avisa_com_link_e_pula_o_que_tem(monkeypatch):
    _cenario(monkeypatch, [], posse=set(), meus={"jogo velho"}, sorteios=[
        {"id": "9", "nome": "Dwarven Realms", "link": "https://g/9", "ate": "2026-11-20 23:59:00"},
        {"id": "8", "nome": "Jogo Velho", "link": "https://g/8", "ate": None},
    ])
    eventos = gratis.coletar_eventos()
    assert [(e["texto"], e["link"]) for e in eventos] == [
        ("Chave grátis de Dwarven Realms na Steam até 20/11. Resgate pelo link.", "https://g/9")]


def test_respeita_o_intervalo(monkeypatch):
    _cenario(monkeypatch, [{"appid": 2, "nome": "Novo"}], posse=set(), resgate_entra=False)
    assert gratis.coletar_eventos()
    assert gratis.coletar_eventos() == []
    assert gratis.coletar_eventos(forcar=True)


def test_nome_do_sorteio():
    assert gratis._nome_do_sorteio("Dwarven Realms (Steam) Key Giveaway") == "Dwarven Realms"
