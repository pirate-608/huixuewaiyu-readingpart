# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## ⚠️ 三条必须记住的规则
>
> **1. 不要阻塞等待。** MCP 模式下没有任何 tool 会等待 —— 每步立即返回状态
> 与可执行的下一步。用"挂着等输出"的方式轮询会让双方互相等待。
>
> **2. 不要按进程名杀进程。** `Get-Process msedge | Stop-Process` 会连带杀掉
> 用户自己的 WebView2 桌面应用。只停自己的 job。
>
> **3. 不要依赖系统 Python 的 site-packages。** 不用 `--system-site-packages`，
> 不往系统解释器装包 —— 每台机器全局环境不同，借来的依赖换机即失效。
> `doctor.py` 会检测并警告这种情况。
>
> 改动代码前请读 [`MIGRATION_CHECKPOINT.md`](MIGRATION_CHECKPOINT.md)：
> 那里有实测事实、被推翻的假设和踩过的坑。

## Overview

Playwright 自动化，驱动慧学外语 (elang.zju.edu.cn) 的 **PC 版界面**完成英语阅读练习。
读取文章与题目，交由 agent 作答，再用应用自己的 Vue 方法提交。

四个组成部分：

| 文件 | 职责 |
|---|---|
| `scripts/elang_reader.py` | 批处理驱动：浏览器、抓取、作答、提交（CLI） |
| `scripts/elang_session.py` | **显式状态机**（MCP Level 1）—— 每个方法立即返回，绝不阻塞 |
| `scripts/elang_mcp.py` | MCP server（10 个 tool），薄包装状态机 |
| `scripts/config.py` | 凭据解析（**全项目唯一实现**） |

支持脚本：`setup.py`（安装）、`doctor.py`（诊断）、`init_env.py`（凭据模板）、
`install_skill.py`（注册到各 agent 根目录）、`setup_mcp.py`（生成 MCP 注册）。

本仓库同时是 skill，按 `SKILL.md` 的契约被 DSH / Codex / Claude Code 发现。

## Commands

```bash
# 安装（建隔离 venv + 注册 skill + 报告状态）
python scripts/setup.py
python scripts/setup.py --check         # 只报告

# 诊断：依赖 / 浏览器 / 凭据，并给出修复命令
python scripts/doctor.py

# 凭据
python scripts/init_env.py              # 在工作区根生成 .env 模板
python scripts/setup_mcp.py             # 生成 .mcp.json

# 驱动
python scripts/elang_reader.py batch-all
python scripts/elang_reader.py batch 26
python scripts/elang_reader.py solve "<praxis-url>"
python scripts/elang_reader.py batch-all --subjects-only   # 只列主题，零风险
python scripts/elang_reader.py batch-all --limit 1 --dry-run
```

`--dry-run` 会打开提交确认框但**不提交**。

## Architecture

### 凭据（`config.py`）

解析顺序，**全项目只此一处实现**：

```
1. $ELANG_ENV_FILE              显式指定
2. <cwd>/.env                   工作区根 ← 约定
3. ~/.elang/.env                兜底
   另外：ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 环境变量优先于以上任何文件
```

**为什么 `./.env` 就够**：所有 agent（DSH / Claude Code / Codex）运行命令时
工作目录都是工作区根 —— 这是共同契约，所以不需要向上遍历、agent 探测、
指针文件或 `DSH_*` 变量。

**MCP server 的 cwd 也是宿主 cwd**（实测）。所以同一个解析器对两种入口都成立。

环境变量压过文件，是因为 MCP 宿主在 spawn 时注入凭据是可行的（实测透传），
且陈旧的 `.env` 不应覆盖宿主给的值。

### 浏览器

**自带 Chromium** + `launch_persistent_context`，profile 在 `~/.elang/browser-profile`
（用 `ELANG_PROFILE_DIR` 覆盖）。不需要系统装浏览器 —— 这是可分发的前提。
`ELANG_BROWSER=msedge` 是逃生口。

**不要在代码里钉死浏览器版本或路径。** 需要哪个构建取决于 Playwright 版本；
`doctor.py` 负责报告并打印安装命令。`requirements.txt` 里的
`playwright>=1.49,<1.61` 区间必须与浏览器一起升级。

实测：持久化 profile **本身不保留 CAS 会话** ——
`iPlanetDirectoryPro` 与 zjuam 的 `JSESSIONID` 是会话 cookie，会被丢弃。
所以 `elang_session.json`（cookies + localStorage）的显式重放**是必需的**，不是优化。

### PC 版站点结构

站点改版过。两套组件都还在 router 里，但桌面路径渲染 `Pc*` 组件：

