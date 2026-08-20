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
from bisect import bisect_right
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


def _indice_do_offset(doc: Documento, offset: int) -> int | None:
    """Índice do bloco que contém um offset do texto integral."""
    if not doc.blocos:
        return None
    acumulado = 0
    for i, bloco in enumerate(doc.blocos):
        acumulado += len(bloco.texto) + 1
        if acumulado >= offset:
            return i
    return len(doc.blocos) - 1


# Numeração de item ("5.", "6.3.1.") — exige o ponto e o espaço seguintes, o
# que descarta valores monetários ("75.623,60") e referências legais
# ("Lei 13.303/2016").
RE_ITEM = re.compile(r"(?:^|[\s(])(\d{1,2}(?:\.\d{1,3}){0,4})\.(?=\s)")


def item_antes_de(texto: str, posicao: int) -> str:
    """Último item numerado que aparece antes de uma posição do texto.

    Resolver no nível do caractere, e não do bloco, importa: num PDF denso o
    extrator junta vários itens na mesma linha, e o item do bloco seria o
    primeiro deles, não aquele em que o trecho de fato está.
    """
    ultimo = ""
    for m in RE_ITEM.finditer(texto, 0, max(posicao, 0) + 1):
        ultimo = m.group(1)
    return ultimo


def item_do_bloco(doc: Documento, indice: int | None) -> str:
    """Numeração do item do PB/TR a que um bloco pertence.

    O bloco pode não iniciar com numeração (é continuação de parágrafo); nesse
    caso vale o item numerado imediatamente anterior. É o que permite citar
    "item 6.3.1" em vez de "página 4" — num PB denso, a página não localiza o
    trecho para quem vai corrigir.
    """
    if indice is None:
        return ""
    for bloco in reversed(doc.blocos[: indice + 1]):
        if bloco.numeracao:
            return bloco.numeracao
    return ""


def _pagina_do_offset(doc: Documento, offset: int) -> int | None:
    i = _indice_do_offset(doc, offset)
    return doc.blocos[i].pagina if i is not None else None


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
            indice = _indice_do_offset(doc, m.start())
            item = item_antes_de(doc.texto, m.start()) or item_do_bloco(doc, indice)
            achados.append(
                Achado(
                    id=f"ORT-{n:03d}",
                    categoria=Categoria.ORTOGRAFIA,
                    origem=Origem.DETERMINISTICO,
                    titulo=f"Revisão de texto: {rotulo}",
                    status=Status.NAO_CONFORME,
                    severidade=severidade,
                    secao="Revisão textual",
                    item=item,
                    pagina=doc.blocos[indice].pagina if indice is not None else None,
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
    item: str = ""            # item do PB/TR em que o segmento começa
    ate_item: str = ""        # último item alcançado pelo segmento

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"id": self.id, "pagina": self.pagina}
        if self.item:
            d["item"] = self.item if self.item == self.ate_item else f"{self.item} a {self.ate_item}"
        d["texto"] = self.texto
        return d


def segmentar(doc: Documento, max_caracteres: int = 1200) -> list[Segmento]:
    """Agrupa o texto em segmentos revisáveis, preservando limites de parágrafo.

    Cada segmento carrega o item do PB/TR que o abre e o que o fecha, para que
    a revisão possa citar o item em vez da página.

    Segmentos grandes demais fazem o modelo perder trechos no meio; pequenos
    demais tiram o contexto de que ele precisa para julgar concordância e
    coesão. ~1200 caracteres é o meio-termo.
    """
    segmentos: list[Segmento] = []
    atual: list[str] = []
    pagina_atual = doc.blocos[0].pagina if doc.blocos else 1
    item_inicial = ""
    item_atual = ""
    tamanho = 0

    def fechar() -> None:
        nonlocal atual, tamanho, item_inicial
        if atual:
            segmentos.append(
                Segmento(
                    id=f"S{len(segmentos) + 1:03d}",
                    pagina=pagina_atual,
                    texto="\n".join(atual),
                    item=item_inicial,
                    ate_item=item_atual or item_inicial,
                )
            )
            atual = []
            tamanho = 0
            item_inicial = ""

    for i, bloco in enumerate(doc.blocos):
        texto = bloco.texto.strip()
        if not texto or RE_DESCARTAVEL.match(texto) or len(texto) < 12:
            continue
        if bloco.pagina != pagina_atual or tamanho + len(texto) > max_caracteres:
            fechar()
            pagina_atual = bloco.pagina
        if not atual:
            item_inicial = bloco.numeracao or item_do_bloco(doc, i)
        if bloco.numeracao:
            item_atual = bloco.numeracao
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
    """Normaliza para comparar o trecho citado com o texto do documento.

    Colapsa espaçamento (o PDF quebra linhas no meio da frase), uniformiza
    aspas e travessões e ignora caixa. Diferença de maiúscula ("Art." x "art.")
    é variação tipográfica, não sinal de citação inventada — barrar por isso
    descartaria apontamento legítimo.
    """
    t = unicodedata.normalize("NFKC", texto)
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("–", "-").replace("—", "-").replace("­", "")
    return re.sub(r"\s+", " ", t).strip().lower()


def _mapa_de_blocos(doc: Documento) -> tuple[str, list[int]]:
    """Texto achatado de todos os blocos e o offset inicial de cada um."""
    partes: list[str] = []
    inicios: list[int] = []
    pos = 0
    for bloco in doc.blocos:
        t = _achatar(bloco.texto)
        inicios.append(pos)
        partes.append(t)
        pos += len(t) + 1
    return " ".join(partes), inicios


def localizar_no_documento(doc: Documento, trecho: str) -> tuple[str, int | None]:
    """Devolve (item, página) onde o trecho citado aparece.

    A busca é feita sobre o texto achatado dos blocos, o que tolera a quebra de
    linha que o PDF insere no meio da frase. Sem isso, o apontamento só poderia
    citar a página — inútil num PB de seis páginas densas.
    """
    agulha = _achatar(trecho)
    if not agulha:
        return "", None
    texto, inicios = _mapa_de_blocos(doc)
    pos = texto.find(agulha)
    if pos < 0:
        return "", None
    indice = bisect_right(inicios, pos) - 1
    if indice < 0:
        return "", None
    item = item_antes_de(texto, pos) or item_do_bloco(doc, indice)
    return item, doc.blocos[indice].pagina


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

        item, pagina_local = localizar_no_documento(doc, trecho)
        if not isinstance(pagina_local, int):
            pagina_local = ap.get("pagina") if isinstance(ap.get("pagina"), int) else None
        # o item declarado pelo agente só prevalece se o localizador não achou
        if not item and isinstance(ap.get("item"), str):
            item = ap["item"].strip()

        aceitos.append(
            Achado(
                id=f"ORT-IA-{len(aceitos) + 1:03d}",
                categoria=Categoria.ORTOGRAFIA,
                origem=Origem.IA,
                titulo=f"Sugestão de revisão: {tipo}",
                status=Status.ATENCAO,
                severidade=severidade,
                secao="Revisão textual",
                item=item,
                pagina=pagina_local,
                descricao=explicacao,
                evidencia=trecho[:300],
                encontrado=trecho[:200],
                esperado=sugestao,
                orientacao=(f"Sugestão: {sugestao}" if sugestao else explicacao) or "Revisar o trecho.",
                fundamento="Revisão pelo agente (não determinística)",
            )
        )

    return aceitos, recusados
