# 重构待办

第 0 步写特征测试、第 1 步建 domain、第 2 步拆适配器时发现的问题。为了不在旧结构里修一遍、重构时再搬一遍，都推到对应的步骤修。
每条都是那一步的验收条件：那一步做完时，这里对应的条目必须已经划掉。修掉一条就用 ~~删除线~~ 划掉，并写上提交号。

锁住这些现状的测试带有「锁住现状」字样，修的时候连测试一起改。

---

## 第 2 步（ports + adapters）

### ~~`run()` 不校验 `mode`~~ 已修，f3a0d8b

- **现象**：`mode` 除了 `"cached"` 以外的任何字符串都按 live 跑，并把这个非法值原样写进结果文件。只有 web 端点在入口处校验过。
- **影响**：命令行或脚本里把 `cached` 拼错，会悄悄真跑一遍，烧掉 Steel 额度和 Claude 调用。
- **怎么修**：`domain.Mode` 已经有了，入口处转成 `Mode`，不认识的值直接报错。
- **锁住它的测试**：`test_pipeline_contract.py::test_mode_selects_cache[bogus-False]`
- **修法**：`run()` 只接受 `Mode`，传字符串直接报 `TypeError`。命令行和 web 端点在入口处做 `Mode(...)` 转换，web 遇到非法值返回 400。现在由 `test_run_rejects_a_plain_string_mode` 锁住。

### ~~judge 把数组编码成字符串返回，前端静默丢掉冲突列表~~ 已修，f37c347

- **现象**：`out/runs/tokyo-population_20260912T224644Z.json` 里，`judgment.conflicts` 是一个 JSON 字符串 `'["【口径差异…", …]'`，而不是数组。`llm.py` 不按 schema 校验工具返回值，`reconcile.judge` 原样存了下来。
- **影响**：前端用 `Array.isArray` 保护，不崩溃，但「记录在案的冲突」整段静默消失，没有任何提示。违反「失败必须大声」。同样的问题理论上可能出现在任何数组字段和枚举字段上（比如 `relation` 不在四个值里）。
- **怎么修**：LLM adapter 返回前按 schema 校验，不合格的按现有失败路径重试或记成 `_failure`。domain 这一侧已经拦住了：`Judgment.from_dict` 遇到非数组直接报 `TypeError`，`Pair.from_dict` 遇到未知 relation 报 `ValueError`。
- **修法**：Claude 适配器拿到工具返回值后，一律交给 domain 实体的 `from_dict` 严格转换，转换失败算一次结构化失败。它会带着失败原因重问一次，仍然失败就返回带 failure 的实体，并在 stderr 打 ❌。数组元素不是字符串、relation 不在四个值里，也走同一条路径。由 `test_claude_adapters.py` 锁住。
- **还没修的部分**：已经写在磁盘上的那个 tokyo 文件，见第 4 步的迁移脚本。

---

## 第 3 步（use case）

### ~~【最高优先级】抓取失败不进 `failures`~~ 已修，770f4c4

- **现象**：页面抓取失败只发一条 `error` 事件，不会进结果里的 `failures` 数组。`failures` 只收 LLM 的失败。
- **影响**：8 个来源挂了 3 个，结果文件里写的是 `pages_failed: 3, failures: []`，命令行末尾那条 ⚠️ 警告也不会出现。**哪怕所有页面全挂了，也不会有任何警告。** 这直接违反了这个项目的核心原则「失败必须大声」。当初就是因为一条矛盾被静默吞掉，才定下了这条原则。
- **修法**：`RunResult.failures` 把每个 `ok=False` 的页面算成 `Failure(step="fetch", detail=页面的 error, raw=None)`，排在 LLM 失败前面。命令行末尾的警告改成「本次有 N 处失败」。前端历史结果的失败横幅本来就渲染 `run.failures`，不用改就能显示（显示得不好看，见第 7 步）。
- **锁住它的测试**：`test_verify_question.py::test_eight_sources_three_fetch_failures_give_exactly_three_fetch_failures`、`test_all_pages_failing_is_still_loud`，以及有意改写的 `test_pipeline_contract.py::test_claim_index_is_the_source_index_not_the_claim_count`、`test_domain.py::test_failures_include_fetch_failures`。

