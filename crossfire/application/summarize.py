"""从 RunResult 派生仪表盘摘要。前端只渲染，不做判断。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from crossfire.domain import (
    Pair,
    Relation,
    RunResult,
    SourceRulingKind,
    SourceType,
    Tier,
)

LOW_CONFIDENCE = 0.5


@dataclass(frozen=True)
class SourceStatusRow:
    url: str
    domain: str
    status: str  # trusted|wrong|outdated|scope|neutral|failed
    reason: str | None
    key_value: str | None
    claim: str | None
    tier: str
    source_type: str | None
    content_date: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "domain": self.domain,
            "status": self.status,
            "reason": self.reason,
            "key_value": self.key_value,
            "claim": self.claim,
            "tier": self.tier,
            "source_type": self.source_type,
            "content_date": self.content_date,
        }


@dataclass(frozen=True)
class ConflictGroup:
    focus_url: str
    focus_domain: str
    against_urls: tuple[str, ...]
    label_zh: str
    label_en: str

    def to_dict(self) -> dict[str, object]:
        return {
            "focus_url": self.focus_url,
            "focus_domain": self.focus_domain,
            "against_urls": list(self.against_urls),
            "against_count": len(self.against_urls),
            "label_zh": self.label_zh,
            "label_en": self.label_en,
        }


@dataclass(frozen=True)
class RunSummary:
    headline_kind: str
    headline_zh: str
    headline_en: str
    sources: tuple[SourceStatusRow, ...]
    trusted_count: int
    wrong_or_outdated_count: int
    scope_source_count: int
    nli_contradict_pairs: int
    nli_contradict_low_confidence: int
    conflict_groups: tuple[ConflictGroup, ...]
    composition_by_tier: dict[str, int]
    composition_by_source_type: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "headline_kind": self.headline_kind,
            "headline_zh": self.headline_zh,
            "headline_en": self.headline_en,
            "sources": [row.to_dict() for row in self.sources],
            "trusted_count": self.trusted_count,
            "wrong_or_outdated_count": self.wrong_or_outdated_count,
            "scope_source_count": self.scope_source_count,
            "nli_contradict_pairs": self.nli_contradict_pairs,
            "nli_contradict_low_confidence": self.nli_contradict_low_confidence,
            "conflict_groups": [group.to_dict() for group in self.conflict_groups],
            "composition_by_tier": dict(self.composition_by_tier),
            "composition_by_source_type": dict(self.composition_by_source_type),
        }


def domain_of(url: str) -> str:
    host = urlparse(url).hostname or url
    return host.removeprefix("www.")


def _pair_confidence(pair: Pair) -> float | None:
    if not pair.scores or pair.relation is None:
        return None
    value = pair.scores.get(pair.relation.value)
    return float(value) if value is not None else None


def _status_map(result: RunResult) -> dict[str, tuple[str, str | None]]:
    """url → (status, reason)。优先 source_rulings；否则 trusted_sources → trusted，其余 neutral。"""
    out: dict[str, tuple[str, str | None]] = {}
    rulings = result.judgment.source_rulings
    if rulings is not None:
        for ruling in rulings:
            out[ruling.url] = (ruling.ruling.value, ruling.reason)
        return out
    trusted = set(result.judgment.trusted_sources)
    for source in result.question.sources:
        if source.url in trusted:
            out[source.url] = (SourceRulingKind.TRUSTED.value, None)
        else:
            out[source.url] = (SourceRulingKind.NEUTRAL.value, None)
    return out


def _headline(kind: str) -> tuple[str, str, str]:
    table = {
        "consistent": ("consistent", "来源一致", "Sources agree"),
        "mostly_one": ("mostly_one", "大体一致，1 个来源有误/过时", "Mostly consistent — 1 source wrong/outdated"),
        "mostly_many": ("mostly_many", "多数一致，{n} 个来源有误", "Mostly consistent — {n} sources wrong/outdated"),
        "divided": ("divided", "分歧明显", "Clear disagreement"),
        "no_verdict": ("no_verdict", "没有结论", "No verdict"),
    }
    return table[kind]


def headline_for(*, wrong: int, trusted: int, scope: int, judge_failed: bool) -> tuple[str, str, str]:
    if judge_failed:
        kind, zh, en = _headline("no_verdict")
        return kind, zh, en
    if wrong == 0 and scope == 0:
        return _headline("consistent")
    if wrong == 1:
        return _headline("mostly_one")
    if wrong >= 2 and wrong < max(trusted, 1):
        kind, zh, en = _headline("mostly_many")
        return kind, zh.format(n=wrong), en.format(n=wrong)
    if wrong >= trusted and wrong >= 1:
        return _headline("divided")
    # wrong==0 but scope>0 → still "consistent" framing (口径不同不算有误)
    return _headline("consistent")


def _conflict_groups(result: RunResult, status: dict[str, tuple[str, str | None]]) -> tuple[ConflictGroup, ...]:
    partners: dict[str, set[str]] = {}
    for pair in result.pairs:
        if pair.relation is not Relation.CONTRADICT:
            continue
        partners.setdefault(pair.a_url, set()).add(pair.b_url)
        partners.setdefault(pair.b_url, set()).add(pair.a_url)

    # 优先把 wrong/outdated 来源当作 focus；否则每个有 ≥1 个矛盾伙伴的来源各成一组（去重：只为 focus 出组）
    focus_urls = [
        url
        for url, (st, _) in status.items()
        if st in {SourceRulingKind.WRONG.value, SourceRulingKind.OUTDATED.value} and partners.get(url)
    ]
    if not focus_urls:
        focus_urls = [url for url, against in partners.items() if against]

    groups: list[ConflictGroup] = []
    seen: set[str] = set()
    for url in focus_urls:
        if url in seen:
            continue
        against = tuple(sorted(partners.get(url, ())))
        if not against:
            continue
        seen.add(url)
        host = domain_of(url)
        n = len(against)
        groups.append(
            ConflictGroup(
                focus_url=url,
                focus_domain=host,
                against_urls=against,
                label_zh=f"{host} 与 {n} 个来源矛盾",
                label_en=f"{host} contradicts {n} source{'s' if n != 1 else ''}",
            )
        )
    return tuple(groups)


def summarize_run(result: RunResult) -> RunSummary:
    status = _status_map(result)
    claim_by_url = {claim.source_url: claim for claim in result.claims}
    page_by_url = {page.url: page for page in result.pages}

    rows: list[SourceStatusRow] = []
    for source in result.question.sources:
        claim = claim_by_url.get(source.url)
        page = page_by_url.get(source.url)
        # 已成功抽出主张的来源不算 failed（夹具可截短 markdown，不能因此盖掉 ruling）。
        if claim is not None and claim.failure is not None:
            st, reason = "failed", claim.failure.detail
        elif page is not None and not page.ok:
            st, reason = "failed", page.error or "fetch failed"
        elif (claim is None or not claim.answered) and page is not None and not page.usable:
            st, reason = (
                "failed",
                page.unusable_reason.value if page.unusable_reason else "unusable",
            )
        else:
            st, reason = status.get(source.url, (SourceRulingKind.NEUTRAL.value, None))
        rows.append(
            SourceStatusRow(
                url=source.url,
                domain=domain_of(source.url),
                status=st,
                reason=reason,
                key_value=None if claim is None else claim.key_value,
                claim=None if claim is None else claim.text,
                tier=source.tier.value,
                source_type=None if claim is None or claim.source_type is None else claim.source_type.value,
                content_date=None if claim is None else claim.content_date,
            )
        )

    trusted = sum(1 for row in rows if row.status == SourceRulingKind.TRUSTED.value)
    wrong = sum(
        1 for row in rows if row.status in {SourceRulingKind.WRONG.value, SourceRulingKind.OUTDATED.value}
    )
    scope = sum(1 for row in rows if row.status == SourceRulingKind.SCOPE.value)

    contradict_pairs = [pair for pair in result.pairs if pair.relation is Relation.CONTRADICT]
    low_conf = 0
    for pair in contradict_pairs:
        conf = _pair_confidence(pair)
        if conf is not None and conf < LOW_CONFIDENCE:
            low_conf += 1

    kind, zh, en = headline_for(
        wrong=wrong,
        trusted=trusted,
        scope=scope,
        judge_failed=result.judgment.failure is not None,
    )

    by_tier: dict[str, int] = {tier.value: 0 for tier in Tier}
    for source in result.question.sources:
        by_tier[source.tier.value] = by_tier.get(source.tier.value, 0) + 1

    by_type: dict[str, int] = {kind.value: 0 for kind in SourceType}
    for claim in result.claims:
        if claim.source_type is not None:
            by_type[claim.source_type.value] = by_type.get(claim.source_type.value, 0) + 1

    return RunSummary(
        headline_kind=kind,
        headline_zh=zh,
        headline_en=en,
        sources=tuple(rows),
        trusted_count=trusted,
        wrong_or_outdated_count=wrong,
        scope_source_count=scope,
        nli_contradict_pairs=len(contradict_pairs),
        nli_contradict_low_confidence=low_conf,
        conflict_groups=_conflict_groups(result, status),
        composition_by_tier=by_tier,
        composition_by_source_type={k: v for k, v in by_type.items() if v},
    )


def summary_to_dict(result: RunResult) -> dict[str, object]:
    """API / SSE 用的完整 summary 字典（含仪表盘数字行）。"""
    summary = summarize_run(result)
    body = summary.to_dict()
    body["counts"] = {
        "sources": len(result.question.sources),
        "pairs": len(result.pairs),
        "faulty_sources": summary.wrong_or_outdated_count,
        "scope_sources": summary.scope_source_count,
    }
    return body
