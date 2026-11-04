# 开发指引

> **读者：开发 agent**（开发 / 调试本项目）。
> 答题的执行 agent 看 `SKILL.md`；**本文不随 skill 分发**。


This file provides guidance to coding agents working in this repository.

> ## ⚠️ 五条必须记住的规则
>
> **1. 不要阻塞等待。** MCP 模式下没有任何 tool 会等待，每步立即返回状态
> 与可执行的下一步。用"挂着等输出"的方式轮询会让双方互相等待。
>
> **2. 不要按进程名杀进程。** `Get-Process msedge | Stop-Process` 会连带杀掉
> 用户自己的 WebView2 桌面应用。只停自己的 job。
>
> **3. 不要依赖系统 Python 的 site-packages。** 不用 `--system-site-packages`，
> 不往系统解释器装包。每台机器全局环境不同，借来的依赖换机即失效。
> `doctor.py` 会检测并警告这种情况。
>
> **4. 网络失败先判断代理状态，不要重复重试。** 本项目涉及两类网络目的地，
> 它们对代理的要求相反：
>
> | 目的地 | 正常访问方式 | 失败时的典型原因 |
> |---|---|---|
> | GitHub、uv、浏览器下载源 | 经由代理 | 代理未开启，或分流规则把流量绕过了 |
> | 慧学外语（`elang.zju.edu.cn`、`zjuam.zju.edu.cn`） | 直连 | 代理或 TUN 模式仍处于开启状态 |
>
> - `git clone`、`uv tool install`、`elang install-browser` 失败时，先确认代理由
>   是否开启。代理关闭时这些操作容易失败，这不是仓库或工具的问题。
> - 访问慧学外语失败、登录页打不开时，先确认 TUN 模式与系统全局代理已关闭。
>   站点对访问来源有网络限制，重试不会改变结果。
> - 两类失败都不要连续重试。先判断网络状态，再决定下一步。
>
> 这些规则不针对某台机器，任何参与本项目开发的人都适用。
>
> **5. 只支持 Windows，不要做跨平台兼容。** 目标用户是 Windows 桌面上的慧学外语
> 使用者，Linux / macOS 没有实测环境，不值得为此投入。不补功能、不修 bug、
> 不加平台分支；代码里已有的 POSIX 分支（`/tmp`、symlink、chmod）保留即可，
> 不构成承诺，也不要扩展。
>
> 改动代码前请读 [`CHANGELOG.md`](CHANGELOG.md)：
> 那里有实测事实、被推翻的假设和踩过的坑。

## Overview

Playwright 自动化，驱动慧学外语 (elang.zju.edu.cn) 的 **PC 版界面**完成英语阅读练习。
读取文章与题目，交由 agent 作答，再用应用自己的 Vue 方法提交。

五个组成部分：

| 文件 | 职责 |
|---|---|
| `scripts/elang_reader.py` | **引擎**：浏览器、抓取、作答、提交 + CLI 批处理流程 |
| `scripts/elang_session.py` | **显式状态机**（MCP Level 1），每个方法立即返回，不阻塞 |
| `scripts/elang_mcp.py` | MCP server（10 个 tool），薄包装状态机 |
| `scripts/answer_ipc.py` | **CLI 回退的答题侧**：`elang pending/answer/skip/continue/stop` |
| `scripts/config.py` | 凭据与 IPC 路径解析（**全项目唯一实现**） |

支持脚本：`doctor.py`（诊断）、`init_env.py`（凭据模板）、`install_browser.py`、
`install_skill.py`（注册到各 agent 根目录）、`setup_mcp.py`（MCP 注册）、
`setup.py`（克隆仓库后的开发用一键安装）。

**依赖方向**（不要制造环）：

```
elang_reader  ←  elang_session  ←  elang_mcp
elang_reader  ←  answer_ipc      （只 import config，不 import reader）
cli  →  {elang_reader(run), elang_mcp(mcp), answer_ipc(pending/answer/...), SIMPLE}
```

本仓库同时是 skill，按 `SKILL.md` 的契约被 DSH / Codex / Claude Code 发现。

## Commands

**已安装的工具**（用户视角，文档里应优先用这个）：

