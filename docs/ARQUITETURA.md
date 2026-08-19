# Documento de Projeto — MCP Conformidade PB/TR

Versão 1.0 · 19/08/2026

---

## 1. Problema

A análise de conformidade de Projetos Básicos e Termos de Referência hoje é
manual: o analista percorre o roteiro `[TI] Roteiro - Projetos Básicos e Termos
de Referência` item a item, confere numeração, refaz as contas das tabelas de
preços e revisa o texto. São 163 pontos de verificação no roteiro, muitos deles
condicionais (só valem para consultoria, ou só para licitação, ou só quando a
vigência ultrapassa 60 meses).

Três consequências: o tempo de análise é alto, a cobertura varia entre
analistas, e os erros mecânicos — salto de numeração, soma que não fecha, valor
por extenso divergente — passam com frequência porque exigem atenção repetitiva.

## 2. Objetivo

Um servidor MCP que, ao receber o PDF de um PB/TR, produza um relatório de
conformidade cobrindo:

1. os itens do roteiro `[TI]`, aplicados condicionalmente ao tipo de contratação;
2. a numeração hierárquica dos itens;
3. a validação das tabelas e dos valores;
4. a revisão ortográfica e gramatical em pt-BR.

O alvo é **eliminar o trabalho mecânico e dirigir a atenção do analista** para o
mérito — não substituir o parecer.

## 3. Escopo

### Dentro

- Extração de PB/TR em PDF com camada de texto e em DOCX.
- Motor de regras condicionais sobre o checklist do roteiro.
- Verificações determinísticas de numeração, aritmética e valores.
- Revisão textual com dicionário institucional.
- Relatórios em DOCX, XLSX, PDF, Markdown e JSON.

### Fora (por ora)

- Conferência com a **Aba Itens** do sistema de contratações (não está no PDF).
- Verificação da existência física dos anexos no processo.
- Juízo de mérito sobre a suficiência das justificativas.
- OCR de PDF digitalizado (o servidor detecta e avisa).
- Pesquisa de preços — já coberta pelo MCP `govbr-radardeprecos`, com o qual
  este servidor é complementar.

## 4. Arquitetura

```
                    ┌──────────────────────────┐
   PDF/DOCX  ─────► │  extratores/pdf.py       │
                    │  texto · blocos numerados│
                    │  tabelas · células       │
                    └────────────┬─────────────┘
                                 │ Documento
              ┌──────────────────┼───────────────────┐
              ▼                  ▼                   ▼
   ┌──────────────────┐ ┌────────────────┐ ┌──────────────────┐
   │ contexto.py      │ │ numeracao.py   │ │ tabelas.py       │
   │ infere as tags   │ │ hierarquia dos │ │ aritmética,      │
   │ de aplicabilidade│ │ itens          │ │ somatórios,      │
   └────────┬─────────┘ └────────┬───────┘ │ extenso, global  │
            │ tags              │          └────────┬─────────┘
            ▼                   │                   │
   ┌──────────────────┐         │          ┌────────▼─────────┐
   │ checklist.py     │         │          │ ortografia.py    │
   │ motor de regras  │         │          │ LanguageTool +   │
   │ + YAML do roteiro│         │          │ regras próprias  │
   └────────┬─────────┘         │          └────────┬─────────┘
            └──────────┬────────┴───────────────────┘
                       ▼  list[Achado]
              ┌─────────────────┐
              │ analisador.py   │  índice de conformidade, resumo, avisos
              └────────┬────────┘
                       ▼ Relatorio
        ┌──────────────┴──────────────┐
        ▼                             ▼
  relatorios/*                   servidor.py (FastMCP)
  docx · xlsx · pdf · md · json  7 tools + 1 prompt
```

### Decisões de projeto

**O conhecimento normativo mora em YAML, não em código.** As 86 regras do
checklist são dados (`recursos/checklist_roteiro_ti.yaml`). Quando o roteiro for
revisado, edita-se o YAML e sobe-se a versão — sem tocar em Python, sem redeploy
de lógica. A versão usada fica gravada em cada relatório, o que torna a análise
auditável no tempo.

**Regras condicionais em vez de checklist plano.** Aplicar as 86 regras a todo
PB produziria dezenas de falsos "não conforme" (cobrar justificativa de
consultoria num PB de hardware). Cada regra declara as tags de contexto em que
incide; `contexto.py` infere as tags do documento; o agente pode corrigir a
inferência via `tags_contexto`. Regras fora do contexto saem como *Não
aplicável* com a razão explícita.

**Quatro status, não dois.** `conforme` / `não conforme` é insuficiente: muitos
itens do roteiro exigem juízo humano ("verificar se há coerência entre eles").
O sistema usa cinco: **conforme**, **não conforme**, **atenção** (indício
presente mas incompleto), **verificar manualmente** (indício presente, mérito é
humano) e **não aplicável**. Isso é o que impede o relatório de dar falsa
segurança.

**Verificações determinísticas separadas do texto.** Numeração, aritmética e
valor por extenso não dependem de casamento de padrão em linguagem natural — são
exatos, reprodutíveis e não têm falso positivo. São a parte de maior retorno da
automação e por isso ficam em módulos próprios, com testes específicos.