| 路由 | 组件 | 数据 |
|---|---|---|
| `#/pc/read/index` | `PcReadIndex` | `$data.listData` |
| `#/pc/read/learn?subject_id=` | `PcReadLearn` | `$data.resourceList` |
| `#/pc/read/praxis?log_id=&resources_id=` | `PcReadPraxis` | `$data.jobList` |

关键机制：

- **`toPraxis(item)` 由服务端签发 `log_id`**，所以 praxis URL 不能手工拼，
  必须调用它；返回的 `resources_id` 要与目标文章 id 核对
- **完成状态**用应用自己的 `normalizeStatus`：`status === 2` 或 `hisLabel === 1`
- **题目只有通过验证码后才加载**，所以闸门检测 = 有验证码图且 `jobList` 为空
- **作答**：选择题 `selectOption(qIdx, optIdx)`；
  填空题 `insertWordAnswers[jobId]` 是**每空一个值**的数组（type_id 2/5/7/8）
- **提交**两步：`openSubmitConfirm()` → `confirmSubmit()`，它 POST 两次并跳详情页

### Vue 访问的陷阱

`.resource-item` 元素**任何祖先都没有 Vue 实例**，所以行 id 无法从 DOM 读；
只能按位置点击，再从 URL 核对。

更重要的是：**`page.evaluate` 返回对象给的是副本，而 Vue 实例根本无法序列化到 Python。**
把它当参数传回去会得到空值，所有字段读成 0 —— 这就是曾经
"同一页面一处报告有验证码图、另一处报告没有"的根因。
所以实例**钉在页面里**（`window.__elangPraxisVm` / `window.__elangLearnVm`），
所有读取都在浏览器内部完成。

### IPC 目录

`<ipc>` = `$ELANG_TMP_DIR`，否则 `C:/tmp`（Windows）/ `/tmp`（其他）。

保留用途：**验证码交接**（`elang_captcha_request.json` / `elang_captcha.json` /
`elang_captcha_image.png`）、**会话**（`elang_session.json`）、
**断点**（`elang_checkpoint.json`）。

**答案不再走文件。** 旧的 `elang_current.json` / `elang_signal.json` 协议
已归档到 `archive/legacy-ipc/` —— 它让两个进程互相轮询、双方都阻塞。

### CAPTCHA

题目页的闸门。`wait_for_captcha()` 顺序：

1. ddddocr（最多 3 次；**图片没换就停止重试**，这是防死循环的守卫）
2. 视觉/文件交接
3. `ELANG_CAPTCHA_MANUAL=1` 时完全不碰 `verifyCode`，等用户自己输入 ——
   因为输错会让应用刷新图片，**清掉用户已输入的内容**

绝不主动调用 `refreshCaptcha()`：那会在健康的页面上**制造**一个验证码。

### Checkpoint / 断点

`elang_checkpoint.json` 记录已完成主题与总数；已完成的主题会跳过。
每 50 篇等待 `continue` / `stop` 信号。

`--limit N` 与 checkpoint 有一个重要交互：**只处理了部分文章时不会把该主题
标记为完成**，否则下次全量运行会跳过剩余文章。

## 容易踩的坑

- **`job_output(wait=true)` 会挂住**，而脚本可能正等着你 —— 用非阻塞读取
- **`%LOCALAPPDATA%\Temp` 在沙箱下可能挂死**（实测 >25s，Playwright 报
  `EPERM mkdtemp`）；把 `TEMP`/`TMP` 指向工作区即可（实测 0.07s）
- **Playwright 版本与浏览器构建必须匹配**：`uv pip install playwright` 装到
  1.63 会要求 chromium 1243，机器上只有 1223 → 启动失败
- **MCP stdio 用 stdout 传 JSON-RPC**，任何 `print()` 都会污染协议；
  `elang_mcp.py` 用 `quiet_stdout()` 把诊断重定向到 stderr
- **`mcp` 1.x 与 2.x API 不同**（`FastMCP`→`MCPServer`、`isError`→`is_error`）；
  `elang_mcp.py` 两版都兼容

## Requirements

- Python 3.11+
- `uv`（推荐）
- Chromium（`doctor.py` 报告）
- ZJU CAS 账号

### 沙箱限制（实测）

Playwright **无法**在文件沙箱内启动浏览器：driver 走
`asyncio.create_subprocess_exec`，Windows 上需要**命名**管道，
受限沙箱拒绝 `CreateFile("\\.\pipe\...")`（WinError 5）。

精确区分：`subprocess.run(capture_output=True)` 走**匿名**管道（`CreatePipe`），
沙箱下可用；被拒的是 **asyncio 的命名管道**。同步 API 也一样，因为它内部就是 asyncio。

所以驱动浏览器需要更宽的权限，MCP server 也必须在沙箱外运行。
