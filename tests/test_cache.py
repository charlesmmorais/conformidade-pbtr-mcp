"""Testes do cache de análises.

Num servidor exposto na internet, o estado que sobrevive entre as três chamadas
do fluxo é também o caminho mais curto para derrubar a instância por memória.
Estes testes garantem que o cache tem teto, expira por idade e limpa o que
deixou em disco.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import servidor  # noqa: E402

PB_TESTE = RAIZ / "exemplos" / "PB_exemplo_com_erros.pdf"


@pytest.fixture(autouse=True)
def limpar_cache():
    for chave in list(servidor._ANALISES):
        servidor._descartar(chave)
    yield
    for chave in list(servidor._ANALISES):
        servidor._descartar(chave)


@pytest.fixture(scope="module", autouse=True)
def pb_existe():
    if not PB_TESTE.exists():
        subprocess.run([sys.executable, str(RAIZ / "exemplos" / "gerar_pb_teste.py")], check=True)


def _analisar(tmp_path, nome="PB"):
    return servidor.analisar_conformidade(
        caminho_arquivo=str(PB_TESTE),
        diretorio_saida=str(tmp_path),
    )


def test_analise_entra_no_cache(tmp_path):
    r = _analisar(tmp_path)
    assert r["chave_analise"] in servidor._ANALISES


def test_cache_respeita_o_teto(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "MAX_ANALISES", 3)
    for i in range(6):
        chave = f"doc{i}"
        servidor._ANALISES[chave] = servidor._Analise(
            relatorio=None, segmentos=[], base=chave,
            diretorio=None, retornar_conteudo=False, tmp=None,
        )
        servidor._expirar()
    assert len(servidor._ANALISES) <= 3
    # o descarte é do mais antigo: os últimos sobrevivem
    assert "doc5" in servidor._ANALISES
    assert "doc0" not in servidor._ANALISES


def test_analise_expira_por_idade(monkeypatch):
    monkeypatch.setattr(servidor, "TTL_ANALISE_S", 0)
    servidor._ANALISES["velha"] = servidor._Analise(
        relatorio=None, segmentos=[], base="velha",
        diretorio=None, retornar_conteudo=False, tmp=None,
        criado_em=-1000.0,
    )
    servidor._expirar()
    assert "velha" not in servidor._ANALISES


def test_descarte_apaga_relatorios_gerados(tmp_path):
    r = _analisar(tmp_path)
    chave = r["chave_analise"]
    servidor.registrar_revisao_textual(chave_analise=chave, apontamentos=[], formatos=["md"])
    arquivos = list(servidor._ANALISES[chave].arquivos)
    assert arquivos and all(a.exists() for a in arquivos)

    servidor._descartar(chave)
    assert all(not a.exists() for a in arquivos)
    assert chave not in servidor._ANALISES


def test_reanalise_substitui_a_anterior(tmp_path):
    r1 = _analisar(tmp_path)
    n = len(servidor._ANALISES)
    r2 = _analisar(tmp_path)
    assert r1["chave_analise"] == r2["chave_analise"]
    assert len(servidor._ANALISES) == n


def test_mensagem_de_erro_orienta_a_refazer():
    r = servidor.obter_texto_para_revisao(chave_analise="inexistente")
    assert "erro" in r
    assert "analisar_conformidade novamente" in r["erro"]


def test_fluxo_completo_com_cache(tmp_path):
    r1 = _analisar(tmp_path)
    chave = r1["chave_analise"]
    assert r1["revisao_textual"]["status"] == "pendente"

    r2 = servidor.obter_texto_para_revisao(chave_analise=chave)
    assert r2["total_segmentos"] > 0

    r3 = servidor.registrar_revisao_textual(
        chave_analise=chave,
        apontamentos=[{"trecho": "a nível de", "sugestao": "em nível de", "tipo": "impropriedade"}],
        formatos=["md", "json"],
    )
    assert r3["apontamentos_aceitos"] == 1
    assert set(r3["relatorios"]) == {"md", "json"}
