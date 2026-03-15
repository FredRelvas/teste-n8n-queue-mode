# n8n Escalável — Demonstração de Queue Mode

Demonstração prática de como escalar o [n8n](https://n8n.io) horizontalmente usando **Queue Mode** com múltiplos workers, Redis como broker de filas e PostgreSQL para persistência.

O projeto simula um sistema de atendimento multicanal (WhatsApp, email, chat, telefone) onde cada mensagem é processada por uma IA. As requisições são distribuídas automaticamente entre workers paralelos via fila Redis (Bull MQ).

## Arquitetura

```
                        ┌──────────────┐
  requisição POST  ───→ │   n8n-main   │  recebe webhooks, NÃO processa
                        └──────┬───────┘
                               │ enfileira job no Redis
                        ┌──────▼───────┐
                        │    Redis     │  fila de jobs (Bull MQ)
                        └──────┬───────┘
              ┌────────────────┼────────────────┐
         ┌────▼─────┐    ┌────▼─────┐    ┌─────▼────┐
         │ worker-1 │    │ worker-2 │    │ worker-3 │   processam em paralelo
         └────┬─────┘    └────┬─────┘    └────┬─────┘
              └────────────────┼────────────────┘
                        ┌──────▼───────┐
                        │  PostgreSQL  │  salva histórico de execuções
                        └──────────────┘
```

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose
- Python 3.8+

## Passo a Passo

### 1. Clonar o repositório

```bash
git clone https://github.com/SEU_USUARIO/teste-n8n-queue-mode.git # Só copiar o link da página
cd teste-n8n-queue-mode
```

### 2. Instalar dependências Python

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Subir o ambiente

```bash
docker compose up -d
```

Aguarde ~30s para todos os serviços subirem. Verifique com:

```bash
docker compose ps
```

Todos os serviços devem estar "running" ou "healthy". Os 3 workers podem levar alguns segundos a mais.

### 4. Acessar o n8n

Abra http://localhost:5678 no navegador e crie sua conta inicial.

### 5. Importar e publicar o workflow

1. No n8n, clique em **"..."** > **"Import from File"**
2. Selecione o arquivo `workflow-demo-escalabilidade.json`
3. Clique em **"Publish"** (canto superior direito) para ativar o workflow

### 6. Testar manualmente (opcional)

```bash
curl -X POST http://localhost:5678/webhook/demo \
  -H "Content-Type: application/json" \
  -d '{"request_id": 1, "canal": "whatsapp", "prioridade": "alta", "mensagem": "Teste"}'
```

> **Atenção:** use `/webhook/demo` (produção), não `/webhook-test/demo`. O endpoint de teste só funciona enquanto o workflow está aberto no editor.

### 7. Rodar teste de carga

```bash
# Teste leve (20 req, 5 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 20 -c 5

# Teste médio (50 req, 10 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 50 -c 10

# Teste pesado (100 req, 20 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 100 -c 20
```

O parâmetro `-n` define o total de requisições e `-c` quantas são disparadas simultaneamente. Para ver a fila de espera se formar no monitor, use `-c` maior que 15 (a capacidade total dos 3 workers).

### 8. Monitorar filas em tempo real

Em um terminal separado:

```bash
python3 monitor-filas.py
```

Exibe em tempo real: jobs ativos, próximos na fila, log de eventos e sparklines com histórico de carga.

Alternativamente, acesse o **RedisInsight** em http://localhost:5540 e conecte em `localhost:6379`.

### 9. Escalar workers dinamicamente

```bash
# Testar com apenas 1 worker (parar os outros)
docker compose stop n8n-worker-2 n8n-worker-3

# Rodar teste de carga e anotar resultados...

# Agora subir todos os 3 workers
docker compose start n8n-worker-2 n8n-worker-3

# Rodar mesmo teste e comparar resultados!
```

### 10. Limpar tudo

```bash
docker compose down -v  # remove containers E volumes
```

## Estrutura de Arquivos

```
├── docker-compose.yml                  # Infraestrutura (n8n + Redis + Postgres)
├── workflow-demo-escalabilidade.json   # Workflow para importar no n8n
├── load-test.py                        # Script de teste de carga (Python/asyncio)
├── monitor-filas.py                    # Monitor de filas em tempo real (Python/rich)
├── requirements.txt                    # Dependências Python
├── .gitignore                          # Arquivos ignorados pelo git
└── README.md                           # Este arquivo
```

## Comparação Esperada (1 worker vs 3 workers)

Com o workflow de demo (delay de 2-4s simulando IA):

| Cenario | 1 Worker (conc=5) | 3 Workers (conc=5 cada) |
|---------|-------------------|-------------------------|
| 50 req  | ~20-30s total     | ~8-12s total            |
| Throughput | ~2-3 req/s     | ~6-8 req/s              |

## O que faltaria para produção

Esta demo é propositalmente simplificada para fins didáticos. Para um ambiente de produção real, as seguintes mudanças seriam necessárias:

### Segurança e configuração

- **Arquivo `.env` com variáveis sensíveis** — nesta demo, as senhas do banco de dados e a encryption key do n8n estão hardcoded no `docker-compose.yml`. Em produção, devem ficar em um `.env` (fora do controle de versão) ou em um gerenciador de segredos (AWS Secrets Manager, HashiCorp Vault, etc.):
  ```env
  POSTGRES_PASSWORD=senha_forte_gerada_aleatoriamente
  N8N_ENCRYPTION_KEY=chave_unica_de_32_caracteres
  N8N_BASIC_AUTH_USER=admin
  N8N_BASIC_AUTH_PASSWORD=senha_do_editor
  ```
- **`N8N_ENCRYPTION_KEY` compartilhada** — o main e todos os workers precisam da mesma chave. Nesta demo ela foi adicionada manualmente ao docker-compose após o main gerar uma automaticamente. Em produção, defina uma chave fixa no `.env` antes de subir o ambiente pela primeira vez.
- **HTTPS/TLS** — o webhook está exposto em HTTP na porta 5678. Em produção, usar um reverse proxy (nginx/Traefik) com certificado SSL.
- **Autenticação no Redis** — o Redis está sem senha. Em produção: `requirepass` no Redis + `QUEUE_BULL_REDIS_PASSWORD` no n8n.
- **Autenticação no editor n8n** — qualquer pessoa com acesso a porta 5678 pode editar workflows. Usar `N8N_BASIC_AUTH` ou SSO.

### Infraestrutura

- **Autoscaling de workers** — em vez de escalar manualmente com `docker compose stop/start`, usar Kubernetes HPA ou KEDA que leem o tamanho da fila Redis e adicionam/removem workers automaticamente.
- **Health checks nos workers** — o docker-compose atual não tem health checks para os workers. Se um worker travar sem cair, o Docker não vai reiniciá-lo.
- **Persistência do Redis** — a configuração atual usa `appendonly yes` mas sem backup. Em produção, usar Redis Sentinel ou Redis Cluster para alta disponibilidade.
- **Backup do PostgreSQL** — não há estratégia de backup. Em produção, usar pg_dump agendado ou um serviço gerenciado (RDS, Cloud SQL).
- **Limites de recursos** — os containers não tem `mem_limit` nem `cpus` definidos. Em produção, limitar para evitar que um container consuma todos os recursos do host.

### Observabilidade

- **Logging centralizado** — os logs ficam apenas no Docker. Em produção, enviar para ELK, Datadog, Grafana Loki, etc.
- **Métricas e alertas** — o n8n expõe métricas Prometheus (`N8N_METRICS=true` já está ativado), mas não há Prometheus/Grafana configurados para coletá-las e criar dashboards.
- **Alertas na fila** — monitorar se `bull:jobs:failed` cresce ou se `bull:jobs:wait` fica grande por muito tempo.
