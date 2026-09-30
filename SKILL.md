---
name: huixuewaiyu-readingpart
description: Automate English reading exercises on 慧学外语 (elang.zju.edu.cn). Use this skill whenever the user wants to complete reading comprehension questions on elang.zju.edu.cn, mentions "慧学外语", "elang", "英文阅读", or needs help with ZJU English reading homework. Triggers on URLs containing elang.zju.edu.cn, mentions of 慧学外语阅读, or requests to batch-complete reading exercises.
---

# 慧学外语阅读自动答题

通过 Playwright 驱动 elang.zju.edu.cn 的 **PC 版界面**，读取文章与题目，
交由你（agent）作答，再用应用自己的方法提交。

> **改动代码前请先读 `MIGRATION_CHECKPOINT.md`** —— 那里记录了站点改版后的
> 实测事实、被推翻的假设，以及踩过的坑。

---

## 三条必须记住的规则

**1. 凭据放工作区根目录的 `.env`**

```
1. $ELANG_ENV_FILE       显式指定
2. <工作目录>/.env         工作区根 ← 约定位置
3. ~/.elang/.env         兜底
   —— 环境变量 ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 优先于以上任何文件
```

所有 agent 运行命令时的工作目录都是工作区根，所以 `./.env` 天然正确。
**先运行 `doctor.py` 确认它实际读的是哪个文件**，不要假设。

**2. 浏览器不要预设版本或路径**

需要哪个浏览器构建取决于 Playwright 版本，写死会过时。
**先跑 `elang doctor`**，它报告浏览器是否可用；缺失时装它：
`elang install-browser`（默认装到工具私有缓存 `~/.elang/browsers`）。

**3. 不要阻塞等待**

MCP 模式下**没有任何 tool 会等待**：每步立即返回状态与可执行的下一步。
不要用"挂着等输出"的方式轮询 —— 那会让双方互相等待。

---

## 阶段一：确认环境（每次开始前）

```bash
$PY scripts/doctor.py
```

按输出行动：

| 输出 | 行动 |
|---|---|
| `browser launch: FAILED` | 运行 `elang install-browser`（或按 doctor 打印的命令） |
| 报 `EPERM` / `mkdtemp` | 先把 `TEMP`/`TMP` 指向可写目录再试（doctor 会提示） |
| `env file ... (missing)` | 运行 `$PY scripts/init_env.py` 生成模板 |
| `username/password MISSING` | 请用户填写 `.env`，**不要**把密码写进日志或对话 |
| `WARNING: ... OUTSIDE this interpreter's tree` | 依赖是借来的，换台机器会失效；重建隔离 venv |
| 全部 ok | 继续 |

`$PY` 是本项目的解释器：

```powershell
# Windows
$PY = ".venv\Scripts\python.exe"
# Linux / macOS
PY=.venv/bin/python
```

若 `.venv` 不存在，先运行 `python scripts/setup.py`。

---

## 阶段二：使用

两种方式**选其一**，不要同时驱动同一个浏览器。

### 方式 A：MCP（推荐，交互更清晰）

若宿主已注册 `elang-mcp`，工具以 `mcp__elang__*` 出现：

```
elang_start(dry_run, limit)      打开浏览器并登录
elang_status()                   查看状态（绝不启动浏览器）
elang_list_subjects()            主题列表
elang_list_lessons(subject_id)   某主题的文章列表
elang_open_next()                推进到下一篇 → 返回正文与题目
elang_submit_answers(answers)    提交答案
elang_get_captcha()              取验证码图片
elang_solve_captcha(code)        提交验证码
elang_skip_article()             原样提交
elang_stop()                     关闭
```

典型循环：

```
elang_start
  → elang_open_next            状态 awaiting_answers 或 awaiting_captcha
  → （若 awaiting_captcha）elang_get_captcha → 读图 → elang_solve_captcha
  → 按正文作答 → elang_submit_answers
  → 重复 open_next 直到 finished
elang_stop
```

**作答格式**：`answers` 是 `[[qIndex, value], ...]`

- `qIndex` 为 **0 起**的题号（`open_next` 的返回值里有）
- **选择题**：`value` 是 0 起的选项序号
- **填空题**：`value` 是**数组**，每个空一个值，长度必须等于 `blanks`

