"""本地 NLI 比对适配器。训练与上线共用 encoding，避免两套输入格式。"""

from crossfire.adapters.nli.encoding import EncodedPair, encode_pair, encode_pair_row

# NliClaimPairer 不在这里 re-export：加载它没问题（lazy torch），但避免让
# `from crossfire.adapters.nli import *` 暗示主程序默认依赖推理栈。

__all__ = ["EncodedPair", "encode_pair", "encode_pair_row"]
