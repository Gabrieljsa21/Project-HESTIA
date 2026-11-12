# -*- coding: utf-8 -*-
"""Leitura e gravação de JSON em `data/` sem risco de arquivo pela metade.

`gravar_json` escreve num `.tmp` e troca com `os.replace` (atômico no mesmo
disco): uma queda de energia no meio da escrita deixa o arquivo antigo
inteiro, nunca um JSON cortado. A versão anterior fica em `.bak`, e
`ler_json` recorre a ela se o arquivo principal estiver ilegível."""
import json
import os
import shutil


def ler_json(caminho, padrao):
    for candidato in (caminho, caminho + ".bak"):
        if not os.path.exists(candidato):
            continue
        try:
            with open(candidato, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f" [SISTEMA] {candidato} ilegível, tentando a cópia de segurança.")
    return padrao


def gravar_json(caminho, dados, indent=2):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(caminho):
        try:
            shutil.copy2(caminho, caminho + ".bak")
        except Exception:
            pass
    os.replace(temporario, caminho)
