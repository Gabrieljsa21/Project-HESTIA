# -*- coding: utf-8 -*-
"""Assistente de Lançamentos da Steam - monitora a WISHLIST do usuário (não o feed de
atividade, ver atividade.py) e avisa proativamente quando algo relevante acontece:
lançamento do dia, saída de Acesso Antecipado (1.0), virou Free to Play, DLC nova
anunciada, e lembretes antecipados (30/7/1 dias antes do lançamento).

Extraído de `Project G.A.I.A/assistant/features/game_releases/
steam_lancamentos.py` (2026-08-24, ver ARQUITETURA.md) - lógica 100%
idêntica, só a sincronização com o Google Calendar mudou de uma chamada
Python direta pra um webhook (`hestia.integrations.gaia_webhook`), já que o
HESTIA roda em processo separado e não tem (nem deveria ter) credencial
própria do Google.

Usa só APIs OFICIAIS e SEM CHAVE (testado, 2026-07-21):
- IWishlistService/GetWishlist/v1 - lista de appids da wishlist, só com steamid.
- store.steampowered.com/api/appdetails - nome, data de lançamento, se é grátis, se
  está em Acesso Antecipado ("Acesso Antecipado" aparece em `genres`, confirmado com um
  item real da wishlist), lista de DLCs.

Diferente de atividade.py (que raspa uma página autenticada, mais frágil), isso não
depende de sessão/cookie - só do STEAM_ID64 do usuário. Rate limit do appdetails é
severo (por isso o intervalo de 1.5s entre chamadas) - com ~180 itens na wishlist, uma
checagem completa leva alguns minutos, por isso é rodada 1x por dia (a GAIA decide
quando, ver `GET /lancamentos/verificar` em hestia/api_bridge.py), não em loop curto
como o resto do monitoramento.
"""

import os
import json
import time
import requests
from datetime import date

import hestia.integrations.gaia_webhook as gaia_webhook

ARQUIVO_ESTADO = "data/lancamentos_estado.json"
INTERVALO_ENTRE_CHAMADAS_SEGUNDOS = 1.5
BRACKETS_LEMBRETE_DIAS = [30, 7, 1]

_MESES_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def _parse_data_steam(texto):
    """'27 jul. 2026' -> date(2026, 7, 27). None se não conseguir (data "TBA", vazia,
    formato inesperado) - lembrete/comparação de data simplesmente não roda pra esse
    item, não trava o resto da checagem."""
    if not texto:
        return None
    partes = texto.replace(".", "").lower().split()
    if len(partes) != 3:
        return None
    try:
        dia = int(partes[0])
        mes = _MESES_PT.get(partes[1][:3])
        ano = int(partes[2])
        if not mes:
            return None
        return date(ano, mes, dia)
    except (ValueError, IndexError):
        return None


def obter_steamid():
    return os.getenv("STEAM_ID64") or _extrair_steamid_da_sessao()


