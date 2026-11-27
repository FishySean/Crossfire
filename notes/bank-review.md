# 题库审查报告

生成日期（as_of）：2026-11-27
保留 26 道，丢弃 28 道。
类别配额：{'time_lag': 9, 'scope': 16, 'reprint_error': 3}
未凑满：{'scope': 2}

## 保留的题目

| id | 题目 | 类别 | 语言 | 可用 | primary | news | aggregator |
|---|---|---|---|---:|---:|---:|---:|
| nodejs-lts-version | Node.js 当前的 LTS（长期支持）稳定版本号是多少？ | time_lag | zh | 7 | 2 | 2 | 3 |
| python-latest-stable | Python 当前最新稳定版本号是多少？ | time_lag | zh | 8 | 3 | 2 | 3 |
| eiffel-tower-height | What is the current official height of the Eiffel Tower in meters? | time_lag | en | 7 | 1 | 3 | 3 |
| apple-ceo-current | 现任苹果公司（Apple Inc.）CEO 是谁？ | time_lag | zh | 6 | 2 | 1 | 3 |
| un-member-states-count | 联合国目前共有多少个成员国？ | time_lag | zh | 6 | 2 | 3 | 1 |
| world-tallest-building | What is currently the tallest building in the world? | time_lag | en | 7 | 2 | 2 | 3 |
| mysql-latest-ga | MySQL 当前最新 GA（正式发布）版本号是多少？ | time_lag | zh | 9 | 3 | 3 | 3 |
| ubuntu-lts-version | What is the most recent Ubuntu LTS release version? | time_lag | en | 8 | 3 | 2 | 3 |
| shanghai-population-scope | 上海的人口是多少？ | scope | zh | 5 | 1 | 2 | 2 |
| amazon-employee-count-scope | How many employees does Amazon have? | scope | en | 8 | 2 | 3 | 3 |
| usa-land-area-scope | What is the total area of the United States in square kilometers? | scope | en | 6 | 2 | 1 | 3 |
| africa-country-count-scope | 非洲共有多少个国家？ | scope | zh | 6 | 1 | 2 | 3 |
| bitcoin-creator-reprint | 比特币白皮书的作者署名是什么？ | reprint_error | zh | 5 | 1 | 1 | 3 |
| marie-curie-birth-year-reprint | What year was Marie Curie born? | reprint_error | en | 7 | 3 | 2 | 2 |
| titanic-sinking-year-reprint | 泰坦尼克号沉没于哪一年？ | reprint_error | zh | 5 | 2 | 1 | 2 |
| london-population-scope | 伦敦的人口是多少？ | scope | zh | 5 | 2 | 0 | 3 |
| eu-member-states-scope | How many member states does the European Union have? | scope | en | 8 | 3 | 2 | 3 |
| nba-team-count-scope | NBA 目前有多少支球队？ | time_lag | zh | 6 | 1 | 2 | 3 |
| great-barrier-reef-area-scope | 大堡礁的面积是多少？ | scope | zh | 5 | 3 | 0 | 2 |
| great-lakes-area-scope | 北美五大湖的总面积是多少？ | scope | en | 5 | 1 | 2 | 2 |
| euro-zone-member-count-scope | 目前有多少个国家使用欧元作为官方货币？ | scope | en | 8 | 2 | 3 | 3 |
| us-gdp-scope | 美国GDP是多少？ | scope | zh | 8 | 2 | 3 | 3 |
| india-population-scope | India's current population is how much? | scope | en | 7 | 1 | 3 | 3 |
| us-national-park-count-scope | How many national parks does the United States have? | scope | en | 5 | 1 | 1 | 3 |
| amazon-river-basin-area-scope | 亚马孙河流域的面积是多少？ | scope | zh | 7 | 2 | 3 | 2 |
| us-hispanic-population-scope | How many Hispanic or Latino people live in the United States? | scope | en | 7 | 2 | 3 | 2 |

## 丢弃的题目

