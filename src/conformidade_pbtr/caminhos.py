"""Resolução dos arquivos de recursos (checklists e dicionário).

A busca segue esta ordem, e a primeira que existir vence:

1. variável de ambiente específica do recurso
   (``CONFORMIDADE_PBTR_CHECKLIST`` / ``CONFORMIDADE_PBTR_DICIONARIO``);
2. diretório apontado por ``CONFORMIDADE_PBTR_RECURSOS``;
3. ``recursos/`` embarcado no pacote instalado;
4. ``recursos/`` na raiz do repositório (execução a partir do código-fonte).

Isso permite que um órgão use o motor com o seu próprio checklist sem
modificar o código nem reempacotar o projeto.
"""

from __future__ import annotations

import os
from pathlib import Path

# checklist distribuído por padrão
CHECKLIST_PADRAO = "checklist_roteiro_ti.yaml"
DICIONARIO_PADRAO = "dicionario_serpro.txt"

_AQUI = Path(__file__).resolve()
_DIR_PACOTE = _AQUI.parent / "recursos"          # instalado (wheel)
_DIR_REPO = _AQUI.parents[2] / "recursos"        # src/<pkg>/.. -> raiz do repo


def diretorios_de_recursos() -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("CONFORMIDADE_PBTR_RECURSOS")
    if env:
        dirs.append(Path(env).expanduser())
    dirs.extend([_DIR_PACOTE, _DIR_REPO])
    return dirs


def localizar(nome: str) -> Path | None:
    """Procura um arquivo de recurso pelo nome, na ordem dos diretórios."""
    for d in diretorios_de_recursos():
        alvo = d / nome
        if alvo.exists():
            return alvo
    return None


def _resolver(variavel: str, nome_padrao: str, rotulo: str) -> Path:
    explicito = os.environ.get(variavel)
    if explicito:
        caminho = Path(explicito).expanduser()
        if not caminho.exists():
            raise FileNotFoundError(
                f"{rotulo} indicado por {variavel} não existe: {caminho}"
            )
        return caminho

    encontrado = localizar(nome_padrao)
    if encontrado is None:
        procurados = ", ".join(str(d) for d in diretorios_de_recursos())
        raise FileNotFoundError(
            f"{rotulo} '{nome_padrao}' não encontrado. Diretórios consultados: "
            f"{procurados}. Defina {variavel} com o caminho do arquivo."
        )
    return encontrado


def caminho_checklist(explicito: str | None = None) -> Path:
    """Caminho do checklist a usar.

    ``explicito`` pode ser o caminho de um arquivo ou o nome de um checklist
    presente em ``recursos/`` (com ou sem o prefixo ``checklist_`` e a extensão).
    """
    if explicito:
        direto = Path(explicito).expanduser()
        if direto.exists():
            return direto
        # apelido ou nome do arquivo embarcado
        nome = explicito if explicito.endswith((".yaml", ".yml")) else f"checklist_{explicito}.yaml"
        encontrado = localizar(nome)
        if encontrado is None:
            raise FileNotFoundError(f"Checklist não encontrado: {explicito}")
        return encontrado
    return _resolver("CONFORMIDADE_PBTR_CHECKLIST", CHECKLIST_PADRAO, "Checklist")


def caminho_dicionario() -> Path | None:
    """Caminho do dicionário de termos aceitos; None se não houver."""
    try:
        return _resolver("CONFORMIDADE_PBTR_DICIONARIO", DICIONARIO_PADRAO, "Dicionário")
    except FileNotFoundError:
        return None


def checklists_disponiveis() -> list[str]:
    """Nomes dos checklists encontrados nos diretórios de recursos."""
    vistos: dict[str, None] = {}
    for d in diretorios_de_recursos():
        if not d.is_dir():
            continue
        for arq in sorted(d.glob("checklist_*.y*ml")):
            vistos.setdefault(arq.name, None)
    return list(vistos)
