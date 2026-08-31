#!/usr/bin/env python3
"""Vibe-Research 前后端守护进程（双 fork 脱离会话 + 崩溃自动重启）。

用法:
  python3 tools/serve_daemon.py --start   # 启动守护（立即返回，daemon 后台运行）
  python3 tools/serve_daemon.py --stop    # 停止守护及所有子进程
  python3 tools/serve_daemon.py --status  # 查看状态

守护进程双 fork + setsid 脱离调用方会话（WorkBuddy/终端清理杀不到），
子进程（vite / uvicorn）异常退出后 3 秒内自动拉起。
"""
import os
import sys
import time
import signal
import subprocess
from typing import Iterable

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE, "frontend")
BACKEND_DIR = os.path.join(BASE, "backend")

FRONTEND_CMD = [
    "/Users/zhangxu/.workbuddy/binaries/node/versions/22.22.2/bin/npm",
    "run", "dev", "--", "--host", "127.0.0.1", "--port", "5899",
]
BACKEND_CMD = [
    os.path.join(BACKEND_DIR, ".venv/bin/python"),
    "-m", "uvicorn", "app:app",
    "--host", "127.0.0.1", "--port", "8900",
]

PID_FILE = "/tmp/vibe-daemon.pid"
LOG_DIR = "/tmp"
LOG_DAEMON = os.path.join(LOG_DIR, "vibe-daemon.log")
LOG_FRONT = os.path.join(LOG_DIR, "vibe-frontend.log")
LOG_BACK = os.path.join(LOG_DIR, "vibe-backend.log")
FRONTEND_PORT = 5899
BACKEND_PORT = 8900

# 干净环境：显式清空系统/launchd 继承的随机代理变量（代理进程常没启动 → Connection refused），
# 并固定 VR_* 开关让后端 requests 默认直连（见 backend/astock.py monkey patch）。
_AGENT_ENV = {
    "VR_HTTP_PROXY": "0",    # 后端 requests 默认 trust_env=False（不读代理）
    "VR_CHAT_NO_PROXY": "1", # LLM 调用默认直连
    "NO_PROXY": "localhost,127.0.0.1,::1",
    "no_proxy": "localhost,127.0.0.1,::1",
}
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    _AGENT_ENV[_k] = ""


def daemonize():
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    os.umask(0o022)
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)


def write_pid(pid):
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def read_pid():
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def is_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn(cmd, cwd, logfile):
    log = open(logfile, "a")
    env = dict(os.environ)
    env.update(_AGENT_ENV)  # 固定/清空代理相关变量，避免继承过期代理
    return subprocess.Popen(
        cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, close_fds=True, env=env,
    )