| id | 题目 | 类别 | 原因 | 说明 |
|---|---|---|---|---|
| imf-world-gdp-rank-2024 | According to IMF data, which country has the largest GDP in the world? | time_lag | no_primary | 一手来源 0 个，至少要 1 个 |
| openai-ceo | Who is the current CEO of OpenAI? | time_lag | no_primary | 一手来源 0 个，至少要 1 个 |
| us-federal-minimum-wage | What is the current federal minimum wage in the United States (in USD per hour)? | time_lag | too_few_usable | time_lag 已满配额 8，多出来的不保留 |
| tokyo-population-scope | 东京的人口是多少？（请说明口径：都区部、东京都还是大东京都市圈） | scope | too_few_usable | 可用来源 3 个，少于 5 |
| great-wall-length-scope | 中国长城的长度是多少公里？（不同测量口径和朝代范围导致数字差异巨大） | scope | too_few_usable | 可用来源 4 个，少于 5 |
| apple-market-cap-scope | Apple's market capitalization varies depending on whether you use real-time price, closing price, or fully diluted shares. What figure does Apple's investor relations page cite? | scope | too_few_usable | 可用来源 3 个，少于 5 |
| nile-river-length-scope | 尼罗河的长度是多少公里？（不同测量起点导致数字从约 6650 km 到 6853 km 不等） | scope | too_few_usable | 可用来源 1 个，少于 5 |
| china-gdp-scope | 中国2023年GDP总量是多少？ | scope | too_few_usable | 可用来源 4 个，少于 5 |
| amazon-revenue-scope | Amazon's annual revenue in 2023 was how much? | scope | too_few_usable | 可用来源 3 个，少于 5 |
| india-area-scope | 印度的国土面积是多少？ | scope | too_few_usable | 可用来源 3 个，少于 5 |
| new-york-city-population-scope | 纽约市的人口是多少？ | scope | too_few_usable | SourceFinder 没有返回任何候选 |
| australia-area-scope | 澳大利亚的国土面积是多少？ | scope | too_few_usable | 可用来源 2 个，少于 5 |
| beijing-population-scope | 北京市的人口是多少？（户籍人口与常住人口口径下数字不同） | scope | too_few_usable | 可用来源 4 个，少于 5 |
| amazon-river-length-scope | 亚马逊河的长度是多少？ | scope | too_few_usable | 可用来源 1 个，少于 5 |
| sahara-desert-area-scope | 撒哈拉沙漠的面积是多少？ | scope | too_few_usable | 可用来源 3 个，少于 5 |
| china-coastline-length-scope | 中国大陆海岸线有多长？ | scope | too_few_usable | 可用来源 4 个，少于 5 |
| russia-population-scope | 俄罗斯的人口是多少？ | scope | too_few_usable | 可用来源 0 个，少于 5 |
| antarctic-ice-sheet-area-scope | 南极洲的面积通常被引用为多少？ | scope | too_few_usable | 可用来源 2 个，少于 5 |
| mount-everest-height-scope | 珠穆朗玛峰的海拔高度是多少？ | scope | too_few_usable | 可用来源 4 个，少于 5 |
| us-national-debt-scope | 美国国家债务总额是多少？ | scope | too_few_usable | 可用来源 3 个，少于 5 |
| china-population-scope | 中国现在有多少人口？ | scope | too_few_usable | 可用来源 4 个，少于 5 |
| solar-system-planet-count-scope | 太阳系中有多少颗卫星？ | scope | too_few_usable | 可用来源 0 个，少于 5 |
| caspian-sea-area-scope | 里海的面积是多少？ | scope | too_few_usable | 可用来源 1 个，少于 5 |
| antarctica-area-scope | What is the total area of Antarctica? | scope | too_few_usable | 可用来源 4 个，少于 5 |
| los-angeles-population-scope | 洛杉矶的人口是多少？ | scope | too_few_usable | 可用来源 3 个，少于 5 |
| new-york-metro-population-scope | What is the population of New York City? | scope | too_few_usable | 可用来源 4 个，少于 5 |
| chicago-population-scope | 芝加哥的人口是多少？ | scope | too_few_usable | 可用来源 0 个，少于 5 |
| nile-amazon-longest-river-scope | What is the length of the Amazon River? | scope | too_few_usable | 可用来源 4 个，少于 5 |

## 统计

- 按类别：{'time_lag': 9, 'scope': 14, 'reprint_error': 3}
- 按语言：{'zh': 14, 'en': 12}
- 被过滤的页面：148 / 319（46%）
- 过滤原因：{'unusable_page': 38, 'fetch_failed': 59, 'keyword_miss': 51}
- 丢题原因：{'no_primary': 2, 'too_few_usable': 26}

请确认：题目有确定答案、不是公认争议话题；来源层级有混搭；每题至少 1 个 primary；过滤比例可接受。
确认后再进入 5c-2。
