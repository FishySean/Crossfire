# Crossfire 配对训练数据

- 总配对数：474
- 标签分布：{'same_question_different_scope': 67, 'agree': 286, 'unrelated': 30, 'contradict': 91}
- 题目类别分布（按配对计）：{'scope': 233, 'time_lag': 200, 'reprint_error': 41}
- 训练集：385 条配对，题目 ['africa-country-count-scope', 'amazon-employee-count-scope', 'amazon-river-basin-area-scope', 'bitcoin-creator-reprint', 'eiffel-tower-height', 'eu-member-states-scope', 'euro-zone-member-count-scope', 'great-barrier-reef-area-scope', 'great-lakes-area-scope', 'india-population-scope', 'london-population-scope', 'marie-curie-birth-year-reprint', 'mysql-latest-ga', 'nba-team-count-scope', 'titanic-sinking-year-reprint', 'ubuntu-lts-version', 'un-member-states-count', 'us-gdp-scope', 'us-hispanic-population-scope', 'us-national-park-count-scope', 'world-tallest-building']
- 测试集：89 条配对，题目 ['apple-ceo-current', 'nodejs-lts-version', 'python-latest-stable', 'shanghai-population-scope', 'usa-land-area-scope']
- 训练集类别比例：{'scope': 208, 'reprint_error': 41, 'time_lag': 136}
- 测试集类别比例：{'time_lag': 64, 'scope': 25}
- 切分种子：`crossfire-5c2-2026-11-20`，目标训练比例 0.8
- 评测重叠题（强制测试集）：['nodejs-lts-version', 'python-latest-stable']

## 字段

- `label`：Sonnet 多数票（做过一致性的配对）或批量运行那一票
- `votes`：全部投票；`agreement` 为一致比例，**只有 1 票时为 null**（不是 1.0）
- `design_note` 不会出现在本文件里
