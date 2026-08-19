"""Servidor MCP — Conformidade de Projetos Básicos e Termos de Referência.

Tools expostas:
  analisar_conformidade   análise completa (checklist + numeração + tabelas + ortografia)
  verificar_numeracao     apenas a numeração hierárquica
  validar_tabelas         apenas tabelas, aritmética e valores
  revisar_ortografia      apenas a revisão textual pt-BR
  extrair_estrutura       sumário estrutural do PDF (diagnóstico de extração)
  consultar_checklist     consulta as regras do roteiro [TI]
  gerar_relatorio         renderiza um relatório já produzido em outro formato

Prompt exposto:
  conduzir_analise_conformidade   roteiro de condução da análise pelo agente
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from . import analisador
from .caminhos import checklists_disponiveis
from .extratores import pdf as extrator
from .modelos import Relatorio, Status
from .relatorios import FORMATOS
from .validadores import checklist as mod_checklist
from .validadores import contexto as mod_contexto
from .validadores import numeracao as mod_numeracao
from .validadores import ortografia as mod_ortografia
from .validadores import tabelas as mod_tabelas

mcp = FastMCP(
    name="conformidade-pbtr",
    instructions=(
        "Analisa Projetos Básicos (PB) e Termos de Referência (TR) contra o "
        "roteiro [TI] de análise. Quando o usuário pedir para 'conduzir análise "
        "de conformidade' de um PB ou TR e enviar um PDF, chame "
        "analisar_conformidade com o caminho do arquivo e os formatos de saída "
        "desejados. O retorno traz o sumário, as pendências priorizadas e os "
        "caminhos dos relatórios gerados."
    ),
)

DIR_SAIDA = Path(os.environ.get("CONFORMIDADE_PBTR_SAIDA", tempfile.gettempdir()))
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

# cache das análises da sessão: chave -> Relatorio
_CACHE: dict[str, Relatorio] = {}


def _chave(caminho: str) -> str:
    return Path(caminho).stem[:60]


def _sumario(rel: Relatorio, limite_pendencias: int = 40) -> dict[str, Any]:
    return {
        "documento": rel.documento.nome,
        "tipo": rel.documento.tipo,
        "paginas": rel.documento.paginas,
        "contexto_inferido": rel.documento.tags_contexto,
        "checklist_versao": rel.versao_checklist,
        "gerado_em": rel.gerado_em,
        "resumo": rel.resumo.to_dict(),
        "pendencias": [
            {
                "id": a.id,
                "categoria": a.categoria.value,
                "secao": a.secao,
                "titulo": a.titulo,
                "status": a.status.value,
                "severidade": a.severidade.value,
                "pagina": a.pagina,
                "esperado": a.esperado,
                "encontrado": a.encontrado,
                "evidencia": a.evidencia[:240],
                "recomendacao": a.orientacao,
            }
            for a in rel.pendencias()[:limite_pendencias]
        ],
        "total_pendencias": len(rel.pendencias()),
        "avisos": rel.avisos,
    }


# --------------------------------------------------------------- tools

@mcp.tool
def analisar_conformidade(
    caminho_arquivo: Annotated[str, Field(description="Caminho absoluto do PDF ou DOCX do PB/TR.")],
    tipo: Annotated[Literal["PB", "TR"], Field(description="Tipo do documento.")] = "PB",
    formatos: Annotated[
        list[Literal["json", "md", "docx", "xlsx", "pdf"]] | None,
        Field(description="Formatos do relatório a gerar. Padrão: ['md', 'docx']."),
    ] = None,
    revisar_ortografia: Annotated[bool, Field(description="Executar a revisão textual pt-BR.")] = True,
    limite_ortografia: Annotated[int, Field(description="Máximo de apontamentos textuais.", ge=0, le=1000)] = 200,
    tags_contexto: Annotated[
        list[str] | None,
        Field(description="Forçar tags de aplicabilidade (ex.: ['consultoria','licitacao']) além das inferidas."),
    ] = None,
    checklist: Annotated[
        str | None,
        Field(description="Checklist alternativo (caminho do YAML ou nome de um arquivo em recursos/)."),
    ] = None,
    diretorio_saida: Annotated[str | None, Field(description="Onde gravar os relatórios.")] = None,
) -> dict[str, Any]:
    """Conduz a análise de conformidade completa de um PB/TR e gera os relatórios.

    Verifica: (1) os itens do checklist normativo; (2) a numeração hierárquica
    dos itens; (3) a aritmética das tabelas de preços e os valores declarados
    (inclusive valor por extenso); (4) ortografia e gramática em pt-BR.
    """
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}

    try:
        rel = analisador.analisar(
            caminho,
            tipo=tipo,
            usar_languagetool=revisar_ortografia,
            limite_ortografia=limite_ortografia if revisar_ortografia else 0,
            tags_forcadas=tags_contexto,
            caminho_checklist=checklist,
        )
    except FileNotFoundError as exc:
        return {"erro": str(exc), "checklists_disponiveis": checklists_disponiveis()}
    _CACHE[_chave(str(caminho))] = rel

    saida = Path(diretorio_saida).expanduser() if diretorio_saida else DIR_SAIDA
    saida.mkdir(parents=True, exist_ok=True)
    base = f"Relatorio_Conformidade_{caminho.stem[:60]}".replace(" ", "_")

    gerados: dict[str, str] = {}
    erros: dict[str, str] = {}
    for fmt in formatos or ["md", "docx"]:
        ext = "md" if fmt in ("md", "markdown") else fmt
        try:
            gerados[fmt] = FORMATOS[fmt](rel, saida / f"{base}.{ext}")
        except Exception as exc:  # um formato quebrado não invalida a análise
            erros[fmt] = f"{type(exc).__name__}: {exc}"

    resultado = _sumario(rel)
    resultado["relatorios"] = gerados
    resultado["chave_analise"] = _chave(str(caminho))
    if erros:
        resultado["erros_geracao"] = erros
    return resultado


@mcp.tool
def verificar_numeracao(
    caminho_arquivo: Annotated[str, Field(description="Caminho do PDF/DOCX do PB/TR.")],
) -> dict[str, Any]:
    """Verifica apenas a numeração hierárquica dos itens (saltos, duplicidades,
    subitens órfãos, itens fora de ordem e seções obrigatórias ausentes)."""
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}
    doc = extrator.carregar(caminho)
    achados = mod_numeracao.validar(doc)
    return {
        "documento": doc.nome,
        "itens_numerados": sum(1 for b in doc.blocos if b.numeracao),
        "ocorrencias": [a.to_dict() for a in achados],
        "total": len(achados),
    }


@mcp.tool
def validar_tabelas(
    caminho_arquivo: Annotated[str, Field(description="Caminho do PDF/DOCX do PB/TR.")],
) -> dict[str, Any]:
    """Valida as tabelas de preços: colunas mínimas, Quantidade x Valor Unitário
    = Valor Total, fechamento do somatório, coerência mensal, valor por extenso
    e confronto do valor global citado no texto."""
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}
    doc = extrator.carregar(caminho)
    achados = mod_tabelas.validar(doc)
    return {
        "documento": doc.nome,
        "tabelas_detectadas": len(doc.tabelas),
        "cabecalhos": [t.cabecalho for t in doc.tabelas],
        "ocorrencias": [a.to_dict() for a in achados],
        "divergencias": sum(1 for a in achados if a.status == Status.NAO_CONFORME),
    }


@mcp.tool
def revisar_ortografia(
    caminho_arquivo: Annotated[str, Field(description="Caminho do PDF/DOCX do PB/TR.")],
    limite: Annotated[int, Field(description="Máximo de apontamentos.", ge=1, le=1000)] = 200,
    usar_languagetool: Annotated[bool, Field(description="Usar o LanguageTool local.")] = True,
) -> dict[str, Any]:
    """Revisa ortografia e gramática em pt-BR, ignorando as siglas e o jargão do
    SERPRO cadastrados no dicionário do projeto."""
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}
    doc = extrator.carregar(caminho)
    achados, avisos = mod_ortografia.validar(doc, usar_languagetool, limite)
    return {
        "documento": doc.nome,
        "total": len(achados),
        "apontamentos": [a.to_dict() for a in achados],
        "avisos": avisos,
    }


@mcp.tool
def extrair_estrutura(
    caminho_arquivo: Annotated[str, Field(description="Caminho do PDF/DOCX do PB/TR.")],
    incluir_texto: Annotated[bool, Field(description="Devolver também o texto integral.")] = False,
) -> dict[str, Any]:
    """Diagnóstico de extração: seções numeradas, tabelas e contexto inferido.
    Use antes da análise quando houver suspeita de PDF digitalizado."""
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}
    doc = extrator.carregar(caminho)
    doc.tags_contexto = mod_contexto.inferir(doc)
    titulos = [
        {"numeracao": b.numeracao, "texto": b.texto[:120], "pagina": b.pagina}
        for b in doc.blocos
        if b.is_titulo and b.numeracao
    ]
    resultado: dict[str, Any] = {
        "documento": doc.nome,
        "paginas": doc.paginas,
        "caracteres_extraidos": len(doc.texto),
        "blocos": len(doc.blocos),
        "titulos_numerados": titulos[:200],
        "tabelas": [
            {"pagina": t.pagina, "colunas": t.cabecalho, "linhas": len(t.linhas)}
            for t in doc.tabelas
        ],
        "contexto_inferido": doc.tags_contexto,
        "possivel_pdf_digitalizado": len(doc.texto.strip()) < 200 * max(doc.paginas, 1),
    }
    if incluir_texto:
        resultado["texto"] = doc.texto
    return resultado


@mcp.tool
def consultar_checklist(
    secao: Annotated[str | None, Field(description="Filtrar por seção, ex.: '4'.")] = None,
    arquivo: Annotated[str | None, Field(description="Checklist a consultar; omitido, usa o padrão.")] = None,
    aplicabilidade: Annotated[str | None, Field(description="Filtrar por tag, ex.: 'consultoria'.")] = None,
    severidade: Annotated[
        Literal["critico", "alto", "medio", "informativo"] | None,
        Field(description="Filtrar por severidade."),
    ] = None,
) -> dict[str, Any]:
    """Consulta as regras do roteiro [TI] usadas na análise — útil para explicar
    ao usuário o que é exigido em determinada seção do PB/TR."""
    dados = mod_checklist.carregar(arquivo)
    regras = dados.get("regras", [])
    if secao:
        regras = [r for r in regras if str(r.get("secao", "")).startswith(str(secao))]
    if aplicabilidade:
        regras = [r for r in regras if aplicabilidade in (r.get("aplicabilidade") or [])]
    if severidade:
        regras = [r for r in regras if r.get("severidade") == severidade]
    meta = dados.get("metadata") or {}
    return {
        "versao": meta.get("versao"),
        "arquivo": meta.get("arquivo"),
        "fonte": meta.get("fonte"),
        "checklists_disponiveis": checklists_disponiveis(),
        "total": len(regras),
        "regras": [
            {
                "id": r["id"],
                "secao": r.get("secao"),
                "titulo": r.get("titulo"),
                "descricao": " ".join((r.get("descricao") or "").split()),
                "aplicabilidade": r.get("aplicabilidade"),
                "severidade": r.get("severidade"),
                "orientacao": " ".join((r.get("orientacao") or "").split()),
            }
            for r in regras
        ],
    }


@mcp.tool
def gerar_relatorio(
    chave_analise: Annotated[str, Field(description="Chave devolvida por analisar_conformidade.")],
    formato: Annotated[Literal["json", "md", "docx", "xlsx", "pdf"], Field(description="Formato de saída.")],
    diretorio_saida: Annotated[str | None, Field(description="Onde gravar o arquivo.")] = None,
) -> dict[str, Any]:
    """Renderiza em outro formato uma análise já executada nesta sessão, sem
    reprocessar o documento."""
    rel = _CACHE.get(chave_analise)
    if rel is None:
        return {
            "erro": f"Análise '{chave_analise}' não está em cache.",
            "disponiveis": list(_CACHE),
        }
    saida = Path(diretorio_saida).expanduser() if diretorio_saida else DIR_SAIDA
    saida.mkdir(parents=True, exist_ok=True)
    ext = "md" if formato in ("md", "markdown") else formato
    base = f"Relatorio_Conformidade_{chave_analise}".replace(" ", "_")
    return {"arquivo": FORMATOS[formato](rel, saida / f"{base}.{ext}")}


# -------------------------------------------------------------- prompt

@mcp.prompt(name="conduzir_analise_conformidade")
def prompt_conduzir(caminho_arquivo: str = "", tipo: str = "PB") -> str:
    """Roteiro para conduzir a análise de conformidade de um PB ou TR."""
    return f"""Conduza a análise de conformidade do {tipo} indicado, seguindo estes passos:

