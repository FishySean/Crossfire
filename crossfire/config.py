"""整个程序唯一读取 .env 和环境变量的地方。

别的模块一律不许调 load_dotenv、不许读 os.environ，要配置就拿 Settings。tests/test_architecture.py
扫描全仓库，发现就变红。
"""

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from crossfire.domain import Question
from crossfire.domain.evals import ConsistencyInput, EvalCase, JudgeInput
from crossfire.domain.pricing import ModelPrice

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_HAIKU = "claude-haiku-4-5"

# 单价查自 https://docs.anthropic.com/en/docs/about-claude/pricing ，2026-11-20。
# 只列本仓库默认会用到的模型。换模型时在这里加一行；查不到官方价就不要凭记忆填。
MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-4-6": ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
}
# web_search 另计：$10 / 1000 次搜索（失败的不收费）。同页同日。
WEB_SEARCH_PER_THOUSAND_USD = 10.0
# Steel Launch 的 /scrape：$5 / 1000 次（另加按秒计的浏览器时间）。查自
# https://steel.dev/docs/platform/pricing ，2026-11-20。浏览器时间估不进上限，只报页数。
STEEL_SCRAPE_PER_THOUSAND_USD = 5.0


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
    consistency_dir: Path
    bank_file: Path
    bank_review_file: Path
    bank_progress_file: Path
    batch_dir: Path
    batch_progress_file: Path
    dataset_dir: Path
    extract_concurrency: int
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
            consistency_dir=_path(get("CROSSFIRE_CONSISTENCY_DIR", "out/consistency")),
            bank_file=_path(get("CROSSFIRE_BANK_FILE", "questions/bank.yaml")),
            bank_review_file=_path(get("CROSSFIRE_BANK_REVIEW_FILE", "notes/bank-review.md")),
            bank_progress_file=_path(get("CROSSFIRE_BANK_PROGRESS_FILE", "questions/bank-progress.yaml")),
            batch_dir=_path(get("CROSSFIRE_BATCH_DIR", "out/batch-runs")),
            batch_progress_file=_path(get("CROSSFIRE_BATCH_PROGRESS_FILE", "out/batch-progress.yaml")),
            dataset_dir=_path(get("CROSSFIRE_DATASET_DIR", "data")),
            extract_concurrency=_positive_int("CROSSFIRE_EXTRACT_CONCURRENCY", get("CROSSFIRE_EXTRACT_CONCURRENCY", "4"), env_file),
            env_file=env_file,
        )

    def price_for(self, model: str) -> ModelPrice:
        try:
            return MODEL_PRICES[model]
        except KeyError:
            known = "、".join(MODEL_PRICES) or "（空）"
            raise SettingsError(
                f"不知道模型 {model} 的单价。已登记的：{known}。"
                f"去 https://docs.anthropic.com/en/docs/about-claude/pricing 查到后加进 config.MODEL_PRICES，"
                f"并写上查询日期。"
            ) from None

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


def _positive_int(name: str, value: str, env_file: Path) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise SettingsError(f"{name}={value} 不合法，要一个正整数。在 {env_file} 里改。")
    return number


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_questions(settings: Settings) -> list[Question]:
    """读问题清单。文件不存在时返回空列表：web 端照样能看历史结果。"""
    if not settings.questions_file.is_file():
        return []
    data: Any = yaml.safe_load(settings.questions_file.read_text(encoding="utf-8")) or []
    return [Question.from_dict(item) for item in data]


def load_bank_questions(settings: Settings, path: Path | None = None) -> list:
    """读题库（含 category / design_note）。缺文件时报错。"""
    from crossfire.domain import BankQuestion

    bank_path = path or settings.bank_file
    if not bank_path.is_file():
        raise SettingsError(f"找不到题库文件 {bank_path}")
    data: Any = yaml.safe_load(bank_path.read_text(encoding="utf-8")) or []
    return [BankQuestion.from_yaml_dict(item) for item in data]


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
    return settings.evals_dir / "snapshots" / case.snapshot


def load_judge_inputs(settings: Settings, case: EvalCase) -> list[JudgeInput]:
    """judge 题的冻结输入：evals/judge_inputs/<id>.json。"""
    path = settings.evals_dir / "judge_inputs" / f"{case.id}.json"
    if not path.exists():
        raise SettingsError(f"judge 题 {case.id} 缺输入文件 {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    inputs = [JudgeInput.from_dict(item) for item in data["inputs"]]
    if not inputs:
        raise SettingsError(f"{path} 里没有输入")
    return inputs


def load_consistency_inputs(settings: Settings, case_ids: Iterable[str] | None = None) -> list[ConsistencyInput]:
    """先读 out/consistency/inputs/（批量导出），再读 evals/consistency_inputs/。同 id 时批量优先。"""
    directories = [settings.consistency_dir / "inputs", settings.evals_dir / "consistency_inputs"]
    by_stem: dict[str, Path] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            by_stem.setdefault(path.stem, path)
    paths = sorted(by_stem.values(), key=lambda path: path.stem)
    if case_ids is not None:
        wanted = set(case_ids)
        paths = [path for path in paths if path.stem in wanted]
        missing = wanted - {path.stem for path in paths}
        if missing:
            searched = "、".join(str(directory) for directory in directories)
            raise SettingsError(f"找不到稳定性输入：{', '.join(sorted(missing))}（查过 {searched}）")
    inputs: list[ConsistencyInput] = []
    for path in paths:
        try:
            inputs.append(ConsistencyInput.from_dict(json.loads(path.read_text(encoding="utf-8")), source=str(path)))
        except (KeyError, TypeError, ValueError) as error:
            raise SettingsError(f"读 {path} 失败：{error}") from error
    return inputs
