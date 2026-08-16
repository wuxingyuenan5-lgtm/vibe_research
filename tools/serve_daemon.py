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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE, "frontend")
BACKEND_DIR = os.path.join(BASE, "backend")

FRONTEND_CMD = [
    "/Users/zhangxu/.workbuddy/binaries/node/versions/22.22.2/bin/npm",
    "run", "dev",
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
    return subprocess.Popen(
        cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, close_fds=True,
    )


def run_forever():
    write_pid(os.getpid())
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
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def status():
    pid = read_pid()
    print(f"daemon pid: {pid} (alive={is_alive(pid)})")
    import urllib.request
    import urllib.error
    for port, name in ((5899, "frontend"), (8900, "backend")):
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
