# -*- coding: utf-8 -*-
"""Atividade da Steam pela Web API oficial, sem cookie de login.

A página de atividade (`atividade.py`) depende de `STEAM_LOGIN_SECURE`, que
expira sem aviso. Em 2026-11-13 ela estava devolvendo a tela de login havia
semanas e o usuário não recebia atividade nenhuma. Esta fonte cobre, só com
`STEAM_WEBAPI_KEY` e `STEAM_ID64`, o que mais importa ao usuário:

- **compras de amigos e família**: biblioteca de cada amigo
  (`ISteamUser/GetFriendList`) e de cada pessoa de `familia.py`
  (`IPlayerService/GetOwnedGames`); appid novo desde a última checagem vira
  "Fulano comprou X", com destaque para a família. Exige biblioteca pública
  da pessoa (36 de 42 amigos em 2026-11-13);
- **anúncios dos jogos do usuário**: notícias oficiais
  (`ISteamNews/GetNewsForApp`, feed `steam_community_announcements`) dos
  jogos jogados nas últimas duas semanas.

A lista de amigos só aparece para a API se estiver pública no perfil do
usuário (era privada até 2026-11-13, resposta 401); sem ela, só a família
entra. Primeiras partidas e conquistas de amigos continuam só na página
logada.

A primeira leitura de cada pessoa e de cada jogo só grava a linha de base."""
import os
import threading

import requests

from hestia.armazenamento import ler_json, gravar_json
from hestia.core import familia

ARQUIVO_ESTADO = "data/atividade_api_estado.json"
URL_JOGOS = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
URL_RECENTES = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
URL_NOTICIAS = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
URL_AMIGOS = "https://api.steampowered.com/ISteamUser/GetFriendList/v1/"
URL_RESUMOS = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
# SteamID64 = accountid + este offset (mesmo valor de familia.py).
_OFFSET_STEAMID64 = 76561197960265728
FEED_ANUNCIOS = "steam_community_announcements"
MAX_JOGOS_COM_NOTICIAS = 10
NOTICIAS_POR_JOGO = 3
MAX_ANUNCIOS_GUARDADOS = 500

_lock = threading.Lock()


def configurada():
    return bool(os.getenv("STEAM_WEBAPI_KEY") and os.getenv("STEAM_ID64"))


def _get(url, **params):
    params["key"] = os.getenv("STEAM_WEBAPI_KEY")
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("response", resp.json())


def _jogos_da_pessoa(steamid64):
    """{appid (str): nome} ou None se a biblioteca for privada/indisponível."""
    dados = _get(URL_JOGOS, steamid=steamid64, include_appinfo=1, include_played_free_games=1)
    jogos = dados.get("games")
    if jogos is None:
        return None
    return {str(j["appid"]): j.get("name") or f"appid {j['appid']}" for j in jogos}


def _pessoas_acompanhadas():
    """Família + amigos, sem repetição: [{steamid64, accountid, nome, familia}].
    A lista de amigos só vem se estiver pública no perfil do usuário (401
    quando privada); nesse caso fica só a família."""
    pessoas = {}
    for p in familia.listar_familia():
        pessoas[p["steamid64"]] = {**p, "familia": True}
    try:
        amigos = _get(URL_AMIGOS, steamid=os.getenv("STEAM_ID64"), relationship="friend")
        ids = [a["steamid"] for a in amigos.get("friendslist", {}).get("friends", [])]
    except Exception:
        ids = []  # lista de amigos privada ou API fora do ar
    novos = [i for i in ids if i not in pessoas]
    nomes = {}
    for inicio in range(0, len(novos), 100):
        try:
            resumo = _get(URL_RESUMOS, steamids=",".join(novos[inicio:inicio + 100]))
            nomes.update({j["steamid"]: j.get("personaname") for j in resumo.get("players", [])})
        except Exception:
            pass
    for steamid64 in novos:
        pessoas[steamid64] = {
            "steamid64": steamid64,
            "accountid": str(int(steamid64) - _OFFSET_STEAMID64),
            "nome": nomes.get(steamid64),
            "familia": False,
        }
    return list(pessoas.values())


