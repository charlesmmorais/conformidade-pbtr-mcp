"""Testes da resolução de recursos (checklist e dicionário) e do formato do YAML."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conformidade_pbtr import caminhos  # noqa: E402
from conformidade_pbtr.validadores import checklist as mod_checklist  # noqa: E402

SEVERIDADES = {"critico", "alto", "medio", "informativo"}
VERIFICACOES = {"presenca", "coerencia", "anexo", "manual", "numeracao", "calculo"}


@pytest.fixture(scope="module")
def dados():
    mod_checklist.carregar.cache_clear()
    return mod_checklist.carregar()


# ------------------------------------------------------------- resolução

def test_checklist_padrao_existe():
    assert caminhos.caminho_checklist().exists()


def test_dicionario_existe():
    assert caminhos.caminho_dicionario() is not None


def test_variavel_de_ambiente_tem_precedencia(tmp_path, monkeypatch):
    alternativo = tmp_path / "outro.yaml"
    alternativo.write_text(
        "metadata:\n  versao: '9.9.9'\nregras: []\n", encoding="utf-8"
    )
    monkeypatch.setenv("CONFORMIDADE_PBTR_CHECKLIST", str(alternativo))
    assert caminhos.caminho_checklist() == alternativo

    mod_checklist.carregar.cache_clear()
    assert mod_checklist.carregar()["metadata"]["versao"] == "9.9.9"
    mod_checklist.carregar.cache_clear()


def test_checklist_inexistente_falha_com_mensagem_util(monkeypatch):
    monkeypatch.setenv("CONFORMIDADE_PBTR_CHECKLIST", "/nao/existe/x.yaml")
    with pytest.raises(FileNotFoundError, match="CONFORMIDADE_PBTR_CHECKLIST"):
        caminhos.caminho_checklist()


def test_lista_checklists_disponiveis():
    disponiveis = caminhos.checklists_disponiveis()
    assert "checklist_roteiro_ti.yaml" in disponiveis


# ------------------------------------------------------ formato do YAML

def test_metadata_registra_arquivo_usado(dados):
    assert dados["metadata"]["arquivo"] == "checklist_roteiro_ti.yaml"
    assert re.fullmatch(r"\d+\.\d+\.\d+", dados["metadata"]["versao"])


def test_ids_sao_unicos(dados):
    ids = [r["id"] for r in dados["regras"]]
    assert len(ids) == len(set(ids)), "há ids repetidos no checklist"


def test_campos_obrigatorios_de_cada_regra(dados):
    for regra in dados["regras"]:
        rid = regra.get("id", "<sem id>")
        for campo in ("id", "secao", "titulo", "aplicabilidade", "severidade", "verificacao"):
            assert regra.get(campo), f"regra {rid}: campo '{campo}' ausente"
        assert regra["severidade"] in SEVERIDADES, f"regra {rid}: severidade inválida"
        assert regra["verificacao"] in VERIFICACOES, f"regra {rid}: verificação inválida"


def test_toda_regra_tem_orientacao_ou_e_meramente_informativa(dados):
    """Um apontamento sem recomendação transfere trabalho ao analista."""
    for regra in dados["regras"]:
        if regra["severidade"] == "informativo":
            continue
        assert regra.get("orientacao"), f"regra {regra['id']}: sem orientação"


def test_gatilhos_sao_regex_validos(dados):
    for regra in dados["regras"]:
        for gatilho in regra.get("gatilhos") or []:
            try:
                re.compile(gatilho)
            except re.error as exc:
                pytest.fail(f"regra {regra['id']}: gatilho inválido {gatilho!r} ({exc})")


def test_tags_de_aplicabilidade_estao_na_taxonomia(dados):
    taxonomia = set(dados.get("taxonomia_aplicabilidade") or {})
    for regra in dados["regras"]:
        for tag in regra["aplicabilidade"]:
            assert tag in taxonomia, f"regra {regra['id']}: tag '{tag}' fora da taxonomia"


def test_yaml_do_repositorio_carrega_sem_erro():
    for arq in (RAIZ / "recursos").glob("checklist_*.y*ml"):
        with open(arq, encoding="utf-8") as fh:
            dados = yaml.safe_load(fh)
        assert dados.get("regras"), f"{arq.name} não tem regras"
