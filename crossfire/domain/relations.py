from enum import StrEnum


class Relation(StrEnum):
    """两个主张之间的关系。

    值是对外契约：PAIR_SCHEMA 的 enum、前端的样式类名、out/runs/*.json 里都是这些字面量，不能改。
    判定口径的权威版本在 reconcile.PAIR_PROMPT 里，这里只写边界，两处要一起改。
    """

    # 可以同时为真，且指向同一个结论。
    # 一方只是另一方的粗粒度表述（「3.14.7」vs「3.14 处于 bugfix」）也算这一类，粒度差异不是矛盾。
    # 口径不同但答案相同的，也归这里而不是 SAME_QUESTION_DIFFERENT_SCOPE。
    AGREE = "agree"

    # 量的是同一个东西，但不可能同时为真：必有一方错了或已过时。
    # 时间差属于这一类：「Active LTS 是 v22」（2024）vs「是 v24」（2026）量的都是「当前」，前者过时了。
    # 说不出具体是哪两个口径、只能说「可能统计方法不同」的，也是这一类，不许借口径之名回避裁定。
    CONTRADICT = "contradict"

    # 答案不同，但各自为真：差异来自能指名道姓的定义或统计范围，且在同一个当前时刻两者都成立。
    # 例：东京都 1424 万 vs 大东京都市圈 3700 万；珠峰岩面高度 vs 雪盖高度。
    # 调和方式是「说清问的是哪个口径」而不是「判谁错」，所以 judge 不得因它扣置信度。
    # 与 CONTRADICT 的分界：两者放在「现在」是否依然都成立。成立是本类，有一方过时就是 CONTRADICT。
    SAME_QUESTION_DIFFERENT_SCOPE = "same_question_different_scope"

    # 在谈不同的事，既不能互相印证也不能互相反驳。
    # 一方根本没回答这个问题的归这里，而不是 SAME_QUESTION_DIFFERENT_SCOPE。
    UNRELATED = "unrelated"
