from __future__ import annotations

import argparse
import os
import queue
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv


LOCALTUNNEL_URL_PATTERN = re.compile(r"https://[^\s]+\.loca\.lt")


def main() -> int:
    """starts the local app and exposes the CloudMailin webhook via Localtunnel."""
    parser = argparse.ArgumentParser(
        description="Run Project Swift's CloudMailin webhook through Localtunnel."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host interface for FastAPI.")
    parser.add_argument("--port", default=8025, type=int, help="Local FastAPI port.")
    parser.add_argument(
        "--endpoint",
        default="/api/emails/cloudmailin",
        help="Webhook path to print for CloudMailin.",
    )
    parser.add_argument(
        "--subdomain",
        default="",
        help="Optional Localtunnel subdomain request.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload FastAPI when application files change.",
    )
    parser.add_argument(
        "--localtunnel-bin",
        default="npx",
        help="Localtunnel launcher. Use npx by default, or lt if installed globally.",
    )
    args = parser.parse_args()

    load_dotenv()
    app_process: subprocess.Popen[str] | None = None
    tunnel_process: subprocess.Popen[str] | None = None
    output_queue: queue.Queue[tuple[str, str]] = queue.Queue()

    try:
        _ensure_localtunnel_launcher(args.localtunnel_bin)
        app_process = _start_process(
            [
                sys.executable,
                "-m",
                "app.dummy_email_server",
                "--host",
                args.host,
                "--port",
                str(args.port),
                *(["--reload"] if args.reload else []),
            ],
            "fastapi",
            output_queue,
        )
        _wait_for_port("127.0.0.1", args.port)

        tunnel_process = _start_process(
            _localtunnel_command(args.localtunnel_bin, args.port, args.subdomain),
            "localtunnel",
            output_queue,
        )

        tunnel_url = _wait_for_tunnel_url(output_queue)
        _print_cloudmailin_target(tunnel_url, args.endpoint)
        _forward_output(output_queue)
        return 0
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate("localtunnel", tunnel_process)
        _terminate("fastapi", app_process)


def _start_process(
    command: Sequence[str],
    name: str,
    output_queue: queue.Queue[tuple[str, str]],
) -> subprocess.Popen[str]:
    """starts a child process and forwards its combined output to a queue."""
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    threading.Thread(
        target=_read_process_output,
        args=(process, name, output_queue),
        daemon=True,
    ).start()
    return process


def _read_process_output(
    process: subprocess.Popen[str],
    name: str,
    output_queue: queue.Queue[tuple[str, str]],
) -> None:
    """streams child process output without blocking startup orchestration."""
    if process.stdout is None:
        return
    for line in process.stdout:
        output_queue.put((name, line.rstrip()))


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    """waits until the local FastAPI process accepts TCP connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"FastAPI did not start on {host}:{port} within {timeout}s.")


def _localtunnel_command(
    localtunnel_bin: str,
    port: int,
    subdomain: str,
) -> list[str]:
    """builds a Localtunnel command for npx or a globally installed lt binary."""
    binary_name = Path(localtunnel_bin).name
    if binary_name == "npx":
        command = [localtunnel_bin, "localtunnel", "--port", str(port)]
    else:
        command = [localtunnel_bin, "--port", str(port)]
    if subdomain:
        command.extend(["--subdomain", subdomain])
    return command


def _ensure_localtunnel_launcher(localtunnel_bin: str) -> None:
    """fails early with install guidance when Localtunnel cannot be launched."""
    if shutil.which(localtunnel_bin):
        return

    binary_name = Path(localtunnel_bin).name
    if binary_name == "npx":
        raise RuntimeError(
            "npx was not found. Install Node.js/npm first, then rerun this script. "
            "On macOS with Homebrew: brew install node. "
            "If you install Localtunnel globally, run with --localtunnel-bin lt."
        )

    raise RuntimeError(
        f"{localtunnel_bin!r} was not found. Install Localtunnel globally with "
        "npm install -g localtunnel, or use the default npx launcher after "
        "installing Node.js/npm."
    )


def _wait_for_tunnel_url(
    output_queue: queue.Queue[tuple[str, str]],
    timeout: float = 60.0,
) -> str:
    """reads Localtunnel output until the public HTTPS URL appears."""
    deadline = time.time() + timeout
    buffered: list[tuple[str, str]] = []
    while time.time() < deadline:
        try:
            name, line = output_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        buffered.append((name, line))
        print(f"[{name}] {line}", flush=True)
        match = LOCALTUNNEL_URL_PATTERN.search(line)
        if match:
            return match.group(0).rstrip("/")

    for name, line in buffered:
        print(f"[{name}] {line}", flush=True)
    raise RuntimeError("Localtunnel did not report a public URL.")


def _print_cloudmailin_target(tunnel_url: str, endpoint: str) -> None:
    """prints the exact URL to paste into CloudMailin."""
    username = os.getenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "").strip()
    password = os.getenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "").strip()
    clean_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"

    print("\nCloudMailin target URL:", flush=True)
    if username and password:
        secured_url = tunnel_url.replace(
            "https://",
            f"https://{quote(username)}:{quote(password)}@",
            1,
        )
        print(f"{secured_url}{clean_endpoint}", flush=True)
    else:
        print(f"{tunnel_url}{clean_endpoint}", flush=True)
        print(
            "Set SWIFT_CLOUDMAILIN_BASIC_USERNAME and "
            "SWIFT_CLOUDMAILIN_BASIC_PASSWORD before receiving real webhooks.",
            flush=True,
        )
    print("\nPress Ctrl+C to stop FastAPI and Localtunnel.\n", flush=True)


def _forward_output(output_queue: queue.Queue[tuple[str, str]]) -> None:
    """keeps both child processes visible after startup completes."""
    while True:
        name, line = output_queue.get()
        print(f"[{name}] {line}", flush=True)


def _terminate(name: str, process: subprocess.Popen[str] | None) -> None:
    """stops a child process without leaving tunnel or server processes behind."""
    if process is None or process.poll() is not None:
        return
    if sys.platform == "win32":
        process.terminate()
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f"Force-stopping {name}.", flush=True)
        process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
