# -*- coding: utf-8 -*-
"""Monitora a página de atividade da Steam (steamcommunity.com/.../home) do usuário -
compra/primeira-jogada/conquista de amigos, conquistas próprias, e anúncios/patch notes
dos jogos que ele tem - e devolve só o que é NOVO desde a última checagem (a GAIA
decide como avisar: log local, voz, DM do Discord - ver `GET /atividade/verificar` em
hestia/api_bridge.py).

Extraído de `Project G.A.I.A/assistant/features/steam_activity/steam_monitor.py`
(2026-08-24, ver docs/ARQUITETURA.md) - lógica 100% idêntica, sem nenhuma dependência da
GAIA pra começar (só `os.getenv` pras credenciais).

Usa a sessão de login autenticada (STEAM_LOGIN_SECURE no .env) porque essa página é
pessoal - a Steam não expõe atividade/wishlist de amigos por nenhuma API pública
(decisão registrada na GAIA antes da extração, testado e confirmado a ausência).
Raspagem de HTML é mais frágil que uma API oficial (quebra se a Steam mudar o layout),
mas é a única forma de cobrir tudo que aparece nessa página, incluindo wishlist de
amigos.

Sessão expira sem aviso nenhum da própria Steam (achado real, 2026-09-01: o
usuário simplesmente parou de receber notificação nenhuma, sem erro visível em
lugar algum - `_buscar_html` devolvia `status 200` normal, só que era a TELA DE
LOGIN, não o feed). `_validar_sessao`/`obter_status_sessao` (abaixo) detectam
isso de verdade, e `renovar_sessao_via_navegador` tenta se autocurar pegando um
cookie fresco direto do navegador que o usuário já usa no dia a dia (Edge/
Chrome/Firefox via `browser_cookie3`) - nunca pede senha nem 2FA, só lê a
sessão que o próprio navegador já guarda quando o usuário loga normalmente pela
web. A GAIA (`run.py::_monitorar_steam_loop`) só avisa o usuário se essa
autocura também falhar.
"""

import os
import hashlib
import re
from datetime import datetime
import secrets
import threading
import requests
import browser_cookie3
from bs4 import BeautifulSoup

from hestia.core import familia, atividade_api
from hestia import historico
from hestia.armazenamento import ler_json, gravar_json

ARQUIVO_VISTOS = "data/atividade_vista.json"
ARQUIVO_SESSAO_STATUS = "data/atividade_sessao_status.json"
# 🔥 Só navegadores que já funcionam sem elevação/config extra nesse ambiente
# (testado 2026-09-01: Brave pede admin, Firefox exige perfil configurado -
# best-effort, cada um cai pro próximo em silêncio se não achar nada).
_NAVEGADORES_SUPORTADOS = [
    ("Edge", browser_cookie3.edge),
    ("Chrome", browser_cookie3.chrome),
    ("Firefox", browser_cookie3.firefox),
]
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
# 🔥 Servidor com threads (2026-11-12): duas requisições podem ler e regravar
# os mesmos arquivos ao mesmo tempo (status da sessão em toda busca de HTML,
# "vistos" na checagem). O lock serializa só esses trechos curtos de
# leitura-e-gravação, nunca a busca de rede.
_lock_arquivos = threading.Lock()


