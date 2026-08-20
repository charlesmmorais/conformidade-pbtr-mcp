"""Geradores de relatório de conformidade (JSON, Markdown, DOCX, XLSX, PDF)."""

from .documento import gerar_docx
from .markdown import gerar_json, gerar_markdown
from .planilha import gerar_xlsx
from .portatil import gerar_pdf

FORMATOS = {
    "json": gerar_json,
    "md": gerar_markdown,
    "markdown": gerar_markdown,
    "docx": gerar_docx,
    "xlsx": gerar_xlsx,
    "pdf": gerar_pdf,
}

__all__ = [
    "FORMATOS",
    "gerar_json",
    "gerar_markdown",
    "gerar_docx",
    "gerar_xlsx",
    "gerar_pdf",
]
