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

### ~~总长下限仍按原始字符数~~ 第 5a 步已修，d0fe315

- **现象**：`MIN_CONTENT_CHARS=500` 按原始字符数算，没有像正文门槛那样改按宽度。300 个汉字的页面信息量约等于 600 个英文字符，仍被判 `too_short`。
- **修法**：改按显示宽度。锁住旧行为的 `test_locked_total_length_floor_still_counts_raw_characters` 改成了 `test_total_length_floor_counts_display_width`，另加一条 240 个汉字仍判 `too_short` 的测试。200 个真实页面（缓存、夹具、评测快照、历史结果）判定前后完全一致。

### ~~`make_sample_runs.py` 写的是旧格式~~ 第 5a 步已修，5991f30

- **现象**：它往 `out/runs/` 写带 `parse_error` 键的旧格式样例，这些文件既读不进 `RunResult`，迁移脚本也迁不了（会报告为有问题，不写）。
- **修法**：用 domain 实体生成、`run_record` 写出，`tests/test_make_sample_runs.py` 锁住能原样读回。加了 `--out`。
- **注意**：`out/runs/python-latest-version_20260912T201818Z.json` 就是这个脚本以前生成的样例，混在真实历史里，名字看不出来。没有动它。

---

## 第 5 步（成本基准）

### ~~比对抛异常时请求数记成 0~~ 第 5b 步已修，9093f73

- **修法**：`ClaudeCallError` 带着抛出前已发的请求数和 token；比对器接住后写进 Pair.usage。

### ~~网页内容变新后，提取和判决都会答错~~ 第 5a 步已修，d0d86e0 / 03ab9f1 / 5c6dfe4（第 4 步 live 运行发现）

- **诊断**：不是截断、不是表格难读、也不是 bugfix/security 定义含糊（devguide 页面自己写了 bugfix 即 stable）。模型不知道今天是哪天，把比它知识新的版本当成错误：judge 原话「截至 2024 年底，Python 才刚发布 3.13……3.15.2 极有可能是预发布版」。提取器另有两个问题：claim 和自己引用的 evidence 矛盾（引 `| 3.13 | … | security |` 却说 3.13 是最新稳定版）；把 2024 年的 RealPython 文章改写成「目前最新」。
- **修法**：页面记 `fetched_at`；`as_of` 显式传给提取和判决（live 是当天，cached 和评测是快照日期）；judge 加「一手来源优先于自己的知识、反驳必须引原文」；提取加「按页面定义、claim 与 evidence 一致、保留来源的时间口径」。结果文件加 `as_of` 和 `provenance`。
- **回归**：`evals/` 四道题，修复前 python-2026-11 三次只对一次，修复后四道题（含两道各重复 3 次）全部通过。
- **剩下的问题**：见下一节。

原始记录：

- **现象**：`python-latest-version_20261119T230333Z.json` 是 live 模式跑的，4 页都抓到且可用，结论却是 3.13.x、置信度 0.72，正确答案是 3.15.2。Python 3.15 已于 2026-10-09 正式发布，下载页显示 3.15.2，devguide 版本表里 3.15 是 bugfix、3.13 是 security。
  - **提取**：devguide 表格里明明列着 3.15 bugfix，提取器却得出"最新稳定版是 3.13"。
  - **判决**：以"3.15.2 超出已知的发布序列"为理由，否掉了一手官方来源，信了模型自己的先验。
- **为什么 cached 没暴露**：`out/cache` 是 9 月的快照，那时 3.15 还是 prerelease，同一条代码路径答 3.14.7 是对的。
- **影响**：第 5 步要用 Claude 的输出当训练标签。只要网页比模型的知识新，标签本身就是错的，而且置信度不低，噪声不容易被发现。
- **造标签之前必须做**：
  1. 用这次的 live 页面做一组回归用例（存成测试快照），对照提取结果。
  2. 判决 prompt 里讲明：一手来源的明确数据优先于模型自己的知识。
  3. 抽查标签时专门挑"页面比模型训练截止日期新"的问题。

### 第 5a 步留下的问题（造标签之前要看）

### ~~判决「一手来源优先」那段规则的对照实验~~ 第 5b 步已做，4e7eaf6

