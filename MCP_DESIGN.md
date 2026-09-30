# MCP 设计计划

Status: **计划中**，尚未实施。
依据：`MIGRATION_CHECKPOINT.md` 的实测事实 + 当前 `scripts/` 的真实函数表。

---

## 1. 核心问题：当前架构是"双向阻塞"

现在的文件 IPC 协议本质是：

```
solver:  写出 elang_current.json → wait_for_ai(600s) 阻塞轮询 → 读到 signal → 继续
answerer: 轮询文件有没有 waiting_for_ai → 读 → 写答案
```

**双方都在轮询对方。** 这次调试中最大的时间浪费全部来自这里：

- 我用 `job_output(wait=true)` → 自己也被挂住 → 谁也看不到谁（检查点 §20.2）
- 那 600 秒 `AI_TIMEOUT` 本质是**为"对方发现我"留的缓冲**，而不是业务需要
- "下一步该做什么"从来没有显式表达，只能靠读日志猜

**MCP 的真正价值不是"包一层协议"，而是把控制流反过来。**

## 2. 设计原则：控制反转（inversion of control）

| | 现在 | MCP 化之后 |
|---|---|---|
| 谁持有浏览器 | solver 进程持有，agent 在外面 | **MCP server 持有**，跨 tool call 存活 |
| 谁发起动作 | agent 被动响应文件 | **agent 主动调 tool** |
| "等待"是什么 | `wait_for_ai()` 阻塞 600s | **不存在"等待"** —— tool 立刻返回状态 |
| 下一步做什么 | 读日志猜 | **返回值里显式给出** |

关键推论：**`AI_TIMEOUT` 这个常量应该消失。** 文章停在 `awaiting_answers` 状态可以无限久，因为没有任何人在阻塞等待 —— 状态就存在 server 里，agent 想什么时候答就什么时候答。

## 3. 架构

```
┌─────────────────────────────────────────────┐
│ MCP host (DSH / Claude Desktop / ...)       │
└───────────────┬─────────────────────────────┘
                │ stdio (JSON-RPC)
┌───────────────▼─────────────────────────────┐
│ elang-mcp  (长驻进程)                        │
│                                              │
│  Session ──┬─ RunState (状态机)              │
│            ├─ Playwright persistent context  │
│            └─ AnswerBank (answers.json)      │
└───────────────┬─────────────────────────────┘
                │ CDP / in-process
        ┌───────▼────────┐
        │ bundled Chromium│
        └────────────────┘
```

**分层（重要）**：先做 **Level 1**，再做 **Level 2**。

- **Level 1：把 solver 重构成"显式状态机库"**
  `elang_reader.py` 里那些 `async def` 已经是干净的步骤函数
  （`open_browser` / `get_article_list` / `click_article` / `extract_page_content` /
  `set_answers` / `submit` / `wait_for_captcha`）。把它们收进一个
  `ElangSession` 类，**每个方法立刻返回，绝不阻塞等答案**。
  这一步**不需要 MCP 依赖**，而且能立刻用 CLI 验证。

- **Level 2：MCP server 只是 Level 1 的薄包装**
  `mcp` SDK 在这里只负责"把方法暴露成 tool + 产生 JSON Schema"。
  业务逻辑一行都不用改 —— **风险最小**。

**先 Level 1 的理由**：如果直接上 MCP，一旦行为不对，你无法区分
"是 MCP 包装的问题"还是"是 solver 逻辑的问题"。分层后可以分别验证。

## 4. 状态机（整个设计的核心）

```
        ┌──────────┐
        │   idle   │
        └────┬─────┘
             │ elang_start
        ┌────▼──────────────┐
        │  loading_subjects │
        └────┬──────────────┘
             │
        ┌────▼─────────────┐
        │  loading_lessons │◄──────────────┐
        └────┬─────────────┘               │
             │ elang_open_next              │ elang_submit
        ┌────▼───────────────┐              │
        │  awaiting_captcha  │──solve────┐  │
        └────────────────────┘           │  │
                                         │  │
        ┌────────────────────────────────▼──┴─┐
        │           awaiting_answers           │
        └────┬─────────────────────────────────┘
             │ elang_submit
        ┌────▼─────────┐
        │  submitted   │──── 还有下一篇 ──► loading_lessons
        └────┬─────────┘
             │ 没有下一篇
        ┌────▼─────┐
        │ finished │
        └──────────┘

   任意状态下出错 ──► error (带 error_detail)
```