1. Chame `extrair_estrutura` em "{caminho_arquivo}". Se `possivel_pdf_digitalizado`
   for verdadeiro, avise o usuário de que o PDF precisa de OCR antes de prosseguir.

2. Confirme com o usuário o contexto da contratação quando a inferência estiver
   ambígua (licitação x contratação direta x inexigibilidade; serviço x bem x
   consultoria). Passe as correções em `tags_contexto`.

3. Chame `analisar_conformidade` com formatos ["md", "docx", "xlsx", "pdf"].

4. Apresente ao usuário, nesta ordem:
   - o índice de conformidade e a classificação;
   - as pendências CRÍTICAS não conformes, com a recomendação de cada uma;
   - as divergências de tabela/valor, citando o número esperado e o encontrado;
   - os erros de numeração;
   - um resumo quantitativo da revisão textual (não liste todos os apontamentos:
     eles estão no relatório).

5. Destaque separadamente os itens marcados como "verificar manualmente" —
   sobretudo a aderência entre a Aba Itens e as quantidades do PB, que o
   sistema não consegue conferir a partir do PDF.

6. Entregue os arquivos de relatório gerados.

Não afirme que um item está conforme sem que a análise o tenha classificado como
tal; quando a evidência textual for fraca, trate como "verificar manualmente".
"""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