```bash
elang doctor                            # 依赖 / 浏览器 / 凭据，并给出修复命令
elang init-env                          # 在工作区根生成 .env 模板
elang install-browser                   # 复用已装 Chrome/Edge，没有才下载 Chromium
elang setup-mcp --host claude|dsh|codex # 注册 MCP（备份+校验+回滚）
elang install-skill --agent claude --scope global|project
elang run batch-all                     # 驱动求解
elang mcp                               # MCP server（stdio）
elang pending / answer / skip / continue / stop   # CLI 回退的答题侧
```

**仓库内开发**（源码布局，等价入口）：

```bash
.venv/Scripts/python.exe scripts/doctor.py
.venv/Scripts/python.exe scripts/elang_reader.py batch-all --subjects-only
.venv/Scripts/python.exe scripts/elang_reader.py batch-all --limit 1 --dry-run
.venv/Scripts/python.exe scripts/answer_ipc.py pending --brief
```

`--dry-run` 会打开提交确认框但**不提交**。

## Architecture

### 凭据（`config.py`）

解析顺序，**全项目只此一处实现**：

```
1. $ELANG_ENV_FILE                     显式指定
2. <工作目录>/.env                      工作区根 ← 约定
3. ~/.elang/.env                       兜底

键名两套都认（带 ELANG_ 前缀的优先）：
    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD
真实环境变量优先于以上任何文件，两套键名都适用。
```

**为什么 `./.env` 就够**：所有 agent（DSH / Claude Code / Codex）运行命令时
工作目录都是工作区根。这是共同契约，所以不需要向上遍历、agent 探测、
指针文件或 `DSH_*` 变量。

**MCP server 的 cwd 也是宿主 cwd**（实测）。所以同一个解析器对两种入口都成立。

环境变量压过文件，是因为 MCP 宿主在 spawn 时注入凭据是可行的（实测透传），
且陈旧的 `.env` 不应覆盖宿主给的值。

### 浏览器

`launch_persistent_context` + 持久化 profile，profile 在 `~/.elang/browser-profile`
（用 `ELANG_PROFILE_DIR` 覆盖）。浏览器来源有两级，`config.browser_choice()`
是唯一的决定处：

| 优先级 | 来源 | 何时使用 |
|---|---|---|
| 1 | `ELANG_BROWSER` | 显式指定：`chromium`、`chrome`、`msedge`，或可执行文件路径 |
| 2 | 自带 Chromium | 默认。自包含，与运行它的 Playwright 版本匹配 |
| 3 | 已装 Chrome / Edge | 没有自带构建时用它，省掉约 683 MB 下载 |

实测（Playwright 1.60，自带 chromium 148）：系统 Chrome 157 与 Edge 156 都能用
`launch_persistent_context` 启动，headless 与有头均可，且**同一个 profile 目录
可与自带构建双向共用**。此前"`channel=msedge` 会拒绝启动"的结论已推翻——
当时是 `launch()` 额外传了命令行参数，`launch_persistent_context` 不传。

**不要在代码里钉死浏览器版本或路径。** 探测顺序是注册表 App Paths、常见安装
位置、PATH，找到可执行文件后自己读版本；不用 `channel=` 让 Playwright 自己去
注册表找，那样会漏掉 scoop、便携版、tarball 等安装。`doctor.py` 报告**实际会
启动哪一个**，并真的启动一次。`requirements.txt` 里的
`playwright>=1.49,<1.61` 区间必须与浏览器一起升级。

实测：持久化 profile **本身不保留 CAS 会话**。
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
把它当参数传回去会得到空值，所有字段读成 0。这就是曾经
"同一页面一处报告有验证码图、另一处报告没有"的根因。
所以实例**钉在页面里**（`window.__elangPraxisVm` / `window.__elangLearnVm`），
所有读取都在浏览器内部完成。

### IPC 目录

`<ipc>` = `$ELANG_TMP_DIR`，否则 `C:/tmp`（Windows）/ `/tmp`（其他）。

保留用途：**验证码交接**（`elang_captcha_request.json` / `elang_captcha.json` /
`elang_captcha_image.png`）、**会话**（`elang_session.json`）、
**断点**（`elang_checkpoint.json`）。

**答案走文件，但只在 CLI 回退路径上。** `elang run` 遇到题库没覆盖的文章时，
把题目写到 `elang_current.json` 并等待；**答题方是 agent**，用这些命令作答：

