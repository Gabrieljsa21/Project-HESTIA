# -*- coding: utf-8 -*-
"""Monitora a página de atividade da Steam (steamcommunity.com/.../home) do usuário -
compra/primeira-jogada/conquista de amigos, conquistas próprias, e anúncios/patch notes
dos jogos que ele tem - e devolve só o que é NOVO desde a última checagem (a GAIA
decide como avisar: log local, voz, DM do Discord - ver `GET /atividade/verificar` em
hestia/api_bridge.py).

Extraído de `Project G.A.I.A/assistant/features/steam_activity/steam_monitor.py`
(2026-08-24, ver ARQUITETURA.md) - lógica 100% idêntica, sem nenhuma dependência da
GAIA pra começar (só `os.getenv` pras credenciais).

Usa a sessão de login autenticada (STEAM_LOGIN_SECURE no .env) porque essa página é
pessoal - a Steam não expõe atividade/wishlist de amigos por nenhuma API pública
(decisão registrada na GAIA antes da extração, testado e confirmado a ausência).
Raspagem de HTML é mais frágil que uma API oficial (quebra se a Steam mudar o layout,
ou se a sessão expirar - sem alerta próprio pra isso ainda, só o erro genérico no
log), mas é a única forma de cobrir tudo que aparece nessa página, incluindo wishlist
de amigos.
"""

import os
import json
import hashlib
import secrets
import requests
from bs4 import BeautifulSoup

ARQUIVO_VISTOS = "data/atividade_vista.json"
# 🔥 Resumo diário (2026-08-01, pedido do usuário: "essas atividades da steam podia
# ser um relatório diário enviado 10h como os outros") - data persistida em DISCO,
# mesmo padrão de lancamentos.py::obter/salvar_ultima_checagem_diaria - sem
# isso, se o processo estivesse desligado na hora configurada, o catch-up (a GAIA
# decide quando, ver `GET/POST /ultima_checagem_diaria_atividade`) nunca disparava
# depois de religar.
ARQUIVO_CHECAGEM_DIARIA_RESUMO = "data/atividade_checagem_diaria.json"
# 🔥 Gerado uma vez por processo (não precisa mudar a cada chamada) - a Steam parece
# usar isso como sinal de "sessão de navegador real" mesmo sem validar o valor exato em
# si (testado: um valor aleatório funciona) - sem ELE JUNTO com os outros cookies/
# headers de navegador abaixo, a página ocasionalmente vem sem o feed de atividade
# (confirmado: mesma sessão, mesma URL, só faltando esses detalhes -1 em cada ~3
# tentativas voltava uma versão "vazia" da página).
_SESSION_ID_FAKE = secrets.token_hex(12)
# 🔥 Limita o crescimento do arquivo - só precisa saber "já vi isso recentemente" (a
# própria página da Steam só mostra os últimos dias), não guardar histórico eterno.
MAX_VISTOS_GUARDADOS = 300


