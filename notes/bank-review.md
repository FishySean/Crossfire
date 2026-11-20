# 题库审查报告（5c-2 修订）

生成日期（as_of）：2026-11-20  
修订：去掉题目里的答案提示；删除 DNA 争议题；NBA 改为中性问法。

保留 **19** 道。类别：`time_lag` 9、`scope` 7、`reprint_error` 3（配额允许 ±1）。

## 改前 → 改后

| id | 改前 | 改后 | 说明 |
|---|---|---|---|
| shanghai-population-scope | 上海的人口是多少？（常住人口 vs 户籍人口口径不同，数字有差异） | 上海的人口是多少？ | 提示移入 design_note |
| amazon-employee-count-scope | How many employees does Amazon have? (Note: full-time vs …) | How many employees does Amazon have? | 同上 |
| usa-land-area-scope | What is the total area of the United States… (Figures differ…) | What is the total area of the United States in square kilometers? | 同上 |
| africa-country-count-scope | 非洲共有多少个国家？（不同口径：联合国承认 vs …） | 非洲共有多少个国家？ | 同上 |
| bitcoin-creator-reprint | 比特币白皮书的作者署名是什么？（转载常误写为其他形式） | 比特币白皮书的作者署名是什么？ | 同上 |
| marie-curie-birth-year-reprint | Marie Curie's birth year is sometimes misprinted… | What year was Marie Curie born? | 去掉「常被印错」暗示 |
| titanic-sinking-year-reprint | 泰坦尼克号沉没于哪一年？（部分转载文章错误写为 1911 年） | 泰坦尼克号沉没于哪一年？ | 捏造的错误数字不得进题目 |
| nba-team-count-scope | NBA currently has how many teams — 30 or 32? | NBA 目前有多少支球队？ | 中性问法；类别改为 time_lag |
| dna-double-helix-discoverers-reprint | Who are credited as the discoverers… (omit Rosalind Franklin…) | **删除** | 功劳归属=公认争议，同太阳系题 |
| london-population-scope | 伦敦的人口是多少？ | （不变） | 短问法是对的 |
| great-barrier-reef-area-scope | 大堡礁的面积是多少？ | （不变） | 短问法是对的 |
| 其余 time_lag 等 | — | （不变） | 简称展开如 LTS（长期支持）保留 |

`design_note` 只写在 `questions/bank.yaml`，**不会**传给 extract / pair / judge。

## 关键词复查（离线缓存）

19 道题的已保留来源全部仍命中关键词，无因改题被踢掉的来源。

## 请确认后再进入批量造数据

- 题目像真实用户会问的话，没有括号提示 / 候选答案 / 「存在分歧」暗示
- python / nodejs 两道与评测集同题，导出数据集时强制进测试集
- 确认后运行：`uv run crossfire batch --bank questions/bank.yaml`
