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
MARKER_FILES = ("web/server.py", "crossfire/composition.py", "pyproject.toml")
PORT_FIRST = 8765
PORT_LAST = 8775
READY_TIMEOUT_SECONDS = 15.0
READY_POLL_SECONDS = 0.2
# 默认只本机可访问。自提问会花 Anthropic / Steel 额度；绑到 0.0.0.0 等于把钱包敞口给局域网。
HOST = "127.0.0.1"


def warn_if_public_bind(host: str) -> None:
    """绑到所有网卡时大声警告。mutation：若默认 HOST 被改成 0.0.0.0，测试会红。"""
    if host not in {"0.0.0.0", "::", "[::]"}:
        return
    print()
    print("!" * 64)
    print("警告：服务监听了所有网卡（host=" + host + "）。")
    print("任何能访问到这台机器的人，都能用你的 Anthropic / Steel API 额度。")
    print("除非你非常清楚自己在做什么，请改回 127.0.0.1。")
    print("!" * 64)
    print()

# 模块名 -> pip 包名，报缺失时按包名提示，import 名和包名不一致的很容易看懵。
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "anthropic": "anthropic",
    "steel": "steel-sdk",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
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


def load_settings(env_file=None):
    """读配置并检查当前抓取器真正需要的 key。缺 key 不阻止启动（看历史 / ?fake= 彩排仍可用）。

    配置写错（比如 PAIRER 不认识）就返回 None，不启动。
    """
    from crossfire.config import ENV_FILE, KEY_PURPOSES, Fetcher, Key, Settings, SettingsError

    env_file = env_file or ENV_FILE
    try:
        settings = Settings.from_env(env_file)
    except SettingsError as error:
        print(BAD + _indent(str(error)))
        return None
    needed = [Key.ANTHROPIC]
    if settings.fetcher is Fetcher.STEEL:
        needed.append(Key.STEEL)
    for key in needed:
        if key not in settings.missing(key):
            print(OK + f"{key.value} 已配置 —— 用于{KEY_PURPOSES[key]}")
    try:
        Settings.from_env(env_file, require=needed)
    except SettingsError as error:
        print(BAD + _indent(str(error)))
        print(INFO + "没有也能启动：查看历史结果、?fake= 假事件彩排都不需要密钥。")
        if settings.fetcher is Fetcher.HTTP:
            print(INFO + "当前 FETCHER=http：live 提问只要 ANTHROPIC_API_KEY，不需要 STEEL_API_KEY。")
        else:
            print(INFO + "当前 FETCHER=steel：live / prefetch 还需要 STEEL_API_KEY。")
    return settings


def _indent(text):
    return text.replace("\n", "\n" + INFO)


def check_dependencies():
    missing = sorted({pkg for mod, pkg in REQUIRED_MODULES.items() if importlib.util.find_spec(mod) is None})
    if missing:
        print(BAD + f"依赖未安装：{', '.join(missing)}")
        print(INFO + "在项目目录里运行 `uv sync`（或 `pip install -e .`）后重试。")
        return False
    print(OK + "依赖已安装")
    return True


def check_cache(cache_dir):
    cached = [d.name for d in cache_dir.glob("*") if d.is_dir() and any(d.glob("*.json"))] if cache_dir.is_dir() else []
    if cached:
        print(OK + f"抓取缓存：{len(cached)} 个问题有缓存（{', '.join(sorted(cached))}）")
    else:
        print(BAD + f"{cache_dir} 下没有抓取缓存")
        print(INFO + "cached 模式会读这里；Ask / live 不依赖已有缓存。")
        print(INFO + "若要离线演示预置题：uv run crossfire prefetch --all（FETCHER=steel 时才要 STEEL_API_KEY）。")
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
    if not check_dependencies():
        print("\n缺少依赖，无法启动。装好依赖后再运行 python app.py。")
        return 1
    settings = load_settings()
    if settings is None:
        print("\n配置有误，无法启动。按上面的提示改好 .env 后再运行 python app.py。")
        return 1
    check_cache(settings.cache_dir)

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

    from web.server import create_app

    warn_if_public_bind(HOST)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=HOST, port=port, log_level="warning"))
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
