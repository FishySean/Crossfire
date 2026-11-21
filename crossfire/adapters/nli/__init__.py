"""本地 NLI 比对适配器。训练与上线共用 encoding，避免两套输入格式。"""

from crossfire.adapters.nli.encoding import EncodedPair, encode_pair, encode_pair_row

__all__ = ["EncodedPair", "encode_pair", "encode_pair_row"]
