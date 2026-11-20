"""按三类分歧提出候选题目。不搜索、不找来源。"""

from datetime import date
from typing import Any

from crossfire.adapters.anthropic.client import ClaudeClient
from crossfire.domain import ProposedQuestion, QuestionCategory, Usage
from crossfire.domain.bank import CATEGORY_QUOTAS

PROPOSE_PROMPT = """你在为一个事实查证引擎出题。引擎会抓多个网页、提取主张、两两比对找矛盾。

今天的日期：{as_of}

请严格按下面的配额出题（一类一道都不要多，一类不够就少交，不要为了凑数降低标准）：
{quota_lines}

类别说明：
1. time_lag（时间差型）：答案随时间变过，网上新旧说法并存。例如软件当前稳定版、现任职位、最新纪录。
2. scope（口径不同型）：不同定义得出不同数字。例如城市人口（行政区 vs 都市圈）、公司员工数。
3. reprint_error（转载出错型）：一手来源正确，转载站可能抄错或过时。
   注意：不要幻想「专门搜抄错的网站」。出的题应是一手来源有明确答案、二手站历史上常写错或过时的事实
   （年份、署名、数字）。这类题天然难找，配额本来就少。

硬性排除：
- 不要出「公认有争议」的话题。反例：太阳系有几颗行星。有争议时来源会在同一条主张里同时写出两种立场，
  比对层看不到矛盾，训练数据没有用。
- 题目必须能用一句话、一个确定的答案（或按口径分别给出的确定答案）回答。
- 不要「为什么」「怎么样」这类开放题。
- 中文和英文题都要有，大约各一半。
- id 用小写英文短横线，全局唯一，能看出主题。不要用这些已有 id：{avoid_ids}
- keywords 列出 3–8 个词或短语，抓到页面后用来确认正文真的在谈这个问题。

通过 record 工具返回。"""

PROPOSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in QuestionCategory],
                    },
                    "language": {"type": "string", "enum": ["zh", "en"]},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "question", "category", "language", "keywords"],
            },
        }
    },
    "required": ["questions"],
}


def _parse(data: dict[str, Any]) -> list[ProposedQuestion]:
    questions = [ProposedQuestion.from_dict(item) for item in data["questions"]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"题目 id 重复：{sorted({i for i in ids if ids.count(i) > 1})}")
    for question in questions:
        if len(question.keywords) < 2:
            raise ValueError(f"{question.id} 的 keywords 少于 2 个")
    return questions


class ClaudeQuestionProposer:
    def __init__(self, client: ClaudeClient, *, avoid_ids: tuple[str, ...] = ()) -> None:
        self._client = client
        self._avoid_ids = avoid_ids
        self.last_usage = Usage(0, 0, 0)

    def propose(self, quotas: dict[QuestionCategory, int], as_of: date) -> list[ProposedQuestion]:
        needed = {category: n for category, n in quotas.items() if n > 0}
        if not needed:
            return []
        lines = "\n".join(f"- {category.value}: {count} 道" for category, count in needed.items())
        avoid = ", ".join(self._avoid_ids) if self._avoid_ids else "（无）"
        prompt = PROPOSE_PROMPT.format(as_of=as_of.isoformat(), quota_lines=lines, avoid_ids=avoid)
        call = self._client.call(prompt, PROPOSE_SCHEMA, "propose", _parse, max_tokens=4000)
        self.last_usage = call.usage
        questions = call.value or []
        # 硬裁：每类不超过配额
        kept: list[ProposedQuestion] = []
        left = dict(needed)
        for question in questions:
            if left.get(question.category, 0) <= 0:
                continue
            if question.id in self._avoid_ids:
                continue
            kept.append(question)
            left[question.category] -= 1
        return kept
