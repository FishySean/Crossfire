"""启动阶段检查 NLI 模型路径 / Hugging Face 仓库是否可用。

不 import torch：只做路径与依赖探测，真正加载在 pairer 里。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from crossfire.config import ROOT, Settings, SettingsError

NLI_DEPS = ("torch", "transformers", "sentencepiece")


def nli_deps_missing() -> list[str]:
    return [name for name in NLI_DEPS if importlib.util.find_spec(name) is None]


def is_local_model_ref(ref: str) -> bool:
    """看起来像本地路径（存在，或含路径分隔符 / 以 . 开头），而不是 org/name 仓库名。"""
    path = Path(ref).expanduser()
    if path.exists():
        return True
    if ref.startswith(".") or ref.startswith("/") or ref.startswith("~"):
        return True
    # Windows 盘符或显式相对 models/...
    if len(ref) >= 2 and ref[1] == ":":
        return True
    if "/" in ref and Path(ref).parts[0] in {"models", "out", "data", "tmp"}:
        return True
    return False


def require_nli_ready(settings: Settings) -> None:
    """PAIRER=nli 时在组装阶段调用：缺依赖或模型不可用立刻报错。"""
    missing = nli_deps_missing()
    if missing:
        raise SettingsError(
            "PAIRER=nli 需要推理依赖，当前缺少："
            + "、".join(missing)
            + "。\n"
            "安装：uv sync --group nli\n"
            "（nli 组只有推理用的 torch / transformers / sentencepiece；"
            "训练另装 --group train，多一个 matplotlib。）"
        )

    ref = settings.nli_model.strip()
    if not ref:
        raise SettingsError(
            f"NLI_MODEL 为空。填 Hugging Face 仓库名（默认 FishySean/crossfire-pairer）"
            f"或本地目录（例如 models/crossfire-pairer-v1）。在 {settings.env_file} 里改。"
        )

    local = Path(ref).expanduser()
    if not local.is_absolute():
        local = (ROOT / local).resolve() if not Path(ref).is_absolute() else local

    # 明确的本地路径：必须存在且含权重
    if is_local_model_ref(ref) or local.exists():
        path = local if local.exists() else Path(ref).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        if not path.is_dir():
            raise SettingsError(
                f"NLI_MODEL={ref} 被当成本地路径，但目录不存在：{path}\n"
                "把训练好的 package 解压到 models/crossfire-pairer-v1/，"
                "或改成 Hugging Face 仓库名（例如 FishySean/crossfire-pairer）。"
            )
        weight = path / "model.safetensors"
        if not weight.is_file() and not (path / "pytorch_model.bin").is_file():
            raise SettingsError(
                f"本地模型目录 {path} 里找不到 model.safetensors（或 pytorch_model.bin）。\n"
                "请确认已从 Google Drive 下载 package 并解压到该目录。"
            )
        return

    # Hugging Face 仓库名
    revision = (settings.nli_model_revision or "").strip()
    if not revision:
        raise SettingsError(
            f"NLI_MODEL={ref} 是 Hugging Face 仓库名，但 NLI_MODEL_REVISION 为空。\n"
            "上传模型后把 commit hash 填进 NLI_MODEL_REVISION（见 scripts/publish_model.py 的输出），\n"
            "或开发时改用本地路径：NLI_MODEL=models/crossfire-pairer-v1"
        )
    try:
        from huggingface_hub import model_info
    except ImportError as error:
        raise SettingsError(
            "检查 Hugging Face 仓库需要 huggingface_hub（随 transformers 安装）。\n"
            "请先：uv sync --group nli"
        ) from error
    try:
        model_info(ref, revision=revision)
    except Exception as error:
        raise SettingsError(
            f"无法从 Hugging Face 读取 {ref} @ {revision}：{type(error).__name__}: {error}\n"
            "确认仓库存在、revision 正确、网络可用；"
            "或改用本地路径 NLI_MODEL=models/crossfire-pairer-v1。"
        ) from error
