"""一键启动本地查证界面：自检 → 选端口 → 起服务 → 就绪后开浏览器。

进阶用法（自己控制参数）仍然是 `uv run uvicorn web.server:app --port 8765`，
这个脚本只是把它包成对非开发者友好的入口，不改任何路由逻辑。
"""

import argparse
import importlib.util
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKER_FILES = ("web/server.py", "crossfire/pipeline.py", "pyproject.toml")
CACHE_DIR = ROOT / "out" / "cache"
PORT_FIRST = 8765
PORT_LAST = 8775
READY_TIMEOUT_SECONDS = 15.0
READY_POLL_SECONDS = 0.2
HOST = "127.0.0.1"

# 模块名 -> pip 包名，报缺失时按包名提示，import 名和包名不一致的很容易看懵。
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "anthropic": "anthropic",
    "steel": "steel-sdk",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
}

REQUIRED_KEYS = {
    "ANTHROPIC_API_KEY": "Claude 调用（提取主张、两两比对、最终判断）",
    "STEEL_API_KEY": "Steel 云端浏览器抓取网页",
}

OK = "  \u2713 "
BAD = "  \u2717 "
INFO = "    "


def ensure_project_root():
    """不在项目根目录也能跑：自动切过去，而不是让 import 炸成 ModuleNotFoundError。"""
    missing = [name for name in MARKER_FILES if not (ROOT / name).is_file()]
    if missing:
        print(BAD + f"项目文件不完整，缺少：{', '.join(missing)}")
        print(INFO + f"请确认 {ROOT} 是完整的 Crossfire 仓库（git clone 后不要只拷贝单个文件）。")
        return False

    here = Path.cwd().resolve()
    if here == ROOT:
        print(OK + f"工作目录：{ROOT}")
    else:
        os.chdir(ROOT)
        print(OK + f"工作目录已从 {here} 切换到 {ROOT}")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return True


def read_env_file():
    """只读 .env 的键，不覆盖已有环境变量，也不依赖 python-dotenv（它可能还没装）。"""
    values = {}
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return values
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def check_api_keys():
    """缺 key 不阻止启动：看历史结果和 ?fake= 彩排都不需要 key，只有真跑一次才需要。"""
    from_file = read_env_file()
    missing = []
    for key, purpose in REQUIRED_KEYS.items():
        value = os.environ.get(key) or from_file.get(key, "")
        if value and not value.startswith("your_"):
            print(OK + f"{key} 已配置 —— 用于{purpose}")
        else:
            missing.append(key)
            print(BAD + f"{key} 缺失 —— 用于{purpose}")
    if missing:
        print(INFO + f"在 {ROOT / '.env'} 里加上：" + "、".join(f"{k}=你的密钥" for k in missing))
        print(INFO + "没有也能启动：查看历史结果、?fake= 假事件彩排都不需要密钥，只有真跑一次查证需要。")
    return missing


def check_dependencies():
    missing = sorted({pkg for mod, pkg in REQUIRED_MODULES.items() if importlib.util.find_spec(mod) is None})
    if missing:
        print(BAD + f"依赖未安装：{', '.join(missing)}")
        print(INFO + "在项目目录里运行 `uv sync`（或 `pip install -e .`）后重试。")
        return False
    print(OK + "依赖已安装")
    return True


def check_cache():
    cached = [d.name for d in CACHE_DIR.glob("*") if d.is_dir() and any(d.glob("*.json"))] if CACHE_DIR.is_dir() else []
    if cached:
        print(OK + f"抓取缓存：{len(cached)} 个问题有缓存（{', '.join(sorted(cached))}）")
    else:
        print(BAD + f"{CACHE_DIR} 下没有抓取缓存")
        print(INFO + "cached 模式会退回真实抓取，变慢且需要 STEEL_API_KEY。")
        print(INFO + "先跑 `uv run python scripts/prefetch.py --all` 把来源抓进缓存，演示才稳。")
    return cached


def pick_port():
    for port in range(PORT_FIRST, PORT_LAST + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # 跟 uvicorn 一样设 SO_REUSEADDR，否则刚停掉的服务留下的 TIME_WAIT
            # 会让这里误判端口被占用，Ctrl+C 之后一分钟内都换不回原端口。
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
        return port
    return None


def wait_until_ready(port, server):
    """轮询到服务真的应答为止，起了就开浏览器会先显示一次“无法连接”。"""
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    url = f"http://{HOST}:{port}/api/runs"
    while time.monotonic() < deadline:
        if not server.started and getattr(server, "should_exit", False):
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(READY_POLL_SECONDS)
    return False


def main():
    parser = argparse.ArgumentParser(description="启动 Crossfire 本地查证界面")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    print("Crossfire 启动自检")
    if not ensure_project_root():
        return 1
    deps_ok = check_dependencies()
    check_api_keys()
    if not deps_ok:
        print("\n缺少依赖，无法启动。装好依赖后再运行 python app.py。")
        return 1
    check_cache()

    port = pick_port()
    if port is None:
        print(BAD + f"{PORT_FIRST}-{PORT_LAST} 全部被占用")
        print(INFO + f"用 `lsof -i :{PORT_FIRST}` 看是谁占着，关掉它再试。")
        return 1
    if port != PORT_FIRST:
        print(OK + f"端口 {port}（{PORT_FIRST} 起的端口被占用，自动顺延）")
    else:
        print(OK + f"端口 {port}")

    import uvicorn

    from web.server import app

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    url = f"http://{HOST}:{port}"
    # Ctrl+C 在等待就绪期间也要走同一条收尾路径，否则会甩一段原始堆栈出来。
    try:
        if not wait_until_ready(port, server):
            print(f"\n{READY_TIMEOUT_SECONDS:.0f} 秒内服务没有应答，已放弃等待。")
            print(f"手动确认：`uv run uvicorn web.server:app --port {port}`，看它报什么错。")
            return 1

        print(f"\n界面已就绪：{url}")
        print("  历史结果、实时运行都在这个页面上")
        print("  没有密钥时可以用 " + f"{url}/?fake=dense 彩排整条流程")
        print("  停止：按 Ctrl+C")
        if not args.no_browser:
            webbrowser.open(url)

        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        print("已停止，端口已释放。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # 服务还没起来时按 Ctrl+C（自检、加载依赖阶段），也不该甩堆栈。
        print("\n已取消。")
        sys.exit(130)
