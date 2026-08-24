# -*- coding: utf-8 -*-
"""Cópia mínima de `Project G.A.I.A/assistant/integrations/search/search_ddg.py`
(2026-08-24) - módulo compartilhado com Jornalista/`<PESQUISAR:>` na GAIA, então
não pôde ser MOVIDO (continua lá pros outros consumidores), só copiado aqui pro
único uso do HESTIA (`hestia/core/conquistas.py::buscar_guia_conquista`)."""
import json
import os
from ddgs import DDGS

HISTORY_PATH = os.path.join("cache", "busca_ddg", "pesquisa_ddg.json")
LINKS_PATH = os.path.join("cache", "busca_ddg", "pesquisa_links.json")


def limpar_cache_de_pesquisa():
    """Deleta os arquivos de cache toda vez que o HESTIA reinicia."""
    for path in [HISTORY_PATH, LINKS_PATH]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


limpar_cache_de_pesquisa()


def load_history():
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(data):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_links(query, links):
    os.makedirs(os.path.dirname(LINKS_PATH), exist_ok=True)
    all_links = {}
    if os.path.exists(LINKS_PATH):
        try:
            with open(LINKS_PATH, "r", encoding="utf-8") as f:
                all_links = json.load(f)
        except Exception:
            pass
    all_links[query] = links
    with open(LINKS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_links, f, indent=2, ensure_ascii=False)


def search_ddg(query, retornar_detalhes=False):
    """retornar_detalhes=True devolve (resposta, resultados) em vez de só a resposta -
    resultados é a lista estruturada [{"titulo", "corpo", "link"}, ...] de cada item,
    pra quem quer VALIDAR qual resultado é relevante (ex.: confirmar que fala do jogo
    certo, não só que bateu algum termo da busca) antes de decidir qual link seguir -
    ver hestia/core/conquistas.py. Em cache hit não recalcula os resultados (não foram
    salvos de novo nessa chamada) - volta lista vazia, quem chamou cai de volta pro
    resumo só."""
    def devolver(resposta, resultados):
        return (resposta, resultados) if retornar_detalhes else resposta

    history = load_history()
    if query in history:
        return devolver(history[query], [])

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="br-pt", max_results=5))

        if not results:
            return devolver("Não achei nada útil... Tenta reformular?", [])

        formatted = []
        links = []
        estruturados = []
        for r in results:
            title = r.get("title", "").strip()
            body = r.get("body", "").strip()
            href = r.get("href", "")
            if title and body:
                formatted.append(f"• {title}: {body[:200]}...")
                estruturados.append({"titulo": title, "corpo": body, "link": href})
            if href:
                links.append(href)

        answer = "\n".join(formatted)
        save_links(query, links)
        history[query] = answer
        save_history(history)
        return devolver(answer, estruturados)

    except Exception:
        return devolver("Busca falhou - internet zuada ou query esquisita. Tenta de novo?", [])