def _extrair_steamid_da_sessao():
    """Fallback: extrai o steamid64 de dentro da página autenticada (g_steamID), caso
    STEAM_ID64 não esteja configurado explicitamente no .env - reaproveita a mesma
    sessão (STEAM_LOGIN_SECURE) já usada por atividade.py, pra não pedir mais uma
    credencial só pra isso."""
    cookie = os.getenv("STEAM_LOGIN_SECURE")
    url = os.getenv("STEAM_PERFIL_URL")
    if not cookie or not url:
        return None
    try:
        import re
        resp = requests.get(url, cookies={"steamLoginSecure": cookie}, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        m = re.search(r'g_steamID\s*=\s*"(\d+)"', resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


def obter_wishlist_appids(steamid):
    resp = requests.get(
        f"https://api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid={steamid}",
        headers={"User-Agent": "Mozilla/5.0"}, timeout=15,
    )
    if resp.status_code != 200:
        return []
    itens = resp.json().get("response", {}).get("items", [])
    return [it["appid"] for it in itens]


def obter_detalhes_app(appid):
    """Devolve {nome, coming_soon, data (date|None), is_free, early_access, dlc} do
    appid, ou None se a busca falhar/o app não existir mais (removido da loja etc.)."""
    try:
        resp = requests.get(
            f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=br&l=portuguese",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15,
        )
        dados = resp.json().get(str(appid), {})
        if not dados.get("success"):
            return None
        info = dados["data"]
        release = info.get("release_date", {})
        genres = [g.get("description", "") for g in info.get("genres", [])]
        return {
            "nome": info.get("name", f"appid {appid}"),
            "coming_soon": bool(release.get("coming_soon")),
            "data": _parse_data_steam(release.get("date", "")),
            "is_free": bool(info.get("is_free")),
            "early_access": "Acesso Antecipado" in genres,
            # 🔥 "type" da appdetails - "game"/"dlc"/"demo"/etc. Junto com early_access,
            # é o máximo de granularidade que a Steam expõe publicamente - NÃO existe um
            # campo oficial pra "alpha" (só early_access mesmo) - ver _rotulo_lancamento.
            "tipo": info.get("type", "game"),
            "dlc": info.get("dlc", []),
        }
    except Exception:
        return None


def _carregar_estado():
    if not os.path.exists(ARQUIVO_ESTADO):
        return {}
    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _salvar_estado(estado):
    os.makedirs(os.path.dirname(ARQUIVO_ESTADO), exist_ok=True)
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


ARQUIVO_CHECAGEM_DIARIA = "data/lancamentos_checagem_diaria.json"


def obter_ultima_checagem_diaria():
    """Data ("AAAA-MM-DD") da última vez que verificar_lancamentos() rodou de
    verdade - persistido em DISCO (2026-07-25, pedido do usuário), não só em memória,
    pra sobreviver a reinícios. Sem isso, se o processo ficasse desligado durante a
    hora configurada (a GAIA decide isso, ver `GET/POST /ultima_checagem_diaria` em
    hestia/api_bridge.py) e fosse ligado de novo só depois, o catch-up nunca disparava."""
    if not os.path.exists(ARQUIVO_CHECAGEM_DIARIA):
        return None
    try:
        with open(ARQUIVO_CHECAGEM_DIARIA, "r", encoding="utf-8") as f:
            return json.load(f).get("ultima_data")
    except Exception:
        return None


def salvar_ultima_checagem_diaria(data_str):
    os.makedirs(os.path.dirname(ARQUIVO_CHECAGEM_DIARIA), exist_ok=True)
    with open(ARQUIVO_CHECAGEM_DIARIA, "w", encoding="utf-8") as f:
        json.dump({"ultima_data": data_str}, f, ensure_ascii=False, indent=2)


def verificar_lancamentos(steamid=None):
    """Percorre a wishlist inteira (uma chamada appdetails por item, com pausa entre
    cada - demora alguns minutos com muitos itens) e devolve a lista de eventos NOVOS
    (textos prontos pra notificar) desde a última checagem. Primeira vez que vê um
    appid: só grava o estado base, nunca notifica de algo que "já era" antes do
    HESTIA existir saber disso (mesmo raciocínio de atividade.py)."""
    steamid = steamid or obter_steamid()
    if not steamid:
        return []

    appids_atuais = set(obter_wishlist_appids(steamid))
    if not appids_atuais:
        return []

    estado = _carregar_estado()
    eventos = []

    for appid_int in appids_atuais:
        appid = str(appid_int)
        detalhes = obter_detalhes_app(appid_int)
        time.sleep(INTERVALO_ENTRE_CHAMADAS_SEGUNDOS)
        if detalhes is None:
            continue

        anterior = estado.get(appid)
        nome = detalhes["nome"]
        data_iso = detalhes["data"].isoformat() if detalhes["data"] else None
        # 🔥 Link da loja (2026-07-29, pedido do usuário) - o appid já é conhecido aqui
        # sem precisar de outra chamada de API, mesma fórmula que já era usada só pro
        # evento do Google Calendar (ver sincronizar_evento_lancamento abaixo); agora
        # também vai anexado em toda notificação (log/voz/Discord), não só na agenda.
        link_steam = f"https://store.steampowered.com/app/{appid}"

        # 🔥 Só toca a agenda (webhook pra GAIA) se algo relevante mudou desde a última
        # sincronização (jogo novo, ou data/coming_soon diferente do que já está marcado
        # como "agendado") - evita reprocessar/re-enviar o mesmo evento todo dia pra
        # ~180 jogos quando nada mudou. O próprio `anterior` (data/coming_soon já
        # registrados) serve de "snapshot da última sincronização" - não precisa de um
        # campo redundante pra isso, só do flag `agendado_calendario` pra saber se
        # aquele snapshot já foi de fato espelhado no calendário (e não só salvo no
        # estado local).
        ja_agendado_com_esses_dados = (
            anterior is not None
            and anterior.get("agendado_calendario")
            and anterior.get("data") == data_iso
            and anterior.get("coming_soon") == detalhes["coming_soon"]
        )
        if detalhes["coming_soon"] and detalhes["data"]:
            if ja_agendado_com_esses_dados:
                agendado_calendario = True
            else:
                agendado_calendario = gaia_webhook.sincronizar_evento_lancamento(appid, nome, detalhes["data"], link_steam)
        else:
            agendado_calendario = False

        if anterior is None:
            estado[appid] = {
                "nome": nome,
                "coming_soon": detalhes["coming_soon"],
                "data": data_iso,
                "is_free": detalhes["is_free"],
                "early_access": detalhes["early_access"],
                "tipo": detalhes["tipo"],
                "dlc": detalhes["dlc"],
                "lembretes_enviados": [],
                "agendado_calendario": agendado_calendario,
            }
        else:
            if anterior.get("coming_soon") and not detalhes["coming_soon"]:
                eventos.append(f"🎮 Hoje foi lançado {nome}, que está na sua lista de desejos da Steam!\n{link_steam}")
                # 🔥 Lançou de vez - o evento de "data futura" não faz mais sentido no
                # calendário (já não é mais coming_soon, então não caiu no if acima).
                gaia_webhook.remover_evento_lancamento(appid)
                agendado_calendario = False
            elif not anterior.get("is_free") and detalhes["is_free"]:
                eventos.append(f"🎮 {nome} (da sua wishlist) agora é Free to Play!\n{link_steam}")
            elif anterior.get("early_access") and not detalhes["early_access"] and not detalhes["coming_soon"]:
                eventos.append(f"🎮 {nome} (da sua wishlist) saiu do Acesso Antecipado - versão 1.0 lançada!\n{link_steam}")
            elif detalhes["coming_soon"] and detalhes["data"]:
                dias_restantes = (detalhes["data"] - date.today()).days
                ja_notificado = anterior.get("lembretes_enviados", [])
                # 🔥 Marca TODAS as faixas já cruzadas de uma vez (não só a mais
                # próxima) - se a distância já satisfaz duas faixas ao mesmo tempo (ex.:
                # 5 dias satisfaz tanto "30 dias" quanto "7 dias", já que 5 <= 30 E 5 <=
                # 7), marcar só uma deixava a outra "pendente" pra disparar de novo na
                # próxima checagem mesmo sem nada ter mudado (bug real, confirmado num
                # teste isolado - o mesmo lembrete repetia sem motivo).
                cruzadas = [b for b in BRACKETS_LEMBRETE_DIAS if 0 <= dias_restantes <= b and b not in ja_notificado]
                if cruzadas:
                    if dias_restantes == 0:
                        eventos.append(f"🎮 {nome} (sua wishlist) lança HOJE!\n{link_steam}")
                    else:
                        eventos.append(f"🎮 Faltam {dias_restantes} dia(s) pro lançamento de {nome}, que está na sua wishlist.\n{link_steam}")
                    ja_notificado.extend(cruzadas)
                anterior["lembretes_enviados"] = ja_notificado

            dlc_novas = set(detalhes["dlc"]) - set(anterior.get("dlc", []))
            if dlc_novas:
                eventos.append(f"🎮 {nome} (sua wishlist) recebeu {len(dlc_novas)} DLC nova(s) anunciada(s).\n{link_steam}")

            estado[appid] = {
                "nome": nome,
                "coming_soon": detalhes["coming_soon"],
                "data": data_iso,
                "is_free": detalhes["is_free"],
                "early_access": detalhes["early_access"],
                "tipo": detalhes["tipo"],
                "dlc": detalhes["dlc"],
                "lembretes_enviados": anterior.get("lembretes_enviados", []),
                "agendado_calendario": agendado_calendario,
            }

    # 🔥 Remove do estado quem saiu da wishlist (spec: "jogos removidos da wishlist") -
    # não precisa notificar a remoção em si, só parar de rastrear (senão o arquivo
    # cresce pra sempre e um item removido/re-adicionado depois vira "falso antigo") e
    # tirar o evento do calendário (senão fica um "lançamento" de um jogo que o usuário
    # nem quer mais acompanhar).
    for appid_guardado in list(estado.keys()):
        if int(appid_guardado) not in appids_atuais:
            gaia_webhook.remover_evento_lancamento(appid_guardado)
            del estado[appid_guardado]

    _salvar_estado(estado)
    return eventos


def _rotulo_lancamento(item):
    """Rótulo do TIPO de lançamento - o máximo de granularidade que a Steam expõe
    publicamente é isso: Demo (type == "demo"), Acesso Antecipado (genre "Acesso
    Antecipado") ou Lançamento oficial (nem um nem outro). NÃO existe um campo oficial
    pra "alpha"/"beta" separado - jogos nessas fases aparecem como Acesso Antecipado ou
    simplesmente "em breve" sem mais detalhe, a Steam não distingue isso."""
    if item.get("tipo") == "demo":
        return "Demo"
    if item.get("early_access"):
        return "Acesso Antecipado"
    return "Lançamento oficial"


def obter_proximos_lancamentos(limite=10):
    """Lê o CACHE local (data/lancamentos_estado.json) - não refaz a
    varredura da wishlist (que leva minutos) - e devolve os `limite` jogos ainda não
    lançados mais próximos, ordenados por data. Usado pela tag <LANCAMENTOS> (pedido
    explícito, "quais os próximos lançamentos da minha wishlist") - sem isso, a LLM não
    tinha NENHUMA forma de responder isso com dados reais e caía pra busca genérica no
    Google, inventando nomes de jogo que não existem (confirmado numa conversa real).
    Lista vazia se o cache ainda não existir (nenhuma checagem automática rodou ainda)."""
    estado = _carregar_estado()
    itens = [
        {"nome": v["nome"], "data": v["data"], "tipo_lancamento": _rotulo_lancamento(v)}
        for v in estado.values()
        if v.get("coming_soon") and v.get("data")
    ]
    itens.sort(key=lambda i: i["data"])
    return itens[:limite]


def formatar_tabela_lancamentos(itens):
    """Monta a tabela JÁ ALINHADA de verdade (largura de coluna calculada com
    len() real, não "no olho") - LLM é péssima em alinhar colunas de texto
    manualmente (confirmado numa conversa real: cada linha saía com o "|" em
    lugar diferente). A tag <LANCAMENTOS> (GAIA, core/tools/handlers.py) pede pra LLM
    só COPIAR esse bloco, não reformatar - o trabalho de alinhar já foi feito aqui."""
    if not itens:
        return ""
    cabecalho = ["Jogo", "Data", "Tipo"]
    linhas = [[i["nome"], i["data"], i["tipo_lancamento"]] for i in itens]
    larguras = [
        max(len(cabecalho[c]), max((len(linha[c]) for linha in linhas), default=0))
        for c in range(3)
    ]

    def _linha(campos):
        return " | ".join(campo.ljust(larguras[c]) for c, campo in enumerate(campos))

    separador = "-|-".join("-" * larguras[c] for c in range(3))
    texto = _linha(cabecalho) + "\n" + separador
    for linha in linhas:
        texto += "\n" + _linha(linha)
    return texto