**Ortografia em duas camadas.** LanguageTool local (offline, determinístico,
auditável) para gramática geral, mais 20 regras próprias para os erros
recorrentes em documentos administrativos que o LT não pega bem ("a nível de",
"R$ 1.000,00 reais", "à partir"). As duas camadas são deduplicadas por offset.
Se o Java não estiver instalado, a camada própria continua e a análise registra
um aviso — a ferramenta nunca falha por causa da revisão textual.

**Cache de sessão.** `analisar_conformidade` guarda o `Relatorio` em memória sob
uma chave; `gerar_relatorio` re-renderiza em outro formato sem reprocessar o
PDF (a análise com LanguageTool leva ~20 s).

## 5. Modelo de dados

`Achado` é a unidade do relatório:

| Campo | Papel |
|---|---|
| `id` | `PB-04-002` (regra do roteiro), `NUM-003`, `TAB-01-L02`, `VAL-EXT-01`, `ORT-G007` |
| `categoria` | checklist · estrutura · numeracao · tabela · valor · ortografia |
| `status` | conforme · nao_conforme · atencao · verificar_manual · nao_aplicavel |
| `severidade` | critico (4) · alto (3) · medio (2) · informativo (1) |
| `esperado` / `encontrado` | o que o roteiro pede × o que o documento traz |
| `evidencia` + `pagina` | trecho citável, para o analista localizar |
| `orientacao` | o que fazer para corrigir |
| `fundamento` | rastreabilidade (regra do roteiro, versão do checklist, regra do LT) |

Todo achado é rastreável até a norma que o originou — requisito para que o
relatório sirva de instrução processual.

## 6. Fluxo de uso

O usuário diz *"conduzir análise de conformidade do PB"* e envia o PDF. O agente:

1. chama `extrair_estrutura` — se o PDF for digitalizado, avisa e para;
2. confirma o contexto quando a inferência for ambígua;
3. chama `analisar_conformidade` com os formatos desejados;
4. apresenta índice → pendências críticas → divergências de valor → numeração →
   resumo da revisão textual;
5. destaca à parte os itens de conferência manual, sobretudo a Aba Itens;
6. entrega os arquivos.

O prompt `conduzir_analise_conformidade` codifica esse roteiro, incluindo a
instrução de não afirmar conformidade sem que a análise a tenha classificado.

## 7. Roadmap

### Fase 1 — Núcleo funcional ✅ (entregue)

Extração PDF/DOCX, 86 regras do checklist, validadores de numeração/tabelas/
valores/ortografia, 5 formatos de relatório, 7 tools MCP, 29 testes.

### Fase 2 — Precisão (2 a 3 semanas)

- Calibrar os gatilhos do checklist com **20 a 30 PBs reais já analisados**,
  medindo falso positivo e falso negativo por regra. É o passo de maior impacto
  e depende de amostra real — sem ele, os gatilhos são hipóteses.
- Ampliar o dicionário do SERPRO com os termos que aparecerem nessa amostra.
- Extração de tabelas sem linhas de grade (estratégia `text` do pdfplumber como
  fallback) e de tabelas que quebram entre páginas.
- Conferência cruzada de quantidades: soma por localidade × total do item ×
  quantidade citada no texto corrido.

### Fase 3 — Integração (3 a 4 semanas)

- Leitura da **Aba Itens** (CSV/XLSX exportado ou API do sistema), fechando a
  única verificação crítica hoje impossível.
- Confronto automático PB × ETP × DOD quando os três forem fornecidos:
  quantidades, objeto e valores devem ser coerentes entre si.
- Verificação de cláusulas padrão por similaridade textual contra os arquivos
  `Cláusulas Padrão.docx` e `Cláusulas de OS e OF.docx` — hoje só se verifica a
  presença do assunto, não a fidelidade da redação.
- Ponte com o MCP `govbr-radardeprecos`: quando o PB trouxer preços, checar a
  aderência à IN SEGES/ME 65/2021 e à LA 002.

### Fase 4 — Escala (4+ semanas)

- OCR embutido para PDFs digitalizados (Tesseract pt-BR).
- Análise em lote de uma pasta de PBs, com painel comparativo.
- Trilha de auditoria: histórico de análises por documento, com diff entre
  versões do PB e evolução do índice de conformidade.
- Modo "sugestão de redação": para cada não conformidade, propor o texto da
  cláusula a partir das cláusulas padrão.

## 8. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Falso "conforme" por casamento superficial de palavra-chave | Alto — dá falsa segurança | Status *atenção* e *verificar manualmente*; nunca afirmar mérito; calibração da Fase 2 |
| Falso "não conforme" por redação atípica | Médio — ruído, perda de confiança | `exige_todos_gatilhos`, gatilhos com sinônimos, calibração com amostra real |
| PDF digitalizado | Médio — análise vazia | Detecção automática + aviso; OCR na Fase 4 |
| Roteiro revisado e checklist desatualizado | Alto — análise contra norma vencida | Versão do checklist gravada em todo relatório; YAML editável sem deploy |
| Dependência de Java (LanguageTool) | Baixo | Degradação graciosa para as regras próprias, com aviso |

## 9. Backlog imediato

1. Rodar o analisador sobre 20 PBs reais já analisados e montar a matriz de
   confusão por regra.
2. Ajustar os gatilhos com pior desempenho.
3. Definir o formato de exportação da Aba Itens com a área de sistemas.
4. Empacotar como plugin Cowork, junto com uma skill que dispare a análise ao
   ouvir "conduzir análise de conformidade".
