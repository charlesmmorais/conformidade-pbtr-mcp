"""Extração estruturada de PB/TR em PDF (texto, blocos numerados e tabelas)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pdfplumber

from ..modelos import Bloco, Celula, Documento, Tabela

# Aceita "1." / "5.3." / "5.3.1" / "8.1" — mas exige o ponto final quando a
# numeração tem um único nível, para não confundir com a primeira coluna de
# uma tabela ("1  Suporte técnico  12  R$ ...").
RE_NUMERACAO = re.compile(r"^\s*(?:(\d{1,2}\.)|(\d{1,2}(?:\.\d{1,3}){1,4})\.?)\s+(?=\S)")

# Uma linha com dois ou mais valores monetários é conteúdo de tabela achatado
# pelo extrator, não um item numerado do documento.
RE_VALOR = re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})+,\d{2}")


def _parece_linha_de_tabela(linha: str) -> bool:
    return len(RE_VALOR.findall(linha)) >= 2
RE_MOEDA = re.compile(r"R\$\s*")
RE_NUM_BR = re.compile(r"^-?\(?\s*\d{1,3}(?:\.\d{3})*(?:,\d+)?\s*\)?%?$|^-?\(?\s*\d+(?:,\d+)?\s*\)?%?$")


def normalizar(texto: str) -> str:
    """Minúsculas sem acento — usado para casar gatilhos do checklist."""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def parse_numero_br(bruto: str) -> tuple[float | None, bool]:
    """Converte '1.234,56' / 'R$ 1.234,56' / '(1.234,56)' em float."""
    if bruto is None:
        return None, False
    s = str(bruto).strip()
    if not s:
        return None, False
    moeda = bool(RE_MOEDA.search(s))
    s = RE_MOEDA.sub("", s).strip()
    negativo = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    s = s.replace("%", "").strip()
    if not RE_NUM_BR.match(s if not negativo else f"({s})") and not RE_NUM_BR.match(s):
        return None, moeda
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None, moeda
    return (-v if negativo else v), moeda


def _limpar(celula) -> str:
    if celula is None:
        return ""
    return re.sub(r"\s+", " ", str(celula)).strip()


def extrair(caminho: str | Path, tipo: str = "PB") -> Documento:
    """Lê o PDF e devolve um Documento com blocos e tabelas normalizados."""
    caminho = Path(caminho)
    doc = Documento(caminho=str(caminho), nome=caminho.name, tipo=tipo, formato="pdf")

    partes_texto: list[str] = []
    ordem = 0

    with pdfplumber.open(str(caminho)) as pdf:
        doc.paginas = len(pdf.pages)
        doc.metadados = {k: str(v) for k, v in (pdf.metadata or {}).items()}

        for n_pagina, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text(x_tolerance=1.5, layout=False) or ""
            partes_texto.append(texto)

            for linha in texto.split("\n"):
                linha = linha.rstrip()
                if not linha.strip():
                    continue
                ordem += 1
                m = RE_NUMERACAO.match(linha)
                if m and _parece_linha_de_tabela(linha):
                    m = None  # linha de tabela, não item numerado
                numeracao = (m.group(1) or m.group(2)).rstrip(".") if m else None
                nivel = numeracao.count(".") + 1 if numeracao else 0
                corpo = linha[m.end():] if m else linha.strip()
                is_titulo = bool(
                    numeracao
                    and len(corpo) < 90
                    and not corpo.rstrip().endswith((".", ";", ":"))
                ) or (linha.isupper() and 3 < len(linha) < 90)
                doc.blocos.append(
                    Bloco(
                        texto=linha.strip(),
                        pagina=n_pagina,
                        ordem=ordem,
                        numeracao=numeracao,
                        nivel=nivel,
                        is_titulo=is_titulo,
                    )
                )

            for i, bruta in enumerate(pagina.extract_tables() or []):
                if not bruta or len(bruta) < 2:
                    continue
                cabecalho = [_limpar(c) for c in bruta[0]]
                linhas: list[list[Celula]] = []
                for linha_bruta in bruta[1:]:
                    celulas = []
                    for c in linha_bruta:
                        bruto = _limpar(c)
                        numero, moeda = parse_numero_br(bruto)
                        celulas.append(Celula(bruto=bruto, numero=numero, moeda=moeda))
                    linhas.append(celulas)
                doc.tabelas.append(
                    Tabela(pagina=n_pagina, indice=i, cabecalho=cabecalho, linhas=linhas)
                )

    doc.texto = "\n".join(partes_texto)
    return doc


def extrair_docx(caminho: str | Path, tipo: str = "PB") -> Documento:
    """Fallback para PB/TR entregue em .docx (mesma estrutura de saída)."""
    from docx import Document as Docx

    caminho = Path(caminho)
    doc = Documento(caminho=str(caminho), nome=caminho.name, tipo=tipo, paginas=1, formato="docx")
    d = Docx(str(caminho))
    partes = []
    for ordem, p in enumerate(d.paragraphs, start=1):
        txt = p.text.strip()
        if not txt:
            continue
        partes.append(txt)
        m = RE_NUMERACAO.match(txt)
        numeracao = (m.group(1) or m.group(2)).rstrip(".") if m else None
        doc.blocos.append(
            Bloco(
                texto=txt,
                pagina=1,
                ordem=ordem,
                numeracao=numeracao,
                nivel=numeracao.count(".") + 1 if numeracao else 0,
                is_titulo="Heading" in p.style.name,
            )
        )
    for i, t in enumerate(d.tables):
        if not t.rows:
            continue
        cabecalho = [_limpar(c.text) for c in t.rows[0].cells]
        linhas = []
        for row in t.rows[1:]:
            celulas = []
            for c in row.cells:
                bruto = _limpar(c.text)
                numero, moeda = parse_numero_br(bruto)
                celulas.append(Celula(bruto=bruto, numero=numero, moeda=moeda))
            linhas.append(celulas)
        doc.tabelas.append(Tabela(pagina=1, indice=i, cabecalho=cabecalho, linhas=linhas))
    doc.texto = "\n".join(partes)
    return doc


#: extensões aceitas na entrada
FORMATOS_ACEITOS = (".pdf", ".docx", ".md", ".markdown", ".txt")


def carregar(caminho: str | Path, tipo: str = "PB") -> Documento:
    """Despacha para o extrator conforme a extensão do arquivo.

    PDF é o documento de fé, mas custa caro: um PB de 57 páginas leva dezenas
    de segundos e centenas de MB. Markdown e texto são ordens de grandeza mais
    baratos — a ressalva é que costumam ser conversão do PDF oficial, e o que a
    conversão perde some sem aviso. Por isso o formato fica registrado no
    Documento e aparece no relatório.
    """
    ext = Path(caminho).suffix.lower()
    if ext == ".pdf":
        return extrair(caminho, tipo)
    if ext in (".docx", ".doc"):
        return extrair_docx(caminho, tipo)
    if ext in (".md", ".markdown", ".txt"):
        from .texto import extrair as extrair_texto

        return extrair_texto(caminho, tipo)
    raise ValueError(
        f"Formato não suportado: {ext}. Aceitos: {', '.join(FORMATOS_ACEITOS)}."
    )
