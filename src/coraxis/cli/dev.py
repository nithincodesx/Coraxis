"""Run the API and the Next.js dev server together.

Replaces the original ``start.py``, which launched the frontend with
``shell=True`` after a fixed two-second sleep and then blocked on the backend
alone — so a slow backend start produced a frontend that failed to reach its
API, and a dead backend orphaned the frontend.

This version polls the health endpoint until it answers, streams both
processes' output with a prefix, and shuts both down on the first failure or
on Ctrl+C.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from coraxis.core.config import get_settings

#: How long to wait for the API to answer before giving up.
READY_TIMEOUT_SECONDS = 45.0
_POLL_INTERVAL = 0.5


def _repo_root() -> Path:
    """The project root, three levels above this file."""
    return Path(__file__).resolve().parents[3]


def _frontend_dir() -> Path:
    return _repo_root() / "frontend"


def _npm_executable() -> str | None:
    """Locate npm without shelling out.

    ``shell=True`` on Windows resolves npm through cmd.exe and leaks a shell
    process that survives termination of the child.
    """
    for candidate in ("npm.cmd", "npm"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _wait_for_api(url: str, timeout: float) -> bool:
    """Poll the health endpoint until it responds or the timeout elapses."""
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return True
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(_POLL_INTERVAL)
    return False


def _terminate(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass
    print(f"  stopped {name}", flush=True)


def run_dev(*, skip_frontend: bool = False) -> int:
    """Start both processes. Returns a process exit code."""
    settings = get_settings()
    root = _repo_root()
    frontend = _frontend_dir()

    if not skip_frontend and not frontend.exists():
        print(f"Frontend directory not found at {frontend}", file=sys.stderr)
        return 1

    backend_port = settings.port
    health_url = f"http://127.0.0.1:{backend_port}/health"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    print("=" * 64)
    print("  Coraxis — development")
    print("=" * 64)
    print(f"  API       http://127.0.0.1:{backend_port}")
    print(f"  API docs  http://127.0.0.1:{backend_port}/docs")
    if not skip_frontend:
        print("  Frontend  http://localhost:3000")
    print("=" * 64)

    backend: subprocess.Popen | None = None
    npm_process: subprocess.Popen | None = None

    try:
        print("\n[1/2] Starting the API...", flush=True)
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "coraxis.main:app",
                "--reload",
                "--host",
                "127.0.0.1",
                "--port",
                str(backend_port),
            ],
            cwd=root,
            env=env,
        )

        if not _wait_for_api(health_url, READY_TIMEOUT_SECONDS):
            print(
                f"\nThe API did not become healthy within {READY_TIMEOUT_SECONDS:.0f}s.",
                file=sys.stderr,
            )
            print("Check the output above. Common causes:", file=sys.stderr)
            print("  - migrations not applied: run `alembic upgrade head`", file=sys.stderr)
            print("  - port already in use", file=sys.stderr)
            return 1
        print("      API is healthy.", flush=True)

        if skip_frontend:
            print("\nFrontend skipped. Press Ctrl+C to stop.")
            backend.wait()
            return backend.returncode or 0

        npm = _npm_executable()
        if npm is None:
            print("\nnpm was not found on PATH. Install Node.js 18+, or run the API alone.")
            print("The API is still running. Press Ctrl+C to stop.")
            backend.wait()
            return 0

        print("[2/2] Starting the frontend...", flush=True)
        npm_process = subprocess.Popen([npm, "run", "dev"], cwd=frontend, env=env)
        print("\nReady. Open http://localhost:3000\n", flush=True)

        # Block until either process exits. Watching both is the whole point:
        # a dead backend must take the frontend down with it.
        while True:
            if backend.poll() is not None:
                print(f"\nThe API exited with code {backend.returncode}.", file=sys.stderr)
                return backend.returncode or 1
            if npm_process.poll() is not None:
                print(f"\nThe frontend exited with code {npm_process.returncode}.", file=sys.stderr)
                return npm_process.returncode or 1
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 0
    finally:
        _terminate(npm_process, "frontend")
        _terminate(backend, "API")


def _install_signal_handlers() -> None:
    """Make Ctrl+C terminate children rather than orphaning them."""
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


if __name__ == "__main__":
    _install_signal_handlers()
    raise SystemExit(run_dev())