```
elang pending              # 显示待答文章（立即返回）
elang pending --brief      # 一行摘要
elang answer 0=A 1=C       # 选择题给选项字母
elang answer "5=A,B,C"     # 填空题每空一个值，逗号分隔
elang answer --raw '[[0,1],[1,2]]'
elang skip / continue / stop
```

`answer_ipc.py` **只依赖 config**，不 import `elang_reader`，所以不需要 Playwright。

> **关键：只有 `elang run` 自己在后台阻塞，agent 侧永远不阻塞。**
> 旧的痛点是双方互相等，那是用法错误（以等待输出的方式轮询），不是协议本身的问题。
> 正确姿势：`elang run` 作为后台 job 启动，agent 用 `elang pending --brief`
> 轮询（立即返回），需要作答时再 `elang answer`。
>
> MCP 路径不需要这套机制，它本身就是非阻塞状态机。

### CAPTCHA

题目页的闸门。`wait_for_captcha()` 顺序：

1. ddddocr（最多 3 次；**图片没换就停止重试**，这是防死循环的守卫）
2. 视觉/文件交接
3. `ELANG_CAPTCHA_MANUAL=1` 时完全不碰 `verifyCode`，等待用户自行输入，
   因为输错会让应用刷新图片，**清掉用户已输入的内容**

绝不主动调用 `refreshCaptcha()`：那会在健康的页面上**制造**一个验证码。

### Checkpoint / 断点

`elang_checkpoint.json` 记录已完成主题与总数；已完成的主题会跳过。
每 50 篇等待 `continue` / `stop` 信号。

`--limit N` 与 checkpoint 有一个重要交互：**只处理了部分文章时不会把该主题
标记为完成**，否则下次全量运行会跳过剩余文章。

## 提交前必做：隐私守卫

仓库是**公开**的。第一次克隆后启用提交钩子（一次即可）：

```bash
git config core.hooksPath .githooks
```

它会在每次提交前跑 `scripts/test_no_secrets.py`，命中即**阻断提交**。

手动跑：

```bash
.venv/Scripts/python.exe scripts/test_no_secrets.py
```

它会扫描**受跟踪文件**里的：API key / 私钥 / 字面量密码赋值 /
学号样式数字（10 位、3 开头）/ 本机用户路径，并断言 `.env` 未跟踪且被忽略。

> **踩过的坑**：清理隐私时写的说明文档里**引用了学号原文**，提交后反而把数据
> 带回了历史，导致不得不重写两次。**描述，不要引用原值。**

## 容易踩的坑

- **`job_output(wait=true)` 会挂住**，而脚本可能正等待响应。应使用非阻塞读取
- **`%LOCALAPPDATA%\Temp` 在沙箱下可能挂死**（实测 >25s，Playwright 报
  `EPERM mkdtemp`）；把 `TEMP`/`TMP` 指向工作区即可（实测 0.07s）
- **Playwright 版本与浏览器构建必须匹配**：`uv pip install playwright` 装到
  1.63 会要求 chromium 1243，机器上只有 1223 → 启动失败
- **MCP stdio 用 stdout 传 JSON-RPC**，任何 `print()` 都会污染协议；
  `elang_mcp.py` 用 `quiet_stdout()` 把诊断重定向到 stderr
- **`mcp` 1.x 与 2.x API 不同**（`FastMCP`→`MCPServer`、`isError`→`is_error`）；
  `elang_mcp.py` 两版都兼容

## Requirements

- **Windows 10/11（64 位）**，只支持这一个平台
- Python 3.11+
- `uv`（推荐）
- 浏览器：自带 Chromium，或系统 Chrome / Edge（`doctor.py` 报告）
- ZJU CAS 账号

### 沙箱限制（实测）

Playwright **无法**在文件沙箱内启动浏览器：driver 走
`asyncio.create_subprocess_exec`，Windows 上需要**命名**管道，
受限沙箱拒绝 `CreateFile("\\.\pipe\...")`（WinError 5）。

精确区分：`subprocess.run(capture_output=True)` 走**匿名**管道（`CreatePipe`），
沙箱下可用；被拒的是 **asyncio 的命名管道**。同步 API 也一样，因为它内部就是 asyncio。

所以驱动浏览器需要更宽的权限，MCP server 也必须在沙箱外运行。
