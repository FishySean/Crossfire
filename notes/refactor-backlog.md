# 重构待办

第 0 步写特征测试、第 1 步建 domain 时发现的问题。为了不在旧结构里修一遍、重构时再搬一遍，都推到对应的步骤修。
每条都是那一步的验收条件：那一步做完时，这里对应的条目必须已经划掉。修掉一条就用 ~~删除线~~ 划掉，并写上提交号。

锁住这些现状的测试带有「锁住现状」字样，修的时候连测试一起改。

---

## 第 2 步（ports + adapters）

### `run()` 不校验 `mode`

- **现象**：`mode` 除了 `"cached"` 以外的任何字符串都按 live 跑，并把这个非法值原样写进结果文件。只有 web 端点在入口处校验过。
- **影响**：命令行或脚本里把 `cached` 拼错，会悄悄真跑一遍，烧掉 Steel 额度和 Claude 调用。
- **怎么修**：`domain.Mode` 已经有了，入口处转成 `Mode`，不认识的值直接报错。
- **锁住它的测试**：`test_pipeline_contract.py::test_mode_selects_cache[bogus-False]`

### judge 把数组编码成字符串返回，前端静默丢掉冲突列表（第 1 步新发现，挂靠步骤待确认）

- **现象**：`out/runs/tokyo-population_20260912T224644Z.json` 里，`judgment.conflicts` 是一个 JSON 字符串 `'["【口径差异…", …]'`，而不是数组。`llm.py` 不按 schema 校验工具返回值，`reconcile.judge` 原样存了下来。
- **影响**：前端用 `Array.isArray` 保护，不崩溃，但「记录在案的冲突」整段静默消失，没有任何提示。违反「失败必须大声」。同样的问题理论上可能出现在任何数组字段和枚举字段上（比如 `relation` 不在四个值里）。
- **怎么修**：LLM adapter 返回前按 schema 校验，不合格的按现有失败路径重试或记成 `_failure`。domain 这一侧已经拦住了：`Judgment.from_dict` 遇到非数组直接报 `TypeError`，`Pair.from_dict` 遇到未知 relation 报 `ValueError`。
- **为什么建议第 2 步**：校验应该在 LLM adapter 里做，第 2 步正好重写它。

---

## 第 3 步（use case）

### 【最高优先级】抓取失败不进 `failures`

- **现象**：页面抓取失败只发一条 `error` 事件，不会进结果里的 `failures` 数组。`failures` 只收 LLM 的失败。
- **影响**：8 个来源挂了 3 个，结果文件里写的是 `pages_failed: 3, failures: []`，命令行末尾那条 ⚠️ 警告也不会出现。**哪怕所有页面全挂了，也不会有任何警告。** 这直接违反了这个项目的核心原则「失败必须大声」。当初就是因为一条矛盾被静默吞掉，才定下了这条原则。
- **怎么修**：`RunResult.failures` 把抓取失败算进去（那里写了只改那一处），`Failure.step` 为 `"fetch"`。
- **锁住它的测试**：`test_pipeline_contract.py::test_claim_index_is_the_source_index_not_the_claim_count`（断言了 `failures == []`）、`test_domain.py::test_locked_failures_exclude_fetch_failures`

### `claude_calls` 少算重试

- **现象**：`claude_calls` 固定等于「主张数 + 配对数 + 1」。结构化解析失败的重试（`MAX_ATTEMPTS`）和网络超时的重试（`NETWORK_RETRIES`）都不计入。可 token 用量是把每次重试都累加进去的。
- **影响**：发生重试时，调用次数和 token 数对不上，成本基准（第 5 步）会偏低。`steps.*.calls` 的含义也一样：它数的是记录条数，不是请求数。
- **怎么修**：LLM adapter 报告实际发出的请求数，`RunResult.claude_calls` 改成汇总它。
- **锁住它的测试**：`test_pipeline_contract.py::test_accounting`、`test_domain.py::test_locked_claude_calls_ignores_retries`

### 返回值比磁盘文件多一个 `output_path` 键

- **现象**：`output_path` 是在写完文件之后才加进返回 dict 的，所以返回值比磁盘上的 JSON 多一个键。
- **影响**：拿返回值和读回的文件做比较的代码会对不上。`RunResult` 实体里没有这个字段。
- **锁住它的测试**：`test_pipeline_contract.py::test_result_file_structure_and_atomic_write`

---

## 第 4 步（组合根 + 入口适配）

### `usable` 没人读

- **现象**：`steel_client` 给每个页面算了 `usable` / `unusable_reason`，但 pipeline 从来不看。`ok=True` 的骨架页照样送进 extract。
- **影响**：废页的主张会进入比对和判决，白花调用，还可能污染结论。
- **锁住它的测试**：`test_pipeline_contract.py::test_unusable_pages_still_go_to_extract`
- **注意**：接上之前必须先处理下面那条，否则会开始静默丢掉真实来源。

### 可用性判定的误杀（第 1 步新发现，挂靠步骤待确认）

`usable` 现在没人读，所以这些都还没造成伤害。一旦接上，它们就会**把真实来源当废页丢掉**。

- **标题按子串匹配**：标题里含 `403`、`404`、`not found` 的正常文章都会被判成 `error_page_title`，比如「403(b) retirement plan limits」「Highway 404 closure」。
- **中文短段落被判为骨架**：「一行至少 60 字符才算正文」是按英文定的。每行 30 个汉字（一个完整的中文句子）、总共 1200 字的页面会被判为 `nav_skeleton`。
- **500–599 字的纯文本页原因标错**：零链接的页面被判为 `nav_skeleton`（导航骨架），而不是 `too_short`。`MIN_PROSE_CHARS=600` 比 `MIN_CONTENT_CHARS=500` 更严，`too_short` 实际只对 500 字以下生效。
- **为什么建议第 4 步**：它是「`usable` 没人读」的前置条件，必须在同一步、接线之前修。
- **锁住它的测试**：`test_domain.py` 里三条 `test_locked_*`。
- 现有 142 个真实页面里只有 space.com 被判为废页，判得对。所以演示阶段碰不到这些，扩到数据集规模时一定会碰到。

### 结果文件名只精确到秒

- **现象**：文件名是 `{question_id}_{%Y%m%dT%H%M%SZ}.json`。
- **影响**：同一题在同一秒内跑两次，后一次覆盖前一次。演示碰不到；第 5 步批量造数据集时一定会碰到。

### 早期结果文件没有 `mode` 键（第 1 步新发现，挂靠步骤待确认）

- **现象**：本地 22 个结果文件里有 4 个（2026-09-12 20:18 到 20:53 之间写的）没有 `mode`，因为那时还没有 cached 模式。`RunResult.from_dict` 按规则直接报错。
- **影响**：第 4 步如果让 web 的 `/api/runs/{name}` 改走 `RunResult`，这 4 个历史结果会打不开。
- **要决定的**：补默认值 `live`（那时只有 live，这是事实而不是猜测）、迁移这 4 个文件，还是删掉。

---

## 第 7 步（前端对接整理）

### 前端分不清「提取失败」和「这页没回答问题」

- **现象**：两种情况下 `claim_done.claim` 都是 `null`。提取失败时会另外发一条 `error` 事件，但卡片本身看不出区别。
- **影响**：用户会把一次失败的调用看成「这个来源没有立场」。
- **锁住它的测试**：`test_domain.py::test_unanswered_and_failed_claims_look_the_same_except_for_failure`
