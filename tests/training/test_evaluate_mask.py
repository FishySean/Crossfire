"""evaluate.compare_mask / flip_stats：屏蔽 unrelated 前后的正确性翻转统计。"""

from training.evaluate import flip_stats


def test_flip_stats_counts_correct_to_wrong_and_wrong_to_correct():
    y_true = ["agree", "contradict", "agree", "same_question_different_scope"]
    y_off = ["agree", "unrelated", "unrelated", "unrelated"]
    y_on = ["contradict", "contradict", "agree", "agree"]
    stats = flip_stats(y_true, y_off, y_on)
    assert stats["correct_to_wrong"] == 1  # agree→contradict
    assert stats["wrong_to_correct"] == 2  # unrelated→contradict, unrelated→agree
    assert stats["wrong_to_wrong_changed"] == 1  # unrelated→agree (gold=scope)


def test_flip_stats_no_change_is_zero():
    y_true = ["agree", "contradict"]
    y_pred = ["agree", "unrelated"]
    stats = flip_stats(y_true, y_pred, y_pred)
    assert stats["correct_to_wrong"] == 0
    assert stats["wrong_to_correct"] == 0
    assert stats["wrong_to_wrong_changed"] == 0
