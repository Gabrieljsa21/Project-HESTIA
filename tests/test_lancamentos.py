# -*- coding: utf-8 -*-
"""Regras de aviso da wishlist (`verificar_lancamentos`) e a fila confirmada.

Rede e calendário são trocados por dublês: cada teste monta o estado
anterior em disco, define o que a "loja" responde hoje e confere os avisos."""
from datetime import date, timedelta

import pytest

from hestia.core import lancamentos

HOJE = date.today()


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(lancamentos, "INTERVALO_ENTRE_CHAMADAS_SEGUNDOS", 0)
    monkeypatch.setattr(lancamentos.gaia_webhook, "sincronizar_evento_lancamento", lambda *a, **k: True)
    monkeypatch.setattr(lancamentos.gaia_webhook, "remover_evento_lancamento", lambda *a, **k: True)


def _loja(monkeypatch, detalhes_por_appid):
    monkeypatch.setattr(lancamentos, "obter_wishlist_appids", lambda steamid: list(detalhes_por_appid))
    monkeypatch.setattr(lancamentos, "obter_detalhes_app", lambda appid: detalhes_por_appid[appid])


def _detalhes(data=None, coming_soon=True, is_free=False, early_access=False, dlc=None):
    return {"nome": "Jogo", "coming_soon": coming_soon, "data": data, "is_free": is_free,
            "early_access": early_access, "tipo": "game", "dlc": dlc or []}


def _estado(data=None, coming_soon=True, lembretes=None, is_free=False, early_access=False):
    lancamentos._salvar_estado({"10": {
        "nome": "Jogo", "coming_soon": coming_soon, "data": data.isoformat() if data else None,
        "is_free": is_free, "early_access": early_access, "tipo": "game", "dlc": [],
        "lembretes_enviados": lembretes or [], "agendado_calendario": True,
    }})


def test_primeira_vez_so_grava_estado(monkeypatch):
    _loja(monkeypatch, {10: _detalhes(HOJE + timedelta(days=3))})
    assert lancamentos.verificar_lancamentos("1") == []
    assert "10" in lancamentos._carregar_estado()


def test_faixas_simultaneas_disparam_um_aviso_so(monkeypatch):
    _estado(HOJE + timedelta(days=5))
    _loja(monkeypatch, {10: _detalhes(HOJE + timedelta(days=5))})
    eventos = lancamentos.verificar_lancamentos("1")
    assert len(eventos) == 1 and "Faltam 5 dia(s)" in eventos[0]
    assert sorted(lancamentos._carregar_estado()["10"]["lembretes_enviados"]) == [7, 30]
    assert lancamentos.verificar_lancamentos("1") == []


def test_dia_zero_dispara_mesmo_com_faixa_1_gasta(monkeypatch):
    _estado(HOJE, lembretes=[30, 7, 1])
    _loja(monkeypatch, {10: _detalhes(HOJE)})
    eventos = lancamentos.verificar_lancamentos("1")
    assert len(eventos) == 1 and "lança HOJE" in eventos[0]


def test_adiamento_reseta_faixas(monkeypatch):
    _estado(HOJE + timedelta(days=1), lembretes=[30, 7, 1])
    _loja(monkeypatch, {10: _detalhes(HOJE + timedelta(days=5))})
    eventos = lancamentos.verificar_lancamentos("1")
    assert len(eventos) == 1 and "Faltam 5 dia(s)" in eventos[0]


def test_dia_do_lancamento_pulado_avisa_uma_vez(monkeypatch):
    ontem = HOJE - timedelta(days=1)
    _estado(ontem, lembretes=[30, 7, 1])
    _loja(monkeypatch, {10: _detalhes(ontem)})
    eventos = lancamentos.verificar_lancamentos("1")
    assert len(eventos) == 1 and "tinha lançamento marcado" in eventos[0]
    assert lancamentos.verificar_lancamentos("1") == []


def test_lancou_e_ficou_gratis_no_mesmo_dia_gera_dois_avisos(monkeypatch):
    _estado(HOJE, lembretes=[30, 7, 1, 0])
    _loja(monkeypatch, {10: _detalhes(HOJE, coming_soon=False, is_free=True)})
    eventos = lancamentos.verificar_lancamentos("1")
    assert any("Hoje foi lançado" in e for e in eventos)
    assert any("Free to Play" in e for e in eventos)


def test_saiu_do_acesso_antecipado(monkeypatch):
    _estado(HOJE - timedelta(days=300), coming_soon=False, early_access=True)
    _loja(monkeypatch, {10: _detalhes(HOJE - timedelta(days=300), coming_soon=False)})
    eventos = lancamentos.verificar_lancamentos("1")
    assert len(eventos) == 1 and "Acesso Antecipado" in eventos[0]


def test_saiu_da_wishlist_sai_do_estado(monkeypatch):
    _estado(HOJE + timedelta(days=40))
    _loja(monkeypatch, {11: _detalhes(HOJE + timedelta(days=40))})
    lancamentos.verificar_lancamentos("1")
    assert set(lancamentos._carregar_estado()) == {"11"}


def test_fila_so_perde_aviso_confirmado(monkeypatch):
    monkeypatch.setattr(lancamentos, "verificar_lancamentos", lambda: ["A", "B"])
    lancamentos._executar_varredura()
    status = lancamentos.obter_status_varredura()
    assert [e["texto"] for e in status["eventos"]] == ["A", "B"]
    assert status["ultima_varredura_concluida"] == HOJE.isoformat()
    lancamentos.confirmar_eventos([status["eventos"][0]["id"]])
    assert [e["texto"] for e in lancamentos.obter_status_varredura()["eventos"]] == ["B"]


def test_varredura_com_erro_nao_marca_o_dia(monkeypatch):
    def quebra():
        raise RuntimeError("loja fora do ar")
    monkeypatch.setattr(lancamentos, "verificar_lancamentos", quebra)
    lancamentos._executar_varredura()
    status = lancamentos.obter_status_varredura()
    assert status["ultima_varredura_concluida"] is None
    assert status["ultimo_erro"] == "loja fora do ar"
