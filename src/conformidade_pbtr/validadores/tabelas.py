"""Validação das tabelas de preços e dos valores declarados no PB/TR.

Verifica:
  - presença das colunas mínimas (Descrição, Quantidade, Valor Unitário, Valor Total)
  - aritmética linha a linha        (Quantidade x Valor Unitário = Valor Total)
  - fechamento do somatório         (soma dos totais = linha TOTAL)
  - coerência mensal                (Valor Mensal x nº de meses = Valor Total)
  - valor por extenso               (numeral x extenso)
  - somatório de quantidades por localidade
"""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

from ..extratores.pdf import normalizar, parse_numero_br
from ..modelos import Achado, Categoria, Documento, Severidade, Status, Tabela

TOLERANCIA = 0.02  # R$ 0,02 — absorve arredondamento de centavos

PADROES_COLUNA = {
    "descricao": [r"descri[cç][aã]o", r"especifica[cç][aã]o", r"objeto", r"servi[cç]o", r"^item$"],
    "quantidade": [r"^qtd", r"quantidade", r"^qte"],
    "unitario": [r"valor unit", r"pre[cç]o unit", r"vl.? unit", r"unit[aá]rio"],
    "mensal": [r"valor.*mensal", r"mensalidade", r"pre[cç]o mensal"],
    "meses": [r"meses", r"per[ií]odo", r"n[º°]?\s*de meses"],
    "total": [r"valor total", r"pre[cç]o total", r"vl.? total", r"^total"],
}

RE_EXTENSO = re.compile(
    r"R\$\s*([\d\.]+,\d{2})\s*\(([^)]{6,200})\)", re.IGNORECASE
)
RE_LINHA_TOTAL = re.compile(r"^\s*(total|valor total|total geral|total global)\b", re.I)


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _mapear_colunas(cabecalho: list[str]) -> dict[str, int]:
    """Mapeia papel -> índice da coluna.

    Percorre papel a papel (e não coluna a coluna) para que a ordem dos padrões
    tenha precedência: numa tabela com colunas "Item | Descrição | ...", a
    coluna de descrição é "Descrição" e não "Item".
    """
    mapa: dict[str, int] = {}
    usados: set[int] = set()
    colunas = [_sem_acento(c) for c in cabecalho]

    for papel, padroes in PADROES_COLUNA.items():
        for padrao in padroes:
            p = _sem_acento(padrao)
            for i, c in enumerate(colunas):
                if not c or i in usados:
                    continue
                if re.search(p, c):
                    mapa[papel] = i
                    usados.add(i)
                    break
            if papel in mapa:
                break
    return mapa


def _eh_tabela_preco(mapa: dict[str, int]) -> bool:
    return "total" in mapa and ("unitario" in mapa or "mensal" in mapa or "quantidade" in mapa)


def _extenso_confere(valor: float, extenso: str) -> bool:
    """Compara o valor numérico com a grafia por extenso (tolerante a variações)."""
    alvo = _sem_acento(re.sub(r"\s+", " ", extenso))
    alvo = alvo.replace("reais", "").replace("real", "")
    alvo = alvo.replace("centavos", "").replace("centavo", "")
    alvo = re.sub(r"\b(e|de)\b", " ", alvo)
    alvo = re.sub(r"[^a-z ]", " ", alvo)
    alvo = " ".join(alvo.split())

    ref = num2words(valor, lang="pt_BR", to="currency")
    ref = _sem_acento(ref)
    ref = ref.replace("reais", "").replace("real", "")
    ref = ref.replace("centavos", "").replace("centavo", "")
    ref = re.sub(r"\b(e|de)\b", " ", ref)
    ref = re.sub(r"[^a-z ]", " ", ref)
    ref = " ".join(ref.split())

    if alvo == ref:
        return True
    # comparação por conjunto de tokens (tolera "e" e ordem de centavos)
    return set(alvo.split()) == set(ref.split())


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# ------------------------------------------------------------------ tabelas

