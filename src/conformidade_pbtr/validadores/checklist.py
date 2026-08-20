"""Motor de regras: aplica um checklist YAML ao documento.

O motor não conhece norma alguma — tudo o que ele sabe vem do arquivo de
checklist. Ver `docs/CHECKLIST.md` para o formato e `caminhos.py` para a ordem
de resolução do arquivo.
"""

from __future__ import annotations

import functools
import re
from typing import Any

import yaml

from ..caminhos import caminho_checklist
from ..extratores.pdf import normalizar
from ..modelos import Achado, Categoria, Documento, Severidade, Status
from .ortografia import item_antes_de, item_do_bloco

VERIFICACAO_MANUAL = {"coerencia", "anexo", "manual"}


@functools.lru_cache(maxsize=8)
def carregar(caminho: str | None = None) -> dict[str, Any]:
    """Carrega um checklist YAML.

    `caminho` aceita o caminho de um arquivo, o nome de um checklist embarcado
    (nome de arquivo em `recursos/`) ou None — caso
    em que vale a variável ``CONFORMIDADE_PBTR_CHECKLIST`` ou o padrão.
    """
    p = caminho_checklist(caminho)
    with open(p, encoding="utf-8") as fh:
        dados = yaml.safe_load(fh) or {}
    dados.setdefault("metadata", {})["arquivo"] = p.name
    return dados


def _aplicavel(regra: dict, tags: set[str]) -> bool:
    alvo = set(regra.get("aplicabilidade") or ["sempre"])
    if "sempre" in alvo:
        return True
    return bool(alvo & tags)


def _casar(gatilhos: list[str], texto_norm: str) -> list[str]:
    """Devolve os gatilhos que casaram (padrões já em forma normalizada)."""
    casados = []
    for g in gatilhos:
        try:
            if re.search(normalizar(g), texto_norm, re.IGNORECASE | re.MULTILINE):
                casados.append(g)
        except re.error:
            continue
    return casados


def _evidencia(doc: Documento, padrao: str) -> tuple[str, int | None, str]:
    """Primeiro bloco que casa com o padrão: (trecho, página, item do PB/TR)."""
    p = normalizar(padrao)
    janela = 2  # tolera expressão partida entre linhas
    for i, bloco in enumerate(doc.blocos):
        trecho = " ".join(b.texto for b in doc.blocos[i : i + janela])
        try:
            achatado = re.sub(r"\s+", " ", normalizar(trecho))
            m = re.search(p, achatado, re.IGNORECASE)
            if m:
                item = item_antes_de(achatado, m.start()) or item_do_bloco(doc, i)
                return bloco.texto[:300], bloco.pagina, item
        except re.error:
            break
    return "", None, ""


def validar(doc: Documento, checklist: str | None = None) -> tuple[list[Achado], str]:
    dados = carregar(checklist)
    meta = dados.get("metadata") or {}
    versao = f"{meta.get('versao', '?')} ({meta.get('arquivo', '?')})"
    tags = set(doc.tags_contexto) | {"sempre"}
    # quebras de linha do PDF partem expressões ("Plano de\nContratações"):
    # colapsa todo espaçamento para que os gatilhos casem
    texto_norm = re.sub(r"\s+", " ", normalizar(doc.texto))

    achados: list[Achado] = []
    for regra in dados.get("regras", []):
        rid = regra["id"]
        severidade = Severidade(regra.get("severidade", "medio"))
        verificacao = regra.get("verificacao", "presenca")

        base = dict(
            id=rid,
            categoria=Categoria.CHECKLIST,
            titulo=regra["titulo"],
            severidade=severidade,
            secao=regra.get("secao", ""),
            descricao=" ".join((regra.get("descricao") or "").split()),
            orientacao=" ".join((regra.get("orientacao") or "").split()),
            fundamento=(
                regra.get("fundamento")
                or f"{meta.get('fonte', 'Checklist')} — {regra.get('secao', '')}"
            )
            + f" (regra {rid}, checklist v{versao})",
        )

        if not _aplicavel(regra, tags):
            achados.append(
                Achado(
                    **base,
                    status=Status.NAO_APLICAVEL,
                    encontrado=(
                        "Contexto do documento não aciona esta regra "
                        f"(exige: {', '.join(regra.get('aplicabilidade', []))})"
                    ),
                )
            )
            continue

        gatilhos = regra.get("gatilhos") or []
        if not gatilhos:
            achados.append(
                Achado(**base, status=Status.VERIFICAR_MANUAL,
                       encontrado="Item sem gatilho textual — exige conferência do analista.")
            )
            continue

        casados = _casar(gatilhos, texto_norm)
        exige_todos = bool(regra.get("exige_todos_gatilhos"))
        inverter = bool(regra.get("inverter"))

        if inverter:
            # a regra é uma vedação: casar o gatilho é o sinal de alerta
            if casados:
                evid, pag, item = _evidencia(doc, casados[0])
                achados.append(
                    Achado(**base, status=Status.ATENCAO, pagina=pag, item=item, evidencia=evid,
                           esperado="ausência da hipótese vedada ou justificativa específica",
                           encontrado=f"ocorrência de: {casados[0]}")
                )
            else:
                achados.append(Achado(**base, status=Status.CONFORME,
                                      encontrado="hipótese vedada não identificada"))
            continue

        atende = (len(casados) == len(gatilhos)) if exige_todos else bool(casados)
        faltantes = [g for g in gatilhos if g not in casados]

        if atende and verificacao in VERIFICACAO_MANUAL:
            evid, pag, item = _evidencia(doc, casados[0])
            achados.append(
                Achado(**base, status=Status.VERIFICAR_MANUAL, pagina=pag, item=item, evidencia=evid,
                       encontrado="Indício localizado no texto; a aderência exige conferência humana.")
            )
        elif atende:
            evid, pag, item = _evidencia(doc, casados[0])
            achados.append(
                Achado(**base, status=Status.CONFORME, pagina=pag, item=item, evidencia=evid,
                       encontrado=f"{len(casados)}/{len(gatilhos)} indício(s) localizado(s)")
            )
        elif casados and exige_todos:
            evid, pag, item = _evidencia(doc, casados[0])
            achados.append(
                Achado(**base, status=Status.ATENCAO, pagina=pag, item=item, evidencia=evid,
                       esperado=f"todos os elementos: {', '.join(gatilhos)}",
                       encontrado=f"ausentes: {', '.join(faltantes)}")
            )
        else:
            achados.append(
                Achado(**base, status=Status.NAO_CONFORME,
                       esperado=f"presença de: {', '.join(gatilhos)}",
                       encontrado="nenhuma ocorrência localizada no documento")
            )

    return achados, versao
