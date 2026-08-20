"""Verificação da numeração hierárquica dos itens do PB/TR.

Detecta:
  - saltos na sequência   (5.1 -> 5.3)
  - repetição de item     (5.1 aparece duas vezes como título)
  - reinício indevido     (5.1, 5.2, 5.1)
  - nível órfão           (5.1.1 sem que exista 5.1)
  - fora de ordem         (5.3 antes de 5.2)
  - seção obrigatória ausente (1 a 8, conforme o roteiro)
"""

from __future__ import annotations

from ..modelos import Achado, Bloco, Categoria, Documento, Severidade, Status

SECOES_ROTEIRO = {
    "1": "Objeto",
    "2": "Especificação do Objeto a ser Contratado",
    "3": "Níveis de Serviço e Sancionamentos",
    "4": "Especificação de Valores e Forma de Pagamento",
    "5": "Justificativa da Contratação",
    "6": "Seleção do Fornecedor",
    "7": "Justificativa para Aceitação de Preços",
    "8": "Gestão Contratual",
}


def _chave(num: str) -> tuple[int, ...]:
    return tuple(int(p) for p in num.split("."))


def _fmt(chave: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in chave)


def _numerados(doc: Documento) -> list[Bloco]:
    return [b for b in doc.blocos if b.numeracao]


def validar(doc: Documento) -> list[Achado]:
    achados: list[Achado] = []
    blocos = _numerados(doc)
    if not blocos:
        achados.append(
            Achado(
                id="NUM-000",
                categoria=Categoria.NUMERACAO,
                titulo="Nenhum item numerado identificado",
                status=Status.VERIFICAR_MANUAL,
                severidade=Severidade.ALTO,
                secao="Estrutura",
                descricao=(
                    "O extrator não localizou itens numerados no padrão "
                    "hierárquico (1., 1.1, 1.1.1). O PDF pode ser digitalizado "
                    "(imagem) ou usar numeração automática não textual."
                ),
                orientacao="Submeter o PDF a OCR ou fornecer a versão .docx do PB/TR.",
            )
        )
        return achados

    vistos: dict[tuple[int, ...], Bloco] = {}
    ultimo_por_pai: dict[tuple[int, ...], tuple[int, ...]] = {}
    n = 0

    for bloco in blocos:
        chave = _chave(bloco.numeracao)
        pai = chave[:-1]

        # duplicidade
        if chave in vistos and bloco.is_titulo and vistos[chave].is_titulo:
            n += 1
            achados.append(
                Achado(
                    id=f"NUM-{n:03d}",
                    categoria=Categoria.NUMERACAO,
                    titulo=f"Item {bloco.numeracao} numerado mais de uma vez",
                    status=Status.NAO_CONFORME,
                    severidade=Severidade.ALTO,
                    secao=f"Seção {chave[0]}",
                    pagina=bloco.pagina,
                    item=bloco.numeracao or "",
                    evidencia=bloco.texto[:200],
                    esperado=f"Numeração {bloco.numeracao} única no documento",
                    encontrado=(
                        f"Repetida (1ª ocorrência na p. {vistos[chave].pagina}: "
                        f"'{vistos[chave].texto[:60]}')"
                    ),
                    orientacao="Renumerar o item duplicado e conferir as remissões internas.",
                )
            )
            continue

        anterior = ultimo_por_pai.get(pai)
        if anterior is None:
            # primeiro item deste nível: deve começar em 1 (ou 0 em alguns modelos)
            if chave[-1] not in (0, 1):
                n += 1
                achados.append(
                    Achado(
                        id=f"NUM-{n:03d}",
                        categoria=Categoria.NUMERACAO,
                        titulo=f"Numeração do nível inicia em {bloco.numeracao}",
                        status=Status.NAO_CONFORME,
                        severidade=Severidade.MEDIO,
                        secao=f"Seção {chave[0]}",
                        pagina=bloco.pagina,
                    item=bloco.numeracao or "",
                        evidencia=bloco.texto[:200],
                        esperado=_fmt(pai + (1,)) if pai else "1",
                        encontrado=bloco.numeracao,
                        orientacao="Iniciar a numeração do nível em 1 ou incluir os itens faltantes.",
                    )
                )
            # nível órfão
            if pai and pai not in vistos:
                n += 1
                achados.append(
                    Achado(
                        id=f"NUM-{n:03d}",
                        categoria=Categoria.NUMERACAO,
                        titulo=f"Subitem {bloco.numeracao} sem item pai {_fmt(pai)}",
                        status=Status.NAO_CONFORME,
                        severidade=Severidade.ALTO,
                        secao=f"Seção {chave[0]}",
                        pagina=bloco.pagina,
                    item=bloco.numeracao or "",
                        evidencia=bloco.texto[:200],
                        esperado=f"Existência do item {_fmt(pai)}",
                        encontrado=f"{_fmt(pai)} ausente",
                        orientacao=f"Criar o item {_fmt(pai)} ou reposicionar o subitem.",
                    )
                )
        else:
            esperado = anterior[:-1] + (anterior[-1] + 1,)
            if chave[-1] > esperado[-1]:
                faltantes = [
                    _fmt(anterior[:-1] + (i,))
                    for i in range(anterior[-1] + 1, chave[-1])
                ]
                n += 1
                achados.append(
                    Achado(
                        id=f"NUM-{n:03d}",
                        categoria=Categoria.NUMERACAO,
                        titulo=f"Salto na numeração: {_fmt(anterior)} → {bloco.numeracao}",
                        status=Status.NAO_CONFORME,
                        severidade=Severidade.ALTO,
                        secao=f"Seção {chave[0]}",
                        pagina=bloco.pagina,
                    item=bloco.numeracao or "",
                        evidencia=bloco.texto[:200],
                        esperado=_fmt(esperado),
                        encontrado=f"{bloco.numeracao} (faltando: {', '.join(faltantes)})",
                        orientacao="Incluir os itens faltantes ou renumerar a sequência.",
                    )
                )
            elif chave[-1] < esperado[-1] and bloco.is_titulo:
                n += 1
                achados.append(
                    Achado(
                        id=f"NUM-{n:03d}",
                        categoria=Categoria.NUMERACAO,
                        titulo=f"Item {bloco.numeracao} fora de ordem",
                        status=Status.NAO_CONFORME,
                        severidade=Severidade.MEDIO,
                        secao=f"Seção {chave[0]}",
                        pagina=bloco.pagina,
                    item=bloco.numeracao or "",
                        evidencia=bloco.texto[:200],
                        esperado=f"numeração ≥ {_fmt(esperado)}",
                        encontrado=bloco.numeracao,
                        orientacao="Reordenar os itens ou corrigir a numeração.",
                    )
                )

        ultimo_por_pai[pai] = chave
        vistos.setdefault(chave, bloco)

    # seções obrigatórias do roteiro
    raizes = {c[0] for c in vistos}
    for numero, nome in SECOES_ROTEIRO.items():
        if int(numero) not in raizes:
            n += 1
            achados.append(
                Achado(
                    id=f"NUM-{n:03d}",
                    categoria=Categoria.ESTRUTURA,
                    titulo=f"Seção {numero} ({nome}) não localizada",
                    status=Status.NAO_CONFORME,
                    severidade=Severidade.CRITICO,
                    secao=f"Seção {numero}",
                    esperado=f"Seção {numero} - {nome}",
                    encontrado="ausente na numeração extraída",
                    orientacao=(
                        f"Incluir a seção {numero} - {nome}, prevista no roteiro "
                        "[TI] de Projetos Básicos e Termos de Referência."
                    ),
                )
            )

    return achados
