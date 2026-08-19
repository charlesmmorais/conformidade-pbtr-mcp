# Como contribuir

Obrigado pelo interesse. Este é um projeto do SERPRO para análise de
conformidade de Projetos Básicos e Termos de Referência.

## Ambiente

```bash
git clone https://github.com/charlesmmorais/conformidade-pbtr-mcp.git
cd conformidade-pbtr-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Não há dependência de Java nem de rede: os testes rodam offline.

## Os dois tipos de contribuição

### 1. Regras de checklist

A maior parte do valor do projeto está no YAML, não no Python. Se você encontrou
uma regra com gatilho largo demais (carimba "conforme" em qualquer documento) ou
estreito demais (falso "não conforme" em redação legítima), abra uma issue com:

- o `id` da regra;
- o trecho real do documento que deveria (ou não deveria) ter casado;
- a redação alternativa que você propõe para o gatilho.

Trechos de documentos reais devem vir **anonimizados**: sem nome de fornecedor,
CNPJ, número de processo ou valores identificáveis. O que importa é a forma da
redação, não o caso concreto.

Ao editar `recursos/checklist_roteiro_ti.yaml`:

- não reaproveite um `id` já removido — ele aparece em relatórios já emitidos;
- suba `metadata.versao` (semver) a cada mudança de conteúdo;
- leia [`docs/CHECKLIST.md`](docs/CHECKLIST.md) antes, principalmente a seção
  sobre gatilhos.

### 2. Código

Convenções do projeto:

- **Português** em nomes de módulos, funções e mensagens. O domínio é jurídico-
  administrativo brasileiro; traduzir "achado" para "finding" só afasta quem
  precisa ler o relatório.
- **Todo achado precisa de `esperado`, `encontrado` e `orientacao`.** Um
  apontamento sem recomendação transfere trabalho para o analista em vez de
  reduzi-lo.
- **Nada de afirmar mérito.** Quando a verificação não é determinística, o status
  correto é `atencao` ou `verificar_manual` — nunca `conforme`.
- **Degradação graciosa.** Uma dependência opcional indisponível gera aviso no
  relatório, não exceção. A análise nunca deve falhar inteira por causa de uma
  camada.
- `ruff check .` limpo antes do PR.

## Testes

Todo validador novo precisa de teste sobre o PB sintético
(`exemplos/gerar_pb_teste.py`). Se o seu caso não estiver coberto lá, acrescente
o erro proposital ao gerador e o teste correspondente — é assim que se garante
que o validador continua pegando o que deveria depois de refatorações.

```bash
pytest -q
```

## Pull requests

Um PR por assunto, com descrição do problema antes da solução. Se a mudança
altera o comportamento de alguma regra, inclua o antes/depois do status em um
documento de exemplo.

## Reportando problemas de análise

Ao relatar um falso positivo ou falso negativo, informe:

1. o `id` do achado;
2. o status obtido e o esperado;
3. o trecho anonimizado do documento;
4. as `tags_contexto` inferidas (saem no topo do relatório).

Sem o item 4 é difícil distinguir um gatilho ruim de uma inferência de contexto
errada — são correções diferentes.
