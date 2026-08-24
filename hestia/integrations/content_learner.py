# -*- coding: utf-8 -*-
"""Cópia mínima de `Project G.A.I.A/assistant/integrations/search/content_learner.py`
(2026-08-24) - módulo compartilhado com `<APRENDER:url>`/`<PESQUISAR:>` na GAIA, então
não pôde ser MOVIDO (continua lá pro outro consumidor), só copiado aqui pro único uso
do HESTIA (`hestia/core/conquistas.py::_enriquecer_com_pagina_completa`, buscar o
texto completo de um guia de conquista já validado)."""
import re

import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

LIMITE_CARACTERES = 8000  # evita mandar um artigo gigante inteiro pro resumidor


def _extrair_id_youtube(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _obter_transcricao_youtube(video_id):
    try:
        transcritor = YouTubeTranscriptApi()
        lista = transcritor.list(video_id)
        try:
            transcricao = lista.find_transcript(["pt", "pt-BR"]).fetch()
        except Exception:
            transcricao = lista.find_transcript(list({t.language_code for t in lista})).fetch()
        return " ".join(trecho.text for trecho in transcricao)
    except Exception:
        return None


def _obter_texto_pagina(url):
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        sopa = BeautifulSoup(resp.text, "html.parser")
        for tag in sopa(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        texto = " ".join(sopa.get_text(separator=" ").split())
        return texto or None
    except Exception:
        return None


def obter_conteudo_url(url):
    """Devolve o texto (transcrição ou artigo) da URL, truncado, ou None se falhar."""
    video_id = _extrair_id_youtube(url)
    conteudo = _obter_transcricao_youtube(video_id) if video_id else _obter_texto_pagina(url)
    if not conteudo:
        return None
    return conteudo[:LIMITE_CARACTERES]
