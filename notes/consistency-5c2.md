# 5c-2 一致性实验

选中 8 道题：三类都有，中英文都有。

- Sonnet 自身一致率（batch+2 共 3 票 vs 多数票）：**99.1%**
- Haiku 自身一致率（3 票）：**97.4%**
- Haiku 多数票 vs Sonnet 多数票：**77.6%**（111/143）
- Sonnet 费用 $3.194；Haiku 费用 $1.745

## 混淆最多的类别对

### Sonnet（相对自己的多数票）
- agree → same_question_different_scope：3 次
- unrelated → agree：1 次

### Haiku
- contradict → same_question_different_scope：3 次
- agree → contradict：3 次
- agree → same_question_different_scope：2 次
- agree → unrelated：1 次
- contradict → agree：1 次

## 不是 3 票全一致的 Sonnet 配对

- [amazon-employee-count-scope] 多数 agree（2/3） 各次：['agree', 'same_question_different_scope', 'agree']
  - A: 截至2025年12月31日，亚马逊共有约1,576,000名全职和兼职员工。
  - B: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
- [amazon-employee-count-scope] 多数 unrelated（2/3） 各次：['unrelated', 'unrelated', 'agree']
  - A: 该网页未直接回答Amazon的员工总人数，但提及2024年报中Amazon的相关运营信息，未给出具体员工数字。
  - B: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
- [eiffel-tower-height] 多数 agree（2/3） 各次：['agree', 'same_question_different_scope', 'agree']
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 埃菲尔铁塔目前官方总高度为330米（1,083英尺），包含2022年3月新增的数字广播天线。
- [eiffel-tower-height] 多数 agree（2/3） 各次：['agree', 'agree', 'same_question_different_scope']
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 截至2026年，埃菲尔铁塔的官方高度为330米（含天线）。

## Haiku 与 Sonnet 多数票不一致

