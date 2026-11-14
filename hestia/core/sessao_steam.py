# -*- coding: utf-8 -*-
"""Login próprio do HESTIA na Steam por QR code (2026-11-13, HESTIA 0.6.0).

Por que existe: a página de atividade precisa de um login, e o caminho
antigo (copiar o cookie `steamLoginSecure` do navegador) parou de funcionar.
Edge, Chrome e Brave passaram a criptografar os cookies com uma chave presa
ao próprio navegador (`app_bound_encrypted_key` no `Local State`), e o
`browser_cookie3` responde "Unable to get key for cookie decryption" mesmo
com o navegador fechado.

Fluxo, o mesmo do QR da tela de login do site da Steam:

1. `iniciar_login_qr` abre uma sessão em
   `IAuthenticationService/BeginAuthSessionViaQR` e devolve o QR em PNG.
2. O usuário escaneia e aprova no app da Steam no celular. Nenhuma senha
   passa pelo HESTIA.
3. Uma thread consulta `PollAuthSessionStatus` até a Steam devolver o
   `refresh_token` (dura meses) e o `access_token` (dura cerca de um dia).
4. `obter_cookie` monta `steamLoginSecure` (`<steamid>%7C%7C<access_token>`)
   e renova o `access_token` pelo fluxo de login web (`_renovar_acesso`)
   quando ele está perto de vencer. O `refresh_token` não muda e vale cerca
   de 200 dias; depois disso é preciso escanear o QR de novo.

Os tokens ficam em `data/sessao_steam.json`, cifrados com DPAPI do Windows
(só esta conta do Windows, nesta máquina, consegue abrir)."""
import base64
import io
import json
import secrets
import threading
import time

import requests
from urllib.parse import unquote

from hestia.armazenamento import ler_json, gravar_json

ARQUIVO = "data/sessao_steam.json"
URL_INICIAR = "https://api.steampowered.com/IAuthenticationService/BeginAuthSessionViaQR/v1/"
URL_CONSULTAR = "https://api.steampowered.com/IAuthenticationService/PollAuthSessionStatus/v1/"
URL_FINALIZAR = "https://login.steampowered.com/jwt/finalizelogin"
PLATAFORMA_NAVEGADOR = 2  # EAuthTokenPlatformType.WebBrowser
NOME_DISPOSITIVO = "HESTIA (GAIA)"
DURACAO_QR_S = 180
MARGEM_RENOVACAO_S = 30 * 60

_lock = threading.Lock()
_login = {"estado": "nenhum"}  # estado do QR em andamento, só em memória


# ---------------- proteção dos tokens ----------------

def _proteger(texto):
    import win32crypt
    return base64.b64encode(win32crypt.CryptProtectData(texto.encode("utf-8"), "HESTIA", None, None, None, 0)).decode()


def _abrir(cifrado):
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(cifrado), None, None, None, 0)[1].decode("utf-8")


def _expiracao_jwt(token):
    """`exp` (epoch) do JWT, ou 0 se não der para ler."""
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return int(json.loads(base64.urlsafe_b64decode(carga)).get("exp", 0))
    except Exception:
        return 0


def _salvar_tokens(steamid, conta, refresh_token, access_token, access_token_loja=None):
    dados = {
        "steamid": steamid,
        "conta": conta,
        "refresh_token": _proteger(refresh_token),
        "access_token": _proteger(access_token),
        "refresh_expira": _expiracao_jwt(refresh_token),
    }
    if access_token_loja:
        dados["access_token_loja"] = _proteger(access_token_loja)
    gravar_json(ARQUIVO, dados)


def _steamid_do_token(token):
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return json.loads(base64.urlsafe_b64decode(carga)).get("sub")
    except Exception:
        return None


# ---------------- QR code ----------------

def _png_do_qr(url):
    import segno
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="png", scale=8, border=2, dark="#0d0d0f", light="#f1efe9")
    return base64.b64encode(buffer.getvalue()).decode()


def _consultar_ate_aprovar(client_id, request_id, intervalo, fim):
    original = client_id  # o `client_id` pode mudar no meio (new_client_id)
    while time.time() < fim:
        time.sleep(intervalo)
        with _lock:
            if _login.get("client_id_original") != original:
                return  # outro QR foi pedido depois deste
        try:
            resp = requests.post(URL_CONSULTAR, data={"client_id": client_id, "request_id": request_id}, timeout=15)
            eresult = resp.headers.get("x-eresult", "1")
            dados = resp.json().get("response", {})
        except Exception as e:
            print(f" [SISTEMA] Login por QR: falha ao consultar a Steam: {e}")
            continue
        if eresult != "1":
            with _lock:
                if _login.get("client_id_original") == original:
                    _login.update(estado="expirado")
            return
        client_id = dados.get("new_client_id") or client_id
        if dados.get("refresh_token"):
            steamid = _steamid_do_token(dados["refresh_token"])
            _salvar_tokens(steamid, dados.get("account_name"), dados["refresh_token"], dados["access_token"])
            with _lock:
                _login.update(estado="aprovado", conta=dados.get("account_name"))
            print(f" [SISTEMA] Login na Steam por QR aprovado (conta {dados.get('account_name')}).")
            return
        if dados.get("had_remote_interaction"):
            with _lock:
                if _login.get("estado") == "aguardando":
                    _login.update(estado="escaneado")
    with _lock:
        if _login.get("client_id_original") == original and _login.get("estado") in ("aguardando", "escaneado"):
            _login.update(estado="expirado")


