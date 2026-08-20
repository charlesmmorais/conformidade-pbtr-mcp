"""Modelos de dados do analisador de conformidade de PB/TR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severidade(StrEnum):
    CRITICO = "critico"
    ALTO = "alto"
    MEDIO = "medio"
    INFORMATIVO = "informativo"

    @property
    def peso(self) -> int:
        return {"critico": 4, "alto": 3, "medio": 2, "informativo": 1}[self.value]


class Status(StrEnum):
    CONFORME = "conforme"
    NAO_CONFORME = "nao_conforme"
    ATENCAO = "atencao"           # indício presente, porém incompleto/ambíguo
    NAO_APLICAVEL = "nao_aplicavel"
    VERIFICAR_MANUAL = "verificar_manual"


class Categoria(StrEnum):
    CHECKLIST = "checklist"       # checklist normativo
    NUMERACAO = "numeracao"
    TABELA = "tabela"
    VALOR = "valor"
    ORTOGRAFIA = "ortografia"
    ESTRUTURA = "estrutura"


class Origem(StrEnum):
    """Como o achado foi produzido.

    Separar as duas origens no relatório é o que impede que uma sugestão não
    reprodutível seja lida com o mesmo peso de uma verificação exata.
    """

    DETERMINISTICO = "deterministico"   # regra, cálculo ou casamento de padrão
    IA = "ia"                           # revisão pelo agente que chamou o MCP


# ---------------------------------------------------------------- documento

@dataclass
class Bloco:
    """Parágrafo ou linha lógica extraída do PDF."""
    texto: str
    pagina: int
    ordem: int
    numeracao: str | None = None      # "5.3.1" quando o bloco inicia com numeração
    nivel: int = 0                    # profundidade da numeração
    is_titulo: bool = False


@dataclass
class Celula:
    bruto: str
    numero: float | None = None
    moeda: bool = False


@dataclass
class Tabela:
    pagina: int
    indice: int
    cabecalho: list[str]
    linhas: list[list[Celula]]
    titulo_proximo: str = ""

    @property
    def n_colunas(self) -> int:
        return len(self.cabecalho)


@dataclass
class Documento:
    caminho: str
    nome: str
    tipo: str = "PB"                  # PB | TR
    formato: str = "pdf"              # pdf | docx | md | txt
    paginas: int = 0
    texto: str = ""
    blocos: list[Bloco] = field(default_factory=list)
    tabelas: list[Tabela] = field(default_factory=list)
    tags_contexto: list[str] = field(default_factory=list)
    metadados: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ achados

@dataclass
class Achado:
    id: str                            # ex. PB-04-002 / NUM-003 / TAB-001
    categoria: Categoria
    titulo: str
    status: Status
    severidade: Severidade
    secao: str = ""
    descricao: str = ""
    evidencia: str = ""                # trecho do documento
    item: str = ""                     # numeração do item do PB/TR (ex. "6.3.1")
    pagina: int | None = None
    esperado: str = ""
    encontrado: str = ""
    orientacao: str = ""
    fundamento: str = ""
    origem: Origem = Origem.DETERMINISTICO

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["categoria"] = self.categoria.value
        d["status"] = self.status.value
        d["severidade"] = self.severidade.value
        d["origem"] = self.origem.value
        return d


@dataclass
class Resumo:
    total_regras: int = 0
    conforme: int = 0
    nao_conforme: int = 0
    atencao: int = 0
    nao_aplicavel: int = 0
    verificar_manual: int = 0
    erros_numeracao: int = 0
    erros_tabela: int = 0
    erros_ortografia: int = 0          # regras determinísticas
    sugestoes_ia: int = 0              # revisão pelo agente
    indice_conformidade: float = 0.0   # 0..100, ponderado por severidade

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Relatorio:
    documento: Documento
    achados: list[Achado] = field(default_factory=list)
    resumo: Resumo = field(default_factory=Resumo)
    gerado_em: str = ""
    versao_checklist: str = ""
    avisos: list[str] = field(default_factory=list)

    def por_categoria(self, cat: Categoria, origem: Origem | None = None) -> list[Achado]:
        return [
            a
            for a in self.achados
            if a.categoria == cat and (origem is None or a.origem == origem)
        ]

    def pendencias(self) -> list[Achado]:
        ordem = {Status.NAO_CONFORME: 0, Status.ATENCAO: 1, Status.VERIFICAR_MANUAL: 2}
        pend = [a for a in self.achados if a.status in ordem]
        return sorted(pend, key=lambda a: (ordem[a.status], -a.severidade.peso, a.id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "documento": {
                "nome": self.documento.nome,
                "tipo": self.documento.tipo,
                "formato": self.documento.formato,
                "paginas": self.documento.paginas,
                "tags_contexto": self.documento.tags_contexto,
                "tabelas_detectadas": len(self.documento.tabelas),
            },
            "gerado_em": self.gerado_em,
            "versao_checklist": self.versao_checklist,
            "resumo": self.resumo.to_dict(),
            "achados": [a.to_dict() for a in self.achados],
            "avisos": self.avisos,
        }