### ~~`claude_calls` 少算重试~~ 已修，770f4c4

- **现象**：`claude_calls` 固定等于「主张数 + 配对数 + 1」。结构化解析失败的重试（`MAX_ATTEMPTS`）和网络超时的重试（`NETWORK_RETRIES`）都不计入。可 token 用量是把每次重试都累加进去的。
- **修法**：`Usage` 加 `requests`，`ClaudeClient` 数真正调用 `messages.create` 的次数，两层重试都算。`claude_calls` 改成汇总各记录的 `usage.requests`。`steps.*.calls` 含义不变（记录条数），LLM 步骤另加一个 `requests` 键。现有键一个没改。
- **还没修的部分**：见第 5 步「比对抛异常时请求数记成 0」和第 4 步「旧结果文件迁移」里新增的 `requests` 问题。

### ~~返回值比磁盘文件多一个 `output_path` 键~~ 已修，770f4c4

- **修法**：`VerifyQuestion.execute` 返回的 `RunResult` 与磁盘内容一致（`test_verify_question.py` 锁住），保存位置由 `RunRepository.save` 返回，随 `done` 事件的 `run_file` 发出。
- **还没修的部分**：兼容门面 `pipeline.run` 为了让命令行不改，返回的 dict 里仍然附带 `output_path`。第 4 步入口直接调用 use case、门面删除时自然消失。

### ~~`from_dict` 不校验标量字段的类型~~ 已修，770f4c4

- **修法**：所有 `from_dict` 校验标量类型，不做转换。`confidence` 是 `"0.9"` 或 `true` 都报 `TypeError`，模型输出因此走重试路径。整数被当作数字接受，因为真实结果文件里有 `confidence: 1`。
- **没做的部分**：`published_date` 只校验是字符串，没有校验 YYYY-MM-DD 格式。格式不对时模型多半返回的是 `2024-10` 这样的部分日期，严格校验只会多烧重试，所以没做。

### ~~`mode` 和实际注入的 fetcher 可能对不上~~ 已修，53ab6d5（端口）和本步的兼容门面提交

- **现象**：依赖注入之后，`run()` 里的 `mode` 只是写进结果文件的一个标签，真正决定读缓存还是实时抓取的是注入的 fetcher。`run(mode=Mode.CACHED)` 配上 `SteelPageFetcher` 也能跑，结果文件会把一次实时抓取记成 cached。
- **修法**：`PageFetcher` 端口加了 `mode` 属性，use case 从 fetcher 读，不再单独接收 mode。兼容门面为了让命令行和 web 不改，仍接受 `mode` 参数，但与 fetcher 不一致就报 `ValueError`。

### ~~结果文件名只精确到秒~~ 已修，770f4c4

- **现象**：文件名是 `{question_id}_{%Y%m%dT%H%M%SZ}.json`，同一题同一秒跑两次，后一次覆盖前一次。
- **修法**：文件名格式不变，撞名时依次加 `_2`、`_3` 后缀。用 `"x"` 模式独占创建临时文件来占名字，两个进程同时存也不会互相覆盖。没有改用毫秒或微秒：精度再细也只是让撞车变少，不能保证不撞。

---

## 第 4 步（组合根 + 入口适配）

### ~~`usable` 没人读~~ 已修，1cde97a

- **现象**：`steel_client` 给每个页面算了 `usable` / `unusable_reason`，但 pipeline 从来不看。`ok=True` 的骨架页照样送进 extract。
- **修法**：`Page.usable` 是现算的属性，不存。不可用的页面不提取，`failures` 里记 `step="usability"`、`detail` 是原因；事件流里 `fetch_done` 报 `ok=false`，紧跟一条 `step="usability"` 的 `error`。前端收到 `ok=false` 本来就把卡片画成终态，`web/static/` 没改。
- 锁住旧行为的 `test_unusable_pages_still_go_to_extract` 改成了 `test_unusable_pages_are_not_extracted`。

