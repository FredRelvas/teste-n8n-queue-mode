#!/usr/bin/env python3
"""
=============================================================================
Script de Teste de Carga para n8n em Modo Fila
=============================================================================
Dispara N requisições simultâneas ao webhook do n8n e mede:
  - Tempo total de execução
  - Tempo médio por requisição
  - Throughput (req/s)
  - Taxa de sucesso/erro
  - Percentis (p50, p90, p95, p99)

Uso:
  python load_test.py --url http://localhost:5678/webhook-test/demo --requests 50 --concurrency 10

Pré-requisitos:
  pip install aiohttp
=============================================================================
"""

import asyncio
import aiohttp
import argparse
import time
import statistics
import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class RequestResult:
    status: int
    duration: float  # seconds
    success: bool
    error: str = ""


@dataclass
class LoadTestReport:
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    total_time: float = 0.0
    durations: List[float] = field(default_factory=list)

    def add(self, result: RequestResult):
        self.total_requests += 1
        self.durations.append(result.duration)
        if result.success:
            self.successful += 1
        else:
            self.failed += 1

    def summary(self) -> dict:
        if not self.durations:
            return {"error": "Nenhuma requisição realizada"}

        sorted_d = sorted(self.durations)
        return {
            "total_requisicoes": self.total_requests,
            "sucesso": self.successful,
            "falhas": self.failed,
            "taxa_sucesso": f"{(self.successful / self.total_requests) * 100:.1f}%",
            "tempo_total_s": round(self.total_time, 2),
            "throughput_req_s": round(self.total_requests / self.total_time, 2),
            "tempo_medio_s": round(statistics.mean(self.durations), 3),
            "tempo_min_s": round(min(self.durations), 3),
            "tempo_max_s": round(max(self.durations), 3),
            "p50_s": round(sorted_d[int(len(sorted_d) * 0.50)], 3),
            "p90_s": round(sorted_d[int(len(sorted_d) * 0.90)], 3),
            "p95_s": round(sorted_d[int(len(sorted_d) * 0.95)], 3),
            "p99_s": round(sorted_d[min(int(len(sorted_d) * 0.99), len(sorted_d) - 1)], 3),
        }


async def send_request(
    session: aiohttp.ClientSession,
    url: str,
    request_id: int,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    """Envia uma requisição POST ao webhook do n8n."""
    payload = {
        "request_id": request_id,
        "timestamp": time.time(),
        "canal": ["whatsapp", "email", "chat", "telefone"][request_id % 4],
        "prioridade": ["alta", "media", "baixa"][request_id % 3],
        "mensagem": f"Requisição de teste #{request_id} - Simulação de atendimento",
    }

    async with semaphore:
        start = time.perf_counter()
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                duration = time.perf_counter() - start
                await resp.text()
                return RequestResult(
                    status=resp.status,
                    duration=duration,
                    success=200 <= resp.status < 300,
                )
        except Exception as e:
            duration = time.perf_counter() - start
            return RequestResult(
                status=0,
                duration=duration,
                success=False,
                error=str(e),
            )


async def run_load_test(url: str, total_requests: int, concurrency: int):
    """Executa o teste de carga."""
    report = LoadTestReport()
    semaphore = asyncio.Semaphore(concurrency)

    print("=" * 70)
    print(" TESTE DE CARGA - n8n Queue Mode")
    print("=" * 70)
    print(f"  URL:           {url}")
    print(f"  Requisições:   {total_requests}")
    print(f"  Concorrência:  {concurrency}")
    print("=" * 70)
    print()

    connector = aiohttp.TCPConnector(limit=concurrency, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        start_time = time.perf_counter()

        tasks = [
            send_request(session, url, i, semaphore)
            for i in range(total_requests)
        ]

        print(f"[>>] Disparando {total_requests} requisições...")
        results = await asyncio.gather(*tasks)

        report.total_time = time.perf_counter() - start_time

        for r in results:
            report.add(r)

    # --- Relatório ---
    summary = report.summary()
    print()
    print("=" * 70)
    print(" RESULTADOS")
    print("=" * 70)
    for key, value in summary.items():
        label = key.replace("_", " ").title()
        print(f"  {label:.<35} {value}")
    print("=" * 70)

    # Salva resultado em JSON
    output_file = f"resultado_carga_{total_requests}req_{concurrency}conc.json"
    with open(output_file, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  Resultado salvo em: {output_file}")

    # Mostra erros se houver
    errors = [r for r in results if not r.success]
    if errors:
        print(f"\n  ⚠ {len(errors)} requisições falharam:")
        for e in errors[:5]:
            print(f"    - Status {e.status}: {e.error}")
        if len(errors) > 5:
            print(f"    ... e mais {len(errors) - 5}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Teste de Carga para n8n em Modo Fila",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Teste básico: 20 requisições, 5 simultâneas
  python load_test.py --url http://localhost:5678/webhook-test/demo -n 20 -c 5

  # Teste pesado: 100 requisições, 20 simultâneas
  python load_test.py --url http://localhost:5678/webhook-test/demo -n 100 -c 20

  # Teste com URL de produção do webhook
  python load_test.py --url http://localhost:5678/webhook/demo -n 50 -c 10
        """,
    )
    parser.add_argument(
        "--url", "-u",
        required=True,
        help="URL do webhook do n8n (ex: http://localhost:5678/webhook-test/demo)",
    )
    parser.add_argument(
        "--requests", "-n",
        type=int,
        default=50,
        help="Número total de requisições (default: 50)",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=10,
        help="Número de requisições simultâneas (default: 10)",
    )
    args = parser.parse_args()
    asyncio.run(run_load_test(args.url, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
