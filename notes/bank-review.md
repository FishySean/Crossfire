# 题库审查报告

生成日期（as_of）：2026-11-20
保留 15 道，丢弃 9 道。

> **不完整：跑到后半段 Anthropic 余额不足。**  
> 丢弃表里「SourceFinder 没有返回任何候选」的几道（尼罗河 + 全部 reprint_error）是余额耗尽后的假阴性，不是真的找不到来源。  
> **请充值后再跑一次 `uv run crossfire bank build`，以完整结果为准。** 本次产物仅供预览结构。


## 保留的题目

| id | 题目 | 类别 | 语言 | 可用 | primary | news | aggregator |
|---|---|---|---|---:|---:|---:|---:|
| nodejs-lts-version | Node.js 当前的 LTS（长期支持）稳定版本号是多少？ | time_lag | zh | 7 | 2 | 2 | 3 |
| python-latest-stable | Python 当前最新稳定版本号是多少？ | time_lag | zh | 8 | 3 | 2 | 3 |
| imf-world-gdp-rank-2024 | According to IMF data, which country has the largest GDP in the world? | time_lag | en | 6 | 0 | 3 | 3 |
| eiffel-tower-height | What is the current official height of the Eiffel Tower in meters? | time_lag | en | 7 | 1 | 3 | 3 |
| openai-ceo | Who is the current CEO of OpenAI? | time_lag | en | 5 | 0 | 2 | 3 |
| apple-ceo-current | 现任苹果公司（Apple Inc.）CEO 是谁？ | time_lag | zh | 6 | 2 | 1 | 3 |
| un-member-states-count | 联合国目前共有多少个成员国？ | time_lag | zh | 6 | 2 | 3 | 1 |
| world-tallest-building | What is currently the tallest building in the world? | time_lag | en | 7 | 2 | 2 | 3 |
| mysql-latest-ga | MySQL 当前最新 GA（正式发布）版本号是多少？ | time_lag | zh | 9 | 3 | 3 | 3 |
| ubuntu-lts-version | What is the most recent Ubuntu LTS release version? | time_lag | en | 8 | 3 | 2 | 3 |
| us-federal-minimum-wage | What is the current federal minimum wage in the United States (in USD per hour)? | time_lag | en | 8 | 2 | 3 | 3 |
| shanghai-population-scope | 上海的人口是多少？（常住人口 vs 户籍人口口径不同，数字有差异） | scope | zh | 5 | 1 | 2 | 2 |
| amazon-employee-count-scope | How many employees does Amazon have? (Note: full-time vs full-time-and-part-time figures differ significantly.) | scope | en | 8 | 2 | 3 | 3 |
| usa-land-area-scope | What is the total area of the United States in square kilometers? (Figures differ depending on whether inland water is included.) | scope | en | 6 | 2 | 1 | 3 |
| africa-country-count-scope | 非洲共有多少个国家？（不同口径：联合国承认 vs 非盟成员 vs 实际控制领土） | scope | zh | 6 | 1 | 2 | 3 |

## 丢弃的题目

| id | 题目 | 类别 | 原因 | 说明 |
|---|---|---|---|---|
| tokyo-population-scope | 东京的人口是多少？（请说明口径：都区部、东京都还是大东京都市圈） | scope | too_few_usable | 可用来源 3 个，少于 5 |
| great-wall-length-scope | 中国长城的长度是多少公里？（不同测量口径和朝代范围导致数字差异巨大） | scope | too_few_usable | 可用来源 4 个，少于 5 |
| apple-market-cap-scope | Apple's market capitalization varies depending on whether you use real-time price, closing price, or fully diluted shares. What figure does Apple's investor relations page cite? | scope | too_few_usable | 可用来源 3 个，少于 5 |
| nile-river-length-scope | 尼罗河的长度是多少公里？（不同测量起点导致数字从约 6650 km 到 6853 km 不等） | scope | too_few_usable | SourceFinder 没有返回任何候选 |
| bitcoin-creator-reprint | 比特币白皮书的作者署名是什么？（转载常误写为其他形式） | reprint_error | too_few_usable | SourceFinder 没有返回任何候选 |
| marie-curie-birth-year-reprint | Marie Curie's birth year is sometimes misprinted in secondary sources. What is her correct birth year? | reprint_error | too_few_usable | SourceFinder 没有返回任何候选 |
| titanic-sinking-year-reprint | 泰坦尼克号沉没于哪一年？（部分转载文章错误写为 1911 年） | reprint_error | too_few_usable | SourceFinder 没有返回任何候选 |
| dna-double-helix-discoverers-reprint | Who are credited as the discoverers of the DNA double helix structure? (Some reprintings omit Rosalind Franklin or misattribute the discovery.) | reprint_error | too_few_usable | SourceFinder 没有返回任何候选 |
| great-fire-of-london-year-reprint | 伦敦大火发生在哪一年？（部分转载误写为 1667 年） | reprint_error | too_few_usable | SourceFinder 没有返回任何候选 |

## 统计

- 按类别：{'time_lag': 11, 'scope': 4}
- 按语言：{'zh': 7, 'en': 8}
- 被过滤的页面：32 / 134（24%）
- 过滤原因：{'unusable_page': 20, 'fetch_failed': 6, 'keyword_miss': 6}

请确认：题目有确定答案、不是公认争议话题；来源层级有混搭；过滤比例可接受。
确认后再进入 5c-2。
