"""Relatório em Markdown e JSON."""

from __future__ import annotations

import json
from pathlib import Path

from ..modelos import Categoria, Origem, Relatorio, Status

ICONE = {
    Status.CONFORME: "✅",
    Status.NAO_CONFORME: "❌",
    Status.ATENCAO: "⚠️",
    Status.VERIFICAR_MANUAL: "🔎",
    Status.NAO_APLICAVEL: "➖",
}

ROTULO = {
    Status.CONFORME: "Conforme",
    Status.NAO_CONFORME: "Não conforme",
    Status.ATENCAO: "Atenção",
    Status.VERIFICAR_MANUAL: "Verificar manualmente",
    Status.NAO_APLICAVEL: "Não aplicável",
}

TITULO_CATEGORIA = {
    Categoria.CHECKLIST: "1. Conformidade com o roteiro [TI]",
    Categoria.ESTRUTURA: "2. Estrutura do documento",
    Categoria.NUMERACAO: "3. Numeração dos itens",
    Categoria.TABELA: "4. Tabelas e aritmética",
    Categoria.VALOR: "5. Valores declarados",
    Categoria.ORTOGRAFIA: "6. Revisão textual",
}


def _classificacao(indice: float) -> str:
    if indice >= 90:
        return "Apto — ajustes pontuais"
    if indice >= 75:
        return "Apto com ressalvas"
    if indice >= 50:
        return "Requer revisão substantiva"
    return "Não apto — reformulação necessária"