def _chave(*partes):
    """Chave estável e curta (hash) pra identificar um evento sem depender de timestamp
    exato - a Steam agrupa atividade por DIA nos rollups, não por hora/minuto.
    Partes normalizadas (minúsculas, espaços colapsados): a mesma compra ou o
    mesmo anúncio vindo da página logada e da Web API (`atividade_api.py`)
    gera a mesma chave e só é avisado uma vez."""
    texto = "|".join(" ".join(str(p).lower().split()) for p in partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _carregar_vistos():
    """Lista em ordem de chegada (mais antigo primeiro). Antes era um `set`,
    e o corte em `MAX_VISTOS_GUARDADOS` descartava chaves em ordem
    aleatória: um evento recente podia sair da lista e voltar a ser
    notificado como novo."""
    return list(ler_json(ARQUIVO_VISTOS, []))


def _salvar_vistos(vistos):
    gravar_json(ARQUIVO_VISTOS, vistos[-MAX_VISTOS_GUARDADOS:], indent=None)


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
    html = resp.text
    _marcar_status_sessao(_validar_sessao(html))
    return html


# 🔥 1 falha isolada NÃO é prova de sessão expirada de verdade - a própria
# raspagem já é conhecida por voltar vazia/errada ~1 em cada 3 tentativas
# mesmo com sessão válida (ver docstring de `_SESSION_ID_FAKE` acima, achado
# ANTES desta extração) - confirmado na prática (2026-09-01): um teste manual
# isolado leu a tela de login, mas a checagem seguinte, com o MESMO cookie
# (hash comparado, idêntico byte a byte), leu a sessão como válida. Exige
# falhas SEGUIDAS (2 checagens de 20min = 40min de sinal consistente) antes
# de declarar expiração de verdade - senão a autocura/aviso dispararia por
# falso positivo boa parte do tempo.
LIMITE_FALHAS_CONSECUTIVAS_SESSAO = 2


_RE_STEAMID_LOGADO = re.compile(r'g_steamID\s*=\s*"\d+"')


def _validar_sessao(html):
    """`g_steamID` é uma variável JS global que a Steam injeta em toda página
    da Community, independente de idioma: com o número da conta quando há
    login, e `g_steamID = false;` na tela de login. Até 2026-11-13 a checagem
    era só "o texto g_steamID aparece", que a tela de login também satisfaz:
    a sessão expirada passava por válida e ninguém era avisado (achado real,
    o usuário ficou semanas sem atividade nenhuma). Ainda exige falhas
    seguidas antes de declarar expirada (`LIMITE_FALHAS_CONSECUTIVAS_SESSAO`)."""
    return bool(_RE_STEAMID_LOGADO.search(html or ""))


def _carregar_status_bruto():
    return ler_json(ARQUIVO_SESSAO_STATUS, {})


def _marcar_status_sessao(valida_desta_tentativa):
    with _lock_arquivos:
        _marcar_status_sessao_sem_lock(valida_desta_tentativa)


def _marcar_status_sessao_sem_lock(valida_desta_tentativa):
    if valida_desta_tentativa:
        novo = {"valida": True, "falhas_consecutivas": 0}
    else:
        falhas = _carregar_status_bruto().get("falhas_consecutivas", 0) + 1
        novo = {"valida": falhas < LIMITE_FALHAS_CONSECUTIVAS_SESSAO, "falhas_consecutivas": falhas}
    gravar_json(ARQUIVO_SESSAO_STATUS, novo, indent=None)


def obter_status_sessao():
    """`{"valida": None}` = nenhuma checagem real rodou ainda; `True`/`False`
    = já filtrado por `LIMITE_FALHAS_CONSECUTIVAS_SESSAO` (não é a leitura
    crua da última tentativa isolada)."""
    dados = _carregar_status_bruto()
    return {"valida": dados.get("valida")} if dados else {"valida": None}


def _atualizar_env(chave, valor):
    """Atualiza o `.env` na hora (linha existente, ou nova no fim) - sobrevive
    a reinício. O processo ATUAL já usa o valor novo direto de `os.environ`
    (ver `renovar_sessao_via_navegador`), não depende de reler o arquivo."""
    caminho = ".env"
    linhas = []
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            linhas = f.readlines()
    encontrada = False
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(f"{chave}="):
            linhas[i] = f"{chave}='{valor}'\n"
            encontrada = True
            break
    if not encontrada:
        linhas.append(f"{chave}='{valor}'\n")
    with open(caminho, "w", encoding="utf-8") as f:
        f.writelines(linhas)


def renovar_sessao_via_navegador():
    """Tenta pegar um `steamLoginSecure` fresco direto do navegador que o
    usuário já usa no dia a dia - sem pedir senha nem 2FA a ninguém, só lê a
    sessão que o próprio navegador já guarda quando ele loga normalmente pela
    web (pedido do usuário, 2026-09-01: "n da p automatizar" + "gere algo p q
    estando logando, eu ou a gaia consiga pegar facil oq precisa"). Atualiza o
    processo atual (efeito imediato, sem reiniciar) E o `.env` (sobrevive a
    reinício). Devolve `{"sucesso": bool, "origem": nome do navegador ou None}`."""
    for nome, funcao in _NAVEGADORES_SUPORTADOS:
        try:
            jar = funcao(domain_name="steamcommunity.com")
            valor = next((c.value for c in jar if c.name == "steamLoginSecure"), None)
        except Exception:
            continue
        if valor:
            os.environ["STEAM_LOGIN_SECURE"] = valor
            with _lock_arquivos:
                _atualizar_env("STEAM_LOGIN_SECURE", valor)
            return {"sucesso": True, "origem": nome}
    return {"sucesso": False, "origem": None}


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
    # 🔥 accountids de "família" (2026-09-01, pedido do usuário: "quero receber
    # principalmente qnd alguem da familia compra algo novo") - lido 1x por
    # chamada, comparado por accountid (data-miniprofile), nunca por nome (que
    # pode mudar). Ver hestia/core/familia.py.
    familia_ids = familia.accountids_familia()

    for bloco in soup.select("div.blotter_gamepurchase"):
        autor_tag = bloco.select_one(".blotter_author_block a[data-miniprofile]")
        autor = autor_tag.get_text(strip=True) if autor_tag else "alguém"
        jogo_tag = bloco.select_one(".blotter_author_block a[href*='store.steampowered.com']")
        jogo = jogo_tag.get_text(strip=True) if jogo_tag else "um jogo"
        id_autor = autor_tag.get("data-miniprofile") if autor_tag else autor
        eventos.append({
            "chave": _chave("compra", id_autor, jogo),
            "link": jogo_tag.get("href") if jogo_tag else None,
            "texto": f"{autor} comprou {jogo} na Steam.",
            "familia": id_autor in familia_ids,
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
            "chave": _chave("anuncio", jogo, titulo),
            "link": titulo_tag.get("href") if titulo_tag else None,
            "texto": texto,
            "familia": False,  # anúncio é do jogo/grupo, não tem autor-amigo
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
            "familia": id_autor in familia_ids,
        })

    return eventos


ARQUIVO_ULTIMA_CHECAGEM = "data/atividade_ultima_checagem.json"


def _eventos_da_api():
    """Eventos da Web API (`atividade_api.py`) no mesmo formato da página."""
    try:
        brutos = atividade_api.coletar_eventos()
    except Exception as e:
        print(f" [SISTEMA] Erro na atividade pela Web API: {e}")
        return []
    return [{
        "chave": _chave(e["tipo"], e["autor"], e["alvo"]),
        "texto": e["texto"],
        "familia": e["familia"],
        "link": e.get("link"),
    } for e in brutos]


def verificar_novidades_steam():
    """Junta a página logada (se a sessão valer) e a Web API, compara com o que
    já foi visto (arquivo local) e devolve só os eventos NOVOS - já atualizando
    o arquivo de "vistos". Lista vazia se nada estiver configurado, a busca
    falhar ou não houver nada novo - nunca levanta exceção (a GAIA chama isso
    a cada 20min, ver `GET /atividade/verificar` em hestia/api_bridge.py)."""
    try:
        html = None
        try:
            html = _buscar_html()
        except Exception as e:
            print(f" [SISTEMA] Página de atividade indisponível: {e}")
        eventos_pagina = _extrair_eventos(html) if html else []
        eventos_api = _eventos_da_api()
        eventos = eventos_pagina + eventos_api
        # 🔥 Página voltando depois de um tempo sem login (2026-11-13, 0.5.0):
        # tudo o que ela mostra dos últimos dias pareceria novo e iria de uma
        # vez para o Discord. A primeira leitura depois da volta só entra nos
        # "vistos"; da API continua avisando normalmente.
        anterior = ler_json(ARQUIVO_ULTIMA_CHECAGEM, None)
        pagina_voltou = bool(eventos_pagina) and anterior is not None and not anterior.get("eventos_pagina")
        gravar_json(ARQUIVO_ULTIMA_CHECAGEM, {
            "em": datetime.now().isoformat(timespec="seconds"),
            "eventos_pagina": len(eventos_pagina),
            "eventos_api": len(eventos) - len(eventos_pagina),
            "api_configurada": atividade_api.configurada(),
        })
        with _lock_arquivos:
            primeira_vez = not os.path.exists(ARQUIVO_VISTOS)
            vistos = _carregar_vistos()
            ja_vistos = set(vistos)
            candidatos = eventos_api if pagina_voltou else eventos
            novos = [e for e in candidatos if e["chave"] not in ja_vistos]
            # Chave já vista vai para o fim (mais recente): continua na lista
            # enquanto aparecer na página, em vez de envelhecer e ser cortada.
            atuais = [e["chave"] for e in eventos]
            atuais_set = set(atuais)
            vistos = [c for c in vistos if c not in atuais_set] + list(dict.fromkeys(atuais))
            _salvar_vistos(vistos)
        if primeira_vez:
            # 🔥 Primeira checagem só estabelece a linha de base, não notifica - sem
            # isso, toda a atividade recente (pode ser 15-20 itens) seria avisada de
            # uma vez só na primeira vez que rodar com isso configurado.
            return []
        # Mesma chave vinda das duas fontes no mesmo ciclo: avisa uma vez.
        novos = list({e["chave"]: e for e in novos}.values())
        historico.registrar("atividade", novos)
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
        eventos = _extrair_eventos(html) if html else []
        if eventos:
            return eventos[:limite]
        # Sem página logada: o que a Web API já trouxe e foi avisado.
        return [
            {"chave": "", "texto": h["texto"], "familia": h["familia"], "link": h.get("link")}
            for h in historico.listar(limite, categoria="atividade")
        ]
    except Exception as e:
        print(f" [SISTEMA] Erro ao obter atividade atual da Steam: {e}")
        return []


def obter_status_atividade():
    """Última checagem (horário e quantos eventos cada fonte trouxe), para a
    tela de status da GAIA."""
    return {
        "sessao_valida": obter_status_sessao().get("valida"),
        "ultima_checagem": ler_json(ARQUIVO_ULTIMA_CHECAGEM, None),
        "api_configurada": atividade_api.configurada(),
        "familia": len(familia.listar_familia()),
    }


def obter_ultima_checagem_diaria_resumo():
    """Data ("AAAA-MM-DD") da última vez que o resumo diário de atividade rodou de
    verdade - mesmo padrão de lancamentos.py::obter_ultima_checagem_diaria
    (persistido em disco, não só em memória, pra sobreviver a reinícios e permitir
    catch-up se o processo esteve desligado na hora configurada)."""
    return ler_json(ARQUIVO_CHECAGEM_DIARIA_RESUMO, {}).get("ultima_data")


def salvar_ultima_checagem_diaria_resumo(data_str):
    gravar_json(ARQUIVO_CHECAGEM_DIARIA_RESUMO, {"ultima_data": data_str})
