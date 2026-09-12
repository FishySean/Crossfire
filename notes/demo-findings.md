# 演示素材笔记

跑演示问题时发现的、适合写进 slides 的点。每条都有对应的运行结果文件。

## nodejs-lts-version

运行结果：`out/runs/nodejs-lts-version_20260912T212324Z.json`
6 个矛盾，最终答案 Node.js 24（Krypton），置信度 0.97。

### 官网不等于最有判别力的来源

`nodejs.org/en/about/previous-releases` 是这题里层级最高的官方页面之一，但它**没有参与任何一个矛盾**。
原因是它把 v22 和 v24 统统标成 `LTS`，不区分 Active LTS 和 Maintenance LTS。
粒度太粗，所以跟每个来源都判成 agree，对「当前哪个版本是 Active LTS」这个问题不提供任何判别力。

真正能当裁判的是 `github.com/nodejs/release`，它那张表里有明确的 `**Active LTS**` 标注：

    | 24.x | **Active LTS** | Krypton | 2025-05-06 | 2025-10-28 | 2026-10-20 | 2028-04-30 |

这条正好反驳「一手源权重最高所以只看官网就行」的直觉。
权威性和判别力是两件事：一个来源可以完全正确却完全无用，因为它的表述粒度回答不了你的问题。
查证引擎的价值恰恰在于它能发现「最该信的那个来源其实没说」，然后去找真正说清楚了的那个。
