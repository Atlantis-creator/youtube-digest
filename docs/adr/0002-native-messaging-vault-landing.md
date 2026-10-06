# 平台字幕导入经 Native Messaging 本地程序落盘

日期：2026-09-27

状态：已接受

## 背景

用户希望在侧栏点一下，就把当前视频的原文字幕落入 Obsidian Wiki 的 `2 - Source Material/<作者>/`，并为这份新来源做一次 Git 提交。扩展页面不能写任意磁盘路径，也不能运行 git。本机已有 video-transcriber（127.0.0.1:8767），实现了同一套来源落盘规则，但它为国内平台的 ASR 转录而建，需要先手动启动。

## 决定

新增 `native-host/ytd_vault_host.py`，经 `install.ps1` 注册为 Chrome Native Messaging 主机（当前用户注册表，清单绑定扩展 ID）。点击「存到 Wiki」时由 background 调用 `chrome.runtime.sendNativeMessage`，Chrome 按需拉起该脚本：列出 Wiki、查重、写入唯一文件，再执行 `git commit --only -- <该文件>`，然后退出。落盘规则按 `for_obsidian` Knowledge System 的契约在本仓库独立实现，不引用 video-transcriber 的代码。

## 取舍

- 复用 video-transcriber 的本地服务：规则现成，但每次都要先启动工具，用户明确拒绝。
- File System Access API：无需安装，但做不了 git 提交，重开浏览器后还可能要重新授权。
- 共用 video-transcriber 的 `landing.py`：会让扩展依赖另一个仓库的路径和内部函数，任何一方重构都会悄悄破坏另一方。代价是两边各维护一份几十行的规则，契约变更需同步两处。

Native Messaging 的代价：需要一次性安装（Python 3 与注册表键），扩展 ID 或本目录变动后要重新运行 `install.ps1`；不在 Chrome Web Store 发布包的安装流程里。

## 依据

- 用户确认：不想每次先启动 video-transcriber；本地程序独立实现（Q9 A）。
- https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging

## 后续

2026-10-06（Atlantis-creator/for_obsidian#45）：for_obsidian 把三个分库合成一个 Wiki（其 ADR 0006），落盘位置改为 `Wiki/收藏/<作者>/`，本地程序不再「列出 Wiki」，侧栏不再选库。查重规则与 video-transcriber 仍各自实现，但改为共用同一份用例 `tests/fixtures/dedupe_cases.json`，契约变更时两边同步这份文件。
