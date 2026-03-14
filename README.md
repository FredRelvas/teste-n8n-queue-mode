# n8n Escalável - Guia Rápido

## Pré-requisitos
- Docker e Docker Compose instalados
- Python 3.8+ com `pip install aiohttp`

## Passo a Passo

### 1. Subir o ambiente
```bash
docker compose up -d
```
Aguarde ~30s para todos os serviços subirem. Verifique com:
```bash
docker compose ps
```
Todos os serviços devem estar "running" / "healthy".

### 2. Acessar o n8n
Abra http://localhost:5678 no navegador. Crie sua conta inicial.

### 3. Importar o workflow de demonstração
- No n8n, clique em **"..."** > **"Import from File"**
- Selecione o arquivo `workflow-demo-escalabilidade.json`
- Clique em **"Publish"** (canto superior direito) para ativar o workflow

### 4. Testar manualmente (opcional)
```bash
curl -X POST http://localhost:5678/webhook/demo \
  -H "Content-Type: application/json" \
  -d '{"request_id": 1, "canal": "whatsapp", "prioridade": "alta", "mensagem": "Teste"}'
```

> **Atenção:** use `/webhook/demo` (produção), não `/webhook-test/demo`. O endpoint de teste só funciona enquanto o workflow está aberto no editor.

### 5. Rodar teste de carga
```bash
# Instalar dependência (apenas na primeira vez)
pip install aiohttp

# Teste leve (20 req, 5 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 20 -c 5

# Teste médio (50 req, 10 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 50 -c 10

# Teste pesado (100 req, 20 simultâneas)
python3 load-test.py -u http://localhost:5678/webhook/demo -n 100 -c 20
```

> **Pré-requisito:** o workflow deve estar publicado (passo 3) antes de rodar os testes.

### 6. Monitorar filas
```bash
# Instalar dependências (apenas na primeira vez)
pip install redis rich

# Terminal dedicado para monitoramento
python3 monitor-filas.py

# Ou via RedisInsight: http://localhost:5540
# Adicione conexão: host=localhost, porta=6379
```

### 7. Escalar workers dinamicamente
```bash
# Testar com apenas 1 worker (parar os outros)
docker compose stop n8n-worker-2 n8n-worker-3

# Rodar teste de carga e anotar resultados...

# Agora subir todos os 3 workers
docker compose start n8n-worker-2 n8n-worker-3

# Rodar mesmo teste e comparar resultados!
```

### 8. Limpar tudo
```bash
docker compose down -v  # remove containers E volumes
```

## Estrutura de Arquivos
```
wecancer/
├── docker-compose.yml                  # Infraestrutura completa
├── env                                 # Variáveis de ambiente
├── workflow-demo-escalabilidade.json   # Workflow para importar no n8n
├── load-test.py                        # Script de teste de carga (Python)
├── monitor-filas.py                    # Monitor de filas Redis (Python/rich)
└── README.md                           # Este arquivo
```

## Comparação Esperada (1 worker vs 3 workers)

Com o workflow de demo (delay de 2-4s simulando IA):

| Cenário | 1 Worker (conc=5) | 3 Workers (conc=5 cada) |
|---------|-------------------|-------------------------|
| 50 req  | ~20-30s total     | ~8-12s total            |
| Throughput | ~2-3 req/s     | ~6-8 req/s              |

O campo `worker` na resposta JSON mostra qual hostname processou cada requisição,
provando a distribuição entre os workers.
