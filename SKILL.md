---
name: huixuewaiyu-readingpart
description: Automate English reading exercises on 慧学外语 (elang.zju.edu.cn). Use this skill whenever the user wants to complete reading comprehension questions on elang.zju.edu.cn, mentions "慧学外语", "elang", "英文阅读", or needs help with ZJU English reading homework. Triggers on URLs containing elang.zju.edu.cn, mentions of 慧学外语阅读, or requests to batch-complete reading exercises.
---

# 慧学外语阅读自动答题

通过 Playwright 驱动 elang.zju.edu.cn 的 **PC 版界面**，读取文章与题目，
交由你（agent）作答，再用应用自己的方法提交。

工具已经装好时，一切从 **`elang`** 命令开始。**不要再去找仓库里的 `.venv` 或
用 `python scripts/...`** —— 那是开发布局，不是使用方式。

> 改代码前读 `MIGRATION_CHECKPOINT.md`：那里有实测事实与被推翻的假设。

---

## 四条必须记住的规则

**1. 凭据放工作区根目录的 `.env`**

```
1. $ELANG_ENV_FILE       显式指定
2. <工作目录>/.env         工作区根 ← 约定位置
3. ~/.elang/.env         兜底
   —— 环境变量 ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 优先于以上任何文件
```

所有 agent 运行命令时的工作目录都是工作区根，所以 `./.env` 天然正确。
**先跑 `elang doctor`**，它会显示实际读的文件与每个值的来源，不要假设。

**2. 浏览器不要预设版本或路径**

需要哪个构建取决于 Playwright 版本，写死会过时。
**先跑 `elang doctor`**；缺失时装：`elang install-browser`
（默认装到工具私有缓存 `~/.elang/browsers`，已有可用构建时什么都不做）。

**3. 不要阻塞等待**

MCP 模式下**没有任何 tool 会等待**。
CLI 模式下只有 `elang run` 自己阻塞（它本就是长任务），**你侧的命令全部立即返回**。
绝不要用"挂着等 job 输出"的方式轮询 —— 那会让双方互相等待。

**4. 先查题库，再自己答**

题库覆盖的文章会自动完成，不要重复劳动。
MCP 的 `open_next` 命中时返回 `bank_answers`，直接拿去提交即可。
CLI 命中时脚本自己就提交了，根本不会来问你。

---

## 阶段一：确认环境（每次开始前）

```bash
elang doctor
```

按输出行动：

| 输出 | 行动 |
|---|---|
| `elang: command not found` | 没装。见「安装」一节，或让用户先装 |
| `browser ... FAILED` | `elang install-browser`（网络/TLS 报错直接重试） |
| 报 `EPERM` / `mkdtemp` | 把 `TEMP`/`TMP` 指向可写目录再试（doctor 会提示） |
| `env file ... (missing)` | `elang init-env` 生成模板，然后**让用户自己填密码** |
| `username/password ... missing` | 请用户填写 `.env`，**不要**把密码写进日志或对话 |
| `WARNING: ... OUTSIDE this interpreter's tree` | 依赖是借来的，换台机器会失效；重装工具 |
| 末行 `All good.` | 继续 |

**`doctor` 末尾不是 `All good.` 就不要往下走。**

---

## 阶段二：使用

两种方式**选其一**，不要同时驱动同一个浏览器。

### 方式 A：MCP（推荐，交互最清晰）

注册（若宿主还没有）：

```bash
elang setup-mcp --host <claude|dsh|codex>     # 会备份 + 校验 + 失败回滚
```

注册后工具以 **`mcp__elang__*`** 出现（server 名为 `elang`）：

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
  → elang_open_next            状态 awaiting_answers / awaiting_captcha / finished
  → （awaiting_captcha）elang_get_captcha → 读图 → elang_solve_captcha
  → （有 bank_answers）直接 submit_answers(bank_answers)
  → （没有）按正文作答 → elang_submit_answers
  → 重复 open_next 直到 finished
