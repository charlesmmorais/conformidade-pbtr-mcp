"""Testes da revisão textual feita pelo agente.

O ponto central é a trava contra citação inventada: um apontamento só entra no
relatório se o trecho citado existir literalmente no documento. Sem isso, uma
alucinação do modelo viraria achado num relatório que instrui processo.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import analisar  # noqa: E402
from conformidade_pbtr.modelos import Categoria, Origem, Status  # noqa: E402
from conformidade_pbtr.relatorios import FORMATOS  # noqa: E402
from conformidade_pbtr.validadores import ortografia  # noqa: E402

PB_TESTE = RAIZ / "exemplos" / "PB_exemplo_com_erros.pdf"


@pytest.fixture(scope="module")
def relatorio():
    if not PB_TESTE.exists():
        subprocess.run([sys.executable, str(RAIZ / "exemplos" / "gerar_pb_teste.py")], check=True)
    return analisar(PB_TESTE)


# ----------------------------------------------------------- segmentação

def test_segmenta_o_documento(relatorio):
    segmentos = ortografia.segmentar(relatorio.documento)
    assert segmentos, "nenhum segmento gerado"
    assert all(s.texto.strip() for s in segmentos)
    assert all(s.pagina >= 1 for s in segmentos)
    ids = [s.id for s in segmentos]
    assert len(ids) == len(set(ids))


def test_segmentos_respeitam_o_tamanho_maximo(relatorio):
    for s in ortografia.segmentar(relatorio.documento, max_caracteres=600):
        # um bloco isolado pode estourar o teto; o corte é entre blocos
        assert len(s.texto) < 600 + 400


def test_segmentacao_descarta_ruido(relatorio):
    textos = [s.texto for s in ortografia.segmentar(relatorio.documento)]
    juntos = "\n".join(textos)
    # linhas que são só numeração ou valores não viram segmento próprio
    assert not any(t.strip().isdigit() for t in juntos.split("\n"))


# ------------------------------------------------ trava contra alucinação

def test_aceita_apontamento_com_trecho_literal(relatorio):
    aceitos, recusados = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "a nível de", "sugestao": "em nível de", "tipo": "impropriedade",
          "explicacao": "Locução inadequada."}],
    )
    assert len(aceitos) == 1
    assert not recusados
    achado = aceitos[0]
    assert achado.origem == Origem.IA
    assert achado.status == Status.ATENCAO
    assert achado.categoria == Categoria.ORTOGRAFIA


def test_recusa_trecho_inexistente(relatorio):
    aceitos, recusados = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "cláusula que jamais foi escrita neste documento",
          "sugestao": "x", "tipo": "gramatica"}],
    )
    assert not aceitos
    assert len(recusados) == 1
    assert "não localizado" in recusados[0]["motivo"]


def test_recusa_trecho_vazio_ou_curto(relatorio):
    aceitos, recusados = ortografia.converter_apontamentos(
        relatorio.documento, [{"trecho": "a"}, {"sugestao": "sem trecho"}]
    )
    assert not aceitos
    assert len(recusados) == 2


def test_recusa_duplicado(relatorio):
    aceitos, recusados = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "a nível de", "tipo": "impropriedade"},
         {"trecho": "a nível de", "tipo": "clareza"}],
    )
    assert len(aceitos) == 1
    assert len(recusados) == 1
    assert "duplicado" in recusados[0]["motivo"]


def test_tolera_diferenca_de_espacamento_e_aspas(relatorio):
    """O PDF quebra linhas no meio da frase; a comparação normaliza espaço."""
    aceitos, recusados = ortografia.converter_apontamentos(
        relatorio.documento, [{"trecho": "a   nível\n  de", "tipo": "impropriedade"}]
    )
    assert len(aceitos) == 1, recusados


def test_lista_vazia_nao_gera_achado(relatorio):
    aceitos, recusados = ortografia.converter_apontamentos(relatorio.documento, [])
    assert not aceitos and not recusados


# ------------------------------------------------- integração no relatório

def test_achados_de_ia_ficam_fora_do_indice(relatorio):
    from conformidade_pbtr.analisador import recalcular

    indice_antes = relatorio.resumo.indice_conformidade
    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento, [{"trecho": "afim de", "tipo": "gramatica", "sugestao": "a fim de"}]
    )
    relatorio.achados.extend(aceitos)
    recalcular(relatorio)
    assert relatorio.resumo.indice_conformidade == indice_antes
    assert relatorio.resumo.sugestoes_ia == len(aceitos)

    relatorio.achados = [a for a in relatorio.achados if a.origem != Origem.IA]
    recalcular(relatorio)


def test_relatorios_separam_as_origens(relatorio, tmp_path):
    from conformidade_pbtr.analisador import recalcular

    aceitos, _ = ortografia.converter_apontamentos(
        relatorio.documento,
        [{"trecho": "prazo de execução", "tipo": "ambiguidade",
          "sugestao": "definir o marco inicial do prazo",
          "explicacao": "O termo inicial não está definido."}],
    )
    relatorio.achados.extend(aceitos)
    recalcular(relatorio)

    md = Path(FORMATOS["md"](relatorio, tmp_path / "rel.md")).read_text(encoding="utf-8")
    assert "Verificações determinísticas" in md
    assert "Sugestões da revisão pelo agente" in md
    assert "não é reprodutível" in md

    for fmt in ("docx", "xlsx", "pdf", "json"):
        caminho = Path(FORMATOS[fmt](relatorio, tmp_path / f"rel.{fmt}"))
        assert caminho.stat().st_size > 500

    relatorio.achados = [a for a in relatorio.achados if a.origem != Origem.IA]
    recalcular(relatorio)


def test_nenhuma_dependencia_de_languagetool():
    """A remoção precisa ser real: nada de import residual."""
    fontes = list((RAIZ / "src").rglob("*.py"))
    for f in fontes:
        conteudo = f.read_text(encoding="utf-8")
        assert "language_tool_python" not in conteudo, f"{f.name} ainda importa o LanguageTool"
    assert "language-tool-python" not in (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
