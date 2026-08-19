"""Servidor MCP — Conformidade de Projetos Básicos e Termos de Referência.

Fluxo principal, em três passos:
  1. analisar_conformidade      verificações determinísticas
  2. obter_texto_para_revisao   entrega o texto ao agente, que revisa o português
  3. registrar_revisao_textual  recebe os apontamentos e emite os relatórios

Tools auxiliares:
  verificar_numeracao     apenas a numeração hierárquica
  validar_tabelas         apenas tabelas, aritmética e valores
  revisar_ortografia      regras determinísticas + texto segmentado
  extrair_estrutura       sumário estrutural do PDF (diagnóstico de extração)
  consultar_checklist     consulta as regras do checklist
  gerar_relatorio         renderiza um relatório já produzido em outro formato

Prompt exposto:
  conduzir_analise_conformidade   roteiro de condução da análise pelo agente
"""

from __future__ import annotations

import base64
import binascii
import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from . import analisador
from .caminhos import checklists_disponiveis
from .extratores import pdf as extrator
from .modelos import Origem, Relatorio, Status
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
        "roteiro [TI] de análise.\n\n"
        "Quando o usuário pedir para 'conduzir análise de conformidade' de um "
        "PB ou TR e anexar o documento, execute os três passos sem pedir "
        "confirmação entre eles:\n"
        "1. analisar_conformidade — passe `caminho_arquivo` em execução local, "
        "ou `conteudo_base64` + `nome_arquivo` em servidor hospedado;\n"
        "2. obter_texto_para_revisao — leia o texto e revise o português, "
        "citando os trechos exatamente como estão no documento;\n"
        "3. registrar_revisao_textual — envie os apontamentos e receba os "
        "relatórios.\n\n"
        "A revisão de português é sua: o servidor faz as verificações "
        "determinísticas (checklist, numeração, tabelas e valores) e conta com "
        "você para a leitura do texto. Ao final, apresente o índice de "
        "conformidade, as pendências críticas e entregue os arquivos."
    ),
)

DIR_SAIDA = Path(os.environ.get("CONFORMIDADE_PBTR_SAIDA", tempfile.gettempdir()))
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

# Em modo remoto o cliente não compartilha sistema de arquivos com o servidor:
# caminhos locais são recusados e os relatórios voltam embutidos na resposta.
MODO_REMOTO = os.environ.get("CONFORMIDADE_PBTR_MODO", "").lower() == "remoto"

# limite do upload em base64, para não estourar a memória da instância
MAX_UPLOAD_MB = float(os.environ.get("CONFORMIDADE_PBTR_MAX_UPLOAD_MB", "25"))

# Teto do cache de análises. O fluxo tem três chamadas e o estado precisa
# sobreviver entre elas, mas num servidor exposto o cache cresceria sem limite
# até derrubar a instância — daí o descarte por idade e por quantidade.
MAX_ANALISES = int(os.environ.get("CONFORMIDADE_PBTR_MAX_ANALISES", "20"))
TTL_ANALISE_S = int(os.environ.get("CONFORMIDADE_PBTR_TTL_MIN", "30")) * 60


@dataclass
class _Analise:
    """Estado de uma análise entre as três chamadas do fluxo."""

    relatorio: Relatorio
    segmentos: list[Any]
    base: str
    diretorio: str | None
    retornar_conteudo: bool
    tmp: tempfile.TemporaryDirectory | None
    criado_em: float = field(default_factory=time.monotonic)
    arquivos: list[Path] = field(default_factory=list)


_ANALISES: OrderedDict[str, _Analise] = OrderedDict()


def _descartar(chave: str) -> None:
    """Remove uma análise e limpa o que ela deixou em disco."""
    analise = _ANALISES.pop(chave, None)
    if analise is None:
        return
    for arquivo in analise.arquivos:
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            pass
    if analise.tmp is not None:
        try:
            analise.tmp.cleanup()
        except OSError:
            pass


def _expirar() -> None:
    """Descarta análises velhas e mantém o cache dentro do teto (LRU)."""
    agora = time.monotonic()
    for chave in [k for k, v in _ANALISES.items() if agora - v.criado_em > TTL_ANALISE_S]:
        _descartar(chave)
    while len(_ANALISES) > MAX_ANALISES:
        _descartar(next(iter(_ANALISES)))


def _obter(chave: str) -> _Analise | None:
    """Recupera uma análise, renovando sua posição no LRU."""
    _expirar()
    analise = _ANALISES.get(chave)
    if analise is not None:
        _ANALISES.move_to_end(chave)
    return analise