提交后返回值含 `echo` 与 `incomplete` —— **务必检查 `incomplete`**，
它列出没有回读为已答的题。

### 方式 B：CLI

```bash
$PY scripts/elang_reader.py batch-all                        # 全部主题（220 篇）
$PY scripts/elang_reader.py batch 26                         # 单个主题
$PY scripts/elang_reader.py batch-all --subjects-only        # 只列主题，零风险
$PY scripts/elang_reader.py batch-all --limit 1 --dry-run    # 安全试跑
```

**首次务必先 `--subjects-only` 或 `--limit 1 --dry-run`**，
确认路径与登录都正常，再放开全量。

---

## 阶段三：验证码

验证码是**题目页的闸门** —— 题目只有通过验证码后才加载。处理顺序：

1. **ddddocr 自动识别**（最多 3 次；若图片没换就停止重试，避免死循环）
2. **交接**：图片写到 `<ipc>/elang_captcha_image.png`，
   请求写到 `<ipc>/elang_captcha_request.json`
   → 你读图片，把 `{"captcha_code":"XXXX"}` 写到 `<ipc>/elang_captcha.json`
3. **人工**：设 `ELANG_CAPTCHA_MANUAL=1`，脚本完全不碰 `verifyCode`，
   等用户在页面上自己输入

**为什么人工模式要"完全不碰"**：输错会让应用刷新图片，
从而**清掉用户已输入的内容**。

MCP 模式下用 `elang_get_captcha` / `elang_solve_captcha`，逻辑相同。

---

## 关于 IPC 目录

`<ipc>` = `$ELANG_TMP_DIR`，否则 Windows 用 `C:/tmp`、其他平台 `/tmp`。

该目录用于验证码交接与会话保存（`elang_session.json`）。
**答案不再通过文件传递** —— 旧的 `elang_current.json` / `elang_signal.json`
协议已归档（见 `archive/README.md`），原因是双方轮询会互相阻塞。

---

## 站点结构（PC 版）

| 路由 | 组件 | 关键数据 |
|---|---|---|
| `#/pc/read/index` | `PcReadIndex` | `$data.listData` |
| `#/pc/read/learn?subject_id=` | `PcReadLearn` | `$data.resourceList` |
| `#/pc/read/praxis?log_id=&resources_id=` | `PcReadPraxis` | `$data.jobList` |

- **`toPraxis(item)` 由服务端签发 `log_id`**，所以 praxis URL 不能手工拼
- **完成状态**用应用自己的 `normalizeStatus`（`status===2` 或 `hisLabel===1`）
- **作答**：选择题 `selectOption()`；填空题 `insertWordAnswers[jobId]`（每空一个值）
- **提交**是两步：`openSubmitConfirm()` → `confirmSubmit()`

### Vue 访问的陷阱

`page.evaluate` **返回**对象给的是副本，而 Vue 实例**根本无法序列化到 Python**。
把实例当参数传回去只会得到空值，所有字段读成 0 —— 这正是曾经
"同一页面一处说有验证码图、另一处说没有"的原因。
所以实例**钉在页面里**（`window.__elangPraxisVm` / `window.__elangLearnVm`），
所有读取都在浏览器内部完成。

---

## 环境要求

- Python 3.11+
- `uv`（推荐，用于建隔离环境）
- Chromium 浏览器（用 `doctor.py` 确认）
- ZJU CAS 账号

**不要**把依赖装进系统 Python，也不要用 `--system-site-packages` 借系统包 ——
那会让工具换台机器就失效。`doctor.py` 会检测并警告这种情况。

### 沙箱说明（实测）

Playwright **无法**在文件沙箱内启动浏览器：它的 driver 走
`asyncio.create_subprocess_exec`，在 Windows 上需要**命名**管道，
而受限沙箱拒绝 `CreateFile("\\.\pipe\...")`（WinError 5）。
同步 API 也一样（内部就是 asyncio）。

所以驱动浏览器需要更宽的权限；MCP server 也必须在沙箱外运行。
详见 `MCP_DESIGN.md`。
