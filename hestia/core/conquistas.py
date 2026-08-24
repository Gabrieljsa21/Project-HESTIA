# -*- coding: utf-8 -*-
"""Assistente de Conquistas (Steam) - progresso de conquistas de um jogo específico da
Steam do usuário, SOB PEDIDO (tag <CONQUISTAS:jogo>, GAIA - core/tools/handlers.py).
Diferente de atividade.py (feed de atividade de amigos/anúncios) e lancamentos.py
(wishlist) - esse lê CONQUISTAS de um jogo que o usuário já tem, comparando o que já
foi destravado com o que falta.

Extraído de `Project G.A.I.A/assistant/features/achievements/steam_conquistas.py`
(2026-08-24, ver ARQUITETURA.md) - 1 mudança de contrato real: `obter_progresso_
conquistas` recebe SÓ appid numérico agora (`_resolver_appid`, que lia a lista de
jogos escaneados LOCALMENTE nesta máquina via `features/app_launcher/apps_scanner.py`,
ficou do lado da GAIA - dado local-da-máquina não faz sentido virar chamada de rede pro
HESTIA). `nome_conhecido` (opcional) deixa a GAIA repassar o nome já resolvido, pra não
perder qualidade de resposta quando a API da Steam não devolver `gameName`.

Usa duas APIs oficiais da Steam:
- ISteamUserStats/GetPlayerAchievements/v0001 - progresso REAL do usuário (achieved/
  nome/descrição) - precisa de CHAVE (STEAM_WEBAPI_KEY no .env, grátis em
  steamcommunity.com/dev/apikey) + STEAM_ID64, porque expõe dado de conta específica.
  Falha com "Profile is not public" se as estatísticas DESSE JOGO estiverem privadas
  (é um toggle por jogo, separado do perfil geral - dá pra estar público no geral e
  privado só nas estatísticas de um jogo específico).
- ISteamUserStats/GetGlobalAchievementPercentagesForGame/v2 - SEM CHAVE, % de jogadores
  no mundo todo que têm cada conquista - usado só pra destacar quais das que faltam são
  mais raras (não existe campo oficial de "dificuldade" na Steam, isso é o mais perto
  que ela expõe publicamente).

"Como conseguir" uma conquista específica NÃO vem de nenhuma API - a Steam não expõe
isso. A tag <CONQUISTAS> só entrega os DADOS reais (nome/descrição/conseguida/
raridade); o guia em si vem de `buscar_guia_conquista` (tag <GUIA_CONQUISTA>, GAIA),
que pesquisa (hestia/integrations/search_ddg.py) numa cadeia de fontes PRIORIZADAS
(pedido do usuário, 2026-07-25: padronizar em vez de deixar a LLM escolher termo/site
cada vez) - Steam Community Guides (oficial, cobre qualquer jogo com página na Steam)
-> PowerPyx (especialista em guia de conquista/troféu passo a passo) -> GameFAQs (base
comunitária mais antiga e ampla, cobre jogo nichado/antigo que os anteriores não têm)
-> F95zone (referência pra jogos/visual novels adultos, que os 3 anteriores não
cobrem) -> busca livre sem restrição de site, só se as 4 anteriores não acharem nada
útil.
"""

import os
import re
import requests

import hestia.integrations.search_ddg as search_ddg
from hestia.integrations.content_learner import obter_conteudo_url

_FONTES_GUIA_CONQUISTA = [
    ("Steam Community Guides", "site:steamcommunity.com"),
    ("PowerPyx", "site:powerpyx.com"),
    ("GameFAQs", "site:gamefaqs.gamespot.com"),
    ("F95zone", "site:f95zone.to"),
]

# 🔥 search_ddg devolve esses textos fixos quando a busca não achou nada / falhou (ver
# search_ddg.py) - usado pra saber quando pular pra próxima fonte da cadeia, em vez de
# aceitar uma resposta vazia como se fosse um guia de verdade.
_MARCADORES_BUSCA_SEM_RESULTADO = ("não achei nada útil", "busca falhou")

URL_PLAYER_ACHIEVEMENTS = "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
URL_GLOBAL_PERCENTAGES = "https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForGame/v2/"


def _busca_teve_resultado(resultado):
    texto = (resultado or "").strip().lower()
    if not texto:
        return False
    return not any(marcador in texto for marcador in _MARCADORES_BUSCA_SEM_RESULTADO)