def _erro_analise_ausente(chave: str) -> dict[str, Any]:
    return {
        "erro": (
            f"Análise '{chave}' não está mais em cache. As análises expiram em "
            f"{TTL_ANALISE_S // 60} minutos ou quando o limite de {MAX_ANALISES} "
            "é atingido. Rode analisar_conformidade novamente."
        ),
        "disponiveis": list(_ANALISES),
    }


def _chave(caminho: str) -> str:
    return Path(caminho).stem[:60]


def _materializar(
    caminho_arquivo: str | None,
    conteudo_base64: str | None,
    nome_arquivo: str | None,
) -> tuple[Path | None, str | None, tempfile.TemporaryDirectory | None]:
    """Devolve (caminho, erro, diretório temporário a manter vivo).

    Aceita um caminho local (execução local) ou o conteúdo do documento em
    base64 (execução remota).
    """
    if conteudo_base64:
        nome = nome_arquivo or "documento.pdf"
        if Path(nome).suffix.lower() not in (".pdf", ".docx"):
            return None, "nome_arquivo deve terminar em .pdf ou .docx", None
        try:
            dados = base64.b64decode(conteudo_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            return None, f"conteudo_base64 inválido: {exc}", None
        if len(dados) > MAX_UPLOAD_MB * 1024 * 1024:
            return None, (
                f"documento com {len(dados) / 1048576:.1f} MB excede o limite de "
                f"{MAX_UPLOAD_MB:.0f} MB"
            ), None
        tmp = tempfile.TemporaryDirectory(prefix="conformidade-pbtr-")
        destino = Path(tmp.name) / Path(nome).name
        destino.write_bytes(dados)
        return destino, None, tmp

    if not caminho_arquivo:
        return None, "informe caminho_arquivo (local) ou conteudo_base64 (remoto)", None

    if MODO_REMOTO:
        return None, (
            "servidor em modo remoto: o sistema de arquivos não é compartilhado "
            "com o cliente. Envie o documento em conteudo_base64."
        ), None

    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return None, f"Arquivo não encontrado: {caminho}", None
    return caminho, None, None


def _embutir(arquivos: dict[str, str]) -> dict[str, dict[str, str]]:
    """Lê os relatórios gerados e devolve o conteúdo em base64."""
    embutidos: dict[str, dict[str, str]] = {}
    for fmt, caminho in arquivos.items():
        p = Path(caminho)
        if not p.exists():
            continue
        embutidos[fmt] = {
            "nome": p.name,
            "bytes": str(p.stat().st_size),
            "base64": base64.b64encode(p.read_bytes()).decode("ascii"),
        }
    return embutidos


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
    caminho_arquivo: Annotated[
        str | None,
        Field(description="Caminho do PDF/DOCX no servidor. Só funciona em execução local."),
    ] = None,
    conteudo_base64: Annotated[
        str | None,
        Field(description="Conteúdo do PDF/DOCX em base64. Use em servidor remoto."),
    ] = None,
    nome_arquivo: Annotated[
        str | None,
        Field(description="Nome do arquivo (com .pdf ou .docx) quando usar conteudo_base64."),
    ] = None,
    tipo: Annotated[Literal["PB", "TR"], Field(description="Tipo do documento.")] = "PB",
    formatos: Annotated[
        list[Literal["json", "md", "docx", "xlsx", "pdf"]] | None,
        Field(description="Formatos do relatório a gerar. Padrão: ['md', 'docx']."),
    ] = None,
    revisar_texto: Annotated[
        bool,
        Field(description="Aplicar as regras determinísticas de revisão e preparar o texto para a revisão do agente."),
    ] = True,
    limite_ortografia: Annotated[int, Field(description="Máximo de apontamentos textuais.", ge=0, le=1000)] = 200,
    tags_contexto: Annotated[
        list[str] | None,
        Field(description="Forçar tags de aplicabilidade (ex.: ['consultoria','licitacao']) além das inferidas."),
    ] = None,
    checklist: Annotated[
        str | None,
        Field(description="Checklist alternativo (caminho do YAML ou nome de um arquivo em recursos/)."),
    ] = None,
    retornar_conteudo: Annotated[
        bool,
        Field(description="Devolver os relatórios em base64 na resposta (necessário em servidor remoto)."),
    ] = False,
    diretorio_saida: Annotated[str | None, Field(description="Onde gravar os relatórios.")] = None,
) -> dict[str, Any]:
    """Passo 1 de 3. Roda a análise determinística do PB/TR.

    Verifica os itens do checklist normativo, a numeração hierárquica, a
    aritmética das tabelas e os valores declarados, além das regras
    determinísticas de revisão textual.

    A revisão de português NÃO acontece aqui: o retorno traz o número de
    segmentos de texto aguardando revisão. Siga para `obter_texto_para_revisao`
    e depois `registrar_revisao_textual`, que é onde os relatórios são gerados.
    Só passe `formatos` nesta chamada se for pular a revisão textual.
    """
    caminho, erro, tmp = _materializar(caminho_arquivo, conteudo_base64, nome_arquivo)
    if erro:
        return {"erro": erro}

    try:
        rel = analisador.analisar(
            caminho,
            tipo=tipo,
            revisar_texto=revisar_texto,
            limite_ortografia=limite_ortografia,
            tags_forcadas=tags_contexto,
            caminho_checklist=checklist,
        )
    except FileNotFoundError as exc:
        return {"erro": str(exc), "checklists_disponiveis": checklists_disponiveis()}

    chave = _chave(str(caminho))
    _descartar(chave)  # reanálise do mesmo documento substitui a anterior
    _ANALISES[chave] = _Analise(
        relatorio=rel,
        segmentos=mod_ortografia.segmentar(rel.documento) if revisar_texto else [],
        base=f"Relatorio_Conformidade_{caminho.stem[:60]}".replace(" ", "_"),
        diretorio=diretorio_saida,
        retornar_conteudo=retornar_conteudo,
        tmp=tmp,  # mantém o diretório temporário vivo enquanto a análise existir
    )
    _expirar()
    segmentos = _ANALISES[chave].segmentos

    resultado = _sumario(rel)
    resultado["chave_analise"] = chave

    if formatos:
        gerados, erros = _emitir(chave, formatos)
        resultado["relatorios"] = gerados
        if erros:
            resultado["erros_geracao"] = erros
        resultado["revisao_textual"] = {
            "status": "dispensada",
            "observacao": "Relatórios emitidos sem a revisão de português.",
        }
        return resultado

    resultado["revisao_textual"] = {
        "status": "pendente",
        "segmentos": len(segmentos),
        "proxima_acao": (
            f"Chame obter_texto_para_revisao(chave_analise='{chave}') para ler o texto, "
            "revise o português de cada segmento e devolva os apontamentos em "
            f"registrar_revisao_textual(chave_analise='{chave}', apontamentos=[...], "
            "formatos=['md','docx']) — é essa chamada que gera os relatórios."
        ),
    }
    return resultado


