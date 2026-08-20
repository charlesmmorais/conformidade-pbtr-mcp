# Micro manual — análise de conformidade de PB/TR

## O que a ferramenta faz

Lê o PDF de um Projeto Básico ou Termo de Referência e devolve um relatório com
quatro camadas de verificação: os itens do roteiro `[TI]`, a numeração
hierárquica, a aritmética das tabelas e os valores, e a revisão de português.

**O que ela não faz:** julgar o mérito. Ela confirma que o assunto foi tratado,
não que a justificativa é suficiente. O parecer continua sendo seu.

## 1. Instalar

Uma vez só, na sua máquina:

```powershell
cd C:\Users\<você>\...\conformidade-pbtr-mcp
python -m venv .venv
.venv\Scripts\pip install -e .
```

E no `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "conformidade-pbtr": {
      "command": "C:\\...\\conformidade-pbtr-mcp\\.venv\\Scripts\\conformidade-pbtr.exe",
      "env": { "CONFORMIDADE_PBTR_SAIDA": "C:\\...\\relatorios" }
    }
  }
}
```

Reinicie o Claude Desktop. Os relatórios vão cair na pasta indicada em
`CONFORMIDADE_PBTR_SAIDA`.

> Rode **local**. O servidor hospedado existe para integração com outro
> sistema; para quem tem o PDF na máquina, o local é mais rápido e sem limite
> de tamanho.

## 2. Usar

Anexe o PDF e diga:

> **conduzir análise de conformidade do PB**

Só isso. A IA encadeia os três passos sozinha — verificações determinísticas,
leitura do texto, geração dos relatórios — e entrega DOCX, XLSX e PDF.

Se o documento for TR, diga "do TR". Se a inferência de contexto errar (veja
abaixo), corrija em linguagem natural: *"é licitação, não contratação direta"*.

## 3. Ler o relatório

**Índice de conformidade** — média ponderada por severidade, só dos itens
verificáveis automaticamente.

| Faixa | Leitura |
|---|---|
| ≥ 90 | Apto, ajustes pontuais |
| ≥ 75 | Apto com ressalvas |
| ≥ 50 | Requer revisão substantiva |
| < 50 | Reformulação necessária |

**Cinco status**, e a diferença entre eles é o que evita falsa segurança:

| Status | Significa |
|---|---|
| Conforme | o assunto foi localizado no texto |
| Não conforme | nenhuma ocorrência localizada |
| Atenção | tratado, mas incompleto — a lista do que falta vem junto |
| **Verificar manualmente** | há indício; o mérito exige você |
| Não aplicável | o contexto do documento não aciona a regra |

Todo achado cita o **item do PB** ("item 6.3.1"), não só a página. Comece pela
aba *Checklist* da planilha, filtrando por severidade `critico`.

**Sugestões de revisão** aparecem em seção própria, marcadas como não
reprodutíveis, e ficam fora do índice. Vêm da leitura por IA: úteis, mas não
têm o mesmo peso de uma conta que fecha ou não fecha.

## 4. Os três cuidados que importam

**Confira o contexto inferido**, no topo do relatório. A ferramenta deduz do
texto se é licitação, contratação direta, serviço, consultoria etc., e isso
decide quais regras se aplicam. Ela erra com frequência, quase sempre por causa
de negações — um PB que diz *"não se trata de contratação direta"* pode ser
classificado como contratação direta. Se as tags estiverem erradas, mande
corrigir e peça para refazer.

**Presença não é adequação.** "Matriz de riscos: conforme" quer dizer que
existe uma matriz, não que ela esteja boa.

**A Aba Itens.** O sistema imprime o cabeçalho com o preço total no próprio
PDF, e ele diverge do corpo do documento com alguma frequência — nos dois PBs
analisados até agora, divergiu nos dois (R$ 18,84 e R$ 1,60). Vale sempre
conferir esse par de valores à mão.

## 5. Quando o resultado parecer errado

Se um item aparecer como "não conforme" mas você souber que está no documento,
quase sempre é o **gatilho** da regra que não cobriu a redação usada. Casos
reais já corrigidos: o PB escrevia "Formas de Pagamento" no plural, "menor
**valor** global" em vez de "menor preço", "Impactos da Não Contratação" em vez
de "consequências".

Abra uma issue com o `id` da regra, o trecho anonimizado que deveria ter casado
e a redação que você propõe. Ou edite direto o
`recursos/checklist_roteiro_ti.yaml` e suba a versão — o formato está em
[`CHECKLIST.md`](CHECKLIST.md).

## 6. Verificações avulsas

Quando quiser só uma parte, peça em linguagem natural:

| Pedido | Tool |
|---|---|
| "confira só a numeração deste PB" | `verificar_numeracao` |
| "as tabelas fecham?" | `validar_tabelas` |
| "revise o português" | `revisar_ortografia` |
| "esse PDF é legível?" | `extrair_estrutura` |
| "o que o roteiro exige na seção 4?" | `consultar_checklist` |
| "gera de novo em PDF" | `gerar_relatorio` |

## Limites conhecidos

- **PDF digitalizado** não é analisável — aplique OCR antes. A ferramenta avisa.
- **Anexos**: verifica-se se o documento os cita, não se os arquivos existem.
- **Aba Itens do sistema**: conferência manual, como acima.
- O checklist reflete o roteiro `[TI]` na versão gravada em cada relatório.
  Se o roteiro mudar, o YAML precisa acompanhar.