def validar_tabela(tab: Tabela, seq: int) -> tuple[list[Achado], float | None]:
    """Valida uma tabela; devolve os achados e o total geral quando identificado."""
    achados: list[Achado] = []
    mapa = _mapear_colunas(tab.cabecalho)
    ref = f"Tabela {seq} (p. {tab.pagina})"

    if not _eh_tabela_preco(mapa):
        return achados, None

    faltando = [
        rotulo
        for papel, rotulo in (
            ("descricao", "Descrição"),
            ("quantidade", "Quantidade"),
            ("unitario", "Valor Unitário"),
            ("total", "Valor Total"),
        )
        if papel not in mapa
    ]
    if faltando:
        achados.append(
            Achado(
                id=f"TAB-{seq:02d}-COL",
                categoria=Categoria.TABELA,
                titulo=f"{ref}: colunas mínimas ausentes",
                status=Status.NAO_CONFORME,
                severidade=Severidade.ALTO,
                secao="4 - Valores e Forma de Pagamento",
                pagina=tab.pagina,
                esperado="Descrição, Quantidade, Valor Unitário e Valor Total",
                encontrado=f"cabeçalho: {' | '.join(tab.cabecalho)}",
                orientacao=(
                    "Acrescentar as colunas ausentes ("
                    + ", ".join(faltando)
                    + "), conforme item 4 do roteiro."
                ),
            )
        )

    soma_totais = 0.0
    total_declarado: float | None = None
    n_erros = 0

    for i, linha in enumerate(tab.linhas, start=1):
        def celula(papel: str, _linha=linha):
            idx = mapa.get(papel)
            if idx is None or idx >= len(_linha):
                return None
            return _linha[idx]

        c_total = celula("total")
        if c_total is None or c_total.numero is None:
            continue

        rotulo = ""
        if "descricao" in mapa and mapa["descricao"] < len(linha):
            rotulo = linha[mapa["descricao"]].bruto
        primeira = linha[0].bruto if linha else ""

        # linha de fechamento: o rótulo "TOTAL" pode estar em qualquer célula
        idx_total = mapa.get("total")
        if any(
            RE_LINHA_TOTAL.match(cel.bruto)
            for j, cel in enumerate(linha)
            if j != idx_total and cel.bruto
        ):
            total_declarado = c_total.numero
            continue

        c_qtd, c_unit, c_mensal, c_meses = (
            celula("quantidade"),
            celula("unitario"),
            celula("mensal"),
            celula("meses"),
        )

        esperado = None
        formula = ""
        if c_qtd and c_unit and c_qtd.numero is not None and c_unit.numero is not None:
            esperado = c_qtd.numero * c_unit.numero
            formula = f"{c_qtd.bruto} x {c_unit.bruto}"
        elif c_mensal and c_meses and c_mensal.numero is not None and c_meses.numero is not None:
            esperado = c_mensal.numero * c_meses.numero
            formula = f"{c_mensal.bruto} x {c_meses.bruto} meses"

        if esperado is not None and abs(esperado - c_total.numero) > TOLERANCIA:
            n_erros += 1
            achados.append(
                Achado(
                    id=f"TAB-{seq:02d}-L{i:02d}",
                    categoria=Categoria.TABELA,
                    titulo=f"{ref}, linha {i}: valor total divergente",
                    status=Status.NAO_CONFORME,
                    severidade=Severidade.CRITICO,
                    secao="4 - Valores e Forma de Pagamento",
                    pagina=tab.pagina,
                    evidencia=(rotulo or primeira)[:120],
                    esperado=f"{formula} = {_fmt(esperado)}",
                    encontrado=f"{c_total.bruto} (diferença de {_fmt(c_total.numero - esperado)})",
                    orientacao="Corrigir o valor total da linha ou os fatores que o compõem.",
                )
            )
        soma_totais += c_total.numero

    if total_declarado is not None and abs(total_declarado - soma_totais) > TOLERANCIA:
        achados.append(
            Achado(
                id=f"TAB-{seq:02d}-SOMA",
                categoria=Categoria.TABELA,
                titulo=f"{ref}: somatório não fecha com a linha de total",
                status=Status.NAO_CONFORME,
                severidade=Severidade.CRITICO,
                secao="4 - Valores e Forma de Pagamento",
                pagina=tab.pagina,
                esperado=f"soma das linhas = {_fmt(soma_totais)}",
                encontrado=f"total declarado = {_fmt(total_declarado)} "
                f"(diferença de {_fmt(total_declarado - soma_totais)})",
                orientacao="Refazer o somatório da tabela e conferir o valor global da contratação.",
            )
        )
    elif total_declarado is None and soma_totais > 0:
        achados.append(
            Achado(
                id=f"TAB-{seq:02d}-SEMTOTAL",
                categoria=Categoria.TABELA,
                titulo=f"{ref}: sem linha de total",
                status=Status.ATENCAO,
                severidade=Severidade.MEDIO,
                secao="4 - Valores e Forma de Pagamento",
                pagina=tab.pagina,
                esperado="linha de fechamento com o valor total",
                encontrado=f"soma das linhas calculada: {_fmt(soma_totais)}",
                orientacao="Incluir linha de total na tabela de preços.",
            )
        )

    if not n_erros and _eh_tabela_preco(mapa) and not faltando:
        achados.append(
            Achado(
                id=f"TAB-{seq:02d}-OK",
                categoria=Categoria.TABELA,
                titulo=f"{ref}: aritmética consistente",
                status=Status.CONFORME,
                severidade=Severidade.INFORMATIVO,
                secao="4 - Valores e Forma de Pagamento",
                pagina=tab.pagina,
                encontrado=f"{len(tab.linhas)} linha(s) conferida(s); soma = {_fmt(soma_totais)}",
            )
        )

    return achados, (total_declarado if total_declarado is not None else soma_totais or None)


