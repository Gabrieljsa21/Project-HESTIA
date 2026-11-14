# -*- coding: utf-8 -*-
"""Jogos grátis por tempo limitado que o usuário ainda não tem (2026-11-14,
HESTIA 0.10.0, pedido do usuário: "tem como hestia checar os jogos q estao
gratis por tempo limitado e q n tenho?" e "se possivel, ja pega a key").

Duas fontes:

- **Loja da Steam:** busca por desconto de 100% (`maxprice=free&specials=1`).
  Jogo pago que fica grátis para manter. Quando acha um que não está na
  conta, o HESTIA resgata sozinho (`freelicense/addfreelicense/<subid>`), com o
  login por QR, e confere na lista de posse da loja se entrou.
- **GamerPower:** chaves Steam distribuídas por outros sites. Essas não dá
  para resgatar sozinho (cada site pede login, tarefas ou captcha), então
  vão como aviso com o link.

Roda dentro da checagem de atividade (a cada 20 min pela GAIA), mas só
consulta as fontes a cada `INTERVALO_S`; cada oferta nova vira um evento de
tipo "gratis" no mesmo caminho dos avisos de atividade."""
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

import requests

from hestia.armazenamento import ler_json, gravar_json
from hestia.core import sessao_steam

ARQUIVO = "data/gratis_estado.json"
INTERVALO_S = 3 * 3600
MAX_TENTATIVAS_RESGATE = 3
URL_BUSCA = "https://store.steampowered.com/search/results/"
URL_DETALHES = "https://store.steampowered.com/api/appdetails"
URL_PAGINA = "https://store.steampowered.com/app/{appid}/"
URL_RESGATE = "https://store.steampowered.com/freelicense/addfreelicense/{subid}"  # o do botão "Adicionar à conta" (main.js)
URL_POSSE = "https://store.steampowered.com/dynamicstore/userdata/"
URL_GAMERPOWER = "https://www.gamerpower.com/api/giveaways"
URL_MEUS_JOGOS = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
CABECALHOS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
COOKIES_IDADE = {"birthtime": "631152001", "wants_mature_content": "1", "lastagecheckage": "1-0-1990"}

_lock = threading.Lock()


def _resgate_ligado():
    return os.getenv("HESTIA_GRATIS_RESGATAR", "1") != "0"


def _normalizar(nome):
    nome = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", nome).strip()


def _nome_do_sorteio(titulo):
    """'Dwarven Realms (Steam) Key Giveaway' -> 'Dwarven Realms'."""
    titulo = re.sub(r"\((steam|key)\)", "", titulo, flags=re.I)
    titulo = re.sub(r"\b(steam\s+)?(key\s+)?giveaway\b|\bfree\b.*$", "", titulo, flags=re.I)
    return " ".join(titulo.split()).strip(" -:")


# ---------------- o que o usuário já tem ----------------

def _sessao_loja():
    cookie = sessao_steam.obter_cookie(loja=True)
    if not cookie:
        return None
    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    sessao.cookies.set("steamLoginSecure", cookie, domain="store.steampowered.com")
    sessao.cookies.set("sessionid", os.urandom(12).hex(), domain="store.steampowered.com")
    for nome, valor in COOKIES_IDADE.items():
        sessao.cookies.set(nome, valor, domain="store.steampowered.com")
    return sessao


def _posse_na_loja(sessao):
    """(appids, subids) da conta pela loja logada; inclui licenças grátis
    que o GetOwnedGames não lista. None se a sessão não estiver valendo."""
    if sessao is None:
        return None
    dados = sessao.get(URL_POSSE, timeout=20).json()
    apps, subs = dados.get("rgOwnedApps") or [], dados.get("rgOwnedPackages") or []
    if not apps and not subs:
        return None  # resposta de deslogado
    return set(apps), set(subs)


