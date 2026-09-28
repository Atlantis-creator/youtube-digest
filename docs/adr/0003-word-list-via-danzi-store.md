# 加入词表调用 danzi 的 vocabulary_store.py，不在本仓库重写

日期：2026-09-28

状态：已接受

## 背景

用户希望查词之后可以一键加入 `for_obsidian/word/` 词表。词表的格式由 `for_obsidian/word/DESIGN.md` 规定：lemma 归一、alias 去重、Windows 下仅大小写不同的文件名合并、按来源分组的语境实例编号与去重、词条和逐字稿顶部回链一次写入两个文件。这些规则已经由 danzi-skill 的 `scripts/vocabulary_store.py`（约 1400 行）实现，`record-lookup` 子命令接收一份 JSON payload 完成一次快查写入。

## 决定

native host 新增加入词表操作：先在 vault 各 Wiki 的 Source Material 里按视频网址找到已落盘的逐字稿，再用子进程调用 `vocabulary_store.py record-lookup`，然后对词条和逐字稿执行 `git commit --only`。脚本路径默认是 `<vault>/.claude/skills/danzi-skill/scripts/vocabulary_store.py`，可以在设置页改。

这与 ADR 0002「落盘规则在本仓库独立实现」方向相反，是有意为之。

## 取舍

- 在 native host 里重写：不依赖外部路径，但要复制约 1400 行规则，两份实现几乎一定会分叉，而分叉的后果是词表里出现格式不一致的词条，事后很难发现。ADR 0002 能独立实现，是因为落盘规则只有几十行。
- 等 danzi-skill 定型后再做：用户认为 danzi 仍有没设计好的部分，但那部分是对话流程；`record-lookup` 的 payload 契约已经稳定，可以先依赖。
- 视频未落盘时用 YouTube 网址当外部来源：DESIGN 规定视频网址只是元数据，以后导入同一视频的逐字稿会在词条里产生第二个来源单元。因此改为要求先「存到 Wiki」，未落盘时按钮置灰。

代价：danzi 改了 CLI 参数或 payload 字段后，加入词表会失败。失败时 native host 原样返回脚本的错误信息，便于定位。

## 依据

- 用户确认：词条由 danzi 的存储脚本写入（Q4 A）；视频未落盘时按钮置灰（Q3 C）；只本地提交、不 push，且连同目标文件上已有的未提交改动一起提交（Q5 A、Q11 C）。
- `for_obsidian/word/DESIGN.md`、`.claude/skills/danzi-skill/references/cli.md`