**每个 tool 都返回同一个信封**，包含 `state` 与 `next_actions`：

```json
{
  "state": "awaiting_answers",
  "run_id": "r-7f3a",
  "article": {
    "index": 3, "total": 6,
    "resources_id": "1884",
    "log_id": "2186416",
    "title": "A Traveler's Treasure Hunt",
    "passage": "...",
    "questions": [
      {
        "qIndex": 0, "kind": "choice", "type_id": 1,
        "text": "Geocaching containers are only found in remote wilderness areas.",
        "options": [{"label": "A", "text": "True"},
                    {"label": "B", "text": "False"}],
        "answer_format": "letter"
      },
      {
        "qIndex": 5, "kind": "fill", "type_id": 5, "blanks": 7,
        "text": "__（1）__ : a game in which players try to find certain items...",
        "options": [{"label": "A", "text": "avocation", "value": "A-avocation"}],
        "answer_format": "value_per_blank"
      }
    ]
  },
  "blocking": false,
  "next_actions": ["elang_submit_answers", "elang_skip_article", "elang_status"],
  "hint": "Answer each question; fill questions need one value per blank."
}
```

`blocking` 恒为 `false` —— **这是与现在最大的区别**。没有任何 tool 会阻塞等待。

## 5. Tool 表面

分五组，命名前缀 `elang_`。

### 5.1 生命周期

| Tool | 参数 | 返回 |
|---|---|---|
| `elang_start` | `subject_id?`, `all?`, `dry_run?` | `state=running/awaiting_*` |
| `elang_status` | — | 当前状态 + 进度（**永不做动作**） |
| `elang_stop` | — | 关浏览器、存 session、`state=idle` |

### 5.2 推进

| Tool | 参数 | 返回 |
|---|---|---|
| `elang_list_subjects` | — | subject 列表（`id`, `name`, `resource_num`） |
| `elang_list_articles` | `subject_id` | 文章列表 + 完成状态 |
| `elang_open_article` | `index?` / `resources_id?` | **推进到下一篇**；返回 `awaiting_captcha` 或 `awaiting_answers` |

> `elang_open_article` 是替代 `click_article` + `extract_page_content` +
> `wait_for_ai` 三件事的单一入口。**它绝不等待答题。**

### 5.3 作答（本文档的核心）

```python
elang_submit_answers(
    answers: list[Answer],
    dry_run: bool = False,
) -> Envelope

# Answer = {"qIndex": int, "value": int | str | list[str]}
#   choice  -> value = 选项序号 (0-based) 或 字母 "A"/"B"
#   fill    -> value = "A-avocation" 或 ["A-...", "B-..."]（每空一个）
```

**语义校验必须在服务端做**（这是现在的盲点）：

1. `qIndex` 必须在范围内、不重复
2. choice：`value` 必须在选项数内
3. fill：**值个数必须等于 `blanks`** —— 不匹配直接报错，而不是静默填充
4. 校验通过后回读 `$data`，返回**实际落盘的答案映射**：

```json
{
  "state": "submitted",
  "result": {
    "submitted": true,
    "questions_answered": 6,
    "questions_total": 6,
    "echo": {
      "0": {"kind": "choice", "chosen": "B"},
      "5": {"kind": "fill", "blanks": ["A-avocation", "..."], "assigned": 7}
    }
  }
}
```

`echo` 是关键：**现在的 `submit: answered 5/6` 就是个未解之谜**（检查点 §23 #1）。
有了 echo，"哪一空没被算作已答"当场就看得见。

| Tool | 参数 |
|---|---|
| `elang_skip_article` | — |
| `elang_auto_answer` | — （先用 `answers.json` 题库尝试） |

### 5.4 验证码

| Tool | 参数 | 返回 |
|---|---|---|
| `elang_get_captcha` | — | 图片（**base64 或 resource**）+ `attempts_so_far` |
| `elang_solve_captcha` | `code: str` | 成功 → 推进到 `awaiting_answers` |