def _nomes_dos_meus_jogos():
    chave = os.getenv("STEAM_WEBAPI_KEY")
    steamid = os.getenv("STEAM_ID64") or (ler_json(sessao_steam.ARQUIVO, {}) or {}).get("steamid")
    if not chave or not steamid:
        return set()
    resp = requests.get(URL_MEUS_JOGOS, params={
        "key": chave, "steamid": steamid, "include_appinfo": 1, "include_played_free_games": 1,
    }, timeout=20)
    jogos = resp.json().get("response", {}).get("games", [])
    return {_normalizar(j.get("name")) for j in jogos}


# ---------------- fontes ----------------

def _ofertas_da_steam():
    """[{appid, nome}] com 100% de desconto agora."""
    resp = requests.get(URL_BUSCA, params={
        "maxprice": "free", "specials": 1, "infinite": 1, "count": 100, "cc": "br", "l": "portuguese",
    }, headers=CABECALHOS, timeout=20)
    html = resp.json().get("results_html", "")
    ofertas = []
    for bloco in html.split('<a href="')[1:]:
        appid = re.search(r'data-ds-appid="(\d+)"', bloco)
        nome = re.search(r'<span class="title">([^<]+)</span>', bloco)
        desconto = re.search(r'data-discount="(\d+)"', bloco)
        if appid and nome and desconto and desconto.group(1) == "100":
            ofertas.append({"appid": int(appid.group(1)), "nome": nome.group(1).strip()})
    return ofertas


def _detalhes_da_oferta(appid):
    """(subid grátis, texto do prazo) pela API e pela página da loja."""
    subid = None
    try:
        dados = requests.get(URL_DETALHES, params={"appids": appid, "cc": "br", "l": "portuguese"},
                             headers=CABECALHOS, timeout=20).json()
        info = (dados.get(str(appid)) or {}).get("data") or {}
        for grupo in info.get("package_groups", []):
            for sub in grupo.get("subs", []):
                if sub.get("price_in_cents_with_discount") == 0:
                    subid = sub.get("packageid")
                    break
            if subid:
                break
    except Exception as e:
        print(f" [SISTEMA] Grátis: falha nos detalhes do app {appid}: {e}")
    prazo = None
    try:
        pagina = requests.get(URL_PAGINA.format(appid=appid), cookies=COOKIES_IDADE, headers=CABECALHOS,
                              params={"l": "portuguese", "cc": "br"}, timeout=20).text
        achado = re.search(r'game_purchase_discount_countdown">([^<]+)<', pagina)
        if achado:
            prazo = " ".join(achado.group(1).split())
        if not subid:
            achado = re.search(r"AddFreeLicense\(\s*(\d+)", pagina)
            subid = int(achado.group(1)) if achado else None
    except Exception as e:
        print(f" [SISTEMA] Grátis: falha na página do app {appid}: {e}")
    return subid, prazo


def _sorteios_gamerpower():
    """[{id, nome, link, ate}] de chaves Steam ativas."""
    resp = requests.get(URL_GAMERPOWER, params={"platform": "steam", "type": "game"}, headers=CABECALHOS, timeout=20)
    if resp.status_code != 200:
        return []
    itens = []
    for g in resp.json() or []:
        if (g.get("status") or "Active").lower() != "active":
            continue
        fim = g.get("end_date")
        itens.append({
            "id": str(g.get("id")),
            "nome": _nome_do_sorteio(g.get("title", "")),
            "link": g.get("open_giveaway_url") or g.get("gamerpower_url"),
            "ate": None if not fim or fim == "N/A" else fim[:10],
        })
    return itens


# ---------------- resgate ----------------

def _resgatar(sessao, subid):
    sessionid = sessao.cookies.get("sessionid", domain="store.steampowered.com")
    resp = sessao.post(URL_RESGATE.format(subid=subid), data={"ajax": "true", "sessionid": sessionid},
                       headers={"Origin": "https://store.steampowered.com", "Referer": "https://store.steampowered.com/"},
                       timeout=20)
    return resp.status_code


# ---------------- ciclo ----------------

def _formatar_prazo(ate):
    if not ate:
        return ""
    try:
        return f" até {datetime.fromisoformat(ate).strftime('%d/%m')}"
    except ValueError:
        return f" ({ate})"


