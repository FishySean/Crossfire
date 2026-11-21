"""训练用的四个关系标签，以及和基座三分类的对应关系。"""

from crossfire.domain import Relation

# 训练标签顺序固定；改顺序必须同步改分类头初始化。
LABELS: tuple[str, ...] = (
    Relation.AGREE.value,
    Relation.CONTRADICT.value,
    Relation.SAME_QUESTION_DIFFERENT_SCOPE.value,
    Relation.UNRELATED.value,
)

LABEL2ID = {label: index for index, label in enumerate(LABELS)}
ID2LABEL = {index: label for label, index in LABEL2ID.items()}

# 基座 mDeBERTa：0=entailment, 1=neutral, 2=contradiction
# 我们的四类里，三个旧类沿用对应行的权重；口径不同是新行。
BASE_ROW_FOR_LABEL = {
    Relation.AGREE.value: 0,  # ← entailment
    Relation.UNRELATED.value: 1,  # ← neutral
    Relation.CONTRADICT.value: 2,  # ← contradiction
    # same_question_different_scope: 无旧行，见 resize_classifier
}