def _compras_dos_amigos(estado):
    """Appid novo na biblioteca de alguém = compra (ou jogo grátis
    resgatado). Desde 2026-11-13 (0.5.0) cobre todos os amigos, não só a
    família: o usuário deixou a lista de amigos pública."""
    eventos = []
    bibliotecas = estado.setdefault("bibliotecas", {})
    for pessoa in _pessoas_acompanhadas():
        steamid64 = pessoa["steamid64"]
        try:
            jogos = _jogos_da_pessoa(steamid64)
        except Exception as e:
            print(f" [SISTEMA] Biblioteca de {pessoa.get('nome') or steamid64} indisponível na API: {e}")
            continue
        if jogos is None:
            continue  # biblioteca privada
        anteriores = bibliotecas.get(steamid64)
        bibliotecas[steamid64] = sorted(jogos)
        if anteriores is None:
            continue  # primeira leitura: linha de base
        nome = pessoa.get("nome") or ("Alguém da família" if pessoa["familia"] else "Um amigo")
        for appid in sorted(set(jogos) - set(anteriores)):
            eventos.append({
                "tipo": "compra",
                "autor": pessoa["accountid"],
                "alvo": jogos[appid],
                "texto": f"{nome} comprou {jogos[appid]} na Steam.",
                "familia": pessoa["familia"],
                "link": f"https://store.steampowered.com/app/{appid}",
            })
    return eventos


def _anuncios_dos_meus_jogos(estado):
    eventos = []
    vistos = estado.setdefault("anuncios_vistos", [])
    jogos_com_base = set(estado.setdefault("jogos_com_noticias", []))
    try:
        recentes = _get(URL_RECENTES, steamid=os.getenv("STEAM_ID64")).get("games", [])
    except Exception as e:
        print(f" [SISTEMA] Jogos recentes indisponíveis na API: {e}")
        return eventos
    for jogo in recentes[:MAX_JOGOS_COM_NOTICIAS]:
        appid = str(jogo["appid"])
        nome = jogo.get("name") or f"appid {appid}"
        try:
            itens = requests.get(
                URL_NOTICIAS,
                params={"appid": appid, "count": NOTICIAS_POR_JOGO, "feeds": FEED_ANUNCIOS, "maxlength": 280},
                timeout=20,
            ).json().get("appnews", {}).get("newsitems", [])
        except Exception:
            continue
        primeira_vez = appid not in jogos_com_base
        jogos_com_base.add(appid)
        for item in itens:
            gid = str(item.get("gid"))
            if gid in vistos:
                continue
            vistos.append(gid)
            if primeira_vez:
                continue
            titulo = item.get("title") or "novo anúncio"
            texto = f"{nome} publicou um anúncio: {titulo}"
            resumo = " ".join((item.get("contents") or "").split())
            if resumo:
                texto += f" - resumo: {resumo[:280]}..."
            eventos.append({
                "tipo": "anuncio",
                "autor": nome,
                "alvo": titulo,
                "texto": texto,
                "familia": False,
                "link": item.get("url") or f"https://store.steampowered.com/news/app/{appid}",
            })
    estado["anuncios_vistos"] = vistos[-MAX_ANUNCIOS_GUARDADOS:]
    estado["jogos_com_noticias"] = sorted(jogos_com_base)
    return eventos


STEAMID64_BASE = 76561197960265728


def accountids_com_biblioteca():
    """accountids (como no `data-miniprofile` da página) de quem a API já
    acompanha a biblioteca: a compra dessas pessoas vem daqui, com o nome
    certo, e a página não precisa repetir."""
    estado = ler_json(ARQUIVO_ESTADO, {})
    ids = set()
    for steamid64 in estado.get("bibliotecas", {}):
        try:
            ids.add(str(int(steamid64) - STEAMID64_BASE))
        except ValueError:
            continue
    return ids


def coletar_eventos():
    """Eventos novos desde a última chamada (só os da API). Cada evento traz
    `tipo`, `autor` e `alvo` para `atividade.py` montar a chave e evitar
    aviso repetido quando a página logada também mostrar o mesmo fato."""
    if not configurada():
        return []
    with _lock:
        estado = ler_json(ARQUIVO_ESTADO, {})
        eventos = _compras_dos_amigos(estado) + _anuncios_dos_meus_jogos(estado)
        gravar_json(ARQUIVO_ESTADO, estado)
    return eventos