def coletar_eventos(forcar=False):
    """Consulta as fontes (no máximo a cada `INTERVALO_S`, salvo `forcar`),
    resgata o que der e devolve eventos novos no formato da atividade da Web
    API: {tipo: "gratis", autor, alvo, texto, familia, link}. A primeira
    consulta também avisa: oferta grátis vale enquanto durar, não é passado."""
    with _lock:
        estado = ler_json(ARQUIVO, {})
        if not forcar and time.time() - estado.get("consultado_em", 0) < INTERVALO_S:
            return []
        estado["consultado_em"] = time.time()
        gravar_json(ARQUIVO, estado)

    eventos, atuais = [], []
    sessao = _sessao_loja()
    try:
        posse = _posse_na_loja(sessao)
    except Exception as e:
        print(f" [SISTEMA] Grátis: falha ao ler a posse na loja: {e}")
        posse = None
    tentativas = estado.get("tentativas", {})

    try:
        ofertas = _ofertas_da_steam()
    except Exception as e:
        print(f" [SISTEMA] Grátis: falha na busca da loja: {e}")
        ofertas = []
    for oferta in ofertas:
        appid = oferta["appid"]
        if posse and appid in posse[0]:
            continue
        subid, prazo = _detalhes_da_oferta(appid)
        link = f"https://store.steampowered.com/app/{appid}/"
        item = {"origem": "steam", "id": str(appid), "nome": oferta["nome"], "link": link, "prazo": prazo, "resgatado": False}
        resgatado = False
        chave_tentativa = str(subid)
        if subid and posse is not None and _resgate_ligado() and tentativas.get(chave_tentativa, 0) < MAX_TENTATIVAS_RESGATE:
            tentativas[chave_tentativa] = tentativas.get(chave_tentativa, 0) + 1
            try:
                _resgatar(sessao, subid)
                nova = _posse_na_loja(sessao)
                resgatado = bool(nova) and (appid in nova[0] or subid in nova[1])
            except Exception as e:
                print(f" [SISTEMA] Grátis: falha ao resgatar {oferta['nome']}: {e}")
        item["resgatado"] = resgatado
        if resgatado:
            texto = f"{oferta['nome']} estava grátis na Steam e já está na sua conta."
        else:
            texto = f"{oferta['nome']} está grátis na Steam" + (f" ({prazo.lower()})" if prazo else "") + ". Resgate pelo link."
            atuais.append(item)
        eventos.append({"tipo": "gratis", "autor": "steam", "alvo": str(appid), "texto": texto,
                        "familia": False, "link": link})

    try:
        sorteios = _sorteios_gamerpower()
        meus = _nomes_dos_meus_jogos() if sorteios else set()
    except Exception as e:
        print(f" [SISTEMA] Grátis: falha no GamerPower: {e}")
        sorteios, meus = [], set()
    nomes_steam = {_normalizar(o["nome"]) for o in ofertas}
    for s in sorteios:
        nome = _normalizar(s["nome"])
        if nome in meus or nome in nomes_steam:
            continue
        atuais.append({"origem": "gamerpower", "id": s["id"], "nome": s["nome"], "link": s["link"],
                       "prazo": _formatar_prazo(s["ate"]).strip() or None, "resgatado": False})
        eventos.append({"tipo": "gratis", "autor": "gamerpower", "alvo": s["id"],
                        "texto": f"Chave grátis de {s['nome']} na Steam{_formatar_prazo(s['ate'])}. Resgate pelo link.",
                        "familia": False, "link": s["link"]})

    with _lock:
        estado = ler_json(ARQUIVO, {})
        estado.update(atuais=atuais, tentativas=tentativas, atualizado_em=datetime.now().isoformat(timespec="seconds"),
                      sessao_loja=posse is not None)
        gravar_json(ARQUIVO, estado)
    return eventos


def listar():
    """Ofertas da última consulta que ainda não estão na conta."""
    estado = ler_json(ARQUIVO, {})
    return {"itens": estado.get("atuais", []), "atualizado_em": estado.get("atualizado_em"),
            "sessao_loja": estado.get("sessao_loja"), "resgate_automatico": _resgate_ligado()}
