"""ChinaTrip dev server manager (Windows-zombie-proof hot reload).

Why: uvicorn --reload on this Windows box leaves spawn-worker zombies that
keep serving stale code (WatchFiles logs "Reloading..." but the old worker
keeps the inherited listen socket, and the old/new double-bind makes
responses flip between code versions). Fix: run uvicorn as a SINGLE process
(no --reload) under this managed watcher; every restart is a forced
taskkill /T /F of the whole tree plus a bind-check before respawn.

Usage (run with the repo venv python, or just use dev_server.cmd):
  python scripts/dev_watch.py watch     # managed hot reload (default)
  python scripts/dev_watch.py start     # detached single-process (no reload)
  python scripts/dev_watch.py restart   # stop + start (detached)
  python scripts/dev_watch.py stop      # kill everything on the port
  python scripts/dev_watch.py status    # serving? who owns the port?
Optional: --port 8000 (default 8000)
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

PORT = 8000
HOST = "0.0.0.0"
REPO = Path(__file__).resolve().parents[1]
CODES = REPO / "CHINATRIP CODES"
VENV_PY = CODES / ".venv" / "Scripts" / "python.exe"
LOGS = REPO / "devlogs"
WATCH_DIR = CODES / "app"


def ps(command: str) -> str:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def port_owner_pids(port: int) -> list[int]:
    query = (
        "(Get-NetTCPConnection -LocalPort "
        + str(port)
        + " -State Listen -ErrorAction SilentlyContinue)"
        + ".OwningProcess | Select-Object -Unique"
    )
    out = ps(query)
    return [int(x) for x in out.split() if x.strip().isdigit()]


def uvicorn_pids(port: int) -> list[int]:
    """python processes that look like a uvicorn for this port + their
    spawn_main children (the zombie worker class)."""
    roots = ps(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        + "Where-Object { $_.CommandLine -match 'uvicorn' "
        + "-and $_.CommandLine -match '--port\\s+"
        + str(port)
        + "' } | "
        + "Select-Object -ExpandProperty ProcessID"
    )
    root_ids = [int(x) for x in roots.split() if x.strip().isdigit()]
    if not root_ids:
        return []
    id_list = ",".join(str(i) for i in root_ids)
    kids = ps(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        + "Where-Object { $_.CommandLine -match 'spawn_main' "
        + "-and ($_.ParentProcessId -in "
        + id_list
        + ") } | "
        + "Select-Object -ExpandProperty ProcessID"
    )
    return root_ids + [int(x) for x in kids.split() if x.strip().isdigit()]


def kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True
    )


def stop_all(port: int) -> None:
    roots = sorted(set(port_owner_pids(port)) | set(uvicorn_pids(port)))
    for pid in roots:
        print(f"[dev_watch] killing tree {pid}", flush=True)
        kill_tree(pid)
    if roots:
        time.sleep(1.0)


def port_free(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while True:
        sock = socket.socket()
        try:
            sock.bind((HOST, port))
            sock.close()
            return True
        except OSError:
            sock.close()
            if time.time() >= deadline:
                return False
            time.sleep(0.3)


def uvicorn_cmd() -> list[str]:
    return [
        str(VENV_PY),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]


def spawn_child() -> subprocess.Popen:
    return subprocess.Popen(uvicorn_cmd(), cwd=str(CODES))


def spawn_detached() -> None:
    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"uvicorn-{PORT}.log"
    # The detached child inherits the log handle; closing the parent's copy
    # after Popen does not affect it.
    with open(log_path, "ab") as log:
        log.write(
            (
                "\n===== start " + time.strftime("%Y-%m-%d %H:%M:%S") + " =====\n"
            ).encode()
        )
        log.flush()
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            uvicorn_cmd(),
            cwd=str(CODES),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    print(f"started detached pid={proc.pid} (log: {log_path})")


def status(port: int) -> None:
    import json
    import urllib.request

    owners = port_owner_pids(port)
    print(f"port {port} owners: {owners or 'none'}")
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/openapi.json", timeout=3
        ) as resp:
            data = json.load(resp)
        print(f"serving: {len(data.get('paths', {}))} routes")
    except Exception as exc:  # noqa: BLE001 - status probe reports anything
        print(f"serving: NO ({exc.__class__.__name__})")


def watch_mode(port: int) -> None:
    from watchfiles import DefaultFilter, watch

    stop_all(port)
    if not port_free(port):
        print(f"FATAL: port {port} still busy; refusing to start", flush=True)
        sys.exit(1)
    proc = spawn_child()
    print(
        f"[dev_watch] uvicorn pid={proc.pid} single-process (no --reload)",
        flush=True,
    )
    try:
        for changes in watch(
            str(WATCH_DIR),
            watch_filter=DefaultFilter(),
            debounce=400,
            rust_timeout=1500,
            yield_on_timeout=True,
        ):
            try:
                if proc.poll() is not None:
                    print(
                        f"[dev_watch] child exited rc={proc.returncode}; respawning",
                        flush=True,
                    )
                    stop_all(port)
                    proc = spawn_child()
                    print(f"[dev_watch] uvicorn pid={proc.pid}", flush=True)
                    continue
                if not changes:
                    continue
                # watchfiles >=1.0 yields (Change, path) tuples.
                py_changed = [str(p) for c, p in changes if Path(p).suffix == ".py"]
                if not py_changed:
                    continue
                print(f"[dev_watch] changed: {'; '.join(py_changed)}", flush=True)
                kill_tree(proc.pid)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                if not port_free(port):
                    print("[dev_watch] port busy after kill; sweeping", flush=True)
                    stop_all(port)
                if not port_free(port):
                    print(
                        "[dev_watch] FATAL: port still busy; not restarting",
                        flush=True,
                    )
                    sys.exit(1)
                time.sleep(0.2)
                proc = spawn_child()
                print(f"[dev_watch] uvicorn pid={proc.pid}", flush=True)
            except Exception as exc:  # noqa: BLE001 - watcher must survive handler bugs
                print(
                    f"[dev_watch] handler error (watcher stays up): {exc!r}",
                    flush=True,
                )
                continue
    except KeyboardInterrupt:
        pass
    finally:
        kill_tree(proc.pid)
        print("[dev_watch] stopped", flush=True)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "watch"
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    if action == "watch":
        watch_mode(port)
    elif action == "stop":
        stop_all(port)
        print("stopped")
    elif action in ("start", "restart"):
        stop_all(port)
        if not port_free(port):
            print(f"FATAL: port {port} still busy; not starting")
            sys.exit(1)
        spawn_detached()
    elif action == "status":
        status(port)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