- **做法**：judge-python-2026-11 冻结修复前 3 次的 claims/pairs；有那段规则和删掉那段各判 3 次。
- **结果**：两边都是 3/3 通过。有了明确的 as_of 之后，判决靠「官方下载页 + 时效」就能采信 3.15.2，这段规则没有改变结果。
- **决定**：保留，当第二道防线。当初答错发生在模型不知道日期的时候；这段只多几十个 token。依据写在 `JUDGE_PROMPT` 旁边的注释里。



- **devguide 提取仍然一半挑错行**：修复后的 6 次 python-2026-11 运行里，devguide 的 claim 有 3 次说「bugfix 阶段最新的是 3.14」（3.15 也是 bugfix，首发更晚）。最终答案没错，是因为下载页直接写着 3.15.2、judge 采信了它。作为训练标签，这些单条 claim 是错的。
- **judge 把数组编码成字符串仍然会发生**：第 5b 全量评测里又出现了 4 次，都靠重试救回来。第 2 步只是让它大声失败，没有消除。
- ~~**pairer prompt 里没有日期**~~ 第 5b 步已修，55f9b22。
- ~~**everest、solar-system 的缓存没有 `fetched_at`**~~ 第 5b 步：everest 题已删（aad1277）；solar-system 已重新 prefetch 并带上 `fetched_at`；cached 模式下 as_of 为空直接拒绝（6f851a2）。
- **补上的 `fetched_at` 是上界**：python、nodejs、tokyo 的缓存时间取的是第一次用到这份内容（markdown 逐字相同）的 cached 运行的开始时间，真实抓取只会更早，但不早于首个提交 2026-09-12T18:49:03Z。同一天内，日期不受影响。
- **`leads_with` 是启发式**：答案先讲背景、后给结论会被误判没通过。目前真实回答都是结论先行。
- **东京的标准答案有两个官方数**：2026 年 8 月推计 14,303,513 和 2025 年国势调查速报 14,246,219，判分接受 1,420 万到 1,440 万之间的任何数。
- **评测的预计请求数不含重试**：第 5b 全量预计最多 135 次，实际 139 次。
- ~~**`out/runs` 还没迁到带 `as_of`/`provenance` 的格式**~~ 第 5b 步已 `--apply`（备份 `out/runs.bak-20261120T021133Z`），28 个文件全部补了两个 null，包括 220214Z。

---

## 第 5a / 5c-2 副作用：提取把 as_of 填进 published_date

- **现象**：EXTRACT_PROMPT 告知「今天的日期：{as_of}」后，页面无发布日时模型常把 as_of 填进 `published_date`。5c-2 题库里 13 条等于 2026-11-20 的日期，核对缓存后 12 条为编造（多维基/ESPN），牵连 62 对标签。
- **影响**：比对把旧文当成「今天发布」，时间差判断失真；只改日期不重判会导致输入与标签不一致。
- **修法**：prompt 禁止用 as_of 代替；`scrub_as_of_published_date` 在 extract 后核对原文，找不到则改 null 并警告；受影响配对重跑比对。测试：`tests/test_published_dates.py`。

## 第 7b 步：`published_date` / `content_date` 拆分

- **原因**：收紧 `published_date` 后，realpython 等页的「内容时间点」丢了；训练集却是在收紧前造的 → train/serve skew。
- **规则**：`published_date` = 页面元数据式发布/更新日；`content_date` + `content_date_evidence` = 主张所述时间点。两者都 scrub as_of。
- **NLI**：`encoding.effective_date`：有 published 用 published，否则 content_date；训练/推理共用 `encode_pair`。

## 训练后错误分析：contradict 是否被 mysql 模式主导

- **现象**：训练集里约六成 `contradict` 来自 `mysql-latest-ga` 一道题（19/34）。MySQL 有 Innovation / LTS 两条并行版本线，很多「数字冲突」更接近口径不同，而不是同一事实上的真矛盾。
- **风险**：微调后模型对 contradict 的内部图像，可能主要是「两个版本号互相打架」，迁移到员工数、球队数等真矛盾时会偏。
- **待做**：完整训练结束后做错误分析时，按题目拆开看 contradict 的 precision/recall；专门抽查非 mysql 的矛盾对，确认不是只会抄 mysql 的样子。验证集选型已改为少挪走难题，mysql 留在训练集里——这更要求事后检查。

---

## 第 5c-1 步（自动找来源、建题库）