def iniciar_login_qr():
    """Abre um QR novo (o anterior, se houver, deixa de valer)."""
    resp = requests.post(URL_INICIAR, data={"device_friendly_name": NOME_DISPOSITIVO, "platform_type": PLATAFORMA_NAVEGADOR}, timeout=15)
    resp.raise_for_status()
    dados = resp.json()["response"]
    fim = time.time() + DURACAO_QR_S
    with _lock:
        _login.clear()
        _login.update(estado="aguardando", client_id_original=dados["client_id"], expira=fim)
    threading.Thread(
        target=_consultar_ate_aprovar,
        args=(dados["client_id"], dados["request_id"], max(2, int(dados.get("interval", 5))), fim),
        name="login-qr-steam", daemon=True,
    ).start()
    return {"qr_png": _png_do_qr(dados["challenge_url"]), "url": dados["challenge_url"], "expira_em_s": DURACAO_QR_S}


def status_login_qr():
    with _lock:
        return {"estado": _login.get("estado", "nenhum"), "conta": _login.get("conta")}


# ---------------- uso da sessão ----------------

def situacao():
    dados = ler_json(ARQUIVO, None)
    if not dados:
        return {"conectada": False}
    return {"conectada": True, "conta": dados.get("conta"), "refresh_expira": dados.get("refresh_expira")}


def desconectar():
    with _lock:
        gravar_json(ARQUIVO, {})


DOMINIOS = {"comunidade": "steamcommunity.com", "loja": "store.steampowered.com"}


def _renovar_acesso(refresh_token):
    """Novos `access_token` pelo fluxo de login web da Steam, o mesmo que o
    navegador usa depois do QR: `jwt/finalizelogin` com o `refresh_token`
    como `nonce` e o `settoken` de cada domínio, que devolve o cookie
    `steamLoginSecure` daquele domínio. Cada token só vale no próprio domínio
    (`aud` web:community ou web:store; o da Community na loja aparece como
    deslogado, testado em 2026-11-14). `GenerateAccessTokenForApp` recusa
    token de navegador (eresult 15, AccessDenied; testado em 2026-11-13).
    Devolve {"comunidade": token, "loja": token}, só com os que vieram."""
    sessao = requests.Session()
    resp = sessao.post(URL_FINALIZAR, data={
        "nonce": refresh_token, "sessionid": secrets.token_hex(12),
        "redirect_uri": "https://steamcommunity.com/login/home/?goto=",
    }, headers={"Origin": "https://steamcommunity.com", "Referer": "https://steamcommunity.com/"}, timeout=20)
    dados = resp.json()
    tokens = {}
    for nome, dominio in DOMINIOS.items():
        destino = next((t for t in dados.get("transfer_info", []) if dominio in t.get("url", "")), None)
        if not destino:
            continue
        sessao.post(destino["url"], data={**destino.get("params", {}), "steamID": dados.get("steamID")}, timeout=20)
        cookie = sessao.cookies.get("steamLoginSecure", domain=dominio)
        if cookie:
            tokens[nome] = unquote(cookie).split("||", 1)[1]
    return tokens


def obter_cookie(loja=False):
    """Valor de `steamLoginSecure` do login por QR para a Community (padrão)
    ou para a loja (`loja=True`, usado no resgate de jogos grátis), renovando
    o acesso quando falta menos de `MARGEM_RENOVACAO_S` para vencer. Se a
    renovação falhar, o acesso atual vale até o fim; depois disso volta None
    e é preciso escanear o QR de novo."""
    campo = "access_token_loja" if loja else "access_token"
    with _lock:
        dados = ler_json(ARQUIVO, None)
        if not dados or not dados.get("refresh_token"):
            return None
        try:
            refresh = _abrir(dados["refresh_token"])
            atual = {"comunidade": _abrir(dados["access_token"])}
            if dados.get("access_token_loja"):
                atual["loja"] = _abrir(dados["access_token_loja"])
        except Exception as e:
            print(f" [SISTEMA] Login da Steam ilegível: {e}")
            return None
        nome = "loja" if loja else "comunidade"
        access = atual.get(nome, "")
        if _expiracao_jwt(access) - time.time() < MARGEM_RENOVACAO_S:
            try:
                novos = _renovar_acesso(refresh)
            except Exception as e:
                novos = {}
                print(f" [SISTEMA] Falha ao renovar o login da Steam: {e}")
            if novos.get(nome):
                atual.update(novos)
                access = atual[nome]
                _salvar_tokens(dados["steamid"], dados.get("conta"), refresh, atual["comunidade"], atual.get("loja"))
            elif _expiracao_jwt(access) <= time.time():
                print(f" [SISTEMA] Login da Steam ({campo}) vencido e sem renovação; escaneie o QR de novo.")
                return None
    return f"{dados['steamid']}%7C%7C{access}"
