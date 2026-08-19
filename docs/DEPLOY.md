# Deploy no Fly.io

O servidor roda em dois modos. Local, falando **stdio** com o Claude Desktop.
Hospedado, falando **HTTP** — que é o caso aqui.

## O que muda no modo hospedado

O cliente e o servidor deixam de compartilhar sistema de arquivos. Isso tem duas
consequências práticas:

**O documento sobe na chamada.** `caminho_arquivo` não funciona: um caminho da
máquina do analista não existe dentro do contêiner. Envie o PDF em
`conteudo_base64` junto com `nome_arquivo`. Com `CONFORMIDADE_PBTR_MODO=remoto`
o servidor recusa caminhos locais com mensagem explícita, em vez de devolver
"arquivo não encontrado" e deixar a causa obscura.

**Os relatórios voltam embutidos.** Em modo remoto a resposta traz cada
relatório como `{nome, bytes, base64}` — gravar em `/tmp` no contêiner não
entregaria nada a ninguém, já que o disco é efêmero e some no próximo deploy.

O limite de upload é de 25 MB (`CONFORMIDADE_PBTR_MAX_UPLOAD_MB`). Base64 infla
o payload em ~33%, então um PB de 25 MB chega como ~33 MB de JSON.

## Antes do primeiro deploy: exposição do endpoint

**Um endpoint MCP público e sem autenticação aceita análises de qualquer um.**
Não há segredo no checklist, mas há consumo de CPU e memória por requisição, e
os documentos enviados passam pela sua instância. Decida a exposição antes de
subir:

| Opção | Quando usar | Como |
|---|---|---|
| **Rede privada (recomendado)** | O cliente é interno ou está na mesma organização Fly | Remova `[http_service]` do `fly.toml` e acesse por [Flycast](https://fly.io/docs/networking/flycast/) (`.flycast` interno), sem IP público |
| **Proxy autenticado** | Precisa de acesso externo | Ponha um proxy (Cloudflare Access, oauth2-proxy) na frente e mantenha a app sem IP público |
| **Token na aplicação** | Time pequeno, uso controlado | Configure a autenticação do FastMCP e guarde o segredo com `fly secrets set` |

Público e aberto só faz sentido para um ambiente de testes com dados fictícios.

## Deploy

```bash
fly auth login

# ajuste `app` no fly.toml antes, ou deixe o launch renomear
fly launch --no-deploy --copy-config

fly deploy
fly logs
curl https://<sua-app>.fly.dev/health
```

O `/health` responde com o checklist carregado e o número de regras:

```json
{"status":"ok","checklist":"checklist_roteiro_ti.yaml","regras":86,"modo":"remoto"}
```

Ele falha com 503 se o checklist não carregar — o erro de recurso ausente
derruba o health check em vez de aparecer só na primeira análise real.

## Dimensionamento

A JVM do LanguageTool pede cerca de 1 GB sozinha. Com 512 MB o processo morre
por OOM na primeira análise, e o sintoma (máquina reiniciando sem log claro) não
aponta para a causa. Por isso o `fly.toml` traz `memory = "2gb"`.

Se o custo pesar, `COM_LANGUAGETOOL=0` no `[build.args]` derruba a imagem de
~1 GB para ~250 MB e permite rodar com 512 MB — a revisão textual passa a usar
só as 20 regras próprias do projeto, que cobrem os erros mais recorrentes em
documentos administrativos mas não fazem análise gramatical geral. As outras
três camadas (checklist, numeração, tabelas) não são afetadas.

`min_machines_running = 1` evita que a primeira análise após um período ocioso
pague a subida da JVM. Com `auto_stop_machines = "suspend"` a máquina suspende
mantendo a memória, o que torna o retorno rápido.

## Conectando o cliente

```json
{
  "mcpServers": {
    "conformidade-pbtr": {
      "type": "http",
      "url": "https://<sua-app>.fly.dev/mcp"
    }
  }
}
```

Chamada típica no modo hospedado:

```jsonc
{
  "name": "analisar_conformidade",
  "arguments": {
    "conteudo_base64": "<PDF em base64>",
    "nome_arquivo": "PB_123_2026.pdf",
    "tipo": "PB",
    "formatos": ["md", "docx", "xlsx"]
  }
}
```

## Rodando local em HTTP (para testar antes do deploy)

```bash
MCP_TRANSPORT=http PORT=8080 CONFORMIDADE_PBTR_MODO=remoto conformidade-pbtr
curl http://127.0.0.1:8080/health
```

Ou pela imagem, o que também valida o Dockerfile:

```bash
docker build -t conformidade-pbtr .
docker run --rm -p 8080:8080 conformidade-pbtr
```

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `http` para servidor hospedado |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | Endereço de escuta em modo HTTP |
| `CONFORMIDADE_PBTR_MODO` | — | `remoto` recusa caminhos locais e embute os relatórios |
| `CONFORMIDADE_PBTR_MAX_UPLOAD_MB` | `25` | Teto do upload em base64 |
| `CONFORMIDADE_PBTR_SAIDA` | temp do sistema | Onde os relatórios são gravados |
| `CONFORMIDADE_PBTR_CHECKLIST` | checklist embarcado | Checklist alternativo |
| `CONFORMIDADE_PBTR_RECURSOS` | `recursos/` | Diretório alternativo de recursos |