def _run_capture(cmd: list[str]) -> list[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _kill_pid(pid: int, sig: int = signal.SIGTERM) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        return


def _kill_group(pid: int, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(pid, sig)
    except OSError:
        _kill_pid(pid, sig)


def _listening_pids(port: int) -> list[int]:
    pids: list[int] = []
    for line in _run_capture(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]):
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _wait_until_ports_clear(ports: Iterable[int], timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    port_list = list(ports)
    while time.time() < deadline:
        if all(not _listening_pids(port) for port in port_list):
            return True
        time.sleep(0.25)
    return all(not _listening_pids(port) for port in port_list)


def _managed_process_lines() -> list[str]:
    return _run_capture(["ps", "-axo", "pid=,command="])


def _matches_managed(command: str) -> bool:
    return (
        "Vibe-Research/frontend/node_modules/.bin/vite" in command
        or "uvicorn app:app --host 127.0.0.1 --port 8900" in command
        or "tools/serve_daemon.py --start" in command
    )


def cleanup_orphans(exclude_pids: Iterable[int] = ()) -> None:
    keep = {int(pid) for pid in exclude_pids}
    targets: set[int] = set()
    for line in _managed_process_lines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid in keep:
            continue
        if _matches_managed(parts[1]):
            targets.add(pid)
    targets.update(pid for pid in _listening_pids(FRONTEND_PORT) if pid not in keep)
    targets.update(pid for pid in _listening_pids(BACKEND_PORT) if pid not in keep)
    for pid in sorted(targets):
        _kill_group(pid, signal.SIGTERM)
    if targets:
        time.sleep(1)
        for pid in sorted(targets):
            _kill_group(pid, signal.SIGKILL)
        _wait_until_ports_clear((FRONTEND_PORT, BACKEND_PORT))


def ensure_service_ports_available(exclude_pids: Iterable[int] = ()) -> None:
    cleanup_orphans(exclude_pids=exclude_pids)
    stubborn = {
        pid
        for port in (FRONTEND_PORT, BACKEND_PORT)
        for pid in _listening_pids(port)
    }
    for pid in sorted(stubborn):
        _kill_group(pid, signal.SIGTERM)
    if stubborn:
        time.sleep(1)
        for pid in sorted(stubborn):
            _kill_group(pid, signal.SIGKILL)
        _wait_until_ports_clear((FRONTEND_PORT, BACKEND_PORT))


def run_forever():
    write_pid(os.getpid())
    ensure_service_ports_available(exclude_pids=[os.getpid()])
    with open(LOG_DAEMON, "a") as dl:
        dl.write(f"[daemon] start pid={os.getpid()} at {time.strftime('%F %T')}\n")
    procs = {
        "frontend": spawn(FRONTEND_CMD, FRONTEND_DIR, LOG_FRONT),
        "backend": spawn(BACKEND_CMD, BACKEND_DIR, LOG_BACK),
    }
    while True:
        for name, proc in list(procs.items()):
            code = proc.poll()
            if code is not None:
                with open(LOG_DAEMON, "a") as dl:
                    dl.write(f"[daemon] {name} exited code={code}, restarting at {time.strftime('%F %T')}\n")
                if name == "frontend":
                    ensure_service_ports_available(exclude_pids=[os.getpid()])
                else:
                    for pid in _listening_pids(BACKEND_PORT):
                        _kill_group(pid, signal.SIGTERM)
                    if _listening_pids(BACKEND_PORT):
                        time.sleep(1)
                        for pid in _listening_pids(BACKEND_PORT):
                            _kill_group(pid, signal.SIGKILL)
                        _wait_until_ports_clear((BACKEND_PORT,))
                procs[name] = spawn(
                    FRONTEND_CMD if name == "frontend" else BACKEND_CMD,
                    FRONTEND_DIR if name == "frontend" else BACKEND_DIR,
                    LOG_FRONT if name == "frontend" else LOG_BACK,
                )
        time.sleep(3)


def stop():
    pid = read_pid()
    if pid and is_alive(pid):
        # 杀掉子进程组：遍历 /proc 不可用，通过 launchctl 风格的子进程查找用 pgrep
        try:
            out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
            for c in out:
                try:
                    os.kill(int(c), signal.SIGTERM)
                except OSError:
                    pass
        except Exception:
            pass
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        print(f"daemon {pid} stopped")
    else:
        print("daemon not running")
    cleanup_orphans()
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def status():
    pid = read_pid()
    print(f"daemon pid: {pid} (alive={is_alive(pid)})")
    import urllib.request
    import urllib.error
    for port, name in ((FRONTEND_PORT, "frontend"), (BACKEND_PORT, "backend")):
        ok = False
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            ok = True
        except urllib.error.HTTPError:
            ok = True  # 有响应即服务在监听（404 也算）
        except Exception:
            ok = False
        print(f"  {name} :{port} {'OK' if ok else 'DOWN'}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        stop()
    elif len(sys.argv) > 1 and sys.argv[1] == "--status":
        status()
    else:
        old = read_pid()
        if old and is_alive(old):
            print(f"daemon already running (pid={old})")
        else:
            daemonize()
            run_forever()
            print("daemon started")