elang_stop
```

**作答格式**：`answers` 是 `[[qIndex, value], ...]`

- `qIndex` 为 **0 起**的题号（`open_next` 返回值里有）
- **选择题**：`value` 是 **0 起**的选项序号
- **填空题**：`value` 是**数组**，每个空一个值，长度必须等于 `blanks`

**提交后必须检查返回的两个字段**：

- `echo` —— 实际落进去的值
- `incomplete` —— 没有回读为已答的题；**非空就说明没答全**

`open_next` 若返回 `bank_note`，那是"标题命中了题库但没采用"的原因
（通常是题目数量与题库记录不一致），照常自己答。

### 方式 B：CLI（回退路径，你负责答题）

```bash
elang run batch-all                        # 全部主题（220 篇）
elang run batch 26                         # 单个主题
elang run batch-all --subjects-only        # 只列主题，零风险
elang run batch-all --limit 1 --dry-run    # 安全试跑
```

**首次务必先 `--subjects-only` 或 `--limit 1 --dry-run`**，
确认路径与登录都正常，再放开全量。

#### 你（agent）就是答题方

题库覆盖的文章脚本会自己提交，**剩下的需要你答**：它会写题目然后等待。

**这一步最容易搞错**：`elang run` 在**它自己那个后台 job 里**阻塞是正常的；
**你不要等它的输出**。正确循环：

```
1. 把 `elang run batch-all` 作为后台 job 启动
2. 轮询（非阻塞，立即返回）：
       elang pending --brief
   看 status=：
       waiting_for_ai    -> 有文章待答，进入第 3 步
       checkpoint        -> 每 50 篇的断点，用 elang continue 或 elang stop
       其他 / 文件不存在   -> 还在跑或已结束，继续轮询
3. 读题目： elang pending
4. 作答：
       elang answer 0=A 1=C              选择题给选项字母（题号从 0 开始）
       elang answer "5=A,B,C"            填空题每空一个值，逗号分隔
       elang answer --raw '[[0,1],[5,["A-x"]]]'
   词库填空给字母即可，工具会映射成选项的 value
5. 回到第 2 步，直到 job 结束
```

**绝不要**用 `job_output(wait=true)` 之类"挂着等输出"的方式轮询。

**不答的后果**：`elang run` 等 600s 超时，那篇标记 `timeout` 并跳过。
拿不准就用 `elang skip`（原样提交，不计分但不阻塞）。

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

**如果 OCR 认不准，不要反复猜** —— 交接给用户，连续错会触发更多验证码。

---

## 关于 IPC 目录

`<ipc>` = `$ELANG_TMP_DIR`，否则 Windows 用 `C:/tmp`、其他平台 `/tmp`。

用途：

| 文件 | 用途 |
|---|---|
| `elang_captcha_request.json` / `elang_captcha.json` / `elang_captcha_image.png` | 验证码交接 |
| `elang_session.json` | cookies + localStorage 复用（**必需**，见下） |
| `elang_checkpoint.json` | 断点：已完成主题与总数 |
| `elang_current.json` / `elang_signal.json` | **仅 CLI 模式**：你与 `elang run` 之间的答题交接 |

**CLI 模式的答题确实走文件**，但你不需要手写它们 —— 用 `elang pending` /
`elang answer` 即可（它们只是这两组文件的便捷封装）。

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

## 安装（工具没装时）

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
elang install-browser        # uv 只装 Python 环境，不装浏览器二进制
elang init-env               # 生成 .env 模板
elang doctor                 # 到这一步应为 All good.
```

装 skill（让 agent 能发现本契约）：

```bash
elang install-skill --agent <dsh|codex|claude> --scope <global|project>
```

`uv` 不存在时：**告诉用户，不要擅自安装**（那是系统级决定）。

## 环境要求

- Python 3.11+
- `uv`（安装工具用）
- Chromium（`elang install-browser` 负责）
- ZJU CAS 账号

**不要**把依赖装进系统 Python，也不要用 `--system-site-packages` 借系统包 ——
那会让工具换台机器就失效。`elang doctor` 会检测并警告。

### 沙箱说明（实测）

Playwright **无法**在文件沙箱内启动浏览器：它的 driver 走
`asyncio.create_subprocess_exec`，在 Windows 上需要**命名**管道，
而受限沙箱拒绝 `CreateFile("\\.\pipe\...")`（WinError 5）。
同步 API 也一样（内部就是 asyncio）。

所以驱动浏览器需要更宽的权限；**MCP server 也必须在沙箱外运行**，
否则 `elang_status` 正常但 `elang_start` 会失败。

### 会话保持

持久化 profile **本身不保留 CAS 会话** —— `iPlanetDirectoryPro` 与 zjuam 的
`JSESSIONID` 是会话 cookie，会被丢弃。所以 `<ipc>/elang_session.json`
的显式重放**是必需的，不是优化**。令牌有效期约 2 小时，工具会在到期前刷新。
