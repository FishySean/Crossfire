# 重构待办（收尾整理）

第 0–7d 步验收后的状态。详细现象与修法见 git 历史；这里只保留索引。

---

## 已完成

- 第 0–1：特征测试；domain 实体与严格 `from_dict`
- 第 2：ports + adapters；`mode` 校验；LLM 工具返回按 domain 校验（失败大声）
- 第 3：`VerifyQuestion`；抓取失败进 `failures`；`Usage.requests`；原子撞名保存；fetcher.mode
- 第 4：组合根；可用性；单一 `config.py`；`migrate_runs.py`；入口只经 composition
- 第 5a/5b：`as_of` / provenance；一手来源优先；评测集；pairer 带日期；缓存 `fetched_at`
- 第 5c：题库 / SourceFinder / 批量造数；余额不足立刻停（不静默空列表）
- 第 6–7：NLI 训练与接入；前端事件补字段；失败横幅；不问伪造平滑进度
- 第 7c：Ask a Question（费用估算 + 确认）
- 第 7d：`HttpPageFetcher` 默认 `FETCHER=http`
- 第 8：Source / SourceFinder URL 校验；Actions → Node 24；双语 README；architecture；MIT
- 第 8b：ask 费用常数按真实运行校准；来源确定后二次上限检查；确认框显示 4～8 来源区间

---

## 延后

### 模型迭代

- `max_epochs` 可能偏低（seed 42/44 第 12 轮验证损失仍在降）→ 试 `--epochs 25`
- unrelated 类权重可能过重 → 平方根权重（`--class-weight-scheme`，未实现）
- scope 召回 0.25 → 先看权重，再考虑补数据（约 $8）
- contradict 微调几乎无增益；需按题拆开的错误分析脚本
- 置信度未校准（temperature scaling 等）；界面已提示「模型自估，未经校准」
- mysql 题占 contradict 标签比例偏高 → 事后按题检查迁移性
- 原则：一次只改一样

### 界面上的可选功能

- 搜索历史查询（历史还少）
- 底部来源统计柱状图（数据现成，锦上添花）

### Steel 以外的抓取改进

- HTTP 对严反爬 / JS 壳仍会挂；可再接其它浏览器/代理适配器（端口已在，加 `Fetcher` 分支即可）
- Steel 免费额度约 **2026-12-11** 到期（按首次 session 推算）——默认已不依赖它

### 标签 / 提取质量（造下一批评测前要看）

- 部分页面提取仍会挑错表格行（最终答案靠一手下载页撑住）
- judge 偶发把数组编成字符串（靠重试救；根因未消）
- `leads_with` 判分启发式；东京标准答案接受区间口径

---

## 决定不做（附理由）

| 项 | 理由 |
|---|---|
| 左侧导航栏（Home / History） | 单页应用，加导航是空架子 |
| 题目配图（天际线等） | 跟查证无关，还有版权问题 |
| 中间证据网络图 | 卡片+连线已够；网络图工作量大、信息不会更多 |
| 伪造平滑的 `pair_done` 进度 | 批量推理本来成簇到达；只报真实发生的事（同心跳原则） |
| 严格校验 `published_date` 为完整 YYYY-MM-DD | 模型常回部分日期；硬校验只会多烧重试 |
| 迁移旧 `requests` 时按「每条 1 次」补数 | 那是编出来的；未知写成 `null`，总数也随 `null` |

---

## 第 8 步：非法 URL 扫描结论

对已入库的 `questions/**/*.yaml` 与本地 `out/cache/**/*.json` 用 `clean_source_url` 全量扫描：**0 条非法网址**。  
`HttpPageFetcher` 报过的 `InvalidURL`（URL 中带换行）来自搜索结果瞬时脏数据，未写进提交的题库/缓存。  
修复策略：入口校验（`Source` / `CandidateSource` 构造）+ SourceFinder 丢弃并打日志 + HTTP 抓取器防御；不改历史缓存文件。