**图片如何交给支持视觉的 agent**：优先用 **MCP resource**（`image/png`），
因为那正是协议里为"把二进制交给模型"设计的机制；base64 只作回退。

关键：`elang_get_captcha` **不重试、不刷新**。刷新会让已输入的验证码失效
（检查点 §19.2 实测过），所以重试决策必须交给 agent。

### 5.5 会话

| Tool | 说明 |
|---|---|
| `elang_login` | 显式登录（首次或会话失效时） |
| `elang_session_info` | 是否有有效会话、profile 路径 |

## 6. 与文件 IPC 的关系

**过渡期**：Level 1 的 `ElangSession` 可以同时提供两种前端
（CLI 文件 IPC + 未来的 MCP），因为状态机是共享的。

**目标态**：MCP 成为唯一接口，`elang_current.json` / `elang_signal.json`
那套协议**退休**。`review.py` 保留作为**无 MCP 环境的回退**（例如用户在
纯终端里手动跑），但不再是主路径。

> 不建议"两套并行长期存在" —— 状态会分叉。同一时刻只允许一个前端驱动。

## 7. 必须解决的技术风险

### 7.1 ✅ 已实测：沙箱到底禁的是什么（**结论已明确**）

原先我笼统记为"沙箱禁止创建管道"，**不准确**。`temp/probe_sandbox.py` 实测结果：

```
[probe] 1. subprocess with PIPED stdio
        rc=0 stdout='piped-ok'          <- Python 的 subprocess 管道是通的
[probe] 2. playwright launch_persistent_context
        FAILED: PermissionError: [WinError 5]
```

完整调用栈指向**确切位置**：

```
playwright/_impl/_transport.py:120   asyncio.create_subprocess_exec(...)
asyncio/windows_utils.py:136         stdin_rh, stdin_wh = pipe(overlapped=(False,True))
asyncio/windows_utils.py:63          _winapi.CreateFile(address, ...)   # \\.\pipe\...
PermissionError: [WinError 5] 拒绝访问。
```

**精确结论：**

| 机制 | 走什么 | 沙箱下 |
|---|---|---|
| `subprocess.run(capture_output=True)` | `_winapi.CreatePipe`（**匿名**管道） | ✅ 可用 |
| `asyncio.create_subprocess_exec(stdin=PIPE)` | `CreateFile` on `\\.\pipe\...`（**命名**管道） | ❌ WinError 5 |

→ **被禁的不是"管道"，而是 asyncio 在 Windows 上创建*命名*管道。**
而 Playwright 的 driver transport 恰好走这条路（`asyncio.create_subprocess_exec`）。

**对 MCP 的含义：**

- ❌ 沙箱内的 MCP server **无法**用 Playwright 的默认 transport 拉起浏览器
- ✅ 浏览器本身没问题，profile 路径也没问题（换成工作区内路径后，失败点依然
  是 `transport.connect()`，不是 `mkdir`）
- ✅ 因此**用 `async` Playwright API 就会踩到**；同步 API（`sync_playwright`）
  走 `subprocess` 而非 asyncio，**理论上可能不受影响** —— **值得实测**

**候选方案（已实测 A，结论如下）：**

| 方案 | 说明 | 评估 |
|---|---|---|
| **A. 用同步 Playwright API** | 期望绕开 asyncio 的命名管道 | ❌ **实测失败**。`sync_api` 内部就是 asyncio（`_context_manager.py:56  self._loop.run_until_complete(...)`），落到**同一个** `create_subprocess_exec` → WinError 5 |
| **B. server 跑在沙箱外** ✅ | 以 full access 启动 server，host 经 stdio 连 | **推荐**。已验证：full access 下一切正常 |
| **C. `connect_over_cdp`** | server 连既有浏览器，不拉 driver | 仍需 server 能自启浏览器；回到"手动起"问题 |

**最终结论（三条都已实测或已知）：**

> **任何使用 Playwright 的进程都无法在 DSH `workspace-write` 沙箱内启动浏览器**，
> 因为 Playwright 必然经 asyncio 在 Windows 上创建**命名**管道，而沙箱拒绝
> `CreateFile("\\.\pipe\...")`。这与同步/异步 API 无关，也与 profile 路径无关。

