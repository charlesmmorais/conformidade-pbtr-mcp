"""Revisão textual em pt-BR.

Duas camadas, com naturezas diferentes e que por isso não se misturam no
relatório:

1. **Regras determinísticas** (aqui neste módulo). Erros recorrentes em
   documentos administrativos que valem uma verificação exata: "a nível de",
   "afim de", "à partir", palavra repetida, grafias trocadas. São
   reprodutíveis, citam a regra que dispararam e não custam nada.

2. **Revisão pelo agente**. O módulo segmenta o texto e entrega os trechos ao
   modelo que chamou o MCP — que já está com o documento em contexto. O modelo
   devolve os apontamentos por `registrar_revisao_textual`, e cada um só entra
   no relatório se o trecho citado existir *literalmente* no documento. Essa
   verificação é o que impede que uma citação inventada vire achado.

A camada 2 pega o que a 1 nunca pegaria — ambiguidade, vaguidão, "poderá" onde
deveria ser "deverá" — mas não é reprodutível. Por isso seus achados entram
como *sugestão de revisão*, marcados com origem `ia`, e ficam fora do índice de
conformidade.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass

from ..caminhos import caminho_dicionario
from ..modelos import Achado, Categoria, Documento, Origem, Severidade, Status

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
    (
        r"\bconcerteza\b",
        "grafia de com certeza",
        'Escreve-se "com certeza", separado.',
        Severidade.ALTO,
    ),
]


@functools.lru_cache(maxsize=1)
def carregar_dicionario() -> set[str]:
    """Termos aceitos — siglas e jargão que não devem virar apontamento."""
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


def _pagina_do_offset(doc: Documento, offset: int) -> int | None:
    if not doc.blocos:
        return None
    acumulado = 0
    for bloco in doc.blocos:
        acumulado += len(bloco.texto) + 1
        if acumulado >= offset:
            return bloco.pagina
    return doc.blocos[-1].pagina


def validar(doc: Documento, limite: int = 200) -> list[Achado]:
    """Aplica as regras determinísticas de revisão."""
    achados: list[Achado] = []
    n = 0
    for padrao, rotulo, orientacao, severidade in REGRAS_LOCAIS:
        for m in re.finditer(padrao, doc.texto, re.IGNORECASE):
            if n >= limite:
                return achados
            n += 1
            ini = max(0, m.start() - 60)
            fim = min(len(doc.texto), m.end() + 60)
            achados.append(
                Achado(
                    id=f"ORT-{n:03d}",
                    categoria=Categoria.ORTOGRAFIA,
                    origem=Origem.DETERMINISTICO,
                    titulo=f"Revisão de texto: {rotulo}",
                    status=Status.NAO_CONFORME,
                    severidade=severidade,
                    secao="Revisão textual",
                    pagina=_pagina_do_offset(doc, m.start()),
                    evidencia="..." + doc.texto[ini:fim].replace("\n", " ") + "...",
                    encontrado=m.group(0),
                    orientacao=orientacao,
                    fundamento="Regra determinística de revisão",
                )
            )
    return achados


# ------------------------------------------- segmentação para o agente

# Linhas que não vale a pena mandar para revisão: numeração solta, valores,
# cabeçalho/rodapé de página.
RE_DESCARTAVEL = re.compile(
    r"^\s*(?:[\d\.\-–—|R$%,\s]+|p[aá]g(?:ina)?\.?\s*\d+(?:\s*/\s*\d+)?)\s*$",
    re.IGNORECASE,
)


@dataclass
class Segmento:
    id: str
    pagina: int
    texto: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "pagina": self.pagina, "texto": self.texto}


def segmentar(doc: Documento, max_caracteres: int = 1200) -> list[Segmento]:
    """Agrupa o texto em segmentos revisáveis, preservando limites de parágrafo.

    Segmentos grandes demais fazem o modelo perder trechos no meio; pequenos
    demais tiram o contexto de que ele precisa para julgar concordância e
    coesão. ~1200 caracteres é o meio-termo.
    """
    segmentos: list[Segmento] = []
    atual: list[str] = []
    pagina_atual = doc.blocos[0].pagina if doc.blocos else 1
    tamanho = 0

    def fechar() -> None:
        nonlocal atual, tamanho
        if atual:
            segmentos.append(
                Segmento(
                    id=f"S{len(segmentos) + 1:03d}",
                    pagina=pagina_atual,
                    texto="\n".join(atual),
                )
            )
            atual = []
            tamanho = 0

    for bloco in doc.blocos:
        texto = bloco.texto.strip()
        if not texto or RE_DESCARTAVEL.match(texto) or len(texto) < 12:
            continue
        if bloco.pagina != pagina_atual or tamanho + len(texto) > max_caracteres:
            fechar()
            pagina_atual = bloco.pagina
        atual.append(texto)
        tamanho += len(texto) + 1

    fechar()
    return segmentos


# --------------------------------- apontamentos vindos do agente (IA)

TIPOS = {
    "ortografia": Severidade.MEDIO,
    "gramatica": Severidade.MEDIO,
    "concordancia": Severidade.MEDIO,
    "regencia": Severidade.MEDIO,
    "crase": Severidade.MEDIO,
    "pontuacao": Severidade.INFORMATIVO,
    "clareza": Severidade.INFORMATIVO,
    "ambiguidade": Severidade.ALTO,
    "impropriedade": Severidade.ALTO,
    "coesao": Severidade.INFORMATIVO,
}


def _achatar(texto: str) -> str:
    """Normaliza espaçamento e aspas para comparar o trecho citado com o texto."""
    t = unicodedata.normalize("NFKC", texto)
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("–", "-").replace("—", "-").replace("­", "")
    return re.sub(r"\s+", " ", t).strip()


def converter_apontamentos(
    doc: Documento,
    apontamentos: list[dict],
) -> tuple[list[Achado], list[dict]]:
    """Converte os apontamentos do agente em achados, descartando os que não
    citam trecho existente no documento.

    Devolve (achados aceitos, apontamentos recusados com o motivo). A checagem
    literal do trecho é o que separa uma revisão útil de uma alucinação: se o
    modelo não consegue apontar onde está o erro, o apontamento não entra.
    """
    aceitos: list[Achado] = []
    recusados: list[dict] = []
    texto_plano = _achatar(doc.texto)
    vistos: set[str] = set()

    for i, ap in enumerate(apontamentos, start=1):
        trecho = str(ap.get("trecho") or "").strip()
        if len(trecho) < 4:
            recusados.append({"indice": i, "motivo": "trecho ausente ou curto demais", "apontamento": ap})
            continue

        agulha = _achatar(trecho)
        if agulha not in texto_plano:
            recusados.append(
                {
                    "indice": i,
                    "motivo": "trecho não localizado literalmente no documento",
                    "trecho": trecho,
                    "apontamento": ap,
                }
            )
            continue

        chave = agulha.lower()
        if chave in vistos:
            recusados.append({"indice": i, "motivo": "apontamento duplicado", "trecho": trecho})
            continue
        vistos.add(chave)

        tipo = str(ap.get("tipo") or "gramatica").lower()
        severidade = TIPOS.get(tipo, Severidade.INFORMATIVO)
        sugestao = str(ap.get("sugestao") or "").strip()
        explicacao = str(ap.get("explicacao") or "").strip()

        pagina = ap.get("pagina")
        if not isinstance(pagina, int):
            pagina = _pagina_do_offset(doc, doc.texto.find(trecho[:40]))

        aceitos.append(
            Achado(
                id=f"ORT-IA-{len(aceitos) + 1:03d}",
                categoria=Categoria.ORTOGRAFIA,
                origem=Origem.IA,
                titulo=f"Sugestão de revisão: {tipo}",
                status=Status.ATENCAO,
                severidade=severidade,
                secao="Revisão textual",
                pagina=pagina,
                descricao=explicacao,
                evidencia=trecho[:300],
                encontrado=trecho[:200],
                esperado=sugestao,
                orientacao=(f"Sugestão: {sugestao}" if sugestao else explicacao) or "Revisar o trecho.",
                fundamento="Revisão pelo agente (não determinística)",
            )
        )

    return aceitos, recusados
