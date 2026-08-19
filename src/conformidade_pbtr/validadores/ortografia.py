"""Revisão ortográfica e gramatical em pt-BR.

Estratégia em duas camadas:
  1. LanguageTool local (pt-BR) — gramática, concordância, regência, crase.
     Exige Java 8+. As siglas e jargões do SERPRO ficam em
     `recursos/dicionario_serpro.txt` e são ignorados.
  2. Regras próprias (sempre ativas) — erros recorrentes em PB/TR que o
     LanguageTool não pega ou pega mal: "a nível de", "afim de", "de encontro
     a", uso de "R$" com "reais" duplicado, espaçamento antes de pontuação,
     "mesmo" como pronome, etc.

Se o LanguageTool não estiver disponível, a camada 2 continua rodando e o
relatório registra o aviso — a análise nunca falha por causa disso.
"""

from __future__ import annotations

import functools
import re

from ..caminhos import caminho_dicionario
from ..modelos import Achado, Categoria, Documento, Severidade, Status

# Regras do LanguageTool desativadas: geram ruído em texto jurídico/administrativo.
REGRAS_DESATIVADAS = {
    "WHITESPACE_RULE",
    "UPPERCASE_SENTENCE_START",
    "PT_BARBARISMS_REPLACE",
    "FRAGMENT_TWO_ARTICLES",
    "DOUBLE_PUNCTUATION",
    # "nº" é a forma consagrada em documentos administrativos brasileiros;
    # a sugestão "n.º/núm." do LanguageTool só gera ruído em PB/TR.
    "NUMBER_ABREVIATION",
}

CATEGORIAS_DESATIVADAS = {"TYPOGRAPHY", "STYLE", "REDUNDANCY"}


# ------------------------------------------------------- regras próprias

REGRAS_LOCAIS: list[tuple[str, str, str, Severidade]] = [
    (
        r"\ba n[íi]vel de\b",
        '"a nível de"',
        'Substituir por "em nível de", "no âmbito de" ou reescrever.',
        Severidade.MEDIO,
    ),
    (
        r"\bafim de\b",
        '"afim de"',
        'Usar "a fim de" (finalidade). "Afim" significa semelhante.',
        Severidade.MEDIO,
    ),
    (
        r"\bde encontro a(o|os|s)?\b",
        '"de encontro a"',
        '"De encontro a" significa oposição. Se a ideia é concordância, usar "ao encontro de".',
        Severidade.MEDIO,
    ),
    (
        r"R\$\s*[\d\.,]+\s*reais\b",
        'valor com "R$" e "reais"',
        'Redundância: usar "R$ 1.000,00" ou "mil reais", não os dois.',
        Severidade.MEDIO,
    ),
    (
        r"\bhaja visto\b",
        '"haja visto"',
        'A forma correta é "haja vista".',
        Severidade.MEDIO,
    ),
    (
        r"\bem vias de\b",
        '"em vias de"',
        'A forma consagrada é "em via de".',
        Severidade.INFORMATIVO,
    ),
    (
        r"\bmau\s+(funcionamento|uso|dimensionamento)\b",
        '"mau" antes de substantivo',
        'Conferir: "mau" é adjetivo (mau funcionamento) e "mal" é advérbio (mal dimensionado).',
        Severidade.INFORMATIVO,
    ),
    (
        r"\s+[,;.](?=\s|$)",
        "espaço antes de pontuação",
        "Remover o espaço que antecede a vírgula/ponto.",
        Severidade.INFORMATIVO,
    ),
    (
        r"\b(\w{3,})\s+\1\b",
        "palavra repetida",
        "Palavra duplicada — remover a repetição.",
        Severidade.MEDIO,
    ),
    (
        r"\bpara\s+mim\s+(?:fazer|executar|analisar|elaborar|realizar)\b",
        '"para mim" + infinitivo',
        'Usar "para eu fazer".',
        Severidade.MEDIO,
    ),
    (
        r"\bà\s+partir\b",
        '"à partir"',
        'Não há crase antes de verbo: "a partir".',
        Severidade.MEDIO,
    ),
    (
        r"\bà\s+qualquer\b",
        '"à qualquer"',
        'Não há crase antes de "qualquer": "a qualquer".',
        Severidade.MEDIO,
    ),
    (
        r"\bàs?\s+(ela|ele|elas|eles|voc[êe]s?)\b",
        "crase antes de pronome",
        "Não ocorre crase antes de pronome pessoal.",
        Severidade.MEDIO,
    ),
    (
        r"\bexce[cç][aã]o (a|de) regra\b",
        '"exceção a regra"',
        'Usar "exceção à regra" (crase).',
        Severidade.INFORMATIVO,
    ),
    (
        r"\bmeio ambiente\s+ambiental\b",
        "redundância",
        "Redundância — reescrever.",
        Severidade.INFORMATIVO,
    ),
    (
        r"\bdevido\s+a\s+que\b",
        '"devido a que"',
        'Preferir "uma vez que" ou "porque".',
        Severidade.INFORMATIVO,
    ),
    (
        r"\bimpricind[íi]vel|\bimprecind[íi]vel",
        "grafia de imprescindível",
        'A grafia correta é "imprescindível".',
        Severidade.ALTO,
    ),
    (
        r"\bexcess[aã]o\b",
        "grafia de exceção",
        'A grafia correta é "exceção".',
        Severidade.ALTO,
    ),
    (
        r"\bconcerteza\b|\bcom certeza\s+absoluta\b",
        "grafia/registro",
        'Usar "com certeza" e evitar reforços desnecessários.',
        Severidade.INFORMATIVO,
    ),
    (
        r"\bfrizar\b",
        "grafia de frisar",
        'A grafia correta é "frisar".',
        Severidade.ALTO,
    ),
    (
        r"\bdiscriss[aã]o\b|\bdescrimina[cç][aã]o de valores\b",
        "grafia de discriminação",
        'Para detalhamento, usar "discriminação"; "descriminação" é tornar não criminoso.',
        Severidade.ALTO,
    ),
]


