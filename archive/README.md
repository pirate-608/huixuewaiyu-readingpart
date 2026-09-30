# archive/ — 已过时的实现与文档

这里的文件**不再被当前工具使用**。保留它们是为了追溯设计演进，不是供运行。

当前实现请见仓库根目录与 `scripts/`。

---

## 归档了什么，为什么

### `legacy-install/`

| 文件 | 曾经的用途 | 为什么过时 |
|---|---|---|
| `install.ps1` | Windows 一键安装：探测 Python → 建 venv → pip 装依赖 → `playwright install chromium` → 复制到 `~/.claude/skills/` → 交互式输入凭据 | 被三件事取代：`scripts/install_skill.py`（skill 摆放）、`scripts/doctor.py`（报告依赖与浏览器状态）、`scripts/init_env.py`（凭据） |
| `install.sh` | 同上，Linux/macOS | 同上 |

**过时的关键点**：旧脚本把**代码复制进 skill 目录并各建一个 venv**，
于是 `~/.claude/skills/...` 和 `~/.agents/skills/...` 各有一份副本，升级要同步两处。
新方案让代码留在仓库、skill 只带文档，消除了重复。

> 顺带修掉的 bug：旧 `install.ps1` 装到 `~/.agents/<name>/`，
> 而 DSH/Codex 实际扫描的是 `~/.agents/skills/<name>/` —— 少了一层 `skills`。

### `legacy-docs/`

| 文件 | 说明 |
|---|---|
| `guide.tex` | LaTeX 版《零基础安装与使用指南》 |
| `guide.pdf` | 上述编译产物（170 KB） |

**过时原因**：正文引用的是 `install.ps1` / `install.sh`，以及旧路由
`#/read/learn?subject_id=`（新版是 `#/pc/read/learn`）。
它描述的整套安装流程已被替换，照着做会走到废弃路径。

### `legacy-api-reference.md`

原 `references/api_reference.md`，描述 **`:8082` 端口 + `token` 请求头 + POST** 的旧接口。

实测新版是 **`/en/*` 路径、GET 为主、JWT 放 `localStorage.authorization`**。
这份文档**每一个字段都是错的**，留着比没有更危险。

### `legacy-ipc/`

旧的**文件 IPC 答题协议**实现：

| 文件 | 说明 |
|---|---|
| `review.py` | 写 `elang_signal.json` 提交答案 |
| `test_session.py` | 验证上述协议的校验与 echo |

**过时原因**：该协议用两个进程互相轮询（脚本写文件等答案，答题方轮询文件），
双方都会阻塞 —— 这是本项目最大的时间浪费来源。
MCP 化后由 `elang_session.py` 的状态机取代：每个 tool 立即返回，
**不存在等待**。文件 IPC 不再有调用方。

---

## 没有归档的东西（说明）

- **`references/answers.json`** —— 题库仍然有效，是当前实现的一部分
- **`references/parse_answers.py`** —— 题库生成工具，仍可用
- **`references/answers.raw`** —— 题库原始数据，是 `answers.json` 的来源

## 构建产物

`guide.aux` / `guide.log` / `guide.out` / `guide.synctex.gz` / `guide.toc`
是 LaTeX 中间产物，**未归档，直接删除** —— 它们可由 `guide.tex` 重新生成，
且 `guide.log` 单文件就有 49 KB。
