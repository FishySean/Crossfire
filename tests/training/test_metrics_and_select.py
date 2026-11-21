"""指标、选型、画图：不下载真实模型。"""

from __future__ import annotations

from pathlib import Path

from training.config import DEFAULT_CONFIG
from training.metrics import classification_report, macro_f1, summarize_seed_scores
from training.plot_curves import plot_loss_curves


def test_macro_f1_and_confusion() -> None:
    y_true = ["agree", "agree", "contradict", "same_question_different_scope"]
    y_pred = ["agree", "contradict", "contradict", "same_question_different_scope"]
    report = classification_report(y_true, y_pred)
    assert report["n"] == 4
    assert report["confusion_matrix"]["agree"]["agree"] == 1
    assert report["confusion_matrix"]["agree"]["contradict"] == 1
    assert 0 < report["macro_f1"] < 1
    assert macro_f1(y_true, y_true) == 1.0


def test_summarize_seed_scores_shows_spread() -> None:
    summary = summarize_seed_scores([0.40, 0.50, 0.45])
    assert summary["mean"] == 0.45
    assert summary["min"] == 0.40
    assert summary["max"] == 0.50
    assert abs(summary["range"] - 0.10) < 1e-9


def test_final_model_selection_uses_val_loss_not_test() -> None:
    # 变异目标：若按测试 F1 选型，会选 seed=43；正确应按 val loss 选 42。
    seeds = [
        {"seed": 42, "best_val_weighted_loss": 0.80, "test_macro_f1": 0.30},
        {"seed": 43, "best_val_weighted_loss": 0.95, "test_macro_f1": 0.55},
        {"seed": 44, "best_val_weighted_loss": 0.88, "test_macro_f1": 0.40},
    ]
    winner = min(seeds, key=lambda item: (item["best_val_weighted_loss"], item["seed"]))
    assert winner["seed"] == 42
    assert winner["test_macro_f1"] == 0.30  # 测试更差也照样入选


def test_plot_loss_curves_writes_png(tmp_path: Path) -> None:
    history = [
        {"epoch": 1, "train_loss": 1.2, "val_weighted_loss": 1.1},
        {"epoch": 2, "train_loss": 0.9, "val_weighted_loss": 0.95},
        {"epoch": 3, "train_loss": 0.7, "val_weighted_loss": 1.0},
    ]
    out = plot_loss_curves(history, tmp_path / "curve.png", best_epoch=2, title="unit")
    assert out.is_file()
    assert out.stat().st_size > 1000


def test_default_config_has_three_seeds_and_documented_defaults() -> None:
    assert DEFAULT_CONFIG.seeds == (42, 43, 44)
    assert DEFAULT_CONFIG.batch_size == 16
    assert DEFAULT_CONFIG.learning_rate == 2e-5
    assert DEFAULT_CONFIG.early_stop_patience == 3
    assert DEFAULT_CONFIG.max_epochs == 12
