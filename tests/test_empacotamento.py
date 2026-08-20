"""Testes de integridade do pacote.

A suíte normal roda a partir de `src/` e por isso não enxerga problema de
empacotamento: um módulo que não entrou no git — ou que o `.gitignore` excluiu
do wheel — continua importando localmente e só quebra no primeiro boot em
produção. Foi exatamente o que aconteceu com `conformidade_pbtr/relatorios`,
excluído por uma linha `relatorios/` no `.gitignore`, que casa em qualquer
nível da árvore.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"

SUBPACOTES = ["extratores", "relatorios", "validadores"]


def _e_repositorio_git() -> bool:
    return (RAIZ / ".git").exists()


@pytest.mark.skipif(not _e_repositorio_git(), reason="fora de um clone git")
def test_todo_modulo_esta_versionado():
    """Nenhum .py de src/ pode estar fora do controle de versão."""
    resultado = subprocess.run(
        ["git", "ls-files", "src"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    )
    versionados = {
        (RAIZ / linha).resolve()
        for linha in resultado.stdout.splitlines()
        if linha.endswith(".py")
    }
    no_disco = {p.resolve() for p in SRC.rglob("*.py") if "__pycache__" not in p.parts}

    faltando = sorted(str(p.relative_to(RAIZ)) for p in no_disco - versionados)
    assert not faltando, (
        "Módulos fora do git — confira o .gitignore, lembrando que um padrão sem "
        f"barra inicial casa em qualquer nível: {faltando}"
    )


@pytest.mark.skipif(not _e_repositorio_git(), reason="fora de um clone git")
def test_recursos_estao_versionados():
    resultado = subprocess.run(
        ["git", "ls-files", "recursos"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    )
    versionados = set(resultado.stdout.split())
    assert any(n.endswith(".yaml") for n in versionados), "checklist fora do git"
    assert any(n.endswith(".txt") for n in versionados), "dicionário fora do git"


@pytest.mark.parametrize("subpacote", SUBPACOTES)
def test_subpacote_tem_init(subpacote):
    """Sem __init__.py o diretório não é empacotado como subpacote."""
    assert (SRC / "conformidade_pbtr" / subpacote / "__init__.py").exists()


@pytest.mark.parametrize("subpacote", SUBPACOTES)
@pytest.mark.skipif(not _e_repositorio_git(), reason="fora de um clone git")
def test_subpacote_nao_esta_ignorado(subpacote):
    """`git check-ignore` acusa o padrão que excluiria o subpacote."""
    alvo = f"src/conformidade_pbtr/{subpacote}/__init__.py"
    resultado = subprocess.run(
        ["git", "check-ignore", "-v", alvo],
        cwd=RAIZ, capture_output=True, text=True,
    )
    assert resultado.returncode != 0, (
        f"{alvo} está sendo ignorado por: {resultado.stdout.strip()}"
    )


def test_todos_os_formatos_de_relatorio_existem():
    sys.path.insert(0, str(SRC))
    from conformidade_pbtr.relatorios import FORMATOS

    assert sorted(FORMATOS) == ["docx", "json", "markdown", "md", "pdf", "xlsx"]