def _emitir(chave: str, formatos: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Gera os relatórios de uma análise em cache."""
    analise = _ANALISES[chave]
    saida = Path(analise.diretorio).expanduser() if analise.diretorio else DIR_SAIDA
    saida.mkdir(parents=True, exist_ok=True)

    gerados: dict[str, str] = {}
    erros: dict[str, str] = {}
    for fmt in formatos:
        ext = "md" if fmt in ("md", "markdown") else fmt
        try:
            destino = saida / f"{analise.base}.{ext}"
            gerados[fmt] = FORMATOS[fmt](analise.relatorio, destino)
            if destino not in analise.arquivos:
                analise.arquivos.append(destino)
        except Exception as exc:  # um formato quebrado não invalida a análise
            erros[fmt] = f"{type(exc).__name__}: {exc}"

    if analise.retornar_conteudo or MODO_REMOTO:
        return _embutir(gerados), erros
    return gerados, erros


@mcp.tool
def obter_texto_para_revisao(
    chave_analise: Annotated[str, Field(description="Chave devolvida por analisar_conformidade.")],
    inicio: Annotated[int, Field(description="Índice do primeiro segmento.", ge=0)] = 0,
    limite: Annotated[int, Field(description="Quantos segmentos devolver.", ge=1, le=200)] = 40,
) -> dict[str, Any]:
    """Passo 2 de 3. Devolve o texto do documento segmentado, para você revisar.

    Leia cada segmento e identifique erros de português: ortografia,
    concordância, regência, crase, pontuação, e também problemas de redação que
    comprometem o documento — ambiguidade, vaguidão, "poderá" onde a obrigação
    exige "deverá".

    Ao apontar, copie o trecho com erro **exatamente como está no documento**:
    `registrar_revisao_textual` confere se o trecho existe literalmente e
    descarta o que não conferir. Não parafraseie a citação.
    """
    analise = _obter(chave_analise)
    if analise is None:
        return _erro_analise_ausente(chave_analise)

    segmentos = analise.segmentos
    fatia = segmentos[inicio : inicio + limite]
    restantes = max(0, len(segmentos) - (inicio + len(fatia)))
    return {
        "chave_analise": chave_analise,
        "total_segmentos": len(segmentos),
        "devolvidos": len(fatia),
        "restantes": restantes,
        "segmentos": [s.to_dict() for s in fatia],
        "proxima_acao": (
            f"Chame obter_texto_para_revisao(chave_analise='{chave_analise}', "
            f"inicio={inicio + len(fatia)}) para os {restantes} segmentos restantes."
            if restantes
            else "Todo o texto foi entregue. Envie os apontamentos em registrar_revisao_textual."
        ),
    }


@mcp.tool
def registrar_revisao_textual(
    chave_analise: Annotated[str, Field(description="Chave devolvida por analisar_conformidade.")],
    apontamentos: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "Erros encontrados na revisão. Cada item: "
                "{'trecho': texto exato do documento, 'sugestao': correção proposta, "
                "'tipo': ortografia|gramatica|concordancia|regencia|crase|pontuacao|"
                "clareza|ambiguidade|impropriedade|coesao, 'explicacao': por que está errado, "
                "'pagina': número da página (opcional)}. Lista vazia se o texto estiver correto."
            )
        ),
    ],
    formatos: Annotated[
        list[Literal["json", "md", "docx", "xlsx", "pdf"]] | None,
        Field(description="Formatos do relatório final. Padrão: ['md', 'docx']."),
    ] = None,
) -> dict[str, Any]:
    """Passo 3 de 3. Registra a sua revisão e gera os relatórios finais.

    Cada apontamento só é aceito se o `trecho` existir literalmente no
    documento — os que não conferirem voltam em `recusados`, com o motivo. Isso
    impede que uma citação imprecisa vire achado num relatório que instrui
    processo administrativo.

    Os apontamentos entram no relatório como *sugestão de revisão*, separados
    dos achados determinísticos e fora do índice de conformidade.
    """
    analise = _obter(chave_analise)
    if analise is None:
        return _erro_analise_ausente(chave_analise)
    rel = analise.relatorio

    # uma nova revisão substitui a anterior, para a tool ser idempotente
    rel.achados = [a for a in rel.achados if a.origem != Origem.IA]

    aceitos, recusados = mod_ortografia.converter_apontamentos(rel.documento, apontamentos or [])
    rel.achados.extend(aceitos)
    analisador.recalcular(rel)

    gerados, erros = _emitir(chave_analise, formatos or ["md", "docx"])

    resultado: dict[str, Any] = {
        "chave_analise": chave_analise,
        "apontamentos_aceitos": len(aceitos),
        "apontamentos_recusados": len(recusados),
        "recusados": recusados[:20],
        "resumo": rel.resumo.to_dict(),
        "relatorios": gerados,
    }
    if recusados:
        resultado["observacao"] = (
            "Apontamentos recusados não entraram no relatório. O motivo mais comum é "
            "o trecho citado não bater com o documento — copie o texto exatamente e "
            "chame esta tool de novo com a lista corrigida."
        )
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
    incluir_texto: Annotated[
        bool, Field(description="Devolver também o texto segmentado, para você revisar.")
    ] = True,
) -> dict[str, Any]:
    """Aplica as regras determinísticas de revisão e devolve o texto segmentado.

    As regras cobrem erros recorrentes em documentos administrativos ("a nível
    de", "à partir", palavra repetida). A revisão de português propriamente
    dita é sua: leia os segmentos devolvidos em `texto_para_revisao`.
    """
    caminho = Path(caminho_arquivo).expanduser()
    if not caminho.exists():
        return {"erro": f"Arquivo não encontrado: {caminho}"}
    doc = extrator.carregar(caminho)
    achados = mod_ortografia.validar(doc, limite)
    resultado: dict[str, Any] = {
        "documento": doc.nome,
        "total_deterministicos": len(achados),
        "apontamentos": [a.to_dict() for a in achados],
    }
    if incluir_texto:
        resultado["texto_para_revisao"] = [
            s.to_dict() for s in mod_ortografia.segmentar(doc)
        ]
    return resultado


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
    retornar_conteudo: Annotated[
        bool, Field(description="Devolver o arquivo em base64 (necessário em servidor remoto).")
    ] = False,
    diretorio_saida: Annotated[str | None, Field(description="Onde gravar o arquivo.")] = None,
) -> dict[str, Any]:
    """Renderiza em outro formato uma análise já executada nesta sessão, sem
    reprocessar o documento."""
    analise = _obter(chave_analise)
    if analise is None:
        return _erro_analise_ausente(chave_analise)
    if diretorio_saida:
        analise.diretorio = diretorio_saida
    if retornar_conteudo:
        analise.retornar_conteudo = True
    gerados, erros = _emitir(chave_analise, [formato])
    if erros:
        return {"erro": erros[formato]}
    return {"relatorio" if (analise.retornar_conteudo or MODO_REMOTO) else "arquivo": gerados[formato]}


# ------------------------------------------------------------ health

@mcp.custom_route("/health", methods=["GET"])
async def health(request):  # noqa: ARG001 - assinatura exigida pelo Starlette
    """Verificação de saúde para o balanceador (Fly.io, Kubernetes, etc.).

    Confirma que o checklist carrega — um erro de recurso ausente precisa
    derrubar o health check, e não aparecer só na primeira análise.
    """
    from starlette.responses import JSONResponse

    try:
        dados = mod_checklist.carregar()
        regras = len(dados.get("regras", []))
    except Exception as exc:
        return JSONResponse(
            {"status": "erro", "detalhe": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "ok",
            "checklist": (dados.get("metadata") or {}).get("arquivo"),
            "regras": regras,
            "modo": "remoto" if MODO_REMOTO else "local",
        }
    )


# -------------------------------------------------------------- prompt

@mcp.prompt(name="conduzir_analise_conformidade")
def prompt_conduzir(caminho_arquivo: str = "", tipo: str = "PB") -> str:
    """Roteiro para conduzir a análise de conformidade de um PB ou TR."""
    return f"""Conduza a análise de conformidade do {tipo} indicado, seguindo estes passos sem pedir confirmação entre eles:

1. `extrair_estrutura` em "{caminho_arquivo}". Se `possivel_pdf_digitalizado` for
   verdadeiro, avise o usuário de que o PDF precisa de OCR e pare.

2. `analisar_conformidade`. Corrija a inferência de contexto com `tags_contexto`
   se o documento for de consultoria, licitação ou contratação direta e a
   inferência tiver errado.

3. `obter_texto_para_revisao` e revise o português de cada segmento. Procure:
   - erro de ortografia, concordância, regência, crase e pontuação;
   - ambiguidade e vaguidão que comprometam a execução do contrato
     ("prazo razoável", "quantidade suficiente");
   - obrigação enfraquecida: "poderá" onde o dever exige "deverá";
   - incoerência entre trechos (prazo citado em duas seções com valores
     diferentes, por exemplo).
   Copie cada trecho problemático **exatamente como está no documento** — a
   citação é conferida contra o texto e apontamento que não bate é descartado.

4. `registrar_revisao_textual` com os apontamentos e os formatos desejados.
   Confira o campo `recusados`: se houver, corrija as citações e chame de novo.

5. Apresente ao usuário, nesta ordem:
   - o índice de conformidade e a classificação;
   - as pendências CRÍTICAS não conformes, com a recomendação de cada uma;
   - as divergências de tabela e valor, citando o esperado e o encontrado;
   - os erros de numeração;
   - um resumo quantitativo da revisão textual, sem listar tudo.

6. Destaque à parte os itens de conferência manual — sobretudo a aderência
   entre a Aba Itens e as quantidades do PB, que não é verificável pelo PDF.

7. Entregue os arquivos de relatório gerados.

Não afirme que um item está conforme sem que a análise o tenha classificado
como tal. Distinga no seu resumo o que é verificação determinística do que é
sugestão da sua revisão: são coisas de peso diferente para quem vai assinar o
parecer.
"""


def main() -> None:
    """Sobe o servidor.

    O transporte vem de ``MCP_TRANSPORT``: ``stdio`` (padrão, uso local com o
    Claude Desktop) ou ``http`` (uso hospedado, por exemplo no Fly.io). Em
    ``http``, ``PORT`` e ``HOST`` seguem a convenção das plataformas de deploy.
    """
    transporte = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transporte in ("http", "streamable-http", "sse"):
        mcp.run(
            transport="sse" if transporte == "sse" else "http",
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