- SourceFinder 端口 + Claude web_search 适配器；BuildQuestionBank；`crossfire bank build`。
- 试点曾因 Anthropic 余额中途不足而不完整；已改断点续跑，中断标 `interrupted`，与真丢弃分开。
- Steel 免费额度按首次 session 2026-09-12 推算约 **2026-12-11** 到期。

### 第四次静默失败（共同模式）

错误发生时被当成「正常的空结果」处理了：

1. 解析失败被吞掉（第 2 步前）
2. 抓取失败不进 `failures`（第 3 步修）
3. `conflicts` 格式坏了被前端隐藏（第 2/7 步）
4. **题库找来源：余额不足时 SourceFinder 返回空列表，题目被记成「找不到来源」悄悄丢掉**（第 5c-1 修：立刻抛错停下；进度里标 `interrupted`）

以后新写的代码，遇到「空结果」都要检查：它到底是真的没有，还是出错了。

## 第 5c 步（批量跑题、导出数据集）

### 比对标签稳定性（从 5b 推迟过来，造数据之前必须先做）

- **目的**：测 Claude 对同一对句子反复判断时的一致率。这是之后训练小模型时准确率的天花板；同时决定比对步骤用 Sonnet 还是换成 Haiku。
- **为什么推迟**：5b 时只有 4 道题的主张，代表性不够。5c 会批量跑很多新题，在那批数据上测更准。命令 `crossfire consistency` 已经写好（fcc37e2），冻结输入在 `evals/consistency_inputs/`。
- **必须在批量造训练数据之前完成**，否则造出来的标签不知道噪声有多大。

---

## 第 7 步（前端对接整理）

### ~~前端分不清「提取失败」和「这页没回答问题」~~ 已修

- **修法**：`claim_done` 新增 `failed`；前端卡片分别显示「提取失败」和「未给出主张」。domain 层现状测试仍锁住（只能靠 failure 区分），前端用事件/结果里的 failure 展示。

### ~~前端遇到 `conflicts` 不是数组时静默隐藏整个冲突区~~ 已修

- **修法**：非数组时显示格式警告；`trusted_sources` 同理。

### ~~不可用页面的卡片标签写的是「抓取失败」~~ 已修

- **修法**：`fetch_done` 新增 `unusable_reason`；前端显示「内容不可用：&lt;原因&gt;」。

### 批量推理时进度是一阵一阵到的：已知现象，不要修

- **现象**：比对换成 GPU 上的 NLI 模型批量推理之后，`pair_done` 会在一批算完时一口气全部到达，而不是一个一个来。Claude 比对器并发发请求时也有类似的成簇现象。
- **决定**：前端照实显示，**不要伪造平滑的进度**（比如把一批事件拆开、按定时器逐个放出来）。跟心跳的原则一样：进度事件只报告真实发生的事。已确认没有伪造平滑进度的代码。

### ~~历史结果的失败横幅把 `failures` 的元素整个 JSON 打印出来~~ 已修

- **修法**：按 `step` / `detail` 渲染，`raw` 默认折叠；标题区分抓取 / 内容不可用 / 模型调用次数。

---

## 模型迭代（延后）

第一个模型（seed 44，测试宏平均 F1 0.614；三种子均值 0.576）已当作「达到要求」接进流水线。下面实验**软件做完后再做**；一次只改一样东西。

- 种子 42、44 的验证损失在第 12 轮还在创新低，`max_epochs` 可能偏低 → 实验：`--epochs 25`
- 模型预测了 11 次 unrelated，测试集里一条 unrelated 都没有，怀疑类别权重过重（unrelated 3.94）→ 实验：权重改为平方根算法（`--class-weight-scheme`；尚未实现，先登记）
- scope 召回只有 0.25（8 条找出 2 条），3 条被判成 unrelated → 先看权重修完的效果，不行再补 scope 数据（约 8 美元）
- contradict F1 0.679，跟基座不训练时的 0.689 基本一样，微调没有带来提升
- 需要一个错误分析脚本，列出所有判错的样例（`error_analysis.py`；尚未实现，先登记）
- **模型置信度没有校准（calibration）**：真实运行里 python.org（3.14.7）对 devguide（3.14 bugfix）实际更接近 agree，NLI 却判成 contradict 且 p=0.995。把握高不等于答对。之后可考虑温度缩放（temperature scaling）等校准方法。界面已加「模型自估，未经校准」提示；校准本身（如温度缩放）仍待做。
- 原则：一次只改一样东西

