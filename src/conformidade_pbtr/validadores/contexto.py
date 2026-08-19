"""Inferência das tags de aplicabilidade (que ramos do roteiro incidem no PB)."""

from __future__ import annotations

import re

from ..extratores.pdf import normalizar
from ..modelos import Documento

# tag -> padrões (já normalizados: minúsculo e sem acento)
PADROES: dict[str, list[str]] = {
    "licitacao": [r"licita[cç][aã]o", r"preg[aã]o", r"edital", r"certame", r"concorrencia"],
    "contratacao_direta": [r"dispensa de licitacao", r"contratacao direta", r"compra direta"],
    "inexigibilidade": [r"inexigibilidade", r"inviabilidade de competicao", r"carta abes"],
    "servico": [r"presta[cç][aã]o de servi", r"servicos? de ", r"execucao dos servicos"],
    "bem": [r"aquisi[cç][aã]o de", r"fornecimento de", r"entrega dos? (bens|equipamentos|produtos)"],
    "consultoria": [r"consultoria"],
    "treinamento": [r"treinamento", r"\bcurso\b", r"capacitacao", r"conteudo programatico"],
    "ordem_servico": [r"ordem de servico", r"\bo\.?s\.?\b\s*n"],
    "ordem_fornecimento": [r"ordem de fornecimento"],
    "chamados": [r"abertura de chamados?", r"chamado tecnico", r"service desk", r"regime de atendimento"],
    "grupo": [r"\bgrupo\s*\d", r"\blote\s*\d"],
    "ativos": [r"vida util", r"ativo imobilizado", r"imobilizado"],
    "hardware": [r"\bhardware\b", r"equipamento", r"moeda estrangeira", r"\bdolar\b", r"cambial"],
    "subscricao": [r"subscri[cç][aã]o", r"assinatura anual", r"licenciamento"],
    "garantia_tecnica": [r"garantia tecnica", r"garantia do fabricante"],
    "garantia_execucao": [r"garantia de execucao", r"garantia contratual"],
    "arp": [r"ata de registro de precos", r"\barp\b", r"registro de precos"],
    "marca_modelo": [r"marca e modelo", r"marca/modelo", r"\bpart\s?number\b"],
    "pagamento_mensal": [r"mensalmente", r"valor mensal", r"parcela mensal", r"contraprestacao mensal"],
    "bb_sao_paulo": [r"banco do brasil", r"regional sao paulo"],
    "rescisao_antecipada": [r"rescisao antecipada"],
    "amostra": [r"\bamostra\b", r"prova de conceito", r"\bpoc\b"],
    "atestado_nao_padrao": [r"atestado de capacidade"],
}

# Regras derivadas que não vêm de palavra-chave direta.
RE_MESES = re.compile(r"(\d{1,3})\s*\(?\s*[a-zà-ú ]*\)?\s*(?:\(\w+\)\s*)?meses")


def _meses_maximos(texto_norm: str) -> int:
    valores = [int(m.group(1)) for m in RE_MESES.finditer(texto_norm)]
    return max(valores) if valores else 0


def inferir(doc: Documento) -> list[str]:
    """Devolve a lista de tags de contexto aplicáveis ao documento."""
    texto = normalizar(doc.texto)
    tags = {"sempre"}

    for tag, padroes in PADROES.items():
        if any(re.search(p, texto) for p in padroes):
            tags.add(tag)

    # atestado fora do padrão só é relevante quando não segue a cláusula padrão
    if "atestado_nao_padrao" in tags and re.search(
        r"clausula editalicia padrao", texto
    ):
        tags.discard("atestado_nao_padrao")

    # vigência acima de 60 meses
    if _meses_maximos(texto) > 60 or re.search(r"(120|180)\s*\(?[a-z ]*\)?\s*meses", texto):
        tags.add("vigencia_acima_60")

    # licitação e contratação direta são mutuamente excludentes: prevalece o
    # sinal mais específico
    if "inexigibilidade" in tags or "contratacao_direta" in tags:
        tags.discard("licitacao")

    return sorted(tags)
