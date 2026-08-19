# syntax=docker/dockerfile:1

# Imagem do servidor MCP de conformidade de PB/TR.
#
# COM_LANGUAGETOOL=1 (padrão) instala a JRE e embute o LanguageTool na imagem,
# para que a primeira requisição não pague o download de ~260 MB. Isso deixa a
# imagem em torno de 1 GB. Com COM_LANGUAGETOOL=0 a imagem cai para ~250 MB e a
# revisão textual roda apenas com as regras próprias do projeto.

FROM python:3.12-slim AS base

ARG COM_LANGUAGETOOL=1
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # pdfplumber depende do pdfminer.six (puro Python), mas o freetype
        # entra pelo Pillow, usado na extração de tabelas
        libfreetype6 \
        libjpeg62-turbo \
    && if [ "$COM_LANGUAGETOOL" = "1" ]; then \
         apt-get install -y --no-install-recommends default-jre-headless; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# camada de dependências, separada do código para aproveitar o cache
COPY pyproject.toml README.md ./
COPY src ./src
COPY recursos ./recursos
RUN pip install --no-cache-dir .

# Baixa o LanguageTool durante o build. Sem isso, a primeira análise em
# produção levaria minutos e poderia estourar o timeout da requisição.
ENV LTP_PATH=/opt/languagetool
RUN if [ "$COM_LANGUAGETOOL" = "1" ]; then \
      mkdir -p "$LTP_PATH" && \
      LTP_PATH="$LTP_PATH" python -c "\
import language_tool_python as lt; \
t = lt.LanguageTool('pt-BR'); \
print('LanguageTool pronto:', t.check('Teste de instalacao.')); \
t.close()"; \
    fi

# O servidor não precisa de root.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app "$LTP_PATH" 2>/dev/null || true
USER appuser

ENV MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8080 \
    CONFORMIDADE_PBTR_MODO=remoto \
    CONFORMIDADE_PBTR_SAIDA=/tmp/relatorios

EXPOSE 8080

CMD ["conformidade-pbtr"]