@functools.lru_cache(maxsize=1)
def carregar_dicionario() -> set[str]:
    caminho = caminho_dicionario()
    if caminho is None or not caminho.exists():
        return set()
    termos = set()
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            termos.add(linha)
            termos.add(linha.lower())
    return termos


@functools.lru_cache(maxsize=1)
def _ferramenta():
    """Instancia o LanguageTool uma única vez por processo."""
    import language_tool_python

    tool = language_tool_python.LanguageTool("pt-BR")
    for regra in REGRAS_DESATIVADAS:
        tool.disabled_rules.add(regra)
    return tool


def _attr(match, *nomes, padrao=""):
    """Acessa atributos do Match tolerando as variações de API do
    language-tool-python (camelCase até a 2.7, snake_case a partir da 2.8)."""
    for nome in nomes:
        try:
            valor = getattr(match, nome)
        except AttributeError:
            continue
        if valor is not None:
            return valor
    return padrao


def _ignorar(match, dicionario: set[str], texto: str) -> bool:
    tamanho = _attr(match, "error_length", "errorLength", padrao=0)
    trecho = texto[match.offset : match.offset + tamanho]
    if trecho.strip() in dicionario:
        return True
    if trecho.strip().upper() in {t.upper() for t in dicionario}:
        return True
    # siglas: caixa alta com até 6 letras, admitindo plural ("DODs", "ETPs")
    # e sufixo numérico ("LA008", "TR014")
    if re.fullmatch(r"[A-ZÇÁÉÍÓÚÂÊÔÃÕ]{2,6}s?(?:[-/]?\d{1,4})?", trecho.strip()):
        return True
    # a sigla-base está no dicionário e o token é a sua flexão de plural
    nucleo = trecho.strip().rstrip("s")
    if nucleo and nucleo in {t for t in dicionario if t.isupper()}:
        return True
    # números, datas, referências normativas
    if re.fullmatch(r"[\d\.,/\-º°%R$ ]+", trecho.strip()):
        return True
    if _attr(match, "category") in CATEGORIAS_DESATIVADAS:
        return True
    return False


