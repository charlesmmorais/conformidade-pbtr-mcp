"""Relatório em PDF (versão final, para juntada ao processo)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..modelos import Categoria, Origem, Relatorio, Status

CORES = {
    Status.CONFORME: colors.HexColor("#C6EFCE"),
    Status.NAO_CONFORME: colors.HexColor("#FFC7CE"),
    Status.ATENCAO: colors.HexColor("#FFEB9C"),
    Status.VERIFICAR_MANUAL: colors.HexColor("#DDEBF7"),
    Status.NAO_APLICAVEL: colors.HexColor("#F2F2F2"),
}

ROTULO = {
    Status.CONFORME: "Conforme",
    Status.NAO_CONFORME: "Não conforme",
    Status.ATENCAO: "Atenção",
    Status.VERIFICAR_MANUAL: "Verificar",
    Status.NAO_APLICAVEL: "N/A",
}

TITULO_CATEGORIA = {
    Categoria.CHECKLIST: "Conformidade com o roteiro [TI]",
    Categoria.ESTRUTURA: "Estrutura do documento",
    Categoria.NUMERACAO: "Numeração dos itens",
    Categoria.TABELA: "Tabelas e aritmética",
    Categoria.VALOR: "Valores declarados",
    Categoria.ORTOGRAFIA: "Revisão textual",
}


def _escapar(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def gerar_pdf(rel: Relatorio, destino: str | Path) -> str:
    d = Path(destino)
    base = getSampleStyleSheet()

    st_titulo = ParagraphStyle("T", parent=base["Title"], fontSize=16, spaceAfter=6)
    st_h1 = ParagraphStyle("H1", parent=base["Heading1"], fontSize=12,
                           textColor=colors.HexColor("#1F4E79"), spaceBefore=12)
    st_corpo = ParagraphStyle("C", parent=base["BodyText"], fontSize=8.5,
                              leading=11, alignment=TA_JUSTIFY)
    st_cel = ParagraphStyle("Cel", parent=st_corpo, fontSize=7, leading=8.5)
    st_cab = ParagraphStyle("Cab", parent=st_cel, textColor=colors.white,
                            fontName="Helvetica-Bold")

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm,
                          "MCP Conformidade PB/TR — uso interno")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"p. {doc.page}")
        canvas.restoreState()

    docp = BaseDocTemplate(str(d), pagesize=A4,
                           leftMargin=2 * cm, rightMargin=2 * cm,
                           topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    frame = Frame(docp.leftMargin, docp.bottomMargin, docp.width, docp.height, id="f")
    docp.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=rodape)])

    fluxo = []
    fluxo.append(Paragraph("Relatório de Análise de Conformidade", st_titulo))
    fluxo.append(Paragraph(
        f"<b>{_escapar(rel.documento.nome)}</b> — {rel.documento.tipo} · .{rel.documento.formato} · "
        f"{rel.documento.paginas} página(s) · gerado em {rel.gerado_em} · "
        f"checklist v{rel.versao_checklist}", st_corpo))
    fluxo.append(Spacer(1, 10))

    r = rel.resumo
    dados = [
        [Paragraph("Situação", st_cab), Paragraph("Qtd.", st_cab),
         Paragraph("Verificação automática", st_cab), Paragraph("Ocorr.", st_cab)],
        ["Conforme", r.conforme, "Erros de numeração", r.erros_numeracao],
        ["Não conforme", r.nao_conforme, "Divergências em tabelas/valores", r.erros_tabela],
        ["Atenção", r.atencao, "Revisão textual (regra)", r.erros_ortografia],
        ["Verificar manualmente", r.verificar_manual, "Sugestões do agente", r.sugestoes_ia],
        ["Não aplicável", r.nao_aplicavel, "Índice de conformidade",
         f"{r.indice_conformidade}%"],
    ]
    t = Table(dados, colWidths=[5.2 * cm, 1.6 * cm, 7.0 * cm, 2.2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
    ]))
    fluxo.append(t)

    if rel.avisos:
        fluxo.append(Spacer(1, 8))
        fluxo.append(Paragraph("Avisos da análise", st_h1))
        for av in rel.avisos:
            fluxo.append(Paragraph("• " + _escapar(av), st_corpo))

    # ------------------------------------------------------- checklist
    itens = sorted(rel.por_categoria(Categoria.CHECKLIST), key=lambda x: x.id)
    if itens:
        fluxo.append(Paragraph(TITULO_CATEGORIA[Categoria.CHECKLIST], st_h1))
        linhas = [[Paragraph(c, st_cab) for c in
                   ("ID", "Item do roteiro", "Situação", "Constatação / recomendação")]]
        estilos = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        for i, a in enumerate(itens, start=1):
            if a.status in (Status.CONFORME, Status.NAO_APLICAVEL):
                detalhe = a.encontrado or "—"
            else:
                detalhe = a.orientacao or a.encontrado or "—"
            linhas.append([
                Paragraph(a.id, st_cel),
                Paragraph(f"<b>{_escapar(a.secao)}</b><br/>{_escapar(a.titulo)}", st_cel),
                Paragraph(ROTULO[a.status], st_cel),
                Paragraph(_escapar(detalhe)[:400], st_cel),
            ])
            estilos.append(("BACKGROUND", (2, i), (2, i), CORES[a.status]))
        tab = Table(linhas, colWidths=[1.7 * cm, 5.6 * cm, 2.1 * cm, 6.6 * cm], repeatRows=1)
        tab.setStyle(TableStyle(estilos))
        fluxo.append(tab)

    # ------------------------------------------- verificações automáticas
    for cat in (Categoria.ESTRUTURA, Categoria.NUMERACAO, Categoria.TABELA,
                Categoria.VALOR, Categoria.ORTOGRAFIA):
        itens = [a for a in rel.por_categoria(cat) if a.status != Status.CONFORME]
        if not itens:
            continue
        fluxo.append(Paragraph(TITULO_CATEGORIA[cat], st_h1))
        if cat == Categoria.ORTOGRAFIA and any(a.origem == Origem.IA for a in itens):
            fluxo.append(Paragraph(
                "<i>Os itens marcados como “sugestão” vêm da leitura do texto por "
                "modelo de linguagem: o trecho citado foi conferido contra o "
                "documento, mas a revisão não é reprodutível.</i>", st_corpo))
        linhas = [[Paragraph(c, st_cab) for c in
                   ("ID", "Ocorrência", "Esperado", "Encontrado", "Recomendação")]]
        estilos = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        for i, a in enumerate(itens[:120], start=1):
            marca = " <b>(sugestão)</b>" if a.origem == Origem.IA else ""
            linhas.append([
                Paragraph(a.id, st_cel),
                Paragraph(_escapar(a.titulo) + marca, st_cel),
                Paragraph(_escapar(a.esperado)[:180], st_cel),
                Paragraph(_escapar(a.encontrado)[:180], st_cel),
                Paragraph(_escapar(a.orientacao)[:220], st_cel),
            ])
            estilos.append(("BACKGROUND", (0, i), (0, i), CORES[a.status]))
        tab = Table(linhas, colWidths=[1.9 * cm, 4.0 * cm, 3.4 * cm, 3.4 * cm, 3.3 * cm],
                    repeatRows=1)
        tab.setStyle(TableStyle(estilos))
        fluxo.append(tab)

    fluxo.append(Spacer(1, 12))
    fluxo.append(Paragraph(
        "<i>As verificações automáticas não substituem a análise do parecerista. "
        "Itens marcados como “Verificar” exigem conferência humana, notadamente a "
        "aderência entre a Aba Itens e as quantidades do PB.</i>", st_corpo))

    docp.build(fluxo)
    return str(d)
