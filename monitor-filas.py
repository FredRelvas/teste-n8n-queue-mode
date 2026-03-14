#!/usr/bin/env python3
"""
Monitor de Filas - n8n Queue Mode
Uso: python3 monitor-filas.py [--host localhost] [--port 6379] [--interval 0.5]
"""

import argparse
import time
from collections import deque
from datetime import datetime

import redis
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

QUEUE = "bull:jobs"
MAX_LOG = 30
HISTORY_LEN = 40  # pontos no sparkline

event_log: deque[Text] = deque(maxlen=MAX_LOG)
wait_history: deque[int] = deque([0] * HISTORY_LEN, maxlen=HISTORY_LEN)
active_history: deque[int] = deque([0] * HISTORY_LEN, maxlen=HISTORY_LEN)
peak_wait = 0
peak_active = 0
prev = {"wait": 0, "active": 0, "completed": 0, "failed": 0}


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_counts(r: redis.Redis) -> dict:
    # BullMQ usa :wait (LIST) + :priority (ZSET) para jobs aguardando
    wait   = r.llen(f"{QUEUE}:wait") + r.zcard(f"{QUEUE}:priority")
    active = r.llen(f"{QUEUE}:active")
    completed = r.zcard(f"{QUEUE}:completed")
    failed    = r.zcard(f"{QUEUE}:failed")
    delayed   = r.zcard(f"{QUEUE}:delayed")
    return dict(wait=wait, active=active, completed=completed,
                failed=failed, delayed=delayed)


def detect_events(cur: dict):
    global peak_wait, peak_active
    peak_wait   = max(peak_wait,   cur["wait"])
    peak_active = max(peak_active, cur["active"])
    wait_history.append(cur["wait"])
    active_history.append(cur["active"])

    delta_wait      = cur["wait"]      - prev["wait"]
    delta_active    = cur["active"]    - prev["active"]
    delta_completed = cur["completed"] - prev["completed"]
    delta_failed    = cur["failed"]    - prev["failed"]

    if delta_wait > 0:
        event_log.append(Text(f"[{ts()}] +{delta_wait} job(s) entrou na fila", style="yellow"))
    if delta_active > 0:
        event_log.append(Text(f"[{ts()}] +{delta_active} job(s) iniciado(s) pelos workers", style="cyan bold"))
    if delta_completed > 0:
        event_log.append(Text(f"[{ts()}] +{delta_completed} job(s) concluído(s) ✓", style="green bold"))
    if delta_failed > 0:
        event_log.append(Text(f"[{ts()}] +{delta_failed} job(s) falhou ✗", style="red bold"))

    prev.update({k: cur[k] for k in prev})


def sparkline(history: deque[int], color: str) -> Text:
    BLOCKS = " ▁▂▃▄▅▆▇█"
    max_val = max(history) or 1
    chars = "".join(BLOCKS[min(int(v / max_val * 8), 8)] for v in history)
    return Text(chars, style=color)


def build_stats_table(c: dict, r: redis.Redis) -> Panel:
    table = Table(show_header=True, header_style="bold white", box=None,
                  padding=(0, 2), expand=True)
    table.add_column("Estado",   style="bold", min_width=18)
    table.add_column("Agora",    justify="right", min_width=6)
    table.add_column("Pico",     justify="right", min_width=6)
    table.add_column(f"Histórico ({HISTORY_LEN} ticks)", min_width=HISTORY_LEN + 2)

    table.add_row(
        "⏳ Aguardando",
        Text(str(c["wait"]),      style="yellow" if c["wait"] else "dim"),
        Text(str(peak_wait),      style="yellow dim"),
        sparkline(wait_history,   "yellow"),
    )
    table.add_row(
        "⚡ Processando",
        Text(str(c["active"]),    style="cyan bold" if c["active"] else "dim"),
        Text(str(peak_active),    style="cyan dim"),
        sparkline(active_history, "cyan"),
    )
    table.add_row(
        "✅ Concluídos",
        Text(str(c["completed"]), style="green"),
        Text("—", style="dim"),
        Text("", style=""),
    )
    table.add_row(
        "❌ Falhados",
        Text(str(c["failed"]),    style="red" if c["failed"] else "dim"),
        Text("—", style="dim"),
        Text("", style=""),
    )
    table.add_row(
        "⏰ Atrasados",
        Text(str(c["delayed"]),   style="dim"),
        Text("—", style="dim"),
        Text("", style=""),
    )

    mem     = r.info("memory").get("used_memory_human", "?")
    clients = r.info("clients").get("connected_clients", "?")
    footer  = f"  Redis: {mem} memória | {clients} clientes"

    return Panel(table, title="[bold cyan]Filas Bull MQ — n8n[/bold cyan]",
                 subtitle=footer, border_style="cyan")


