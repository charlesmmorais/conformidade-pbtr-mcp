"""Testes da citação do item do PB/TR nos achados.

Num PB denso, "página 4" não localiza o trecho para quem vai corrigir — o
analista precisa do número do item ("item 6.3.1"). O item é resolvido a partir
da citação, e não do que o agente declara, para não depender de o modelo
acertar a numeração.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import analisar  # noqa: E402
from conformidade_pbtr.modelos import Categoria, Origem  # noqa: E402
from conformidade_pbtr.relatorios import FORMATOS  # noqa: E402
from conformidade_pbtr.validadores import ortografia  # noqa: E402

PB_TESTE = RAIZ / "exemplos" / "PB_exemplo_com_erros.pdf"


@pytest.fixture(scope="module")
def relatorio():
    if not PB_TESTE.exists():
        subprocess.run([sys.executable, str(RAIZ / "exemplos" / "gerar_pb_teste.py")], check=True)
    return analisar(PB_TESTE)


# --------------------------------------------------- resolução do item

def test_localiza_item_a_partir_do_trecho(relatorio):
    item, pagina = ortografia.localizar_no_documento(relatorio.documento, "a nível de")
    assert item == "3.3", f"esperava o item 3.3, veio {item!r}"
    assert pagina == 1


def test_localiza_item_em_trecho_de_outra_secao(relatorio):
    item, _ = ortografia.localizar_no_documento(relatorio.documento, "frizar")
    assert item == "5.4"


def test_trecho_inexistente_nao_tem_item(relatorio):
    item, pagina = ortografia.localizar_no_documento(relatorio.documento, "isto não existe")
    assert item == ""
    assert pagina is None


def test_item_tolera_quebra_de_linha_e_caixa(relatorio):
    item, _ = ortografia.localizar_no_documento(relatorio.documento, "A   NÍVEL\n  DE")
    assert item == "3.3"


# ------------------------------------------------ propagação nos achados

def test_achado_deterministico_cita_o_item(relatorio):
    ort = [a for a in relatorio.achados if a.categoria == Categoria.ORTOGRAFIA]
    assert ort, "nenhum achado de revisão"
    assert any(a.item for a in ort), "nenhum achado determinístico trouxe o item"


def test_apontamento_do_agente_cita_o_item(relatorio):
    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "afim de", "sugestao": "a fim de", "tipo": "gramatica"}],
    )
    assert len(aceitos) == 1
    assert aceitos[0].item == "5.1"
    assert aceitos[0].origem == Origem.IA


def test_item_resolvido_prevalece_sobre_o_declarado(relatorio):
    """O agente pode errar a numeração; o documento é a fonte."""
    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "afim de", "tipo": "gramatica", "item": "9.9.9"}],
    )
    assert aceitos[0].item == "5.1"


def test_item_declarado_vale_quando_nao_ha_numeracao(relatorio):
    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "PROJETO BÁSICO", "tipo": "clareza", "item": "cabeçalho"}],
    )
    if aceitos:  # o título não pertence a item numerado
        assert aceitos[0].item in ("", "cabeçalho")


def test_achado_de_checklist_cita_o_item(relatorio):
    com_item = [
        a for a in relatorio.achados
        if a.categoria == Categoria.CHECKLIST and a.evidencia and a.item
    ]
    assert com_item, "nenhum achado de checklist trouxe o item"


# ------------------------------------------------------- segmentação

def test_segmentos_trazem_o_item(relatorio):
    segmentos = ortografia.segmentar(relatorio.documento)
    assert any(s.item for s in segmentos)
    d = segmentos[0].to_dict()
    assert "texto" in d and "pagina" in d


# --------------------------------------------------------- relatórios

def test_item_aparece_nos_relatorios(relatorio, tmp_path):
    from conformidade_pbtr.analisador import recalcular

    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento, [{"trecho": "afim de", "sugestao": "a fim de", "tipo": "gramatica"}]
    )
    relatorio.achados.extend(aceitos)
    recalcular(relatorio)

    md = Path(FORMATOS["md"](relatorio, tmp_path / "r.md")).read_text(encoding="utf-8")
    assert "item 5.1" in md

    for fmt in ("docx", "xlsx", "pdf"):
        assert Path(FORMATOS[fmt](relatorio, tmp_path / f"r.{fmt}")).stat().st_size > 500

    relatorio.achados = [a for a in relatorio.achados if a.origem != Origem.IA]
    recalcular(relatorio)
