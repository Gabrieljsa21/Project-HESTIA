"""Log no padrão do ecossistema (CLAUDE.md global, seção "Logs"; 2026-11-14).

`%LOCALAPPDATA%\\Ecossistema\\<PROJETO>\\Logs\\AAAA-MM-DD.log`, fora do
repositório, um arquivo por dia e 30 dias guardados. Os módulos usam
`logging.getLogger(__name__)`; só o ponto de entrada chama `configurar`.
Com `pythonw` não há console: `print`, stderr e exceções não tratadas
também vão para o log.

Modelo de referência: copiar este arquivo como está em cada projeto
(trocando só o nome passado a `configurar`), sem pacote compartilhado.
Cópia do `clio/registro.py` (CLIO 0.18.0) na HESTIA 0.12.0.
"""

import datetime
import logging
import os
import sys
import threading
from pathlib import Path

DIAS_GUARDAR = 30
FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def pasta_logs(projeto: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Ecossistema" / projeto / "Logs"


class ArquivoDoDia(logging.Handler):
    """Grava em `<pasta>/AAAA-MM-DD.log`, trocando de arquivo na virada do dia."""

    def __init__(self, pasta: Path):
        super().__init__()
        self.pasta = pasta
        self.dia: str | None = None
        self.arquivo = None

    def emit(self, registro: logging.LogRecord) -> None:
        try:
            hoje = datetime.date.today().isoformat()
            if hoje != self.dia:
                if self.arquivo:
                    self.arquivo.close()
                self.arquivo = open(self.pasta / f"{hoje}.log", "a", encoding="utf-8")  # noqa: SIM115
                self.dia = hoje
            self.arquivo.write(self.format(registro) + "\n")
            self.arquivo.flush()
        except Exception:
            self.handleError(registro)


class _SaidaParaLog:
    """`sys.stdout`/`sys.stderr` que viram linhas de log (o `print` não se perde)."""

    def __init__(self, nome: str, nivel: int):
        self.log = logging.getLogger(nome)
        self.nivel = nivel

    def write(self, texto: str) -> int:
        for linha in texto.rstrip().splitlines():
            if linha.strip():
                self.log.log(self.nivel, linha.rstrip())
        return len(texto)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def limpar(pasta: Path, dias: int = DIAS_GUARDAR, hoje: datetime.date | None = None) -> int:
    """Apaga os `AAAA-MM-DD.log` com mais de `dias`; outros arquivos ficam."""
    limite = (hoje or datetime.date.today()) - datetime.timedelta(days=dias)
    apagados = 0
    for arquivo in pasta.glob("*.log"):
        try:
            if datetime.date.fromisoformat(arquivo.stem) < limite:
                arquivo.unlink()
                apagados += 1
        except (ValueError, OSError):
            continue
    return apagados


def configurar(projeto: str, nivel: int = logging.INFO) -> Path:
    """Liga o log do projeto e devolve a pasta. Chamar uma vez, no ponto de entrada."""
    pasta = pasta_logs(projeto)
    pasta.mkdir(parents=True, exist_ok=True)
    limpar(pasta)
    formato = logging.Formatter(FORMATO)
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for antigo in list(raiz.handlers):
        raiz.removeHandler(antigo)
    arquivo = ArquivoDoDia(pasta)
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)
    console = sys.__stderr__
    if console is not None and console.isatty():   # rodando num terminal: mostra lá também
        tela = logging.StreamHandler(console)
        tela.setFormatter(formato)
        raiz.addHandler(tela)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # uma linha por requisição enche o log
    sys.stdout = _SaidaParaLog("print", logging.INFO)
    sys.stderr = _SaidaParaLog("stderr", logging.WARNING)
    sys.excepthook = lambda tipo, valor, rastro: logging.getLogger("erro").critical(
        "Exceção não tratada", exc_info=(tipo, valor, rastro))
    threading.excepthook = lambda a: logging.getLogger("erro").error(
        "Exceção na thread %s", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return pasta