def build_active_panel(r: redis.Redis) -> Panel:
    active_ids = r.lrange(f"{QUEUE}:active", 0, -1)
    wait_ids   = r.lrange(f"{QUEUE}:wait", 0, 9)          # até 10 próximos
    prio_ids   = r.zrange(f"{QUEUE}:priority", 0, 9)      # até 10 priority

    lines: list[Text] = []

    if active_ids:
        lines.append(Text("  — ativos —", style="cyan dim"))
        for jid in active_ids:
            jid_str = jid.decode() if isinstance(jid, bytes) else str(jid)
            data    = r.hgetall(f"{QUEUE}:{jid_str}")
            ts_ms   = (data.get(b"processedOn") or b"0").decode()
            elapsed = ""
            if ts_ms and ts_ms != "0":
                elapsed = f"{(time.time() * 1000 - float(ts_ms)) / 1000:.1f}s"
            lines.append(Text(f"  ⚡ job #{jid_str} {elapsed}", style="cyan"))
    else:
        lines.append(Text("  (nenhum job ativo)", style="dim italic"))

    pending = list(wait_ids) + list(prio_ids)
    if pending:
        lines.append(Text(""))
        lines.append(Text("  — próximos na fila —", style="yellow dim"))
        for jid in pending[:10]:
            jid_str = jid.decode() if isinstance(jid, bytes) else str(jid)
            lines.append(Text(f"  ⏳ job #{jid_str}", style="yellow"))
        total_wait = r.llen(f"{QUEUE}:wait") + r.zcard(f"{QUEUE}:priority")
        if total_wait > len(pending):
            lines.append(Text(f"  ... e mais {total_wait - len(pending)}", style="yellow dim"))

    content = Text("\n").join(lines)
    title   = f"[bold cyan]Workers ({len(active_ids)} ativos)[/bold cyan]"
    return Panel(content, title=title, border_style="cyan")


def build_log_panel() -> Panel:
    content = (Text("\n").join(event_log)
               if event_log
               else Text("(aguardando eventos...)", style="dim italic"))
    return Panel(content, title="[bold white]Log de Eventos[/bold white]",
                 border_style="white")


def render(r: redis.Redis, interval: float) -> Table:
    c = get_counts(r)
    detect_events(c)

    root = Table.grid(expand=True)
    root.add_row(build_stats_table(c, r))
    root.add_row(Columns([build_active_panel(r), build_log_panel()],
                         equal=True, expand=True))
    root.add_row(Text(f"  Atualiza a cada {interval}s | Ctrl+C para sair", style="dim"))
    return root


def main():
    parser = argparse.ArgumentParser(description="Monitor de filas n8n")
    parser.add_argument("--host",     default="localhost")
    parser.add_argument("--port",     type=int,   default=6379)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    r = redis.Redis(host=args.host, port=args.port, socket_timeout=3)
    try:
        r.ping()
    except Exception:
        print(f"Erro: não foi possível conectar ao Redis em {args.host}:{args.port}")
        raise SystemExit(1)

    console = Console()
    with Live(render(r, args.interval), console=console,
              refresh_per_second=1 / args.interval, screen=True) as live:
        while True:
            time.sleep(args.interval)
            live.update(render(r, args.interval))


if __name__ == "__main__":
    main()
