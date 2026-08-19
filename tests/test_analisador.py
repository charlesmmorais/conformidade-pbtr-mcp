"""Testes do analisador — usa o PB sintético com erros propositais."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import analisar  # noqa: E402
from conformidade_pbtr.extratores.pdf import parse_numero_br  # noqa: E402
from conformidade_pbtr.relatorios import FORMATOS  # noqa: E402
from conformidade_pbtr.validadores.tabelas import _extenso_confere  # noqa: E402

PB_TESTE = RAIZ / "exemplos" / "PB_exemplo_com_erros.pdf"


@pytest.fixture(scope="session")
def relatorio():
    if not PB_TESTE.exists():
        subprocess.run(
            [sys.executable, str(RAIZ / "exemplos" / "gerar_pb_teste.py")],
            check=True,
        )
    return analisar(PB_TESTE)


# ---------------------------------------------------------------- extração

@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("R$ 1.234,56", 1234.56),
        ("1.234,56", 1234.56),
        ("12", 12.0),
        ("(1.000,00)", -1000.0),
        ("", None),
        ("texto", None),
    ],
)
def test_parse_numero_br(bruto, esperado):
    assert parse_numero_br(bruto)[0] == esperado


def test_extenso_confere():
    assert _extenso_confere(486000.0, "quatrocentos e oitenta e seis mil reais")
    assert not _extenso_confere(486000.0, "quatrocentos e oitenta mil reais")


def test_extracao_basica(relatorio):
    doc = relatorio.documento
    assert doc.paginas >= 1
    assert len(doc.texto) > 1000
    assert len(doc.tabelas) == 1
    assert "Valor Total" in doc.tabelas[0].cabecalho


def test_contexto_inferido(relatorio):
    tags = set(relatorio.documento.tags_contexto)
    assert "licitacao" in tags
    assert "chamados" in tags
    assert "servico" in tags
    assert "inexigibilidade" not in tags


# --------------------------------------------------------------- numeração

def _ids(rel, prefixo):
    return [a for a in rel.achados if a.id.startswith(prefixo)]


def test_detecta_salto_de_numeracao(relatorio):
    titulos = [a.titulo for a in _ids(relatorio, "NUM")]
    assert any("5.1 → 5.3" in t for t in titulos)
    assert any("3.1 → 3.3" in t for t in titulos)


def test_detecta_subitem_orfao(relatorio):
    assert any("3.2.1" in a.titulo for a in _ids(relatorio, "NUM"))


def test_detecta_secao_obrigatoria_ausente(relatorio):
    assert any("Seção 7" in a.titulo for a in relatorio.achados)


def test_nao_confunde_linha_de_tabela_com_item(relatorio):
    """A primeira coluna da tabela ("1", "2", "3") não pode virar item numerado."""
    assert not any("numerado mais de uma vez" in a.titulo for a in relatorio.achados)


# ----------------------------------------------------------------- tabelas

def test_detecta_linha_com_aritmetica_errada(relatorio):
    achado = next(a for a in relatorio.achados if a.id == "TAB-01-L02")
    assert "180.000,00" in achado.esperado
    assert "190.000,00" in achado.encontrado


def test_detecta_somatorio_que_nao_fecha(relatorio):
    achado = next(a for a in relatorio.achados if a.id == "TAB-01-SOMA")
    assert "514.000,00" in achado.esperado
    assert "486.000,00" in achado.encontrado


def test_detecta_extenso_divergente(relatorio):
    achado = next(a for a in relatorio.achados if a.id.startswith("VAL-EXT"))
    assert achado.status.value == "nao_conforme"


# -------------------------------------------------------------- ortografia

@pytest.mark.parametrize(
    "trecho", ["a nível de", "afim de", "deverá deverá", "À partir", "frizar"]
)
def test_regras_deterministicas_de_revisao(relatorio, trecho):
    encontrados = [a.encontrado for a in relatorio.achados if a.id.startswith("ORT")]
    assert any(trecho.lower() in e.lower() for e in encontrados)


# --------------------------------------------------------------- checklist

def test_checklist_aplica_apenas_regras_pertinentes(relatorio):
    por_id = {a.id: a for a in relatorio.achados}
    # documento é de licitação: regras de inexigibilidade não se aplicam
    assert por_id["PB-06-007"].status.value == "nao_aplicavel"
    # matriz de riscos ausente
    assert por_id["PB-06-002"].status.value == "nao_conforme"
    # PCA está citado no texto, ainda que quebrado entre linhas
    assert por_id["PB-05-103"].status.value == "conforme"


def test_aba_itens_exige_conferencia_humana(relatorio):
    achado = next(a for a in relatorio.achados if a.id == "PB-00-003")
    assert achado.status.value == "verificar_manual"


def test_indice_de_conformidade(relatorio):
    assert 0 <= relatorio.resumo.indice_conformidade <= 100
    assert relatorio.resumo.nao_conforme > 0


# --------------------------------------------------------------- relatórios

@pytest.mark.parametrize("formato", ["json", "md", "docx", "xlsx", "pdf"])
def test_geracao_de_relatorios(relatorio, formato, tmp_path):
    caminho = FORMATOS[formato](relatorio, tmp_path / f"rel.{formato}")
    assert Path(caminho).exists()
    assert Path(caminho).stat().st_size > 500
