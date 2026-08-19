# conformidade-pbtr-mcp

**Análise automatizada de conformidade de Projetos Básicos e Termos de Referência (MCP server, pt-BR).**

[![Testes](https://github.com/charlesmmorais/conformidade-pbtr-mcp/actions/workflows/testes.yml/badge.svg)](https://github.com/charlesmmorais/conformidade-pbtr-mcp/actions/workflows/testes.yml)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Servidor [MCP](https://modelcontextprotocol.io) que analisa Projetos Básicos
(PB) e Termos de Referência (TR) contra o roteiro de análise do SERPRO. Você
envia o PDF e diz *"conduzir análise de conformidade do PB"*; o servidor devolve
o índice de conformidade, as pendências priorizadas e os relatórios em DOCX,
XLSX, PDF, Markdown e JSON.

Projeto do **SERPRO — Serviço Federal de Processamento de Dados**.

## O que é verificado

| Camada | Verificação |
|---|---|
| **Checklist normativo** | 86 regras derivadas do roteiro `[TI]` de PB/TR — seções 1 a 8, Declarações e Anexos |
| **Numeração** | saltos (5.1 → 5.3), itens duplicados, subitens órfãos, itens fora de ordem, seções obrigatórias ausentes |
| **Tabelas e valores** | colunas mínimas, `Qtd × Unitário = Total`, fechamento do somatório, coerência mensal, valor por extenso × numeral, valor global do texto × tabela |
| **Revisão textual** | 20 regras determinísticas para erros recorrentes em documentos administrativos, mais a revisão de português feita pelo próprio modelo que chama o MCP |

As regras do checklist são **condicionais**. O servidor infere o contexto da
contratação — licitação, contratação direta, inexigibilidade, serviço, bem,
consultoria, treinamento, chamados, subscrição, ARP, hardware/câmbio, vigência
acima de 60 meses — e aplica só os ramos pertinentes do roteiro. Os demais
aparecem como *Não aplicável*, com a razão explicitada. Sem isso, um PB de
hardware receberia dezenas de falsos "não conforme" por não trazer as
justificativas obrigatórias de consultoria.

### Cinco status, não dois

`conforme` / `não conforme` seria insuficiente: vários itens do roteiro pedem
juízo humano ("verificar se há coerência entre eles"). O relatório usa:

| Status | Significado |
|---|---|
| **Conforme** | indício localizado no documento |
| **Não conforme** | nenhuma ocorrência localizada |
| **Atenção** | assunto tratado, mas incompleto — a lista do que falta vem junto |
| **Verificar manualmente** | indício presente; o mérito exige olho humano |
| **Não aplicável** | o contexto do documento não aciona a regra |

## Como a revisão de português funciona

Quem revisa o texto é o **modelo que chamou o MCP** — ele já está com o
documento em contexto, então não faz sentido o servidor abrir uma segunda
conversa com outro modelo para reler o mesmo texto. O servidor cuida do que é
determinístico e entrega o texto segmentado para o agente ler.

Daí o fluxo em três passos, que o agente encadeia sozinho:

```
1. analisar_conformidade      → checklist, numeração, tabelas, valores
                                 (+ regras determinísticas de revisão)
2. obter_texto_para_revisao   → o agente lê e revisa o português
3. registrar_revisao_textual  → apontamentos entram e os relatórios saem
```

**Cada apontamento do agente só entra no relatório se o trecho citado existir
literalmente no documento.** A conferência é feita contra o texto extraído,
tolerando diferença de espaçamento e aspas. Se o modelo não consegue apontar
onde está o erro, o apontamento é descartado e devolvido em `recusados`, com o
motivo — é o que separa uma revisão útil de uma alucinação num relatório que
instrui processo administrativo.

No relatório, essas sugestões aparecem em seção própria, marcadas como não
reprodutíveis, e **ficam fora do índice de conformidade**. Verificação exata e
sugestão de leitura têm pesos diferentes para quem assina o parecer.

## Instalação

Requisito único: Python 3.11+. Não há dependência de Java nem de serviço externo.

```bash
git clone https://github.com/charlesmmorais/conformidade-pbtr-mcp.git
cd conformidade-pbtr-mcp
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Registro no Claude Desktop / Claude Code (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "conformidade-pbtr": {
      "command": "/caminho/para/conformidade-pbtr-mcp/.venv/bin/conformidade-pbtr",
      "env": {
        "CONFORMIDADE_PBTR_SAIDA": "/caminho/onde/gravar/os/relatorios"
      }
    }
  }
}
```

## Deploy hospedado (Fly.io)

O servidor fala **stdio** localmente e **HTTP** quando hospedado. O repositório
traz `Dockerfile` e `fly.toml` prontos:

```bash
fly launch --no-deploy --copy-config
fly deploy
curl https://<sua-app>.fly.dev/health
```

No modo hospedado o cliente não compartilha disco com o servidor: o PDF sobe em
`conteudo_base64` e os relatórios voltam embutidos na resposta. Leia
[`docs/DEPLOY.md`](docs/DEPLOY.md) antes do primeiro deploy — em especial a
seção sobre exposição do endpoint. A imagem tem ~250 MB e roda em 512 MB.

## Tools expostas

Fluxo principal:

| Tool | Uso |
|---|---|
| `analisar_conformidade` | passo 1 — verificações determinísticas |
| `obter_texto_para_revisao` | passo 2 — devolve o texto segmentado para o agente revisar |
| `registrar_revisao_textual` | passo 3 — recebe os apontamentos e emite os relatórios |

Auxiliares:

| Tool | Uso |
|---|---|
| `verificar_numeracao` | só a numeração hierárquica |
| `validar_tabelas` | só tabelas, aritmética e valores |
| `revisar_ortografia` | regras determinísticas + texto segmentado |
| `extrair_estrutura` | diagnóstico da extração (detecta PDF digitalizado) |
| `consultar_checklist` | consulta as regras, por seção, tag ou severidade |
| `gerar_relatorio` | re-renderiza uma análise da sessão em outro formato |

Prompt `conduzir_analise_conformidade`: roteiro de condução da análise pelo
agente, incluindo a ordem de apresentação dos achados e a instrução de não
afirmar conformidade sem que a análise a tenha classificado como tal.

## Uso direto (sem MCP)

```python
from conformidade_pbtr import analisar
from conformidade_pbtr.relatorios import gerar_docx

rel = analisar("PB_123_2026.pdf", tipo="PB")
print(rel.resumo.indice_conformidade)
gerar_docx(rel, "Relatorio_Conformidade.docx")
```

## Índice de conformidade

Média ponderada por severidade (crítico 4, alto 3, médio 2) sobre os itens
**avaliáveis automaticamente**. Itens *Não aplicável*, *Verificar manualmente*,
os apontamentos de revisão textual e as sugestões do agente ficam fora do
cálculo, para não distorcer a nota.

| Faixa | Leitura |
|---|---|
| ≥ 90 | Apto — ajustes pontuais |
| ≥ 75 | Apto com ressalvas |
| ≥ 50 | Requer revisão substantiva |
| < 50 | Não apto — reformulação necessária |

## Checklist plugável

Todo o conhecimento normativo está em `recursos/checklist_roteiro_ti.yaml` — o
motor não conhece norma alguma. Para acompanhar uma revisão do roteiro, edite o
YAML e suba a `versao` em `metadata`; o nome e a versão do checklist usado ficam
gravados em cada relatório, o que torna a análise auditável no tempo.

O projeto hoje atende ao SERPRO. Dar suporte a outro órgão é acrescentar um YAML
em `recursos/` e apontar `CONFORMIDADE_PBTR_CHECKLIST` para ele — nenhuma
alteração de código. O formato está em [`docs/CHECKLIST.md`](docs/CHECKLIST.md).

## Limites conhecidos

- **Aba Itens** — a conferência entre a Aba Itens do sistema e as quantidades do
  PB não é possível a partir do PDF. O item sai sempre como *Verificar
  manualmente*.
- **PDF digitalizado** — sem camada de texto não há análise. `extrair_estrutura`
  sinaliza o caso; aplique OCR antes.
- **Anexos** — verifica-se se o documento *cita* os anexos, não se os arquivos
  existem no processo.
- **Presença ≠ adequação** — o motor confirma que o assunto foi tratado; o mérito
  da justificativa continua sendo do parecerista.

## Documentação

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — decisões de projeto, modelo de dados e roadmap
- [`docs/CHECKLIST.md`](docs/CHECKLIST.md) — formato do YAML e como escrever bons gatilhos
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — deploy no Fly.io, modo remoto e variáveis de ambiente
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — como contribuir

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest -q          # testes sobre um PB sintético com erros plantados
ruff check .
```

O PB de teste é gerado por `exemplos/gerar_pb_teste.py`, com erros propositais
de numeração, aritmética, valor por extenso e português — é o que garante que
cada validador continua pegando o que deveria.

## Licença

[MIT](LICENSE) — Copyright (c) 2026 SERPRO.
