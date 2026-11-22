"""NliClaimPairer：用 mock，不下载真实模型。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from crossfire.adapters.nli import pairer as pairer_mod
from crossfire.adapters.nli.encoding import encode_pair
from crossfire.adapters.nli.pairer import NliClaimPairer
from crossfire.adapters.nli.resolve import require_nli_ready
from crossfire.composition import build_pairer
from crossfire.config import Settings, SettingsError
from crossfire.domain import Claim, Question, Relation, SourceType, Tier, Usage
from crossfire.domain.models import Provenance

QUESTION = Question.from_dict(
    {
        "id": "nli-q",
        "question": "最新版本是多少？",
        "sources": [
            {"url": "https://a.example/", "tier": "primary"},
            {"url": "https://b.example/", "tier": "news"},
        ],
    }
)


def _claim(url: str, text: str) -> Claim:
    return Claim(
        source_url=url,
        tier=Tier.PRIMARY,
        text=text,
        evidence="e",
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        published_date="2026-01-01",
        confidence=0.9,
        usage=Usage(0, 0, 0),
    )


class _FakeTensor:
    def __init__(self, rows: list[list[float]]):
        self._rows = rows

    def float(self) -> "_FakeTensor":
        return self

    def cpu(self) -> "_FakeTensor":
        return self

    @property
    def shape(self) -> tuple[int, ...]:
        return (len(self._rows), len(self._rows[0]) if self._rows else 0)

    def argmax(self, dim: int = -1) -> SimpleNamespace:
        del dim
        ids = [max(range(len(row)), key=lambda i: row[i]) for row in self._rows]
        return SimpleNamespace(tolist=lambda: ids)

    def __getitem__(self, index: int) -> "_FakeRow":
        return _FakeRow(self._rows[index])


class _FakeRow:
    def __init__(self, values: list[float]):
        self._values = values
        self.shape = (len(values),)

    def __getitem__(self, index: int) -> float:
        return self._values[index]


def _install_fake_stack(monkeypatch, *, logits_rows: list[list[float]], boom: bool = False):
    """把 torch/transformers 换成内存假货，避免下载权重。"""

    captured: dict[str, object] = {}

    class _Movable:
        def to(self, device):
            del device
            return self

    class FakeTok:
        def __call__(self, premises, hypotheses, **kwargs):
            captured["premises"] = list(premises)
            captured["hypotheses"] = list(hypotheses)
            return {"input_ids": _Movable()}

    class FakeModel:
        def __init__(self):
            self.config = SimpleNamespace(
                id2label={
                    0: "agree",
                    1: "contradict",
                    2: "same_question_different_scope",
                    3: "unrelated",
                }
            )
            self._device = SimpleNamespace(type="cpu")

        def to(self, device):
            del device
            return self

        def eval(self):
            return self

        def parameters(self):
            yield SimpleNamespace(device=self._device)

        def __call__(self, **batch):
            del batch
            if boom:
                raise RuntimeError("fake OOM")
            return SimpleNamespace(logits=_FakeTensor(logits_rows))

    class FakeTorch:
        float16 = "fp16"
        float32 = "fp32"
        inference_mode = staticmethod(lambda: _NullCtx())

        class cuda:
            @staticmethod
            def is_available() -> bool:
                return False

        class backends:
            mps = None

        @staticmethod
        def device(name: str) -> str:
            return name

        @staticmethod
        def softmax(logits, dim=-1):
            del dim
            return logits

    class FakeTransformers:
        class AutoTokenizer:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                captured["load_args"] = args
                captured["load_kwargs"] = kwargs
                return FakeTok()

        class AutoModelForSequenceClassification:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                return FakeModel()

    monkeypatch.setattr(pairer_mod, "_import_torch", lambda: FakeTorch)
    monkeypatch.setattr(pairer_mod, "_import_transformers", lambda: FakeTransformers)
    return captured


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_pair_all_uses_encode_pair_and_fills_scores(monkeypatch):
    captured = _install_fake_stack(
        monkeypatch,
        logits_rows=[[0.1, 0.7, 0.1, 0.1], [0.8, 0.05, 0.05, 0.1]],
    )
    a = _claim("https://a.example/", "版本是 3.14.7")
    b = _claim("https://b.example/", "版本是 3.13")
    c = _claim("https://a.example/", "版本是 3.14.7")
    pairer = NliClaimPairer("/tmp/fake-model", batch_size=8, device="cpu")
    pairs = pairer.pair_all(QUESTION, [(a, b), (a, c)], date(2026, 11, 21))
    assert [p.relation for p in pairs] == [Relation.CONTRADICT, Relation.AGREE]
    assert pairs[0].scores is not None and pairs[0].scores["contradict"] == pytest.approx(0.7)
    assert pairs[0].usage.requests == 0
    expected = [
        encode_pair(QUESTION.text, a.text or "", b.text or "", published_date_a=a.published_date, published_date_b=b.published_date),
        encode_pair(QUESTION.text, a.text or "", c.text or "", published_date_a=a.published_date, published_date_b=c.published_date),
    ]
    assert captured["premises"] == [e.premise for e in expected]
    assert captured["hypotheses"] == [e.hypothesis for e in expected]


def test_mutation_different_encoding_changes_model_input(monkeypatch):
    """变异目标：推理时用了不同的输入拼接 → premises 对不上 encode_pair。"""
    captured = _install_fake_stack(monkeypatch, logits_rows=[[1, 0, 0, 0]])
    a = _claim("https://a.example/", "甲")
    b = _claim("https://b.example/", "乙")
    NliClaimPairer("/tmp/fake-model", device="cpu").pair_all(QUESTION, [(a, b)], date(2026, 1, 1))
    encoded = encode_pair(QUESTION.text, "甲", "乙", published_date_a="2026-01-01", published_date_b="2026-01-01")
    assert captured["premises"] == [encoded.premise]
    # 若有人改成 f"{a} [SEP] {b}" 之类，这里会红。
    assert "Claim A" in captured["premises"][0]
    assert captured["hypotheses"] == [encoded.hypothesis]


def test_batch_failure_marks_every_pair_and_does_not_raise(monkeypatch):
    """变异目标：整批失败时抛了异常 → 本测试会红。"""
    _install_fake_stack(monkeypatch, logits_rows=[], boom=True)
    a = _claim("https://a.example/", "甲")
    b = _claim("https://b.example/", "乙")
    c = _claim("https://a.example/", "丙")
    pairer = NliClaimPairer("/tmp/fake-model", batch_size=8, device="cpu")
    pairs = pairer.pair_all(QUESTION, [(a, b), (a, c)], date(2026, 1, 1))
    assert len(pairs) == 2
    assert all(p.failure is not None and p.relation is None for p in pairs)
    assert "OOM" in (pairs[0].failure.detail if pairs[0].failure else "")


def test_provenance_marks_nli_and_zero_api_usage(monkeypatch):
    _install_fake_stack(monkeypatch, logits_rows=[[1, 0, 0, 0]])
    pairer = NliClaimPairer("/tmp/fake-model", revision="abc123", device="cpu")
    a = _claim("https://a.example/", "甲")
    b = _claim("https://b.example/", "乙")
    pair = pairer.pair_all(QUESTION, [(a, b)], date(2026, 1, 1))[0]
    prov = pairer.provenance
    assert prov.implementation == "nli"
    assert prov.prompt_version is None
    assert prov.revision == "abc123"
    assert pair.usage.requests == 0


def test_require_nli_ready_fails_when_local_path_missing(tmp_path):
    """变异目标：PAIRER=nli 但模型不存在时没有提前报错。"""
    settings = Settings.from_mapping(
        {
            "PAIRER": "nli",
            "NLI_MODEL": str(tmp_path / "no-such-model"),
            "ANTHROPIC_API_KEY": "sk",
        },
        env_file=tmp_path / ".env",
    )
    with pytest.raises(SettingsError, match="不存在"):
        require_nli_ready(settings)


def test_build_pairer_nli_fails_fast_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "crossfire.adapters.nli.resolve.nli_deps_missing",
        lambda: [],
    )
    settings = Settings.from_mapping(
        {
            "PAIRER": "nli",
            "NLI_MODEL": str(tmp_path / "missing-weights"),
            "ANTHROPIC_API_KEY": "sk",
            "STEEL_API_KEY": "st",
        },
        env_file=tmp_path / ".env",
    )
    with pytest.raises(SettingsError, match="不存在|找不到"):
        build_pairer(settings)


def test_pair_scores_round_trip():
    from crossfire.domain import Pair

    original = Pair(
        a_url="https://a.example/",
        b_url="https://b.example/",
        relation=Relation.AGREE,
        nature="n",
        usage=Usage(0, 0, 0),
        scores={"agree": 0.9, "contradict": 0.1},
    )
    restored = Pair.from_dict(original.to_dict())
    assert restored.scores == {"agree": 0.9, "contradict": 0.1}
    without = Pair("https://a.example/", "https://b.example/", Relation.AGREE, "n", Usage(0, 0, 0))
    assert "scores" not in without.to_dict()
    assert Pair.from_dict(without.to_dict()).scores is None


def test_provenance_optional_fields_round_trip():
    prov = Provenance(
        model="FishySean/crossfire-pairer",
        prompt_version=None,
        implementation="nli",
        weights_sha256="abc",
        revision="deadbeef",
    )
    data = prov.to_dict()
    assert data["implementation"] == "nli"
    assert Provenance.from_dict({"model": "m", "prompt_version": None}).implementation is None
    assert Provenance.from_dict(data) == prov
