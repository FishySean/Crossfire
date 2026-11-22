import itertools
import json
import os
from pathlib import Path
from typing import IO

from crossfire.adapters.steel.fetchers import cache_path
from crossfire.application.records import page_record, run_record
from crossfire.domain import Page, RunResult


class MissingFetchTimeError(ValueError):
    """页面没有 fetched_at。存进缓存之后就没人知道它是哪天的快照了。"""


class CachePageStore:
    """把抓到的页面写进 cache_dir，CachedPageFetcher 按同样的文件名读回来。抓取失败的页面也照写。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def save(self, page: Page) -> str:
        if page.fetched_at is None:
            raise MissingFetchTimeError(f"{page.url} 没有 fetched_at，不存：cached 模式要靠它确定快照日期")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_path(self.cache_dir, page.url)
        staging = path.with_suffix(".json.tmp")
        staging.write_text(json.dumps(page_record(page), ensure_ascii=False), encoding="utf-8")
        os.replace(staging, path)
        return str(path)


class JsonRunRepository:
    """每次运行写成 runs_dir 下的一个 JSON 文件。

    文件名是 {question_id}_{开始时刻，精确到秒}.json。同一题同一秒再存一次时，依次改用
    _2、_3 后缀，不会覆盖前一个。没有改用更细的时间精度：精度再细也只是让撞车变少，不能保证不撞；
    而且秒级文件名人能直接读，现有的 22 个结果文件也都是这个格式。
    """

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = Path(runs_dir)

    def save(self, result: RunResult) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(run_record(result), ensure_ascii=False, indent=2)
        stem = f"{result.question.id}_{result.started_at.strftime('%Y%m%dT%H%M%SZ')}"
        path, staging = self._reserve(stem)
        with staging:
            staging.write(body)
        # rename 是原子的：web 端读历史结果时，要么看不到这个文件，要么看到完整的 JSON。
        os.replace(staging.name, path)
        return str(path)

    def _reserve(self, stem: str) -> tuple[Path, IO[str]]:
        """占住一个没人用的文件名，返回最终路径和已打开的临时文件。

        用 "x" 模式独占创建临时文件来占名字，两个进程同时存也只有一个能拿到。拿到之后再确认
        最终文件不存在：别人的临时文件只会在 os.replace 那一刻消失、同时最终文件出现，
        所以只要临时文件名能拿到，这里看到的最终文件状态就是准的。
        """
        for n in itertools.count(1):
            path = self.runs_dir / (f"{stem}.json" if n == 1 else f"{stem}_{n}.json")
            staging = path.with_suffix(".json.tmp")
            try:
                handle = open(staging, "x", encoding="utf-8")
            except FileExistsError:
                continue
            if not path.exists():
                return path, handle
            handle.close()
            staging.unlink()
        raise AssertionError("unreachable")


def annotate_run_ask_cost(run_file: str, *, actual_usd: float, estimate: dict) -> None:
    """在已写入的结果 JSON 上追加 ask 费用字段（实际花费 + 运行前估算）。"""
    path = Path(run_file)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["ask_cost"] = {"actual_usd": actual_usd, "estimate": estimate}
    staging = path.with_suffix(".json.tmp")
    staging.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(staging, path)