- [amazon-employee-count-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 截至2025年12月31日，亚马逊共有约1,576,000名全职和兼职员工。
  - B: 亚马逊是美国第二大私人雇主，并于2026年1月进行第二轮大规模裁员，裁减约16,000名企业员工。
- [amazon-employee-count-scope] Sonnet=agree Haiku=same_question_different_scope
  - A: 截至2025年12月31日，亚马逊共有约1,576,000名全职和兼职员工。
  - B: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
  - B: 亚马逊是美国第二大私人雇主，并于2026年1月进行第二轮大规模裁员，裁减约16,000名企业员工。
- [amazon-employee-count-scope] Sonnet=agree Haiku=contradict
  - A: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
  - B: 截至2025年12月31日，亚马逊全球共有1,576,000名全职和兼职员工。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 截至2025年12月31日，亚马逊全球共有1,576,000名全职和兼职员工。
  - B: 亚马逊是美国第二大私人雇主，并于2026年1月进行第二轮大规模裁员，裁减约16,000名企业员工。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=contradict
  - A: 该网页未直接回答Amazon的员工总人数，但提及2024年报中Amazon的相关运营信息，未给出具体员工数字。
  - B: 根据亚马逊最新年报，亚马逊目前雇用约1,556,000名全职和兼职员工。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=contradict
  - A: 该网页未直接回答Amazon的员工总人数，但提及2024年报中Amazon的相关运营信息，未给出具体员工数字。
  - B: 截至2025年12月31日，亚马逊共有约1,576,000名全职和兼职员工。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 该网页未直接回答Amazon的员工总人数，但提及2024年报中Amazon的相关运营信息，未给出具体员工数字。
  - B: 截至2024年12月31日，亚马逊共有约1,556,000名全职和兼职员工（不含独立承包商及季节性员工）。
- [amazon-employee-count-scope] Sonnet=unrelated Haiku=contradict
  - A: 该网页未直接回答Amazon的员工总人数，但提及2024年报中Amazon的相关运营信息，未给出具体员工数字。
  - B: 截至2025年12月31日，亚马逊全球共有1,576,000名全职和兼职员工。
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 截至2026年，埃菲尔铁塔的官方高度为330米（含天线）。
  - B: 埃菲尔铁塔目前的官方高度为330米。
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 埃菲尔铁塔目前官方总高度为330米（1,083英尺），包含2022年3月新增的数字广播天线。
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 埃菲尔铁塔目前的官方高度为330米。
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: The Eiffel Tower's official height is 330 metres.
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 截至2026年，埃菲尔铁塔的官方高度为330米（含天线）。
- [eiffel-tower-height] Sonnet=agree Haiku=same_question_different_scope
  - A: 根据该页面，埃菲尔铁塔的"到顶端"高度（包含天线等设备）为330米，而建筑高度（不含天线等设备）为300米。
  - B: 埃菲尔铁塔目前官方高度为330米（含天线），自2022年起生效。
- [london-population-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 该网页未提供伦敦的人口数据，仅涵盖英国整体及其组成国家（英格兰、威尔士、苏格兰、北爱尔兰）的人口估计。
  - B: 根据2021年人口普查，伦敦（大伦敦地区）的人口为8,799,800人。
- [london-population-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 该网页未提供伦敦的人口数据，仅涵盖英国整体及其组成国家（英格兰、威尔士、苏格兰、北爱尔兰）的人口估计。
  - B: 大伦敦（Greater London）2025年估计人口为9,122,909人。
- [london-population-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 该网页未提供伦敦的人口数据，仅涵盖英国整体及其组成国家（英格兰、威尔士、苏格兰、北爱尔兰）的人口估计。
  - B: 截至2025年中，伦敦（大伦敦）的人口约为910万，官方估计为9,122,909人。
- [london-population-scope] Sonnet=unrelated Haiku=same_question_different_scope
  - A: 截至2025年年中，伦敦的人口出现下降，降幅为0.29%，这是自2021年年中以来首次下降。
  - B: 根据2021年人口普查，伦敦（大伦敦地区）的人口为8,799,800人。
- [london-population-scope] Sonnet=agree Haiku=same_question_different_scope
  - A: 截至2025年年中，伦敦的人口出现下降，降幅为0.29%，这是自2021年年中以来首次下降。
  - B: 截至2025年中，伦敦（大伦敦）的人口约为910万，官方估计为9,122,909人。
- [marie-curie-birth-year-reprint] Sonnet=unrelated Haiku=agree
  - A: The page does not explicitly state the year Marie Curie was 
  - B: Marie Curie was born in 1867.
- [marie-curie-birth-year-reprint] Sonnet=agree Haiku=contradict
  - A: The page does not explicitly state the year Marie Curie was 
  - B: Marie Curie was born in 1867.
- [marie-curie-birth-year-reprint] Sonnet=unrelated Haiku=contradict
  - A: The page does not explicitly state the year Marie Curie was 
  - B: Marie Curie was born in 1867.
- [marie-curie-birth-year-reprint] Sonnet=agree Haiku=contradict
  - A: The page does not explicitly state the year Marie Curie was 
  - B: Marie Curie was born in 1867.
- [marie-curie-birth-year-reprint] Sonnet=agree Haiku=contradict
  - A: The page does not explicitly state the year Marie Curie was 
  - B: Marie Curie was born in 1867.
- [python-latest-stable] Sonnet=contradict Haiku=agree
  - A: 截至2026年10月（该文发布时），Python当前最新稳定版本号为3.15.0。
  - B: 截至该文发布时（2026年），Python 当前最新稳定版本号为 3.15，于 2026 年 10 月 9 日发布。
- [python-latest-stable] Sonnet=agree Haiku=contradict
  - A: Python 当前最新稳定版本号为 3.15.2
  - B: 截至该文发布时（2026年），Python 当前最新稳定版本号为 3.15，于 2026 年 10 月 9 日发布。
- [ubuntu-lts-version] Sonnet=contradict Haiku=agree
  - A: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04 LTS，代号"Resolute Rac
  - B: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04.1 LTS，代号"Resolute R
- [ubuntu-lts-version] Sonnet=agree Haiku=contradict
  - A: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04.1 LTS，代号"Resolute R
  - B: 目前最新的 Ubuntu LTS 版本是 26.04 LTS（Resolute Raccoon），于 2026 年 4 
- [ubuntu-lts-version] Sonnet=agree Haiku=contradict
  - A: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04.1 LTS，代号"Resolute R
  - B: 截至2026年8月（页面状态更新时），最新的Ubuntu LTS版本是Ubuntu 26.04 LTS（Resolute
- [ubuntu-lts-version] Sonnet=contradict Haiku=same_question_different_scope
  - A: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04.1 LTS，代号"Resolute R
  - B: 截至2026年4月24日（该文发布时），最新的Ubuntu LTS版本是Ubuntu 26.04 LTS，代号"Reso
- [ubuntu-lts-version] Sonnet=agree Haiku=same_question_different_scope
  - A: 截至2026年4月23日（该公告发布时），最新的Ubuntu LTS版本是Ubuntu 26.04，代号"Resolut
  - B: 截至该页面发布时，最新的 Ubuntu LTS 版本为 Ubuntu 26.04.1 LTS，代号"Resolute R

## 建议

建议：先别换 Haiku，跟 Sonnet 差得还多（跨模型 77.6%）。

## 花费（5c-2）

| 项目 | 费用 |
|---|---:|
| 批量 19 道（Sonnet extract/pair/judge） | $7.85 |
| 一致性 Sonnet ×2 | $3.19 |
| 一致性 Haiku ×3 | $1.75 |
| **合计** | **$12.79** |

批准上限 $13。5c-1 另约 $2，不计入本步。
