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

## 2. O que digitar no chat

### 2.1. O pedido — versão curta

Anexe o PDF e diga:

```
Conduzir análise de conformidade do PB em anexo.
```

Funciona, mas deixa a ferramenta adivinhar o tipo de contratação — e é aí que
ela mais erra.

### 2.2. O pedido — versão recomendada

Declarar o contexto custa 20 segundos e elimina a maior fonte de ruído do
relatório. Copie, preencha e cole:

```
Conduzir análise de conformidade do PB em anexo.

Contexto da contratação, para você não depender da inferência:
- Modalidade: pregão eletrônico / dispensa / inexigibilidade
- Natureza: serviço / bem / obra / consultoria / treinamento
- Particularidades: ordem de serviço, grupos ou lotes, registro de preços,
  subscrição, garantia de execução, abertura de chamados, preço em moeda
  estrangeira — mantenha só o que se aplica e apague o resto
- Vigência prevista: XX meses

Ao final, confirme quais tags de contexto você usou e gere os relatórios em
DOCX e XLSX.
```

Apagar o que não se aplica é a parte que importa: cada particularidade que
sobra aciona um ramo do roteiro que vai cobrar cláusulas que o seu documento
não precisa ter.

### 2.3. Corrigir o contexto depois

Se você usou a versão curta e as tags saíram erradas:

```
As tags de contexto estão erradas. É licitação, não contratação direta, e não
há consultoria nem treinamento — essas menções são descrição de perfil
profissional. Refaça a análise com o contexto correto.
```

### 2.4. Aprofundar um achado

O relatório é sintético de propósito. Para instruir o processo:

```
Detalhe o achado PB-06-008: transcreva o trecho exato do documento, diga em
que item ele está e explique o que falta para atender o roteiro.
```

### 2.5. A conferência que sempre vale pedir

```
Confira se o valor total do cabeçalho (Aba Itens) bate com o valor declarado
no corpo do documento, e se as tabelas de preços fecham linha a linha —
quantidade x unitário = total, e a soma dos itens contra o valor global.
```

Nos dois PBs analisados até hoje, esse par de valores divergiu nos dois.

### 2.6. Fechar o parecer

```
Escreva um resumo das pendências críticas em texto corrido, no formato que eu
possa aproveitar no parecer de conformidade, citando o número do item do PB em
cada apontamento. Separe o que é constatação objetiva do que é sugestão de
revisão.
```

### 2.7. Verificações avulsas

Quando não quiser a análise inteira:

```
Confira só a numeração deste PB.
As tabelas de preços deste PB fecham?
Revise o português deste PB.
Este PDF é legível ou precisa de OCR?
O que o roteiro exige na seção 4?
Gera o relatório de novo em PDF.
```

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

## Limites conhecidos

- **PDF digitalizado** não é analisável — aplique OCR antes. A ferramenta avisa.
- **Anexos**: verifica-se se o documento os cita, não se os arquivos existem.
- **Aba Itens do sistema**: conferência manual, como acima.
- O checklist reflete o roteiro `[TI]` na versão gravada em cada relatório.
  Se o roteiro mudar, o YAML precisa acompanhar.
