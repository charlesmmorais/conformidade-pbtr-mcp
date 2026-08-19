# Formato do checklist

O motor de regras não conhece norma alguma: tudo o que ele verifica vem de um
arquivo YAML. Trocar o checklist é trocar o conjunto de exigências analisadas,
sem tocar em uma linha de código.

## Checklist distribuído

| Arquivo | Base normativa | Regras |
|---|---|---:|
| `recursos/checklist_roteiro_ti.yaml` | Roteiro `[TI]` de PB/TR do SERPRO, Lei 13.303/2016, normas LA 002 e LA 008 | 86 |

O projeto hoje atende ao SERPRO. Como o motor lê as regras de um arquivo, dar
suporte a outro órgão é acrescentar um YAML em `recursos/` — nenhuma alteração
de código é necessária.

## Como escolher o checklist

Por ordem de precedência:

```bash
# 1. caminho explícito na chamada da tool MCP
#    analisar_conformidade(..., checklist="/caminho/do/checklist.yaml")

# 2. variável de ambiente apontando um arquivo
export CONFORMIDADE_PBTR_CHECKLIST=/caminho/do/meu_checklist.yaml

# 3. diretório alternativo de recursos (checklist + dicionário)
export CONFORMIDADE_PBTR_RECURSOS=/caminho/dos/recursos

# 4. padrão embarcado (checklist_roteiro_ti.yaml)
```

O nome e a versão do checklist usado ficam registrados em todo relatório
emitido — é o que torna a análise auditável no tempo.

## Estrutura do arquivo

```yaml
metadata:
  versao: "1.0.0"
  fonte: "Norma interna XYZ nº 3/2026"

taxonomia_aplicabilidade:
  sempre: "Vale para qualquer documento"
  servicos: "Prestação de serviços"

regras:
  - id: MEU-001
    secao: "4 - Valores"
    titulo: "Valor total em numeral e por extenso"
    descricao: >-
      Texto do que a norma exige, citado ou parafraseado.
    aplicabilidade: [sempre]
    severidade: critico
    verificacao: presenca
    gatilhos:
      - "valor (total|global)"
      - "R\\$\\s*[\\d\\.]+,\\d{2}"
    orientacao: "O que fazer quando o item não for atendido."
    fundamento: "Norma XYZ, art. 4º"
```

### Campos

| Campo | Obrigatório | O que faz |
|---|---|---|
| `id` | sim | Identificador estável. Não reaproveite um id removido — ele aparece nos relatórios já emitidos. |
| `secao` | sim | Agrupa a regra no relatório. |
| `titulo` | sim | Enunciado curto, aparece na tabela do relatório. |
| `descricao` | não | O que a norma exige; entra no relatório quando o item não é atendido. |
| `aplicabilidade` | sim | Lista de tags. `sempre` = incondicional. A regra só é avaliada se alguma tag casar com o contexto inferido do documento. |
| `severidade` | sim | `critico` (peso 4), `alto` (3), `medio` (2), `informativo` (1). Pondera o índice de conformidade. |
| `verificacao` | sim | `presenca` conclui automaticamente; `coerencia`, `anexo` e `manual` marcam o item como *verificar manualmente* mesmo quando o gatilho casa — use quando o mérito exigir olho humano. |
| `gatilhos` | não | Regex aplicados ao texto normalizado (minúsculo, sem acento, espaçamento colapsado). Sem gatilhos, o item vai direto para *verificar manualmente*. |
| `exige_todos_gatilhos` | não | Quando `true`, todos os gatilhos precisam casar; se só parte casar, o status é *atenção* com a lista do que faltou. |
| `inverter` | não | A regra é uma **vedação**: casar o gatilho gera *atenção*, não casar gera *conforme*. Use para "é vedado o pagamento antecipado". |
| `orientacao` | sim | Recomendação exibida quando o item não é atendido. É a parte do relatório que o analista mais usa. |
| `fundamento` | não | Dispositivo legal ou normativo. Vai para a coluna de rastreabilidade. |

### Escrevendo bons gatilhos

Os gatilhos são comparados contra o texto **normalizado**: minúsculas, sem
acentos, com todo espaçamento colapsado em espaço simples. Isso significa que
`"contrata[cç][aã]o"` funciona (as classes de caractere sobrevivem à remoção de
acento) e que expressões partidas por quebra de linha no PDF continuam casando.

Três armadilhas comuns:

1. **Gatilho largo demais.** `"prazo"` casa em qualquer PB e transforma a regra
   num carimbo de "conforme". Prefira `"prazo de (entrega|execu[cç][aã]o)"`.
2. **Gatilho estreito demais.** Uma redação alternativa comum vira falso "não
   conforme". Use alternância: `"n[ií]ve(l|is) de servi[cç]o|\\bSLA\\b|indicador"`.
3. **Presença ≠ adequação.** Casar a palavra "matriz de riscos" prova que o
   assunto foi tratado, não que a matriz esteja correta. Quando o mérito
   importar, use `verificacao: coerencia` para que o item peça revisão humana.

## Calibração

Antes de confiar num checklist novo, rode-o contra documentos já analisados
manualmente e compare. O ponto de partida é assumir que os gatilhos são
hipóteses; só a amostra real diz quais estão largos ou estreitos demais.

```bash
python -m pytest tests/ -q          # a suíte cobre o formato e o motor
```