def _chave(*partes):
    """Chave estável e curta (hash) pra identificar um evento sem depender de timestamp
    exato - a Steam agrupa atividade por DIA nos rollups, não por hora/minuto."""
    texto = "|".join(str(p) for p in partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _carregar_vistos():
    if not os.path.exists(ARQUIVO_VISTOS):
        return set()
    try:
        with open(ARQUIVO_VISTOS, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _salvar_vistos(vistos):
    lista = list(vistos)[-MAX_VISTOS_GUARDADOS:]
    os.makedirs(os.path.dirname(ARQUIVO_VISTOS), exist_ok=True)
    with open(ARQUIVO_VISTOS, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False)


def _buscar_html():
    cookie = os.getenv("STEAM_LOGIN_SECURE")
    url = os.getenv("STEAM_PERFIL_URL")
    if not cookie or not url:
        return None
    resp = requests.get(
        url,
        cookies={
            "steamLoginSecure": cookie,
            "sessionid": _SESSION_ID_FAKE,
            "Steam_Language": "brazilian",
            "timezoneOffset": "-10800,0",
        },
        headers={
            # 🔥 User-Agent/Accept/Referer de navegador de verdade (não só "Mozilla/5.0"
            # genérico) - junto com os cookies acima, resolveu a página vir vazia (ver
            # comentário de _SESSION_ID_FAKE). Accept-Language força pt-BR (testado: sem
            # isso, vem em inglês) - a classificação de eventos abaixo é por ESTRUTURA
            # (classes/IDs) onde dá, mas os rollups (jogou/conquistou) só têm texto livre
            # pra distinguir tipo, por isso o idioma da resposta importa.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://steamcommunity.com/",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    return resp.text


def _extrair_eventos(html):
    """Devolve lista de {"chave": str, "texto": str} - um por evento encontrado na
    página, na ordem em que aparecem. Tipos conhecidos, identificados por ESTRUTURA
    (não por texto, mais robusto a idioma/redação):
    - Compra de jogo: div.blotter_gamepurchase.
    - Anúncio de jogo: div.blotter_userstatus com id="group_announcement<ID>" - a
      própria Steam já dá um ID único, usado direto como chave (mais confiável que
      qualquer coisa que eu monte).
    - Jogou pela primeira vez / conquista (própria ou de amigo): linhas dentro de
      div.blotter_daily_rollup - aqui SÓ existe texto livre pra saber o tipo (testado:
      "jogou X pela primeira vez.", "conquistou em X :"). Qualquer linha de rollup que
      não bata um padrão conhecido AINDA é capturada como evento genérico (texto bruto)
      - nunca descarta silenciosamente por não reconhecer o formato exato (ex.: adição
      à lista de desejos - vi no perfil do usuário mas não recapturei no fetch de teste,
      então não tenho a estrutura exata ainda; o fallback genérico cobre isso mesmo
      assim, só sem uma frase tão polida)."""
    soup = BeautifulSoup(html, "html.parser")
    eventos = []

    for bloco in soup.select("div.blotter_gamepurchase"):
        autor_tag = bloco.select_one(".blotter_author_block a[data-miniprofile]")
        autor = autor_tag.get_text(strip=True) if autor_tag else "alguém"
        jogo_tag = bloco.select_one(".blotter_author_block a[href*='store.steampowered.com']")
        jogo = jogo_tag.get_text(strip=True) if jogo_tag else "um jogo"
        id_autor = autor_tag.get("data-miniprofile") if autor_tag else autor
        eventos.append({
            "chave": _chave("compra", id_autor, jogo),
            "texto": f"{autor} comprou {jogo} na Steam.",
        })

    for bloco in soup.select("div.blotter_userstatus[id^='group_announcement']"):
        jogo_tag = bloco.select_one(".blotter_group_announcement_header_text a")
        jogo = jogo_tag.get_text(strip=True) if jogo_tag else "um jogo"
        titulo_tag = bloco.select_one(".blotter_group_announcement_headline a")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else "novo anúncio"
        # 🔥 Trecho real do corpo do anúncio (não só o título) - sem isso, quando o
        # usuário pergunta "o que mais diz o anúncio", a LLM não tinha NADA de real pra
        # responder e inventava patch notes inteiros do zero (confirmado numa conversa
        # real: "corrigiu travamento do sobrevivente", "Festival de Verão"... nada disso
        # existia nos dados). Ainda é só um resumo curto, não o anúncio inteiro - a
        # instrução em processar_steam (GAIA, core/tools/handlers.py) deixa claro que é
        # só isso mesmo.
        corpo_tag = bloco.select_one(".group_announcement_auto_collapse")
        corpo = corpo_tag.get_text(" ", strip=True)[:280] if corpo_tag else ""
        texto = f"{jogo} publicou um anúncio: {titulo}"
        if corpo:
            texto += f" - resumo: {corpo}..."
        eventos.append({
            "chave": _chave("anuncio", bloco.get("id")),
            "texto": texto,
        })

    for linha in soup.select("div.blotter_daily_rollup_line"):
        span = linha.find("span")
        texto_linha = span.get_text(" ", strip=True) if span else linha.get_text(" ", strip=True)
        if not texto_linha:
            continue
        link_jogo = linha.select_one("a[href*='steamcommunity.com/app/']")
        appid = link_jogo["href"].rstrip("/").split("/")[-1] if link_jogo else ""
        autor_tag = linha.select_one("a[data-miniprofile]")
        id_autor = autor_tag.get("data-miniprofile") if autor_tag else texto_linha[:30]
        eventos.append({
            "chave": _chave("rollup", id_autor, appid, texto_linha[:80]),
            "texto": texto_linha,
        })

    return eventos


def verificar_novidades_steam():
    """Busca a página, compara com o que já foi visto (arquivo local), e devolve só os
    eventos NOVOS - já atualizando o arquivo de "vistos" com TODOS os eventos atuais
    (novos ou não). Lista vazia se a chave não estiver configurada, a busca falhar, ou
    não houver nada novo - nunca levanta exceção pro chamador não precisar de
    try/except a cada checagem (a GAIA chama isso a cada 20min, ver `GET /atividade/
    verificar` em hestia/api_bridge.py)."""
    try:
        html = _buscar_html()
        if not html:
            return []
        eventos = _extrair_eventos(html)
        primeira_vez = not os.path.exists(ARQUIVO_VISTOS)
        vistos = _carregar_vistos()
        novos = [e for e in eventos if e["chave"] not in vistos]
        vistos.update(e["chave"] for e in eventos)
        _salvar_vistos(vistos)
        if primeira_vez:
            # 🔥 Primeira checagem só estabelece a linha de base, não notifica - sem
            # isso, toda a atividade recente (pode ser 15-20 itens) seria avisada de
            # uma vez só na primeira vez que rodar com isso configurado.
            return []
        return novos
    except Exception as e:
        print(f" [SISTEMA] Erro ao verificar atividade da Steam: {e}")
        return []


def obter_atividade_atual(limite=10):
    """Devolve os eventos ATUAIS da página (os `limite` mais recentes), SEM filtrar
    pelo que já foi visto e SEM alterar o arquivo de "vistos" do monitoramento
    automático - usado pela tag <STEAM> (pedido explícito, "manda o relatório da
    Steam") pra responder com o estado de agora, independente do que
    verificar_novidades_steam() já notificou ou não. Lista vazia se a chave não
    estiver configurada ou a busca falhar."""
    try:
        html = _buscar_html()
        if not html:
            return []
        return _extrair_eventos(html)[:limite]
    except Exception as e:
        print(f" [SISTEMA] Erro ao obter atividade atual da Steam: {e}")
        return []


def obter_ultima_checagem_diaria_resumo():
    """Data ("AAAA-MM-DD") da última vez que o resumo diário de atividade rodou de
    verdade - mesmo padrão de lancamentos.py::obter_ultima_checagem_diaria
    (persistido em disco, não só em memória, pra sobreviver a reinícios e permitir
    catch-up se o processo esteve desligado na hora configurada)."""
    if not os.path.exists(ARQUIVO_CHECAGEM_DIARIA_RESUMO):
        return None
    try:
        with open(ARQUIVO_CHECAGEM_DIARIA_RESUMO, "r", encoding="utf-8") as f:
            return json.load(f).get("ultima_data")
    except Exception:
        return None


def salvar_ultima_checagem_diaria_resumo(data_str):
    os.makedirs(os.path.dirname(ARQUIVO_CHECAGEM_DIARIA_RESUMO), exist_ok=True)
    with open(ARQUIVO_CHECAGEM_DIARIA_RESUMO, "w", encoding="utf-8") as f:
        json.dump({"ultima_data": data_str}, f, ensure_ascii=False, indent=2)
