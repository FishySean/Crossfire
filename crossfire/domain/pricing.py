"""按模型估算 API 费用。单价来自 config，这里只做乘法。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """每百万 token 的美元价。"""

    input_per_mtok: float
    output_per_mtok: float

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens * self.input_per_mtok / 1_000_000 + output_tokens * self.output_per_mtok / 1_000_000
