"""把一对主张拼成 NLI 模型的输入。

训练脚本和上线推理必须调用这里的函数，不允许各自再写一份拼接逻辑。
基座 mDeBERTa 是按「前提 / 假设」成对训练的，所以这里也输出 premise + hypothesis。
"""

from dataclasses import dataclass
from typing import Any, Mapping
from unicodedata import normalize


UNKNOWN_DATE = "unknown"


@dataclass(frozen=True)
class EncodedPair:
    """一条配对编码后的两段文本。tokenizer 用 premise 作 text、hypothesis 作 text_pair。"""

    premise: str
    hypothesis: str

    def as_single_string(self) -> str:
        """给人看的完整样子；模型训练/推理仍用 premise + hypothesis 两段。"""
        return f"{self.premise}\n{self.hypothesis}"


def normalize_text(text: str) -> str:
    """全角标点等转成半角兼容形式，减少分词器打出 [UNK]。

    例：？→ ?，，（）→ ,()。正文语义不变。
    """
    return normalize("NFKC", text)


def effective_date(published_date: str | None, content_date: str | None = None) -> str | None:
    """给模型看的日期：优先页面发布日，没有就用内容所述时间。

    训练集是在收紧 published_date 规则之前造的，那时填进 published_date 的大多其实是
    正文里的事件/内容时间点。上线后 published_date 只认页面元数据，大量变成 null；
    若推理时不再回退到 content_date，模型会看见一堆 unknown，跟训练分布不一致
    （train/serve skew）。回退后与训练时「字段里常有内容时间」的含义对齐。
    """
    for value in (published_date, content_date):
        text = (value or "").strip()
        if text:
            return text
    return None


def _date(value: str | None) -> str:
    text = (value or "").strip()
    return text if text else UNKNOWN_DATE


def encode_pair(
    question: str,
    claim_a: str,
    claim_b: str,
    *,
    published_date_a: str | None = None,
    published_date_b: str | None = None,
    content_date_a: str | None = None,
    content_date_b: str | None = None,
) -> EncodedPair:
    """拼一对主张。

    布局：
    - premise（前提）= 问题 + 主张 A + A 的日期
    - hypothesis（假设）= 主张 B + B 的日期

    日期槽位标签仍是 published（与训练时字符串格式一致）；填入值经 effective_date：
    有 published_date 用它，否则用 content_date。

    字段标签用英文固定词（Question / Claim A / Claim B），正文可以是中文或英文。
    缺日期写成 unknown，跟 Claude 比对器用「未知」是同一意图，这里用英文以配合多语基座。
    拼之前做 NFKC，避免全角问号/逗号/括号变成 [UNK]。
    """
    question = normalize_text(question.strip())
    claim_a = normalize_text(claim_a.strip())
    claim_b = normalize_text(claim_b.strip())
    date_a = effective_date(published_date_a, content_date_a)
    date_b = effective_date(published_date_b, content_date_b)
    premise = (
        f"Question: {question}\n"
        f"Claim A (published: {_date(date_a)}): {claim_a}"
    )
    hypothesis = f"Claim B (published: {_date(date_b)}): {claim_b}"
    return EncodedPair(premise=premise, hypothesis=hypothesis)


def encode_pair_row(row: Mapping[str, Any]) -> EncodedPair:
    """从 data/pairs.jsonl 的一行直接编码。只读 question / claim / date 字段。"""
    return encode_pair(
        str(row["question"]),
        str(row["claim_a"]),
        str(row["claim_b"]),
        published_date_a=None if row.get("published_date_a") is None else str(row["published_date_a"]),
        published_date_b=None if row.get("published_date_b") is None else str(row["published_date_b"]),
        content_date_a=None if row.get("content_date_a") is None else str(row["content_date_a"]),
        content_date_b=None if row.get("content_date_b") is None else str(row["content_date_b"]),
    )