def _palavras_significativas(jogo):
    """Palavras do nome do jogo que valem pra identificar ele de verdade num texto -
    ignora artigos/preposições curtas ("of", "the", "a"...) que sozinhas não provam
    nada (ex.: "Whisper of the House" bate em "of"/"the" mas NÃO é "Whisper of the
    Swallows")."""
    return [p for p in re.findall(r"[a-z0-9]+", jogo.lower()) if len(p) > 2]


def _resultado_e_do_jogo_certo(resultado_estruturado, palavras_jogo):
    """Exige que TODAS as palavras significativas do nome do jogo apareçam no
    título+resumo+link desse resultado específico - não só "a busca achou algo" (o
    termo do jogo faz parte da query, mas o buscador pode devolver resultado de OUTRO
    jogo que só bateu por acaso numa palavra genérica da conquista/descrição).
    Validado na prática: sem essa checagem, uma busca por "Whisper of the Swallows" +
    conquista trouxe threads de Project Zomboid, Baldur's Gate 3 e Fallout 76 - nada a
    ver com o jogo pedido."""
    if not palavras_jogo:
        return True  # nome do jogo não teve nenhuma palavra significativa - não dá pra validar
    texto = f"{resultado_estruturado['titulo']} {resultado_estruturado['corpo']} {resultado_estruturado['link']}".lower()
    return all(palavra in texto for palavra in palavras_jogo)


def _escolher_resultado_relevante(resultados_estruturados, palavras_jogo):
    """Entre os resultados estruturados de uma busca, devolve o primeiro que de fato
    fala do jogo certo (ver _resultado_e_do_jogo_certo) - None se nenhum passar."""
    for r in resultados_estruturados:
        if _resultado_e_do_jogo_certo(r, palavras_jogo):
            return r
    return None


def _enriquecer_com_pagina_completa(resultado, link):
    """Os snippets do search_ddg vêm cortados em ~200 caracteres cada - raramente contêm
    o passo a passo inteiro de um guia (o resumo geralmente só descreve o jogo, não o
    "como fazer"). Busca o texto completo da página do link JÁ VALIDADO como sendo do
    jogo certo (mesmo mecanismo de <APRENDER:url> na GAIA) e anexa ao resultado, pra LLM
    ter o guia de verdade pra ler em vez de só o resumo raso do buscador. Sem link
    (nenhum resultado passou a validação) ou página ilegível, devolve o resultado
    original sem quebrar nada."""
    if not link:
        return resultado
    pagina = obter_conteudo_url(link)
    if not pagina:
        return resultado
    return f"{resultado}\n\n[Conteúdo completo de {link}]:\n{pagina}"


def buscar_guia_conquista(jogo, conquista):
    """Busca COMO destravar uma conquista específica, tentando as fontes de
    _FONTES_GUIA_CONQUISTA em ordem (ver docstring do módulo) e parando na primeira que
    trouxer um resultado realmente sobre o JOGO pedido (não só sobre a conquista/termo
    da busca - ver _resultado_e_do_jogo_certo, aplicado a TODAS as fontes, não só à
    Steam). Cai pra busca livre (sem restrição de site) só se nenhuma das 4 achar nada
    relevante. Além do resumo da busca, busca a página completa do link escolhido (ver
    _enriquecer_com_pagina_completa) - guias de verdade raramente cabem no snippet.
    Devolve {"fonte": nome_da_fonte_usada, "resultado": texto}."""
    palavras_jogo = _palavras_significativas(jogo)
    for nome_fonte, filtro_site in _FONTES_GUIA_CONQUISTA:
        resultado, estruturados = search_ddg.search_ddg(f"{jogo} {conquista} {filtro_site}", retornar_detalhes=True)
        if not _busca_teve_resultado(resultado):
            continue
        melhor = _escolher_resultado_relevante(estruturados, palavras_jogo)
        if not melhor:
            continue  # achou resultado, mas nenhum de verdade sobre esse jogo - tenta a próxima fonte
        return {"fonte": nome_fonte, "resultado": _enriquecer_com_pagina_completa(resultado, melhor["link"])}

    resultado_livre, estruturados_livre = search_ddg.search_ddg(f"{jogo} {conquista} guia conquista", retornar_detalhes=True)
    melhor_livre = _escolher_resultado_relevante(estruturados_livre, palavras_jogo)
    link_livre = melhor_livre["link"] if melhor_livre else None
    return {
        "fonte": "busca livre (sem site específico)",
        "resultado": _enriquecer_com_pagina_completa(resultado_livre, link_livre),
    }


