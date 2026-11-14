# -*- coding: utf-8 -*-
"""Capturas de tela da conta na Steam Cloud (2026-11-14, HESTIA 0.11.0).

Divisão combinada com o usuário: a HESTIA é a única que fala com a conta da
Steam (tem o login por QR), então ela só lista, entrega a URL e apaga, sem
decidir nada. Quem compara com a biblioteca local, baixa, mostra e pede
confirmação é a CLIO (`E:\\Fotos\\Steam`), que chama estas funções pela ponte
HTTP (`/capturas/nuvem`).

- Lista: a página "Capturas" do perfil, logada (`browsefilter=myfiles`, 50
  por página, mais novas primeiro), dá os ids e o total ("Showing 1 - 50 of
  N"); os detalhes vêm de `IPublishedFileService/GetDetails` (jogo, nome
  original do arquivo no PC, tamanho e a URL do original, que abre sem
  login e é idêntica byte a byte).
- Apagar: o mesmo formulário da página em modo de gerenciamento
  (`screenshotsaction`, `action=delete`), cujo aviso diz que apaga da Steam
  Cloud. Depois confere no `GetDetails` se cada uma sumiu. Nunca toca nos
  arquivos do PC."""
import os
import re
import secrets
import time
from datetime import datetime

import requests

from hestia.armazenamento import ler_json
from hestia.core import sessao_steam

POR_PAGINA = 50
MAX_APAGAR_POR_CHAMADA = 50
TENTATIVAS_PAGINA = 3
URL_PAGINA = "https://steamcommunity.com/profiles/{steamid}/screenshots/"
URL_ACAO = "https://steamcommunity.com/profiles/{steamid}/screenshotsaction"
URL_DETALHES = "https://api.steampowered.com/IPublishedFileService/GetDetails/v1/"
CABECALHOS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
VISIBILIDADE = {0: "publica", 1: "amigos", 2: "privada", 3: "nao_listada"}
RESULTADO_OK = 1

_RE_TOTAL = re.compile(r"Showing\s+[\d,.]+\s*-\s*[\d,.]+\s+of\s+([\d,.]+)")
_RE_ID = re.compile(r'data-publishedfileid="(\d+)"')


class SemSessao(Exception):
    """Login por QR ausente ou vencido."""


def _steamid():
    return os.getenv("STEAM_ID64") or (ler_json(sessao_steam.ARQUIVO, {}) or {}).get("steamid")


def _sessao():
    cookie = sessao_steam.obter_cookie()
    steamid = _steamid()
    if not cookie or not steamid:
        raise SemSessao("Entre com o QR na tela Steam da GAIA.")
    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    sessao.cookies.set("steamLoginSecure", cookie, domain="steamcommunity.com")
    sessao.cookies.set("sessionid", secrets.token_hex(12), domain="steamcommunity.com")
    return sessao, steamid


def _ids_da_pagina(sessao, steamid, pagina):
    """(ids, total). A página às vezes volta sem a grade (resposta curta, sem
    erro), então tenta de novo antes de desistir."""
    for tentativa in range(TENTATIVAS_PAGINA):
        resp = sessao.get(URL_PAGINA.format(steamid=steamid), params={
            "appid": 0, "sort": "newestfirst", "browsefilter": "myfiles", "view": "grid", "p": pagina, "l": "english",
        }, timeout=30)
        html = resp.text
        if 'g_steamID = "' not in html:
            raise SemSessao("A Steam devolveu a página de login.")
        total = _RE_TOTAL.search(html)
        ids = list(dict.fromkeys(_RE_ID.findall(html)))
        if total:
            return ids, int(re.sub(r"\D", "", total.group(1)))
        if "no screenshots" in html.lower() or "nenhuma captura" in html.lower():
            return [], 0
        time.sleep(1 + tentativa)
    raise RuntimeError(f"A página {pagina} das capturas veio sem a grade.")


def _detalhes(ids):
    """{id: detalhes do GetDetails}."""
    if not ids:
        return {}
    params = {"key": os.getenv("STEAM_WEBAPI_KEY"), "itemcount": len(ids)}
    for i, pid in enumerate(ids):
        params[f"publishedfileids[{i}]"] = pid
    resp = requests.get(URL_DETALHES, params=params, timeout=30)
    resp.raise_for_status()
    return {str(d.get("publishedfileid")): d for d in resp.json().get("response", {}).get("publishedfiledetails", [])}


def _item(pid, d):
    caminho = d.get("filename") or ""
    criado = d.get("time_created")
    return {
        "id": pid,
        "appid": d.get("consumer_appid"),
        "jogo": d.get("app_name"),
        "caminho_original": caminho,
        "nome_arquivo": caminho.rsplit("/", 1)[-1] if caminho else None,
        "enviada_em": datetime.fromtimestamp(criado).isoformat(timespec="seconds") if criado else None,
        "largura": d.get("image_width"),
        "altura": d.get("image_height"),
        "bytes": int(d["file_size"]) if d.get("file_size") else None,
        "url": d.get("file_url"),
        "visibilidade": VISIBILIDADE.get(d.get("visibility"), str(d.get("visibility"))),
    }


def listar(pagina=1):
    """Uma página (50) das capturas na nuvem, mais novas primeiro."""
    pagina = max(1, int(pagina))
    sessao, steamid = _sessao()
    ids, total = _ids_da_pagina(sessao, steamid, pagina)
    detalhes = _detalhes(ids)
    itens = [_item(pid, detalhes[pid]) for pid in ids if detalhes.get(pid, {}).get("result") == RESULTADO_OK]
    return {"total": total, "pagina": pagina, "paginas": max(1, -(-total // POR_PAGINA)), "itens": itens}


def apagar(ids):
    """Apaga da Steam Cloud e confere uma a uma. Só ids numéricos, no máximo
    `MAX_APAGAR_POR_CHAMADA` por vez."""
    ids = [str(i) for i in (ids or [])]
    if not ids:
        return {"apagadas": [], "falhas": []}
    if len(ids) > MAX_APAGAR_POR_CHAMADA:
        raise ValueError(f"No máximo {MAX_APAGAR_POR_CHAMADA} por chamada.")
    invalidos = [i for i in ids if not i.isdigit()]
    if invalidos:
        raise ValueError(f"Ids inválidos: {', '.join(invalidos[:5])}")
    sessao, steamid = _sessao()
    sessionid = sessao.cookies.get("sessionid", domain="steamcommunity.com")
    dados = {"action": "delete", "sessionid": sessionid}
    dados.update({f"screenshots[{i}]": "on" for i in ids})
    resp = sessao.post(URL_ACAO.format(steamid=steamid), data=dados, timeout=60, headers={
        "Origin": "https://steamcommunity.com",
        "Referer": URL_PAGINA.format(steamid=steamid),
    })
    detalhes = _detalhes(ids)
    apagadas, falhas = [], []
    for pid in ids:
        if detalhes.get(pid, {}).get("result") == RESULTADO_OK:
            falhas.append({"id": pid, "motivo": f"continua na nuvem (HTTP {resp.status_code})"})
        else:
            apagadas.append(pid)
    if apagadas:
        print(f" [SISTEMA] Capturas apagadas da Steam Cloud: {len(apagadas)}.")
    return {"apagadas": apagadas, "falhas": falhas}