# ------------------------------------------------------- valores no texto

def validar_extenso(doc: Documento) -> list[Achado]:
    achados: list[Achado] = []
    n = 0
    for m in RE_EXTENSO.finditer(doc.texto):
        numeral, extenso = m.group(1), m.group(2)
        # descarta parênteses que não são valor por extenso (ex.: "(vide item 3)")
        if not re.search(r"reais|centavos|mil|milh|real", normalizar(extenso)):
            continue
        valor, _ = parse_numero_br(numeral)
        if valor is None:
            continue
        n += 1
        if _extenso_confere(valor, extenso):
            achados.append(
                Achado(
                    id=f"VAL-EXT-{n:02d}",
                    categoria=Categoria.VALOR,
                    titulo="Valor por extenso confere com o numeral",
                    status=Status.CONFORME,
                    severidade=Severidade.INFORMATIVO,
                    secao="4 - Valores e Forma de Pagamento",
                    evidencia=m.group(0)[:160],
                )
            )
        else:
            achados.append(
                Achado(
                    id=f"VAL-EXT-{n:02d}",
                    categoria=Categoria.VALOR,
                    titulo="Valor por extenso divergente do numeral",
                    status=Status.NAO_CONFORME,
                    severidade=Severidade.CRITICO,
                    secao="4 - Valores e Forma de Pagamento",
                    evidencia=m.group(0)[:160],
                    esperado=num2words(valor, lang="pt_BR", to="currency"),
                    encontrado=extenso.strip(),
                    orientacao="Corrigir a grafia por extenso do valor.",
                )
            )
    if n == 0:
        achados.append(
            Achado(
                id="VAL-EXT-00",
                categoria=Categoria.VALOR,
                titulo="Valor total por extenso não localizado",
                status=Status.NAO_CONFORME,
                severidade=Severidade.ALTO,
                secao="4 - Valores e Forma de Pagamento",
                esperado='valor no formato "R$ 1.234,56 (mil duzentos e trinta e quatro reais e cinquenta e seis centavos)"',
                encontrado="nenhuma ocorrência",
                orientacao="Registrar o valor total em numeral e por extenso (item 4 do roteiro).",
            )
        )
    return achados


def validar_coerencia_global(doc: Documento, totais: list[float]) -> list[Achado]:
    """Confronta o valor global citado no texto com o total das tabelas."""
    achados: list[Achado] = []
    if not totais:
        return achados
    maior_tabela = max(totais)

    candidatos: list[float] = []
    for m in re.finditer(
        r"valor (?:total|global)[^\n]{0,80}?R\$\s*([\d\.]+,\d{2})",
        doc.texto,
        re.IGNORECASE,
    ):
        v, _ = parse_numero_br(m.group(1))
        if v:
            candidatos.append(v)

    if not candidatos:
        return achados
    if any(abs(c - maior_tabela) <= TOLERANCIA for c in candidatos):
        achados.append(
            Achado(
                id="VAL-GLOBAL",
                categoria=Categoria.VALOR,
                titulo="Valor global do texto confere com a tabela de preços",
                status=Status.CONFORME,
                severidade=Severidade.INFORMATIVO,
                secao="4 - Valores e Forma de Pagamento",
                encontrado=_fmt(maior_tabela),
            )
        )
    else:
        achados.append(
            Achado(
                id="VAL-GLOBAL",
                categoria=Categoria.VALOR,
                titulo="Valor global do texto diverge do total das tabelas",
                status=Status.NAO_CONFORME,
                severidade=Severidade.CRITICO,
                secao="4 - Valores e Forma de Pagamento",
                esperado=f"total apurado nas tabelas: {_fmt(maior_tabela)}",
                encontrado="no texto: " + ", ".join(_fmt(c) for c in candidatos),
                orientacao="Uniformizar o valor global entre o texto corrido e a tabela de preços.",
            )
        )
    return achados


def validar(doc: Documento) -> list[Achado]:
    achados: list[Achado] = []
    totais: list[float] = []
    for seq, tab in enumerate(doc.tabelas, start=1):
        parciais, total = validar_tabela(tab, seq)
        achados.extend(parciais)
        if total:
            totais.append(total)

    if not doc.tabelas:
        achados.append(
            Achado(
                id="TAB-000",
                categoria=Categoria.TABELA,
                titulo="Nenhuma tabela detectada no documento",
                status=Status.VERIFICAR_MANUAL,
                severidade=Severidade.ALTO,
                secao="4 - Valores e Forma de Pagamento",
                descricao=(
                    "O extrator não encontrou tabelas. O PB pode usar tabelas em "
                    "imagem ou sem linhas de grade."
                ),
                orientacao="Conferir manualmente a tabela de preços ou fornecer o arquivo .docx.",
            )
        )

    achados.extend(validar_extenso(doc))
    achados.extend(validar_coerencia_global(doc, totais))
    return achados