### ~~可用性判定的误杀~~ 已修，7f9b0e4

- **标题**：不再按子串匹配。标题按 ` | `、` - `、` – `、`: ` 等分隔符切段，某一段规范化后（小写、标点变空格）**整段**是状态码（403/404）、错误短语，或「码 + 短语」才算错误标题。
- **中文行长**：正文的两个门槛改按显示宽度算，汉字、假名、全角标点算 2。阈值常量没动。
- **500–599 字纯文本页**：链接以外的文字加起来都够不到正文下限时，原因是 `too_short`。链接占比过高的仍先判 `nav_skeleton`。
- **验证**：72 个真实页面（缓存、快照、历史结果里的页面去重）新旧规则判定完全一致；`demo.yaml` 的来源全部可用。

### ~~读 `.env` 的地方分散~~ 已修，73dcc92 / ed0eeb0

- 只有 `crossfire/config.py` 读 `.env` 和环境变量，`tests/test_architecture.py` 扫全仓库强制。`legacy.py` 和 `_wiring.py` 删了。

### ~~旧结果文件迁移~~ 已做：`scripts/migrate_runs.py`（第 4 步第 8 个提交）

- **做法**：默认演练、`--apply` 才写，写之前整目录备份到 `runs.bak-<时间戳>/`，可以重复跑。补 `mode`、补 `requests`、把 `conflicts` 字符串解析回数组。
- **`requests` 的决定（第 4 步定）**：`Usage.requests` 和 `StepStats.requests` 改为 `int | None`，`None` 表示「当时没有记录」。`from_dict` 仍要求**键必须在**，迁移脚本显式写 `"requests": null`。
  - **为什么不按每条 1 次补**：那是编出来的数。旧文件没记录过重试，真实请求数无从得知，写 1 会让成本统计偏低还看不出来；迁移只写事实。
  - **为什么键仍必填**：「读取一律从严」不变。缺键说明文件没迁移过或者是坏的，应该报错；`null` 是迁移脚本有意写下的「未知」，两者要分得开。
  - **为什么总数也是 None**：`model_requests` 只要有一条记录是 `None` 就返回 `None`。把未知当 0 加进去，总数偏小还看不出来。迁移时这类文件顶层的 `claude_calls` 也写成 `null`：旧值本来就没算重试（第 3 步的「claude_calls 少算重试」），留着会和逐条记录对不上。
- **`conflicts` 的意外**：`tokyo-population_20260912T224644Z.json` 的字符串不是合法 JSON，条目里的 `"东京"`、`"当前"` 引号没转义。迁移按 `["…", "…"]` 的外形在 `", "` 处切开，得到 3 条，演练输出里逐条列出供核对；切不开或切出空条目就拒绝迁移这个文件。
- **验收**：在 `out/runs/` 的副本上 `--apply` 后 25 个文件全部能被 `RunResult.from_dict` 读回来，第二次 `--apply` 什么都不改。真实目录还没有 apply，等你确认演练输出。

### ~~早期结果文件没有 `mode` 键~~ 已做，见上面的「旧结果文件迁移」

### 总长下限仍按原始字符数（第 4 步新发现，未排期）

- **现象**：`MIN_CONTENT_CHARS=500` 按原始字符数算，没有像正文门槛那样改按宽度。300 个汉字的页面信息量约等于 600 个英文字符，仍被判 `too_short`。
- **锁住它的测试**：`test_domain.py::test_locked_total_length_floor_still_counts_raw_characters`
- **为什么没顺手修**：这一步只要求修行长；现有真实页面里没有碰到。扩到中文数据集之前要决定。

### `make_sample_runs.py` 写的是旧格式（第 4 步新发现）

