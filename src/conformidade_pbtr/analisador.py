"""Orquestrador da análise de conformidade de PB/TR."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .extratores import pdf as extrator
from .modelos import Categoria, Documento, Origem, Relatorio, Resumo, Severidade, Status
from .validadores import checklist, contexto, numeracao, ortografia
from .validadores import tabelas as val_tabelas

TZ = ZoneInfo("America/Sao_Paulo")


def _calcular_resumo(rel: Relatorio) -> Resumo:
    r = Resumo()
    peso_total = 0.0
    peso_obtido = 0.0

    for a in rel.achados:
        if a.categoria == Categoria.CHECKLIST:
            r.total_regras += 1
        if a.status == Status.CONFORME:
            r.conforme += 1
        elif a.status == Status.NAO_CONFORME:
            r.nao_conforme += 1
        elif a.status == Status.ATENCAO:
            r.atencao += 1
        elif a.status == Status.NAO_APLICAVEL:
            r.nao_aplicavel += 1
        elif a.status == Status.VERIFICAR_MANUAL:
            r.verificar_manual += 1

        if a.categoria == Categoria.NUMERACAO and a.status == Status.NAO_CONFORME:
            r.erros_numeracao += 1
        if a.categoria in (Categoria.TABELA, Categoria.VALOR) and a.status == Status.NAO_CONFORME:
            r.erros_tabela += 1
        if a.categoria == Categoria.ORTOGRAFIA:
            if a.origem == Origem.IA:
                r.sugestoes_ia += 1
            elif a.status == Status.NAO_CONFORME:
                r.erros_ortografia += 1

        # índice: só entram itens avaliáveis automaticamente
        if a.status in (Status.CONFORME, Status.NAO_CONFORME, Status.ATENCAO) and \
                a.severidade != Severidade.INFORMATIVO and \
                a.categoria != Categoria.ORTOGRAFIA:
            peso_total += a.severidade.peso
            if a.status == Status.CONFORME:
                peso_obtido += a.severidade.peso
            elif a.status == Status.ATENCAO:
                peso_obtido += a.severidade.peso * 0.5

    r.indice_conformidade = round(100 * peso_obtido / peso_total, 1) if peso_total else 0.0
    return r


def recalcular(rel: Relatorio) -> Relatorio:
    """Recalcula o resumo — usado depois de acrescentar a revisão do agente."""
    rel.resumo = _calcular_resumo(rel)
    return rel


def analisar(
    caminho: str | Path,
    tipo: str = "PB",
    revisar_texto: bool = True,
    limite_ortografia: int = 200,
    caminho_checklist: str | None = None,
    tags_forcadas: list[str] | None = None,
) -> Relatorio:
    """Executa a análise determinística e devolve o Relatorio.

    A revisão textual pelo agente não acontece aqui: ela é acrescentada depois,
    via `registrar_revisao_textual`, porque quem revisa é o modelo que chamou o
    MCP e já tem o documento em contexto.
    """
    doc: Documento = extrator.carregar(caminho, tipo=tipo)
    doc.tags_contexto = sorted(set(contexto.inferir(doc)) | set(tags_forcadas or []))

    rel = Relatorio(documento=doc, gerado_em=datetime.now(TZ).strftime("%d/%m/%Y %H:%M"))

    achados_checklist, versao = checklist.validar(doc, caminho_checklist)
    rel.versao_checklist = versao
    rel.achados.extend(achados_checklist)
    rel.achados.extend(numeracao.validar(doc))
    rel.achados.extend(val_tabelas.validar(doc))

    if revisar_texto:
        rel.achados.extend(ortografia.validar(doc, limite_ortografia))

    if doc.formato == "pdf" and doc.paginas and len(doc.texto.strip()) < 200 * doc.paginas:
        rel.avisos.append(
            "Pouco texto extraído por página — o PDF pode ser digitalizado. "
            "Recomenda-se aplicar OCR antes da análise."
        )

    if doc.formato in ("md", "markdown", "txt") and not doc.tabelas:
        rel.avisos.append(
            "Nenhuma tabela reconhecida no arquivo: a validação aritmética não "
            "rodou. Em Markdown as tabelas precisam do formato de pipes "
            "(| coluna | coluna |) com a linha separadora abaixo do cabeçalho."
        )

    rel.resumo = _calcular_resumo(rel)
    return rel
