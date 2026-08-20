"""Extração de PB/TR em Markdown e texto puro.

Formato de texto é muito mais barato que PDF — o TR de 57 páginas leva 43 s e
303 MB de pico em PDF, contra frações de segundo aqui — e a estrutura de
tabela vem explícita em vez de reconstruída a partir de coordenadas.

O Documento registra o formato de origem, e o relatório avisa quando um arquivo
de texto não trouxe tabela alguma — sem tabela a validação aritmética não roda,
e uma capacidade que some calada é pior que um aviso.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..modelos import Bloco, Celula, Documento, Tabela
from .pdf import RE_NUMERACAO, parse_numero_br

# Linha de tabela Markdown: "| a | b |"
RE_LINHA_TABELA = re.compile(r"^\s*\|(.+)\|\s*$")
# Separador de cabeçalho: "|---|:--:|"
RE_SEPARADOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# Título Markdown: "## 5. Justificativa"
RE_TITULO_MD = re.compile(r"^\s*(#{1,6})\s+(.*)$")
# Marcador de lista, que não faz parte do conteúdo
RE_MARCADOR = re.compile(r"^\s*[-*+]\s+")


def _celulas(linha: str) -> list[str]:
    """Divide uma linha de tabela Markdown em células."""
    corpo = RE_LINHA_TABELA.match(linha)
    if not corpo:
        return []
    return [c.strip() for c in corpo.group(1).split("|")]


def _limpar_markdown(texto: str) -> str:
    """Remove marcação que não é conteúdo, preservando o texto."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)       # negrito
    texto = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", texto)  # itálico
    texto = re.sub(r"`([^`]+)`", r"\1", texto)            # código
    texto = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texto)  # link
    return texto.strip()


def extrair(caminho: str | Path, tipo: str = "PB") -> Documento:
    """Lê um PB/TR em .md, .markdown ou .txt."""
    caminho = Path(caminho)
    doc = Documento(
        caminho=str(caminho),
        nome=caminho.name,
        tipo=tipo,
        paginas=1,
        formato=caminho.suffix.lower().lstrip("."),
    )

    bruto = caminho.read_text(encoding="utf-8", errors="replace")
    linhas = bruto.split("\n")

    partes: list[str] = []
    ordem = 0
    i = 0
    n_tabela = 0

    while i < len(linhas):
        linha = linhas[i].rstrip()

        # ---------------------------------------------------- tabela
        if RE_LINHA_TABELA.match(linha) and i + 1 < len(linhas) and RE_SEPARADOR.match(linhas[i + 1]):
            cabecalho = _celulas(linha)
            i += 2
            corpo: list[list[Celula]] = []
            while i < len(linhas) and RE_LINHA_TABELA.match(linhas[i]):
                celulas = []
                for bruto_celula in _celulas(linhas[i]):
                    valor = _limpar_markdown(bruto_celula)
                    numero, moeda = parse_numero_br(valor)
                    celulas.append(Celula(bruto=valor, numero=numero, moeda=moeda))
                corpo.append(celulas)
                i += 1
            if corpo:
                doc.tabelas.append(
                    Tabela(
                        pagina=1,
                        indice=n_tabela,
                        cabecalho=[_limpar_markdown(c) for c in cabecalho],
                        linhas=corpo,
                    )
                )
                n_tabela += 1
            continue

        # tabela sem separador (texto puro colado): trata como linha comum
        if not linha.strip():
            i += 1
            continue

        # ---------------------------------------------------- título
        m_titulo = RE_TITULO_MD.match(linha)
        if m_titulo:
            conteudo = _limpar_markdown(m_titulo.group(2))
            ordem += 1
            partes.append(conteudo)
            m_num = RE_NUMERACAO.match(conteudo)
            numeracao = (m_num.group(1) or m_num.group(2)).rstrip(".") if m_num else None
            doc.blocos.append(
                Bloco(
                    texto=conteudo,
                    pagina=1,
                    ordem=ordem,
                    numeracao=numeracao,
                    nivel=numeracao.count(".") + 1 if numeracao else 0,
                    is_titulo=True,
                )
            )
            i += 1
            continue

        # ------------------------------------------------- parágrafo
        conteudo = _limpar_markdown(RE_MARCADOR.sub("", linha))
        if conteudo:
            ordem += 1
            partes.append(conteudo)
            m_num = RE_NUMERACAO.match(conteudo)
            numeracao = (m_num.group(1) or m_num.group(2)).rstrip(".") if m_num else None
            corpo_txt = conteudo[m_num.end():] if m_num else conteudo
            doc.blocos.append(
                Bloco(
                    texto=conteudo,
                    pagina=1,
                    ordem=ordem,
                    numeracao=numeracao,
                    nivel=numeracao.count(".") + 1 if numeracao else 0,
                    is_titulo=bool(
                        numeracao
                        and len(corpo_txt) < 90
                        and not corpo_txt.rstrip().endswith((".", ";", ":"))
                    ),
                )
            )
        i += 1

    doc.texto = "\n".join(partes)
    return doc
