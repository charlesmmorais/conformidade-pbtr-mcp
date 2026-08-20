"""Testes dos formatos de entrada: .pdf, .docx, .md e .txt.

Markdown e texto são muito mais baratos que PDF. O que estes testes garantem é
que "mais barato" não significa "menos verificado": a numeração, as tabelas e a
aritmética precisam sair iguais.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import analisar  # noqa: E402
from conformidade_pbtr.extratores import pdf as extrator  # noqa: E402
from conformidade_pbtr.extratores.pdf import FORMATOS_ACEITOS  # noqa: E402
from conformidade_pbtr.modelos import Categoria, Status  # noqa: E402

PB_PDF = RAIZ / "exemplos" / "PB_exemplo_com_erros.pdf"

MD_EXEMPLO = """# PROJETO BÁSICO Nº 99/2026

## 1. OBJETO

1.1. Contratação de serviços de teste.

## 4. ESPECIFICAÇÃO DE VALORES E FORMAS DE PAGAMENTO

4.1. O valor total estimado é de **R$ 300.000,00** (trezentos mil reais).

| Item | Descrição | Quantidade | Valor Unitário | Valor Total |
|---|---|---|---|---|
| 1 | Serviço A | 10 | R$ 10.000,00 | R$ 100.000,00 |
| 2 | Serviço B | 20 | R$ 10.000,00 | R$ 250.000,00 |
|  | TOTAL |  |  | R$ 300.000,00 |

4.3. O pagamento será mensal.
"""


@pytest.fixture(scope="module")
def pb_pdf():
    if not PB_PDF.exists():
        subprocess.run([sys.executable, str(RAIZ / "exemplos" / "gerar_pb_teste.py")], check=True)
    return PB_PDF


# ------------------------------------------------------------- despacho

def test_formatos_aceitos_declarados():
    assert set(FORMATOS_ACEITOS) == {".pdf", ".docx", ".md", ".markdown", ".txt"}


def test_extensao_desconhecida_falha_com_mensagem_util(tmp_path):
    alvo = tmp_path / "planilha.xlsx"
    alvo.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Formato não suportado"):
        extrator.carregar(alvo)


@pytest.mark.parametrize("ext", [".md", ".markdown", ".txt"])
def test_carrega_formatos_de_texto(tmp_path, ext):
    alvo = tmp_path / f"pb{ext}"
    alvo.write_text(MD_EXEMPLO, encoding="utf-8")
    doc = extrator.carregar(alvo, tipo="PB")
    assert doc.formato == ext.lstrip(".")
    assert doc.texto.strip()


def test_pdf_registra_o_formato(pb_pdf):
    assert extrator.carregar(pb_pdf).formato == "pdf"


# ------------------------------------------------------ conteúdo do MD

@pytest.fixture
def doc_md(tmp_path):
    alvo = tmp_path / "pb.md"
    alvo.write_text(MD_EXEMPLO, encoding="utf-8")
    return extrator.carregar(alvo, tipo="PB")


def test_numeracao_reconhecida_no_md(doc_md):
    numeros = {b.numeracao for b in doc_md.blocos if b.numeracao}
    assert {"1", "1.1", "4", "4.1", "4.3"} <= numeros


def test_tabela_markdown_vira_tabela(doc_md):
    assert len(doc_md.tabelas) == 1
    t = doc_md.tabelas[0]
    assert t.cabecalho == ["Item", "Descrição", "Quantidade", "Valor Unitário", "Valor Total"]
    assert len(t.linhas) == 3
    assert t.linhas[0][4].numero == 100000.0


def test_marcacao_markdown_nao_vaza_para_o_texto(doc_md):
    assert "**" not in doc_md.texto
    assert "R$ 300.000,00" in doc_md.texto


def test_aritmetica_roda_sobre_tabela_markdown(tmp_path):
    """A linha 2 tem 20 x 10.000 = 200.000, mas declara 250.000."""
    alvo = tmp_path / "pb.md"
    alvo.write_text(MD_EXEMPLO, encoding="utf-8")
    rel = analisar(alvo, tipo="PB")
    divergencias = [
        a for a in rel.achados
        if a.categoria == Categoria.TABELA and a.status == Status.NAO_CONFORME
    ]
    assert divergencias, "a divergência aritmética não foi detectada no Markdown"
    assert any("250.000,00" in a.encontrado for a in divergencias)


def test_avisa_quando_texto_nao_tem_tabela(tmp_path):
    alvo = tmp_path / "pb.txt"
    alvo.write_text("1. OBJETO\n1.1. Contratação de serviços.\n", encoding="utf-8")
    rel = analisar(alvo, tipo="PB")
    assert any("tabela" in a.lower() for a in rel.avisos)


def test_nao_avisa_de_ocr_em_arquivo_de_texto(tmp_path):
    alvo = tmp_path / "pb.txt"
    alvo.write_text("1. OBJETO\n", encoding="utf-8")
    rel = analisar(alvo, tipo="PB")
    assert not any("digitalizado" in a for a in rel.avisos)


# ------------------------------------------- equivalência entre formatos

def test_mesmo_conteudo_produz_a_mesma_analise(pb_pdf, tmp_path):
    """PDF e Markdown com o mesmo conteúdo devem dar o mesmo resultado."""
    doc = extrator.carregar(pb_pdf, tipo="PB")

    linhas = [b.texto for b in doc.blocos]
    for t in doc.tabelas:
        if not t.cabecalho or not t.linhas:
            continue
        linhas += ["", "| " + " | ".join(c or " " for c in t.cabecalho) + " |",
                   "|" + "|".join("---" for _ in t.cabecalho) + "|"]
        for linha in t.linhas:
            celulas = [c.bruto or " " for c in linha]
            celulas += [" "] * (len(t.cabecalho) - len(celulas))
            linhas.append("| " + " | ".join(celulas[: len(t.cabecalho)]) + " |")
        linhas.append("")

    alvo = tmp_path / "convertido.md"
    alvo.write_text("\n".join(linhas), encoding="utf-8")

    rel_pdf = analisar(pb_pdf, tipo="PB")
    rel_md = analisar(alvo, tipo="PB")

    assert rel_pdf.resumo.indice_conformidade == rel_md.resumo.indice_conformidade
    ids_pdf = {(a.id, a.status.value) for a in rel_pdf.achados}
    ids_md = {(a.id, a.status.value) for a in rel_md.achados}
    assert ids_pdf == ids_md

    itens_pdf = {a.id: a.item for a in rel_pdf.achados}
    itens_md = {a.id: a.item for a in rel_md.achados}
    assert itens_pdf == itens_md
