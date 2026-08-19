# syntax=docker/dockerfile:1
#
# Imagem do servidor MCP de conformidade de PB/TR.
#
# A revisão de português é feita pelo modelo que chama o MCP, não por um motor
# embutido — por isso a imagem é só Python, sem JVM. São ~250 MB e roda
# confortavelmente em 512 MB de RAM.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libfreetype/libjpeg entram pelo Pillow, usado pelo pdfplumber na extração
# de tabelas.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY recursos ./recursos
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser
USER appuser

ENV MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8080 \
    CONFORMIDADE_PBTR_MODO=remoto \
    CONFORMIDADE_PBTR_SAIDA=/tmp/relatorios

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["conformidade-pbtr"]
