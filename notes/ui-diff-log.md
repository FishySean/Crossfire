# UI visual diff log（阶段二）

参考图：`docs/screenshots/design-newspaper-concepts.jpg` 以**红色圆形 + 黑白天际线**那张为准（天际线改为纯 CSS）。
视口：1440×900 首屏。截图目录：`notes/ui-diff/`。

## Round 1

截图：`round1-above-fold.png`、`round1-full.png`、`round1-node.png`、`round1-table.png`、`round1-mobile.png`

差异清单：

| 区域 | 差异 | 处理 |
|---|---|---|
| 应用外壳 | 设计顶栏品牌 + 侧栏图标导航；实现为侧栏品牌 + 演示/历史控件（按阶段二功能要求） | **有意不做**顶栏搜索/头像：功能规格要求删除顶部控件条、历史与提问进侧栏 |
| 英雄装饰 | 天际线偏弱、红圆偏小 | 加大红圆、加深剪影对比 |
| KPI | 缺图标；第三格已是「有误来源」而非 NLI 矛盾数 | 加 CSS 线框图标；数值逻辑保持 summary.counts |
| 关系图高度 | 360px 挤掉结论 CTA | 降到 300px |
| 结论面板 | 标题/答案偏长，首屏看不到主按钮 | 压缩字号与 gap，答案 4 行截断 |
| 底部三栏 | 首屏外（设计图也常在折线附近） | **有意不做**塞进 900 高：规格要求首屏必须有标题/KPI/图/结论，三栏在下方 |

## Round 2

截图：`round2-above-fold.png`

差异清单：

| 区域 | 差异 | 处理 |
|---|---|---|
| 首屏 | 标题、KPI、关系图、结论、主 CTA 均可见 | 保持 |
| KPI 图标 | 为几何线框，非设计稿插画图标 | **有意不做**插画/图片图标：无图库、保持报纸平面感 |
| 节点卡片 | 无来源 favicon | **有意不做**：避免外链图标与隐私/加载抖动 |
| 细分隔线 | 已用 1px hairline；无大阴影大圆角 | 保持 |
| 纸张纹理 | body 已有 CSS grain | 保持 |

## Round 3（验收）

截图：`round3-above-fold.png`、`round3-node.png`、`round3-table.png`、`round3-mobile.png`

差异清单（仅剩有意不做）：

1. **顶栏式品牌条 / 用户头像** — 阶段二改为侧栏应用外壳，与规格一致。
2. **真实天际线照片** — 规格要求纯 CSS 装饰，不引入图片文件。
3. **KPI/来源 favicon 插画** — 无图表库、不拉第三方图标。
4. **底部三栏进首屏** — 1440×900 优先保证图+结论；三栏紧随其下。
5. **View Transitions 动画** — 实现了 Graph/Table 同步切换；完整 VT 在 reduced-motion/部分浏览器不稳定，故不依赖。

同步到 `docs/screenshots/`：`17-dashboard-mobile.png`、`18-dashboard-above-fold.png`、`19-dashboard-full.png`、`20-dashboard-node.png`、`21-dashboard-table.png`。
