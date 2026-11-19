"""整个程序唯一读取 .env 和环境变量的地方。

别的模块一律不许调 load_dotenv、不许读 os.environ，要配置就拿 Settings。tests/test_architecture.py
扫描全仓库，发现就变红。
"""

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from crossfire.domain import Question
from crossfire.domain.evals import EvalCase

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_MODEL = "claude-sonnet-4-6"


class Pairer(StrEnum):
    """比对器用哪种实现。以后加本地 NLI 模型：这里加一个值，composition.build_pairer 里加一个分支。"""

    CLAUDE = "claude"


class Key(StrEnum):
    ANTHROPIC = "ANTHROPIC_API_KEY"
    STEEL = "STEEL_API_KEY"


KEY_PURPOSES = {
    Key.ANTHROPIC: "Claude 调用（提取主张、两两比对、最终判断）",
    Key.STEEL: "Steel 云端浏览器实时抓取网页（live 模式和预抓取）",
}


class SettingsError(ValueError):
    """配置缺失或不合法。消息直接给人看，写明缺什么、去哪里设置。"""


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    steel_api_key: str | None
    model_extract: str
    model_pair: str
    model_judge: str
    pairer: Pairer
    runs_dir: Path
    cache_dir: Path
    questions_file: Path
    evals_dir: Path
    eval_runs_dir: Path
    env_file: Path

    @classmethod
    def from_env(cls, env_file: Path = ENV_FILE, *, require: Iterable[Key] = ()) -> "Settings":
        """读 env_file 和环境变量，环境变量优先（与 load_dotenv 不覆盖已有变量的规则一致）。

        require 列出这次要做的事必须有的 key。缺了就在这里报错，而不是等第一次调 API 时收到 401。
        只看历史结果什么 key 都不要；cached 运行不要 Steel；预抓取不要 Anthropic。
        """
        values: dict[str, str | None] = {**dotenv_values(env_file), **os.environ}
        settings = cls.from_mapping(values, env_file=env_file)
        settings.require(*require)
        return settings

    @classmethod
    def from_mapping(cls, values: Mapping[str, str | None], *, env_file: Path = ENV_FILE) -> "Settings":
        def get(name: str, default: str) -> str:
            return (values.get(name) or "").strip() or default

        pairer_name = get("PAIRER", Pairer.CLAUDE.value)
        try:
            pairer = Pairer(pairer_name)
        except ValueError:
            allowed = "、".join(p.value for p in Pairer)
            raise SettingsError(f"PAIRER={pairer_name} 不认识，可选值：{allowed}。在 {env_file} 里改。") from None

        return cls(
            anthropic_api_key=_key(values.get(Key.ANTHROPIC.value)),
            steel_api_key=_key(values.get(Key.STEEL.value)),
            model_extract=get("MODEL_EXTRACT", DEFAULT_MODEL),
            model_pair=get("MODEL_PAIR", DEFAULT_MODEL),
            model_judge=get("MODEL_JUDGE", DEFAULT_MODEL),
            pairer=pairer,
            runs_dir=_path(get("CROSSFIRE_RUNS_DIR", "out/runs")),
            cache_dir=_path(get("CROSSFIRE_CACHE_DIR", "out/cache")),
            questions_file=_path(get("CROSSFIRE_QUESTIONS_FILE", "questions/demo.yaml")),
            evals_dir=_path(get("CROSSFIRE_EVALS_DIR", "evals")),
            eval_runs_dir=_path(get("CROSSFIRE_EVAL_RUNS_DIR", "out/eval-runs")),
            env_file=env_file,
        )

    def missing(self, *keys: Key) -> list[Key]:
        present = {Key.ANTHROPIC: self.anthropic_api_key, Key.STEEL: self.steel_api_key}
        return [key for key in keys if not present[key]]

    def require(self, *keys: Key) -> None:
        missing = self.missing(*keys)
        if missing:
            lines = [f"缺少 {key.value}（用于{KEY_PURPOSES[key]}）。" for key in missing]
            lines.append(f"在 {self.env_file} 里加上 " + "、".join(f"{key.value}=你的密钥" for key in missing) + "，")
            lines.append(f"格式参考 {ROOT / '.env.example'}。也可以直接设成同名环境变量。")
            raise SettingsError("\n".join(lines))


def _key(value: str | None) -> str | None:
    # .env.example 里的占位值 your_xxx_here 原样拷过来时算没配。
    value = (value or "").strip()
    return None if not value or value.startswith("your_") else value


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_questions(settings: Settings) -> list[Question]:
    """读问题清单。文件不存在时返回空列表：web 端照样能看历史结果。"""
    if not settings.questions_file.is_file():
        return []
    data: Any = yaml.safe_load(settings.questions_file.read_text(encoding="utf-8")) or []
    return [Question.from_dict(item) for item in data]


def load_eval_cases(settings: Settings) -> list[EvalCase]:
    """读 evals/cases/*.yaml，每个文件一道题，按 id 排序。文件名必须等于 id，快照目录也按 id 找。"""
    cases: list[EvalCase] = []
    for path in sorted((settings.evals_dir / "cases").glob("*.yaml")):
        case = EvalCase.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
        if case.id != path.stem:
            raise SettingsError(f"{path} 里的 id 是 {case.id}，必须和文件名 {path.stem} 一致")
        cases.append(case)
    return sorted(cases, key=lambda case: case.id)


def eval_snapshot_dir(settings: Settings, case: EvalCase) -> Path:
    return settings.evals_dir / "snapshots" / case.id
