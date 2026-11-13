# Funcionalidades do Project HESTIA

Estado atual do que o HESTIA entrega. Quem decide quando consultar e como avisar (voz, Discord, log) é a GAIA. O detalhe técnico de cada decisão fica em `ARQUITETURA.md`.

## Lançamentos da wishlist

Varredura completa da wishlist uma vez por dia, no horário que a GAIA pede. Leva alguns minutos e roda em segundo plano; os avisos ficam numa fila até a GAIA confirmar a entrega, então nenhum se perde se a GAIA estiver fechada ou sem Discord.

Avisos gerados:

- contagem regressiva com 30, 7 e 1 dia antes do lançamento;
- "lança HOJE" no dia marcado;
- aviso de lançamento marcado para um dia que já passou, quando a varredura não rodou no dia exato e a Steam ainda mostra "em breve";
- "Hoje foi lançado" quando a Steam tira o jogo de "em breve";
- jogo que virou Free to Play;
- saída do Acesso Antecipado (versão 1.0);
- DLC nova anunciada.

Mais de uma mudança no mesmo jogo e no mesmo dia gera um aviso para cada uma. Jogo adiado recomeça a contagem regressiva pela data nova. Na primeira vez que um jogo aparece, o HESTIA só registra o estado, sem avisar. Jogos que saem da wishlist deixam de ser acompanhados.

Cada jogo ainda não lançado vira um evento no calendário "Lançamentos Steam" do Google Calendar, pela GAIA.

A data de lançamento pode ficar um dia antes da mostrada na loja (limitação da API pública, ver `ARQUITETURA.md`).

## Próximos lançamentos

Lista dos jogos ainda não lançados da wishlist, ordenados por data, com o tipo (lançamento oficial, Acesso Antecipado ou demo). Lê o resultado da última varredura, sem consultar a Steam de novo. Usada quando o usuário pergunta à GAIA pelos próximos lançamentos.

## Atividade da Steam

Checada a cada 20 minutos (a GAIA pede), por duas fontes. Devolve só o que é novo, e o mesmo fato vindo das duas sai uma vez. A primeira leitura de cada fonte só marca o que já existia.

- **Web API oficial, sem login:** compras novas de todos os amigos e da família (exige a lista de amigos pública no seu perfil e a biblioteca de cada pessoa pública) e anúncios oficiais dos jogos que você jogou nas últimas duas semanas. Só a família ganha destaque.
- **Página de atividade logada:** primeiras partidas e conquistas de amigos (com o nome das conquistas), adições à wishlist de amigos, além de compras e anúncios, cada um com o link do jogo. Usa o login por QR.

Também atende o resumo diário e o pedido "manda o relatório da Steam", que devolvem o estado atual sem mexer no que já foi visto. Sem página logada, eles usam o que a Web API já trouxe.

## Família

Lista de pessoas cadastradas pelo link do perfil Steam. Eventos de atividade delas chegam marcados como família, para a GAIA destacar. Ninguém é filtrado.

## Sessão da Steam

O HESTIA tem login próprio na Steam: a GAIA mostra um QR code, você aprova no app da Steam do celular, e o login vale cerca de 200 dias, renovado sozinho a cada dia. Nenhuma senha passa pelo HESTIA, e os tokens ficam cifrados para a sua conta do Windows. Detecta quando a sessão cai (duas leituras seguidas da tela de login, reconhecida por `g_steamID = false`). Copiar o login do navegador ficou só como reserva, porque Edge, Chrome e Brave não deixam mais ler os cookies.

## Histórico e status

Guarda os 300 avisos mais recentes (lançamentos entregues e novidades de atividade) e expõe o estado do serviço: última varredura da wishlist com jogos lidos, falhas e avisos, fila pendente, última checagem de atividade e situação da sessão. A GAIA mostra os dois na tela Steam do Painel.

## Conquistas

Progresso de conquistas de um jogo da biblioteca: quantas foram obtidas, quais faltam e as cinco mais raras entre as que faltam (pela porcentagem global de jogadores). Avisa quando as estatísticas do jogo estão privadas ou quando o jogo não tem conquistas.

## Guia de conquista

Procura como destravar uma conquista, nesta ordem: guias da comunidade Steam, PowerPyx, GameFAQs, F95zone e busca livre. Só aceita um resultado que fale do jogo pedido e anexa o texto completo da página escolhida.

## Manutenção

Logs diários em `logs/`, apagados depois de 30 dias. Dados em `data/` gravados de forma atômica, com cópia `.bak` usada se o arquivo principal ficar ilegível.