- **现象**：它往 `out/runs/` 写带 `parse_error` 键的旧格式样例，这些文件既读不进 `RunResult`，迁移脚本也迁不了（会报告为有问题，不写）。
- **建议**：改成用 `RunResult` 生成，或者写到单独的目录。没有真实结果时才需要它，所以不急。

---

## 第 5 步（成本基准）

### 比对抛异常时请求数记成 0（第 3 步新发现）

- **现象**：端口约定 `pair_all` 不抛异常，所以 Claude 比对器把调用里抛出的异常（网络重试用尽、鉴权失败）转成带 failure 的 Pair。异常带不出已经发出去的请求数，这一对的 `usage.requests` 只能记 0。网络重试用尽时其实发了 3 次。
- **影响**：只在比对整对抛异常时少算，`claude_calls` 偏低。正常的结构化重试不受影响。
- **怎么修**：让 `ClaudeClient` 抛出的异常带上已发请求数，或者 client 在异常路径也返回 `Structured`。第 5 步做成本基准之前必须修。

---

## 第 7 步（前端对接整理）

### 前端分不清「提取失败」和「这页没回答问题」

- **现象**：两种情况下 `claim_done.claim` 都是 `null`。提取失败时会另外发一条 `error` 事件，但卡片本身看不出区别。
- **影响**：用户会把一次失败的调用看成「这个来源没有立场」。
- **锁住它的测试**：`test_domain.py::test_unanswered_and_failed_claims_look_the_same_except_for_failure`

### 前端遇到 `conflicts` 不是数组时静默隐藏整个冲突区

- **现象**：`web/static/app.js` 用 `Array.isArray(judgment.conflicts)` 做保护，类型不对时整段「记录在案的冲突」直接不渲染，没有任何提示。
- **影响**：后端已经从源头堵住了（见第 2 步），但前端还会读历史结果文件，任何一个坏文件都会让冲突静默消失。违反「失败必须大声」。
- **怎么修**：类型不对时显示一条警告，说明这次运行的冲突列表格式损坏，而不是隐藏。`trusted_sources` 同理。

### 不可用页面的卡片标签写的是「抓取失败」（第 4 步新发现）

- **现象**：为了不改前端，不可用页面的 `fetch_done` 报 `ok=false`，实时视图的卡片因此贴「抓取失败」，其实页面抓到了，只是内容不可用；具体原因只在失败横幅里（`[usability] too_short`）。历史视图里这类卡片显示「未给出主张」，也看不出是被跳过的。
- **怎么修**：`fetch_done` 加一个 `unusable_reason` 字段（或者单独的事件），前端据此显示「内容不可用：导航骨架页」之类。要改事件契约和 `web/static/`，所以放第 7 步。

### 批量推理时进度是一阵一阵到的：已知现象，不要修

- **现象**：比对换成 GPU 上的 NLI 模型批量推理之后，`pair_done` 会在一批算完时一口气全部到达，而不是一个一个来。Claude 比对器并发发请求时也有类似的成簇现象。
- **决定**：前端照实显示，**不要伪造平滑的进度**（比如把一批事件拆开、按定时器逐个放出来）。跟心跳的原则一样：进度事件只报告真实发生的事。

### 历史结果的失败横幅把 `failures` 的元素整个 JSON 打印出来（第 3 步发现）

- **现象**：`web/static/app.js` 的 `renderFailures` 按 `stage` / `url` / `error` / `message` 取字段，而结果文件里的失败是 `{step, detail, raw}`，一个都对不上，于是退回 `JSON.stringify(failure)`。LLM 失败会把整段 `raw` 原始响应打出来；第 3 步起抓取失败也进 `failures`，显示成 `{"step":"fetch","detail":"…","raw":null}`。
- **影响**：失败能看到，不会被静默丢掉，但很难读。横幅标题「N 次调用失败」也没有区分抓取失败和调用失败。
- **怎么修**：按 `step` 和 `detail` 渲染，`raw` 折叠起来。

