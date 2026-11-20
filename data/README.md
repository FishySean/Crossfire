# Crossfire 配对训练数据

- 总配对数：335
- 标签分布：{'same_question_different_scope': 27, 'agree': 232, 'unrelated': 15, 'contradict': 61}
- 题目类别分布（按配对计）：{'scope': 94, 'time_lag': 200, 'reprint_error': 41}
- 训练集：246 条配对，题目 ['nba-team-count-scope', 'eiffel-tower-height', 'ubuntu-lts-version', 'titanic-sinking-year-reprint', 'un-member-states-count', 'world-tallest-building', 'mysql-latest-ga', 'eu-member-states-scope', 'great-barrier-reef-area-scope', 'marie-curie-birth-year-reprint', 'bitcoin-creator-reprint', 'london-population-scope', 'amazon-employee-count-scope', 'africa-country-count-scope']
- 测试集：89 条配对，题目 ['apple-ceo-current', 'nodejs-lts-version', 'python-latest-stable', 'shanghai-population-scope', 'usa-land-area-scope']
- 训练集类别比例：{'scope': 69, 'reprint_error': 41, 'time_lag': 136}
- 测试集类别比例：{'time_lag': 64, 'scope': 25}
- 切分种子：`crossfire-5c2-2026-11-20`，目标训练比例 0.8
- 评测重叠题（强制测试集）：['nodejs-lts-version', 'python-latest-stable']

## 字段

- `label`：Sonnet 多数票（做过一致性的配对）或批量运行那一票
- `votes`：全部投票；`agreement` 为一致比例，**只有 1 票时为 null**（不是 1.0）
- `design_note` 不会出现在本文件里
