#!/usr/bin/env python3
"""Steel.dev 可用性探测：基础抓取 / 内容格式对比 / 并发 session 上限。"""

import argparse
import traceback

from steel import Steel

from crossfire.composition import build_fetcher
from crossfire.config import ROOT, Key, Settings
from crossfire.domain import Mode, Question

DEFAULT_URL = "https://news.ycombinator.com"


def test_1(settings: Settings, url: str) -> None:
    """走正式的抓取实现（含 429 退避），和 verify --mode live 用的是同一个。"""
    print("=== 测试 1：基础抓取 ===")
    print(f"URL: {url}")
    probe = Question.from_dict({"id": "probe", "question": "probe", "sources": [{"url": url, "tier": "primary"}]})
    [page] = build_fetcher(settings, probe, Mode.LIVE).fetch_all([url])
    print(f"ok: {page.ok}")
    print(f"status_code: {page.status_code}")
    if not page.ok:
        print(f"error:\n{page.error}")
        return
    print(f"title: {page.title}")
    md = page.markdown or ""
    print(f"markdown preview ({min(500, len(md))} / {len(md)} chars):")
    print(md[:500])
    print(f"links: {len(page.links)}")


def test_2(settings: Settings, url: str) -> None:
    print("=== 测试 2：内容质量对比 ===")
    print(f"URL: {url}")
    client = Steel(steel_api_key=settings.steel_api_key)
    result = client.scrape(
        url=url,
        format=["markdown", "cleaned_html", "readability"],
    )

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    readability = result.content.readability or {}
    # Steel 把 readability 的 HTML 串按字符下标序列化成了对象，需按数字键顺序拼回来。
    formats = {
        "markdown": result.content.markdown or "",
        "cleaned_html": result.content.cleaned_html or "",
        "readability": "".join(str(readability[k]) for k in sorted(readability, key=int)),
    }

    for name, text in formats.items():
        path = out_dir / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        print(f"{name}: {len(text)} chars -> {path}")


def test_3(settings: Settings) -> None:
    print("=== 测试 3：并发 session 上限探测 ===")
    print("依次创建 session 且暂不释放，最多试到 12 个。")
    client = Steel(steel_api_key=settings.steel_api_key)
    sessions = []
    try:
        for i in range(1, 13):
            try:
                session = client.sessions.create()
                sessions.append(session)
                print(f"已开 session 数量: {len(sessions)} (id={session.id})")
            except Exception as e:
                print("--- 创建失败（完整错误）---")
                traceback.print_exc()
                status = getattr(e, "status_code", None)
                print(f"HTTP status_code: {status}")
                response = getattr(e, "response", None)
                if response is not None:
                    print(f"response.status_code: {response.status_code}")
                    print(f"response.text:\n{response.text}")
                print(f"repr: {e!r}")
                break
        else:
            print("试满 12 个均成功，未触达上限。")
    finally:
        print(f"--- finally：释放全部 {len(sessions)} 个 session ---")
        for session in sessions:
            try:
                client.sessions.release(session.id)
                print(f"released {session.id}")
            except Exception:
                print(f"release 失败: {session.id}")
                traceback.print_exc()


def main() -> None:
    parser = argparse.ArgumentParser(description="Crossfire Steel probe")
    parser.add_argument("--test", type=int, default=1, choices=[1, 2, 3], help="跑哪个测试（默认 1）")
    parser.add_argument("--url", default=DEFAULT_URL, help="测试用 URL")
    args = parser.parse_args()
    settings = Settings.from_env(require=[Key.STEEL])

    try:
        if args.test == 1:
            test_1(settings, args.url)
        elif args.test == 2:
            test_2(settings, args.url)
        else:
            test_3(settings)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
