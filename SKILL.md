---
name: huixuewaiyu-readingpart
description: Automate English reading exercises on 慧学外语 (elang.zju.edu.cn). Use this skill whenever the user wants to complete reading comprehension questions on elang.zju.edu.cn, mentions "慧学外语", "elang", "英文阅读", or needs help with ZJU English reading homework. Triggers on URLs containing elang.zju.edu.cn, mentions of 慧学外语阅读, or requests to batch-complete reading exercises.
---

> **读者：执行 agent**（用本 skill 答题）。
> 开发本项目的 agent 请参阅仓库中的 [CLAUDE.md](https://github.com/pirate-608/huixuewaiyu-readingpart/blob/master/CLAUDE.md)。
> 本文只说明使用方法，不包含实现细节。

# 慧学外语阅读自动答题

通过 Playwright 驱动 elang.zju.edu.cn 的 **PC 版界面**，读取文章与题目，
交由你（agent）作答，再用应用自己的方法提交。

工具已经装好时，一切从 **`elang`** 命令开始。**不要再去找仓库里的 `.venv` 或
用 `python scripts/...`。前者属于开发布局，不是使用方式。

---

## 四条必须记住的规则

**1. 凭据放工作区根目录的 `.env`**

```
1. $ELANG_ENV_FILE                     显式指定
2. <工作目录>/.env                      工作区根 ← 约定
3. ~/.elang/.env                       兜底

键名两套都认（带 ELANG_ 前缀的优先）：
    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD
真实环境变量优先于以上任何文件，两套键名都适用。
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
不要以等待 job 输出的方式轮询，那会让双方互相等待。

**4. 先查题库，再自己答**

题库覆盖的文章会自动完成，不要重复劳动。
MCP 的 `open_next` 命中时返回 `bank_answers`，直接拿去提交即可。
CLI 命中时由脚本直接提交，不会请求作答。

---

## 阶段一：确认环境（每次开始前）

```bash
elang doctor
```

按输出行动：

| 输出 | 行动 |
|---|---|
| `elang: command not found` | 未安装。参见下文安装一节，或请用户先行安装 |
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

- `echo`：实际写入的值
- `incomplete`：未能回读为已答的题目，非空表示没有答全

`open_next` 若返回 `bank_note`，那是"标题命中了题库但没采用"的原因
（通常是题目数量与题库记录不一致），照常自己答。

### 方式 B：CLI（回退路径，你负责答题）

```bash
elang run batch-all                        # 全部主题（11 个，共 220 篇）
elang run batch 26                         # 单个主题
elang run batch-all --subjects-only        # 只列主题，零风险
elang run batch-all --limit 1 --dry-run    # 安全试跑
```

**首次使用应先执行 `--subjects-only` 或 `--limit 1 --dry-run`**，
确认路径与登录都正常，再放开全量。

#### 你（agent）就是答题方

题库覆盖的文章脚本会自己提交，**剩下的需要你答**：它会写题目然后等待。

**此处容易出错**：`elang run` 在自身的后台任务中阻塞属于正常行为；
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

验证码是题目页的前置条件，题目只有在通过验证码后才会加载。处理顺序如下：

1. **ddddocr 自动识别**（最多 3 次；若图片没换就停止重试，避免死循环）
2. **交接**：图片写到 `<ipc>/elang_captcha_image.png`，
   请求写到 `<ipc>/elang_captcha_request.json`
   → 你读图片，把 `{"captcha_code":"XXXX"}` 写到 `<ipc>/elang_captcha.json`
3. **人工**：设 `ELANG_CAPTCHA_MANUAL=1`，脚本完全不碰 `verifyCode`，
   等用户在页面上自己输入

**为什么人工模式要"完全不碰"**：输错会让应用刷新图片，
从而**清掉用户已输入的内容**。

MCP 模式下用 `elang_get_captcha` / `elang_solve_captcha`，逻辑相同。

OCR 结果不确定时不要反复尝试，应交接给用户。连续出错会触发更多验证码。

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

**CLI 模式的答题通过文件传递**，但不需要手工写入，使用 `elang pending` /
`elang answer` 即可（它们只是这两组文件的便捷封装）。

---

## 工具内部做了什么（你不需要操作页面）

了解流程有助于判断卡在哪一步，但你**不需要**碰 DOM 或 Vue：

```
CAS 自动登录（.env 凭据）
  → 主题列表 → 文章列表（跳过已完成）
  → 调 toPraxis 让服务端签发 log_id，进入题目页
  → 验证码闸门（通过后题目才加载）
  → 作答 → 两步确认提交 → 回到文章列表
```

完成状态由应用自己的 `normalizeStatus` 判定，与界面显示一致。
每篇做完会更新 `<ipc>/elang_checkpoint.json`。

实现细节、站点组件名与 Vue 陷阱见仓库中的 [CLAUDE.md](https://github.com/pirate-608/huixuewaiyu-readingpart/blob/master/CLAUDE.md)。
那是**开发 agent** 的文档，不随 skill 分发。

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

**不要**把依赖装进系统 Python，也不要用 `--system-site-packages` 借用系统包，
那会让工具换台机器就失效。`elang doctor` 会检测并警告。

### 沙箱说明（实测）

Playwright **无法**在文件沙箱内启动浏览器：它的 driver 走
`asyncio.create_subprocess_exec`，在 Windows 上需要**命名**管道，
而受限沙箱拒绝 `CreateFile("\\.\pipe\...")`（WinError 5）。
同步 API 也一样（内部就是 asyncio）。

所以驱动浏览器需要更宽的权限；**MCP server 也必须在沙箱外运行**，
否则 `elang_status` 正常但 `elang_start` 会失败。

### 会话保持

持久化 profile **本身不保留 CAS 会话**。`iPlanetDirectoryPro` 与 zjuam 的
`JSESSIONID` 是会话 cookie，会被丢弃。所以 `<ipc>/elang_session.json`
的显式重放**是必需的，不是优化**。令牌有效期约 2 小时，工具会在到期前刷新。
