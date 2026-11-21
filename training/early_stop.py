"""早停看什么：验证集的加权交叉熵损失，不看某一类的 F1。

验证集很小（约 2 道题），某一类可能只有 2 条，单类分数噪声极大。
总体加权损失（用与训练相同的 class weight）足够判断「是否开始过拟合」。
"""

EARLY_STOP_METRIC = "val_weighted_loss"
EARLY_STOP_MODE = "min"  # 损失越低越好；回升则停
