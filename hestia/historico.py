# -*- coding: utf-8 -*-
"""Histórico dos avisos que o HESTIA já entregou (lançamentos confirmados
pela GAIA e novidades de atividade), para a tela Steam do Painel da GAIA
mostrar o que passou. Guarda os `MAX_ITENS` mais recentes."""
import threading
from datetime import datetime

from hestia.armazenamento import ler_json, gravar_json

ARQUIVO = "data/historico_avisos.json"
MAX_ITENS = 300

_lock = threading.Lock()


def registrar(categoria, itens):
    """`itens`: dicts com `texto` e, opcionais, `familia`, `link` e `tipo`
    (o da atividade, 0.9.0; a GAIA filtra a aba Avisos por ele)."""
    if not itens:
        return
    agora = datetime.now().isoformat(timespec="seconds")
    with _lock:
        historico = ler_json(ARQUIVO, [])
        for item in itens:
            historico.append({
                "categoria": categoria,
                "texto": item.get("texto", ""),
                "familia": bool(item.get("familia")),
                "link": item.get("link"),
                "tipo": item.get("tipo"),
                "em": item.get("em") or agora,
            })
        gravar_json(ARQUIVO, historico[-MAX_ITENS:])


def listar(limite=50, categoria=None):
    """Mais recentes primeiro."""
    with _lock:
        historico = ler_json(ARQUIVO, [])
    if categoria:
        historico = [h for h in historico if h.get("categoria") == categoria]
    return list(reversed(historico))[:limite]