def _pagina_do_offset(doc: Documento, offset: int) -> int | None:
    """Aproxima a página a partir do offset no texto concatenado."""
    if not doc.blocos:
        return None
    acumulado = 0
    for bloco in doc.blocos:
        acumulado += len(bloco.texto) + 1
        if acumulado >= offset:
            return bloco.pagina
    return doc.blocos[-1].pagina


def _regras_locais(doc: Documento, limite: int) -> list[tuple[Achado, int, int]]:
    """Devolve (achado, offset_inicial, offset_final) para permitir deduplicação
    contra as ocorrências do LanguageTool."""
    achados: list[tuple[Achado, int, int]] = []
    n = 0
    for padrao, rotulo, orientacao, severidade in REGRAS_LOCAIS:
        for m in re.finditer(padrao, doc.texto, re.IGNORECASE):
            if n >= limite:
                return achados
            n += 1
            ini = max(0, m.start() - 60)
            fim = min(len(doc.texto), m.end() + 60)
            achados.append((
                Achado(
                    id=f"ORT-L{n:03d}",
                    categoria=Categoria.ORTOGRAFIA,
                    titulo=f"Revisão de texto: {rotulo}",
                    status=Status.NAO_CONFORME,
                    severidade=severidade,
                    secao="Revisão textual",
                    pagina=_pagina_do_offset(doc, m.start()),
                    evidencia="..." + doc.texto[ini:fim].replace("\n", " ") + "...",
                    encontrado=m.group(0),
                    orientacao=orientacao,
                    fundamento="Regra interna de revisão (camada própria)",
                ),
                m.start(),
                m.end(),
            ))
    return achados


def validar(
    doc: Documento,
    usar_languagetool: bool = True,
    limite: int = 200,
) -> tuple[list[Achado], list[str]]:
    """Devolve (achados, avisos)."""
    avisos: list[str] = []
    locais = _regras_locais(doc, limite)

    if not usar_languagetool:
        avisos.append("LanguageTool desabilitado por parâmetro; usadas apenas as regras próprias.")
        return [a for a, _, _ in locais], avisos

    try:
        tool = _ferramenta()
    except Exception as exc:  # Java ausente, download bloqueado, etc.
        avisos.append(
            f"LanguageTool indisponível ({type(exc).__name__}: {exc}). "
            "A revisão usou apenas as regras próprias — considere instalar o "
            "Java 8+ para a checagem gramatical completa."
        )
        return [a for a, _, _ in locais], avisos

    dicionario = carregar_dicionario()
    achados: list[Achado] = []
    cobertos: list[tuple[int, int]] = []
    n = 0
    for match in tool.check(doc.texto):
        if n >= limite:
            avisos.append(f"Revisão gramatical truncada em {limite} ocorrências.")
            break
        if _ignorar(match, dicionario, doc.texto):
            continue
        n += 1
        sugestoes = ", ".join((match.replacements or [])[:3]) or "—"
        tipo = _attr(match, "rule_issue_type", "ruleIssueType", padrao="gramática")
        tamanho = _attr(match, "error_length", "errorLength", padrao=0)
        cobertos.append((match.offset, match.offset + tamanho))
        achados.append(
            Achado(
                id=f"ORT-G{n:03d}",
                categoria=Categoria.ORTOGRAFIA,
                titulo=f"Revisão de texto: {tipo}",
                status=Status.NAO_CONFORME,
                severidade=(
                    Severidade.MEDIO
                    if tipo in ("misspelling", "grammar", "typographical")
                    else Severidade.INFORMATIVO
                ),
                secao="Revisão textual",
                pagina=_pagina_do_offset(doc, match.offset),
                descricao=_attr(match, "message"),
                evidencia=str(_attr(match, "context")).replace("\n", " "),
                encontrado=doc.texto[match.offset : match.offset + tamanho],
                esperado=sugestoes,
                orientacao=f"Sugestão: {sugestoes}",
                fundamento=f"LanguageTool pt-BR / regra {_attr(match, 'rule_id', 'ruleId')}",
            )
        )

    # regras próprias só entram quando o LanguageTool não cobriu o mesmo trecho
    exclusivas = [
        a
        for a, ini, fim in locais
        if not any(ini < f and i < fim for i, f in cobertos)
    ]
    return exclusivas + achados, avisos