def _percentuais_globais(appid):
    """{apiname: percentual_float} - dicionário vazio se a chamada falhar (não é
    crítico, só perde o destaque de raridade; a lista principal de conquistas continua
    funcionando normalmente sem isso)."""
    try:
        resp = requests.get(URL_GLOBAL_PERCENTAGES, params={"gameid": appid}, timeout=15)
        achievements = resp.json().get("achievementpercentages", {}).get("achievements", [])
        return {a["name"]: a["percent"] for a in achievements}
    except Exception:
        return {}


def _nomes_em_ingles(appid, chave, steamid):
    """{apiname: nome_em_ingles} - dicionário vazio se a chamada falhar (não é crítico,
    só perde o nome em inglês pra busca de guia; a lista principal continua em
    português normalmente). Guias de conquista na internet são quase sempre em inglês -
    buscar pelo nome traduzido pelo GetPlayerAchievements (l=portuguese) pra um jogo
    nichado costuma trazer resultado irrelevante/nenhum (validado na prática: a mesma
    busca com o nome em português trouxe jogos completamente diferentes, e com o nome em
    inglês trouxe o jogo certo)."""
    try:
        resp = requests.get(
            URL_PLAYER_ACHIEVEMENTS,
            params={"appid": appid, "key": chave, "steamid": steamid, "l": "english"},
            timeout=15,
        )
        achievements = resp.json().get("playerstats", {}).get("achievements", [])
        return {a["apiname"]: a.get("name") for a in achievements if a.get("name")}
    except Exception:
        return {}


def obter_progresso_conquistas(appid, nome_conhecido=None):
    """Devolve o progresso de conquistas do jogo pedido - `appid` é SEMPRE numérico
    aqui (resolução por nome fica do lado da GAIA, que tem acesso à lista de jogos
    escaneados localmente, ver `core/tools/handlers.py` e a docstring do módulo);
    `nome_conhecido` (opcional) é o nome já resolvido pela GAIA, usado só como
    fallback de exibição se a própria API da Steam não devolver `gameName`. Dicionário
    só com o que de fato existe - `encontrado`/`perfil_privado`/`sem_conquistas`
    deixam explícito pra quem chama cada motivo de "não tem dado", em vez de a LLM
    inventar um progresso que não existe (mesmo padrão anti-alucinação de
    <STEAM>/<LANCAMENTOS>)."""
    chave = os.getenv("STEAM_WEBAPI_KEY")
    steamid = os.getenv("STEAM_ID64")
    if not chave or not steamid:
        return {"encontrado": False, "motivo": "sem_configuracao"}

    appid = str(appid)
    try:
        resp = requests.get(
            URL_PLAYER_ACHIEVEMENTS,
            params={"appid": appid, "key": chave, "steamid": steamid, "l": "portuguese"},
            timeout=15,
        )
        dados = resp.json().get("playerstats", {})
    except Exception:
        return {"encontrado": False, "motivo": "falha_de_rede"}

    if not dados.get("success"):
        erro = (dados.get("error") or "").lower()
        nome_final = nome_conhecido or dados.get("gameName") or str(appid)
        if "private" in erro:
            return {"encontrado": True, "jogo": nome_final, "appid": appid, "perfil_privado": True}
        return {"encontrado": True, "jogo": nome_final, "appid": appid, "sem_conquistas": True}

    conquistas = dados.get("achievements", [])
    nome_final = dados.get("gameName") or nome_conhecido or str(appid)
    if not conquistas:
        return {"encontrado": True, "jogo": nome_final, "appid": appid, "sem_conquistas": True}

    percentuais = _percentuais_globais(appid)
    nomes_ingles = _nomes_em_ingles(appid, chave, steamid)
    obtidas = [c for c in conquistas if c.get("achieved")]
    faltando = [
        {
            "nome": c.get("name") or c.get("apiname", ""),
            "nome_ingles": nomes_ingles.get(c.get("apiname")),
            "descricao": c.get("description") or "",
            "raridade": percentuais.get(c.get("apiname")),
        }
        for c in conquistas if not c.get("achieved")
    ]
    mais_raras = sorted((f for f in faltando if f["raridade"] is not None), key=lambda f: f["raridade"])

    return {
        "encontrado": True,
        "jogo": nome_final,
        "appid": appid,
        "perfil_privado": False,
        "sem_conquistas": False,
        "obtidas": len(obtidas),
        "total": len(conquistas),
        "percentual": round(len(obtidas) / len(conquistas) * 100, 1),
        "faltando": faltando,
        "mais_raras_faltando": mais_raras[:5],
    }