**因此 MCP 部署形态是确定的：MCP server 必须在沙箱之外运行。**
这不是缺陷，而是这台机器上的既定约束；在实际部署里表现为
"为 elang-mcp 配置 `danger-full-access`"（等价于当前脚本每次提权的做法，
但**只需配置一次**，而不是每次运行都要批准）。

**对设计的直接影响：**

1. server 的浏览器生命周期必须由**自己**完整管理（它拿得到权限）
2. **绝不能按进程名清理**（检查点 §19.1）—— server 必须自己 `context.close()`
3. profile 可以正常放 `~/.elang/`（full access 下无路径限制）

### 7.2 长驻进程的资源占用

浏览器 + server 常驻。需要：
- 空闲超时自动关浏览器（例如 10 分钟无 tool call）
- `elang_stop` 必须真正释放（记住：**不按进程名杀**，检查点 §19.1）

### 7.3 MCP SDK 依赖

当前 venv **没有 `mcp`**，需要加入 `requirements.txt`（Python 3.14 需确认兼容）。

### 7.4 答案语义的 0-based / 字母混用

`review.py` 现在接受 `0=A`（题号 0-based，选项字母）。
MCP 的 schema 要**明确固定一种**，我倾向：
- `qIndex`：0-based（与 `elang_current.json` 一致）
- `value`：choice 用**字母**（人/模型读起来不易错位），fill 用**选项 value 字符串**

并在 schema 里用 `enum` 约束 choice 的字母集合，让**工具层就能挡住非法输入**。

## 8. 实施阶段

| 阶段 | 内容 | 验证方式 | 风险 | 状态 |
|---|---|---|---|---|
| **0** | 实测 7.1：搞清沙箱到底禁的是哪一步 | 一个最小实验脚本 | — | ✅ **完成**（§24：命名管道） |
| **1** | 抽 `ElangSession`，显式状态机，去掉所有阻塞等待 | 能停在 `awaiting_answers` 且不阻塞 | 中 | ✅ **完成**（§27） |
| **2** | `elang-mcp` server 薄包装 Level 1 | MCP inspector 手工调每个 tool | 低 | ✅ **完成**（§28） |
| **3** | 接进 DSH，用真实 agent 跑完一篇 | 端到端 | 中 | 待做 |
| **4** | 文件 IPC 退休；`review.py` 降级为回退 | 回归 | 低 | 待做 |

### 阶段 1 已完成（`scripts/elang_session.py`）

| 之前 | 现在 |
|---|---|
| `AI_TIMEOUT=600` 阻塞等待 | 状态停在 `awaiting_answers`，**没有超时概念** |
| `answered 5/6` 无从解释 | `echo` + `incomplete` 直接指出哪题没落地 |
| 非法答案静默写入浏览器 | 5 类结构错误**提前拦截**并给出明确消息 |
| 只能靠读日志判断进度 | 每次返回 `state` + `next_actions` |

顺带把 `elang_reader.py` 改成**可安全导入**（凭据与题库惰性加载），
这是它能被当作库使用的先决条件。

## 9. 明确不做的事

- **不做并行多 run**：一个 server 一个浏览器一个 run，避免像这次这样两个进程抢同一个页面（检查点 §19.1）
- **不让 tool 阻塞等待**：如果将来真需要"等"，用 `elang_status` + 显式轮询，而不是挂住调用
- **不自动提交**：作答与提交分开（`submit_answers` 带 `dry_run`），给 agent 一个复核点
- **不内建 LLM**：server 只做浏览器自动化 + 校验，答题由 host 的模型做

## 10. 待确认的开放问题

1. **沙箱管道问题能否绕过**（7.1）—— 决定整个方案的可行性，**优先实测**
2. MCP 图片传输用 `resource` 还是 `base64`？取决于 host 支持度
3. 是否需要 `elang_preview_answers`（只校验不提交）作为独立 tool？倾向：`dry_run` 参数足够
4. 多篇连续作答时，是否允许 agent 一次拿多篇？倾向不允许 —— 保持"一篇一答"的清晰边界