def gerar_markdown(rel: Relatorio, destino: str | Path) -> str:
    d = Path(destino)
    r = rel.resumo
    L: list[str] = []

    L.append(f"# Relatório de Análise de Conformidade — {rel.documento.tipo}")
    L.append("")
    L.append(f"**Documento analisado:** {rel.documento.nome}  ")
    L.append(f"**Formato analisado:** .{rel.documento.formato} · **Páginas:** {rel.documento.paginas} · **Tabelas detectadas:** {len(rel.documento.tabelas)}  ")
    L.append(f"**Gerado em:** {rel.gerado_em} · **Checklist v{rel.versao_checklist}**  ")
    L.append(f"**Contexto inferido:** {', '.join(rel.documento.tags_contexto)}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## Sumário executivo")
    L.append("")
    L.append(f"**Índice de conformidade: {r.indice_conformidade}%** — {_classificacao(r.indice_conformidade)}")
    L.append("")
    L.append("| Situação | Qtd. |")
    L.append("|---|---:|")
    L.append(f"| ✅ Conforme | {r.conforme} |")
    L.append(f"| ❌ Não conforme | {r.nao_conforme} |")
    L.append(f"| ⚠️ Atenção | {r.atencao} |")
    L.append(f"| 🔎 Verificar manualmente | {r.verificar_manual} |")
    L.append(f"| ➖ Não aplicável | {r.nao_aplicavel} |")
    L.append("")
    L.append("| Verificação automática | Ocorrências |")
    L.append("|---|---:|")
    L.append(f"| Erros de numeração | {r.erros_numeracao} |")
    L.append(f"| Divergências em tabelas/valores | {r.erros_tabela} |")
    L.append(f"| Apontamentos de revisão textual (regra) | {r.erros_ortografia} |")
    L.append(f"| Sugestões da revisão pelo agente | {r.sugestoes_ia} |")
    L.append("")

    pend = rel.pendencias()
    criticas = [a for a in pend if a.severidade.value == "critico" and a.status == Status.NAO_CONFORME]
    if criticas:
        L.append("### Pendências críticas")
        L.append("")
        for a in criticas[:15]:
            L.append(f"- **[{a.id}]** {a.titulo} — _{a.secao}_")
        L.append("")

    if rel.avisos:
        L.append("### Avisos da análise")
        L.append("")
        for av in rel.avisos:
            L.append(f"- {av}")
        L.append("")

    L.append("---")
    L.append("")

    for cat in [
        Categoria.CHECKLIST,
        Categoria.ESTRUTURA,
        Categoria.NUMERACAO,
        Categoria.TABELA,
        Categoria.VALOR,
        Categoria.ORTOGRAFIA,
    ]:
        itens = rel.por_categoria(cat)
        if not itens:
            continue
        L.append(f"## {TITULO_CATEGORIA[cat]}")
        L.append("")
        if cat == Categoria.CHECKLIST:
            secao_atual = None
            for a in sorted(itens, key=lambda x: x.id):
                if a.secao != secao_atual:
                    secao_atual = a.secao
                    L.append(f"### {secao_atual}")
                    L.append("")
                L.append(f"**{ICONE[a.status]} [{a.id}] {a.titulo}** — {ROTULO[a.status]}")
                L.append("")
                if a.status in (Status.NAO_CONFORME, Status.ATENCAO, Status.VERIFICAR_MANUAL):
                    if a.descricao:
                        L.append(f"> {a.descricao}")
                        L.append("")
                    if a.encontrado:
                        L.append(f"- Encontrado: {a.encontrado}")
                    if a.evidencia:
                        onde = f"item {a.item}, p. {a.pagina}" if a.item else f"p. {a.pagina or '—'}"
                        L.append(f"- Evidência ({onde}): _{a.evidencia[:220]}_")
                    if a.orientacao:
                        L.append(f"- **Recomendação:** {a.orientacao}")
                    L.append("")
        elif cat == Categoria.ORTOGRAFIA:
            for origem, subtitulo, nota in (
                (
                    Origem.DETERMINISTICO,
                    "6.1 Verificações determinísticas",
                    "Regras exatas e reprodutíveis — mesmo documento, mesmo resultado.",
                ),
                (
                    Origem.IA,
                    "6.2 Sugestões da revisão pelo agente",
                    "Leitura do texto por modelo de linguagem. Cada trecho citado foi "
                    "conferido contra o documento, mas a revisão não é reprodutível: "
                    "trate como sugestão, não como constatação.",
                ),
            ):
                subitens = rel.por_categoria(cat, origem)
                if not subitens:
                    continue
                L.append(f"### {subtitulo}")
                L.append("")
                L.append(f"_{nota}_")
                L.append("")
                for a in subitens:
                    L.append(f"**{ICONE[a.status]} [{a.id}] {a.titulo}**")
                    L.append("")
                    if a.descricao:
                        L.append(f"> {a.descricao}")
                        L.append("")
                    if a.encontrado:
                        L.append(f"- Trecho: `{a.encontrado[:180]}`")
                    if a.esperado:
                        L.append(f"- Sugestão: {a.esperado[:180]}")
                    ref = ", ".join(x for x in (f"item {a.item}" if a.item else "", f"p. {a.pagina}" if a.pagina else "") if x)
                    if ref:
                        L.append(f"- Localização: {ref}")
                    if a.orientacao:
                        L.append(f"- **Recomendação:** {a.orientacao}")
                    L.append("")
        else:
            for a in itens:
                if a.status == Status.CONFORME and cat != Categoria.TABELA:
                    continue
                L.append(f"**{ICONE[a.status]} [{a.id}] {a.titulo}**")
                L.append("")
                if a.descricao:
                    L.append(f"> {a.descricao}")
                    L.append("")
                if a.esperado:
                    L.append(f"- Esperado: {a.esperado}")
                if a.encontrado:
                    L.append(f"- Encontrado: {a.encontrado}")
                if a.evidencia:
                    onde = f"item {a.item}, p. {a.pagina}" if a.item else f"p. {a.pagina or '—'}"
                    L.append(f"- Trecho ({onde}): _{a.evidencia[:220]}_")
                if a.orientacao:
                    L.append(f"- **Recomendação:** {a.orientacao}")
                L.append("")

    L.append("---")
    L.append("")
    L.append(
        "_Relatório gerado automaticamente pelo MCP Conformidade PB/TR. "
        "As verificações automáticas não substituem a análise do parecerista; "
        "itens marcados como 'Verificar manualmente' exigem conferência humana._"
    )

    d.write_text("\n".join(L), encoding="utf-8")
    return str(d)


def gerar_json(rel: Relatorio, destino: str | Path) -> str:
    d = Path(destino)
    d.write_text(
        json.dumps(rel.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(d)
