# -*- coding: utf-8 -*-
"""Lista configurável de "família" - membros da Steam que o usuário quer que
`atividade.py` destaque na atividade de amigos (compra/conquista/anúncio),
em vez de tratar todo mundo do feed igual (pedido do usuário, 2026-09-01:
"quero receber principalmente qnd alguem da familia compra algo novo").

Cadastro é por LINK do perfil (ou vanity/steamid crus), não por accountid -
o usuário não sabe de cabeça o accountid de ninguém, só o link. Resolvido
pra SteamID64 via API oficial (ResolveVanityURL, se for link customizado) e
convertido pra accountid (32 bits baixos) na hora de salvar, que é o mesmo
identificador que a página de atividade expõe em `data-miniprofile` (ver
`atividade.py::_extrair_eventos`) - permite comparar sem chamada de rede a
cada evento.
"""
import os
import re
import json
import requests

ARQUIVO_FAMILIA = "data/familia.json"
# 🔥 SteamID64 = accountid + esse offset fixo (base do universo público "1"
# nos SteamID de 64 bits) - conversão padrão, não é mágica nem heurística.
_OFFSET_STEAMID64 = 76561197960265728


def _extrair_identificador(perfil_ou_id):
    """Aceita URL completa ('.../id/apelido', '.../profiles/765...'), ou só
    o vanity/steamid cru (sem URL) - devolve (tipo, valor)."""
    texto = perfil_ou_id.strip().rstrip("/")
    m = re.search(r"steamcommunity\.com/profiles/(\d+)", texto)
    if m:
        return "steamid", m.group(1)
    m = re.search(r"steamcommunity\.com/id/([^/?]+)", texto)
    if m:
        return "vanity", m.group(1)
    if texto.isdigit():
        return "steamid", texto
    return "vanity", texto


def _resolver_steamid64(perfil_ou_id):
    tipo, valor = _extrair_identificador(perfil_ou_id)
    if tipo == "steamid":
        return valor
    chave = os.getenv("STEAM_WEBAPI_KEY")
    if not chave:
        return None
    try:
        resp = requests.get(
            "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
            params={"key": chave, "vanityurl": valor}, timeout=15,
        )
        dados = resp.json().get("response", {})
        return dados.get("steamid") if dados.get("success") == 1 else None
    except Exception:
        return None


def _obter_nome_exibicao(steamid64):
    """Nome atual pra mostrar na lista do Painel - só cosmético, a
    comparação de eventos usa accountid, nunca o nome (que pode mudar)."""
    chave = os.getenv("STEAM_WEBAPI_KEY")
    if not chave:
        return steamid64
    try:
        resp = requests.get(
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": chave, "steamids": steamid64}, timeout=15,
        )
        jogadores = resp.json().get("response", {}).get("players", [])
        return jogadores[0]["personaname"] if jogadores else steamid64
    except Exception:
        return steamid64


def _accountid_de(steamid64):
    return str(int(steamid64) - _OFFSET_STEAMID64)


def _carregar():
    if not os.path.exists(ARQUIVO_FAMILIA):
        return []
    try:
        with open(ARQUIVO_FAMILIA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _salvar(lista):
    os.makedirs(os.path.dirname(ARQUIVO_FAMILIA), exist_ok=True)
    with open(ARQUIVO_FAMILIA, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)


def listar_familia():
    return _carregar()


def adicionar_familia(perfil_ou_id):
    if not perfil_ou_id or not perfil_ou_id.strip():
        return {"erro": "Cole o link do perfil Steam da pessoa."}
    steamid64 = _resolver_steamid64(perfil_ou_id)
    if not steamid64:
        return {"erro": "Não consegui resolver esse link/perfil da Steam (confira o link ou a STEAM_WEBAPI_KEY)."}
    accountid = _accountid_de(steamid64)
    lista = _carregar()
    if any(item["accountid"] == accountid for item in lista):
        return {"erro": "Essa pessoa já está na lista de família."}
    entrada = {"steamid64": steamid64, "accountid": accountid, "nome": _obter_nome_exibicao(steamid64)}
    lista.append(entrada)
    _salvar(lista)
    return entrada


def remover_familia(accountid):
    lista = [item for item in _carregar() if item["accountid"] != str(accountid)]
    _salvar(lista)


def accountids_familia():
    """Set de accountids (string) - usado por `atividade.py` pra marcar cada
    evento como `familia`, sem essa lógica saber nada de resolução de perfil."""
    return {item["accountid"] for item in _carregar()}
