"""本地 NLI 主张比对器：实现 ClaimPairer，批量推理、不调任何 API。

torch / transformers 只在本模块内延迟导入，主程序未装推理依赖时仍可 import 本文件。
输入必须走 encoding.encode_pair，禁止在这里另写拼接。
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from crossfire.adapters.nli.encoding import encode_pair
from crossfire.application.ports import OnPair
from crossfire.domain import Claim, Failure, Pair, Provenance, Question, Relation, Usage

DEFAULT_BATCH_SIZE = 16
IMPLEMENTATION = "nli"
_ZERO_USAGE = Usage(input_tokens=0, output_tokens=0, requests=0)


def pick_device(explicit: str | None = None) -> str:
    """CUDA → MPS（苹果芯片）→ CPU。"""
    if explicit:
        return explicit
    torch = _import_torch()
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def weights_sha256(model_dir: Path) -> str | None:
    """本地目录下 model.safetensors（或 pytorch_model.bin）的内容哈希；找不到就 None。"""
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = model_dir / name
        if path.is_file():
            return _sha256_file(path)
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise ImportError(
            "缺少 torch。PAIRER=nli 需要推理依赖：uv sync --group nli"
        ) from error
    return torch


def _import_transformers() -> Any:
    try:
        import transformers
    except ImportError as error:
        raise ImportError(
            "缺少 transformers。PAIRER=nli 需要推理依赖：uv sync --group nli"
        ) from error
    return transformers


class NliClaimPairer:
    """本地四分类 NLI 比对。整批失败时每对记 failure，不抛异常（端口约定）。"""

    def __init__(
        self,
        model: str,
        *,
        revision: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        device: str | None = None,
        local_files_only: bool = False,
    ) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size 必须 ≥ 1，收到 {batch_size}")
        self._model_ref = model
        self._revision = revision
        self._batch_size = batch_size
        self._device_name = pick_device(device)
        self._local_files_only = local_files_only
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._id2label: dict[int, str] = {}
        self._weights_sha256: str | None = None
        self._resolved_path: Path | None = None

    @property
    def provenance(self) -> Provenance:
        self._ensure_loaded()
        display = self._model_ref
        if self._resolved_path is not None:
            display = str(self._resolved_path)
        return Provenance(
            model=display,
            prompt_version=None,
            implementation=IMPLEMENTATION,
            weights_sha256=self._weights_sha256,
            revision=self._revision,
        )

    def pair_all(
        self,
        question: Question,
        claim_pairs: Sequence[tuple[Claim, Claim]],
        as_of: date,
        on_pair: OnPair | None = None,
    ) -> list[Pair]:
        del as_of  # 日期已编码进主张的 published_date；本地模型忽略「今天」。
        total = len(claim_pairs)
        if total == 0:
            return []
        try:
            self._ensure_loaded()
            results: list[Pair] = []
            for start in range(0, total, self._batch_size):
                chunk = list(claim_pairs[start : start + self._batch_size])
                try:
                    batch_pairs = self._infer_batch(question, chunk)
                except Exception as error:
                    detail = f"{type(error).__name__}: {error}"
                    print(f"❌ [nli] 整批推理失败，本批 {len(chunk)} 对记为失败：{detail}", file=sys.stderr)
                    batch_pairs = [self._failed(a, b, detail) for a, b in chunk]
                for offset, pair in enumerate(batch_pairs):
                    index = start + offset
                    results.append(pair)
                    if on_pair:
                        on_pair(index, total, pair)
            return results
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            print(f"❌ [nli] 比对器失败，全部 {total} 对记为失败：{detail}", file=sys.stderr)
            results = []
            for index, (a, b) in enumerate(claim_pairs):
                pair = self._failed(a, b, detail)
                results.append(pair)
                if on_pair:
                    on_pair(index, total, pair)
            return results

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        torch = _import_torch()
        transformers = _import_transformers()
        device = torch.device(self._device_name)
        dtype = torch.float32 if self._device_name == "cpu" else torch.float16
        load_kw: dict[str, Any] = {"dtype": dtype}
        if self._revision:
            load_kw["revision"] = self._revision
        if self._local_files_only:
            load_kw["local_files_only"] = True

        ref: str | Path = self._model_ref
        local = Path(self._model_ref).expanduser()
        if local.exists():
            ref = local
            self._resolved_path = local.resolve()
            self._weights_sha256 = weights_sha256(self._resolved_path)
            load_kw["local_files_only"] = True
            load_kw.pop("revision", None)

        tok_kw = {k: v for k, v in load_kw.items() if k != "dtype"}
        tokenizer = transformers.AutoTokenizer.from_pretrained(ref, **tok_kw)
        model = transformers.AutoModelForSequenceClassification.from_pretrained(ref, **load_kw)
        model.to(device)
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        self._id2label = {int(k): str(v) for k, v in model.config.id2label.items()}
        if self._weights_sha256 is None and self._resolved_path is not None:
            self._weights_sha256 = weights_sha256(self._resolved_path)

    def _infer_batch(self, question: Question, chunk: list[tuple[Claim, Claim]]) -> list[Pair]:
        assert self._tokenizer is not None and self._model is not None
        torch = _import_torch()
        premises: list[str] = []
        hypotheses: list[str] = []
        for a, b in chunk:
            encoded = encode_pair(
                question.text,
                a.text or "",
                b.text or "",
                published_date_a=a.published_date,
                published_date_b=b.published_date,
            )
            premises.append(encoded.premise)
            hypotheses.append(encoded.hypothesis)

        encoded_batch = self._tokenizer(
            premises,
            hypotheses,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        device = next(self._model.parameters()).device
        encoded_batch = {key: value.to(device) for key, value in encoded_batch.items()}
        with torch.inference_mode():
            logits = self._model(**encoded_batch).logits
            probs = torch.softmax(logits.float(), dim=-1).cpu()
            pred_ids = probs.argmax(dim=-1).tolist()

        pairs: list[Pair] = []
        for (a, b), pred_id, row in zip(chunk, pred_ids, probs, strict=True):
            label = self._id2label[int(pred_id)]
            scores = {self._id2label[i]: float(row[i]) for i in range(row.shape[0])}
            relation = Relation(label)
            top_p = scores[label]
            pairs.append(
                Pair(
                    a_url=a.source_url,
                    b_url=b.source_url,
                    relation=relation,
                    nature=f"本地 NLI：{label}（p={top_p:.3f}）",
                    usage=_ZERO_USAGE,
                    scores=scores,
                )
            )
        return pairs

    def _failed(self, a: Claim, b: Claim, detail: str) -> Pair:
        return Pair(
            a_url=a.source_url,
            b_url=b.source_url,
            relation=None,
            nature=None,
            usage=_ZERO_USAGE,
            failure=Failure(step="pair", detail=detail, raw=None),
        )
