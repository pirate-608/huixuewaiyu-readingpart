# 慧学外语阅读自动答题

Playwright 自动化 + AI 答题，批量完成[慧学外语](https://elang.zju.edu.cn)英语阅读练习。

> **致谢** — 本项目基于开源项目 [shixu2026/huixuewaiyu-skill](https://gitee.com/shixu2026/huixuewaiyu-skill) 开发，感谢原作者 [shixu2026](https://gitee.com/shixu2026) 的贡献。

## 交给 agent 一句话搞定

不用自己一步步装。把下面这句复制给 agent（DSH / Codex / Claude Code 都行）：

```
读 https://github.com/pirate-608/huixuewaiyu-readingpart 的 SETUP.md，
按里面的步骤帮我装好这个工具。我是 <DSH / Codex / Claude Code> 用户。
```

agent 会读完 [`SETUP.md`](SETUP.md) 里的约定，然后自己完成：装工具 → 装浏览器 →
生成凭据模板（**密码由你自己填，agent 不读**）→ 注册 skill → 注册 MCP，
每步都有验证，失败会报原始错误而不是跳过。

想手动装的话看下面的[快速开始](#快速开始)。

## 特性

- **CAS 自动登录** — 凭据放工作区 `.env`，无需手动登录
- **验证码 OCR** — ddddocr 自动识别；识别不出时交接给视觉模型或人工
- **断点续传** — 每个主题完成后保存进度
- **已完成跳过** — 用应用自己的 `normalizeStatus` 判断，与界面一致
- **零阻塞作答** — MCP 工具每步立即返回状态，不存在超时协商
- **自我诊断** — `elang doctor` 报告环境/浏览器/凭据并给出修复命令
- **跨平台** — Windows / Linux / macOS

## 三个独立产物

| 产物 | 安装方式 | 职责 |
|---|---|---|
| **工具** | `uv tool install` | MCP server + 求解器。自带隔离环境，提供 `elang` 命令 |
| **skill** | `elang install-skill` | **只有文档与契约** —— 告诉 agent 该跑什么命令 |
| **本仓库** | `git clone` | 承载两者；开发用，也可脱离工具独立运行 |

工具的依赖装在 **uv 自己的隔离环境**里，**不碰系统 Python**。

---

## 快速开始

### 1. 装工具

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

### 2. 装浏览器

`uv tool install` 只建 Python 环境，**不装浏览器二进制**，所以这一步是分开的：

```bash
elang install-browser
```

它会先检查是否已有可用构建，**有就什么都不做**；缺失时装到工具的私有缓存
（`~/.elang/browsers`）。用 `--shared` 可装到 Playwright 的共享缓存。

### 3. 配置凭据

```bash
elang init-env      # 在工作区根生成 .env 模板
```

然后在 `.env` 里填写：

```
CAS_USERNAME=你的学号
CAS_PASSWORD=你的密码
```

凭据仅本地存储，不会上传。

### 4. 确认环境

```bash
elang doctor
```

它会报告依赖、浏览器、凭据的实际状态，并**打印需要执行的命令**。
输出末尾出现 `All good.` 即可开始使用。

### 5. 注册 skill（可选）

想让 agent 直接使用：

```bash
elang install-skill                                   # 全局，所有检测到的 agent
elang install-skill --agent claude                    # 只装 Claude Code
elang install-skill --agent dsh,codex --scope project # 装进当前项目
elang install-skill --scope all                       # 全局 + 项目
elang install-skill --check                           # 只看状态
elang install-skill --uninstall --agent claude
```

**`--agent`**：`dsh` / `codex` / `claude`（逗号分隔，默认所有检测到的）。
注意 **DSH 与 Codex 共享 `~/.agents/skills`**，所以给两者安装只写一个目录。

**`--scope`**：
- `global`（默认）—— 所有项目可用，不在你的仓库里留下任何东西
- `project` —— 装在项目内，**优先级高于全局**（DSH 把项目根排在 100/200，
  全局排在 400/500）；因为位于项目内，**可以提交**给协作者
- `all` —— 两者都装

项目根取当前目录最近的含 `.git` / `pyproject.toml` / `SKILL.md` 的祖先目录，
也可用 `--project-root` 指定。

---

## 使用

### 作为 skill

在 agent 里说「慧学外语刷题」或 `/huixuewaiyu-readingpart`。

### 通过 MCP

生成注册文件（含各宿主说明）：

```bash
elang setup-mcp
```

工具以 `mcp__elang__*` 出现：

```
elang_start          打开浏览器并登录
elang_status         查看状态（不会启动浏览器）
elang_list_subjects  主题列表
elang_open_next      推进到下一篇 → 返回正文与题目
elang_submit_answers 提交答案
elang_get_captcha / elang_solve_captcha
elang_skip_article   原样提交
elang_stop           关闭
```

**没有任何工具会阻塞等待** —— 每步立即返回当前状态与可执行的下一步，
所以不需要超时协商。

作答格式是 `[[qIndex, value], ...]`：选择题给 0 起的选项序号；
**填空题给数组，每个空一个值**，长度必须等于空格数。提交后返回里含
`incomplete`，**请检查它** —— 列出没有回读为已答的题。

### 命令行

```bash
elang run batch-all                              # 全部主题（220 篇）
elang run batch 26                               # 单个主题
elang run solve "<praxis-url>"                   # 单篇
elang run batch-all --subjects-only              # 只列主题，零风险
elang run batch-all --limit 1 --dry-run          # 安全试跑
```

**首次务必先 `--subjects-only` 或 `--limit 1 --dry-run`**，确认路径与登录正常再放开全量。

### 其他命令

| 命令 | 作用 |
|---|---|
| `elang doctor` | 环境 / 浏览器 / 凭据报告 |
| `elang init-env` | 生成 `.env` 模板 |
| `elang install-browser` | 安装 Chromium |
| `elang install-skill` | 注册 skill |
| `elang setup-mcp` | 生成 `.mcp.json` |
| `elang list` | 列出全部子命令 |

---

## 凭据在哪

全项目只有一处实现（`scripts/config.py`）：

```
1. $ELANG_ENV_FILE                     显式指定路径
2. <工作目录>/.env                      工作区根 ← 约定位置
3. ~/.elang/.env                       兜底
   —— 另外：ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 环境变量优先于以上任何文件
```

**为什么是「工作目录」**：所有 agent（DSH / Claude Code / Codex）运行命令时，
工作目录都是工作区根 —— 这是它们的共同契约。所以 `./.env` 天然正确，
**不需要任何 agent 特定逻辑**。

**为什么环境变量优先**：MCP 宿主可以在启动工具时注入凭据，
且陈旧的 `.env` 不应覆盖宿主给的值。

> 注意：`elang doctor` 会显示**实际读取的文件**和每个值的来源
> （`from file:CAS_USERNAME` 或 `from environment`）。

---

## 覆盖主题

索引页 `#/pc/read/index` 给出 11 个主题，共 **220 篇**：

| subject_id | 主题 | 文章数 |
|---|---|---|
| 26 | 旅游与交通 | 6 |
| 25 | 历史与文化 | 14 |
| 24 | 文学与艺术 | 15 |
| 23 | 职业与发展 | 15 |
| 22 | 运动与娱乐 | 7 |
| 21 | 学习与教育 | 32 |
| 14 | 商业与经济 | 16 |
| 13 | 科技与创新 | 41 |
| 12 | 健康与生命 | 31 |
| 11 | 自然与农业 | 19 |
| 9 | 家庭与社会 | 24 |
| **合计** | | **220** |

## 工作原理

```
CAS 自动登录（.env 凭据）
  ↓
#/pc/read/index      读取主题列表（PcReadIndex.$data.listData）
  ↓
#/pc/read/learn      读取文章列表与完成状态（PcReadLearn.$data.resourceList）
  ↓
调用 toPraxis(item)  由服务端签发 log_id，路由到
#/pc/read/praxis     题目（PcReadPraxis.$data.jobList）
  ↓
验证码闸门           题目只有通过验证码后才加载
  ↓
作答                 选择题 selectOption()；填空题 insertWordAnswers[]（每空一个值）
  ↓
两步提交             openSubmitConfirm() → confirmSubmit()
```

## 目录结构

```
huixuewaiyu-readingpart/
├── pyproject.toml              # 打包配置（hatchling）
├── README.md                   # 本文件
├── SKILL.md                    # skill 契约（三平台共用）
├── CLAUDE.md                   # 面向 agent 的项目指引
├── .env.example                # 凭据模板
├── .mcp.json.example           # MCP 注册模板（实际文件由 setup-mcp 生成）
├── requirements.txt
├── src/elang/
│   ├── __init__.py             # 让平铺模块在两种布局下都能按裸名导入
│   └── cli.py                  # elang 命令的唯一入口
├── scripts/                    # 实现真源（构建时打进 wheel）
│   ├── config.py               # 凭据解析（全项目唯一实现）
│   ├── doctor.py               # 环境/浏览器/凭据诊断
│   ├── init_env.py             # 生成 .env 模板
│   ├── install_browser.py      # 安装 Chromium
│   ├── install_skill.py        # 注册到各 agent 根目录
│   ├── setup_mcp.py            # 生成 .mcp.json
│   ├── elang_reader.py         # 浏览器自动化核心 + 批处理 CLI
│   ├── elang_session.py        # 显式状态机（零阻塞）
│   ├── elang_mcp.py            # MCP server（10 个 tool）
│   └── setup.py                # 克隆本仓库后的一键安装
├── references/                 # 题库（answers.json 同时打进 wheel）
└── archive/                    # 已过时的实现与文档（见 archive/README.md）
```

### 从源码安装（开发）

```bash
git clone https://github.com/pirate-608/huixuewaiyu-readingpart.git
cd huixuewaiyu-readingpart
python scripts/setup.py          # 装工具 + 注册 skill + 报告状态
```

仓库也可以**脱离工具独立运行**：

```bash
python scripts/elang_reader.py batch-all
python scripts/doctor.py
```

## 依赖

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) —— 用于安装工具（推荐）
- Chromium —— 由 `elang install-browser` 安装
- ZJU CAS 账号

**不要**把依赖装进系统 Python，也不要用 `--system-site-packages` 借系统包 ——
那会让工具换台机器就失效。`elang doctor` 会检测并警告这种情况。

## 注意事项

- 运行期间请勿关闭浏览器窗口
- 连续做若干篇后平台会弹验证码；OCR 失败时会交接给视觉模型或人工
- 应用令牌有效期约 2 小时，长跑时会在到期前自动刷新
- 仅供学习用途，请合理使用

## 文档

| 文件 | 内容 |
|---|---|
| [`MIGRATION_CHECKPOINT.md`](MIGRATION_CHECKPOINT.md) | 站点改版后的实测事实、踩过的坑、被推翻的假设 |
| [`MCP_DESIGN.md`](MCP_DESIGN.md) | MCP 化的设计依据与分层实施计划 |
| [`DISTRIBUTION.md`](DISTRIBUTION.md) | DSH / Codex / Claude Code 三平台分发设计 |
| [`archive/README.md`](archive/README.md) | 归档了什么、为什么 |

## License

MIT
