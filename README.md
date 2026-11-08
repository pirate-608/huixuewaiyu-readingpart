# 慧学外语阅读自动答题

Playwright 自动化 + AI 答题，批量完成[慧学外语](https://elang.zju.edu.cn)英语阅读练习。

> **致谢** 本项目基于开源项目 [shixu2026/huixuewaiyu-skill](https://gitee.com/shixu2026/huixuewaiyu-skill) 开发，感谢原作者 [shixu2026](https://gitee.com/shixu2026) 的贡献。

## 使用 agent 安装并配置

复制以下内容给 agent 执行：

```
读 https://github.com/pirate-608/huixuewaiyu-readingpart （Gitee 镜像 `https://gitee.com/pirate-608/huixuewaiyu-readingpart`）的 SETUP.md，
按里面的步骤帮我安装并配置这个工具。
```

手动安装见[快速开始](#快速开始)。

## 特性

- **CAS 自动登录**：凭据存放在工作区 `.env`，无需手动登录
- **验证码 OCR**：ddddocr 自动识别，识别失败时交接给视觉模型或人工
- **断点续传**：每个主题完成后保存进度
- **已完成跳过**：使用应用自身的 `normalizeStatus` 判断，与界面显示一致
- **零阻塞作答**：MCP 工具每步立即返回状态，不需要超时协商
- **自我诊断**：`elang doctor` 报告环境、浏览器与凭据状态，并给出修复命令

## 支持范围

**本工具仅支持 Windows 10/11（64 位）。** 

---

## 快速开始

### 1. 安装工具

先确认机器上已有 `uv`。Windows 上可以用 winget 安装：

```powershell
winget install --id=astral-sh.uv -e
```

然后安装工具：

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

国内网络访问 GitHub 不稳定时，改用 Gitee 镜像（只读副本，内容相同）：

```bash
uv tool install git+https://gitee.com/pirate-608/huixuewaiyu-readingpart.git
```

**可使用`@`锁定版本**（否则安装最新版本）

```bash
uv tool install "git+https://github.com/pirate-608/huixuewaiyu-readingpart.git@v0.1.1"
elang --version
```

**从源码构建（依赖 Python 3.11）**：

```bash
git clone https://github.com/pirate-608/huixuewaiyu-readingpart.git
python python3 -m venv venv
pip install -r requirements.txt
```
同样能得到 `elang` 命令。步骤见 [SETUP.md](SETUP.md) 的 1b。

**从压缩包构建**：

打开 **<https://elang-install.67656.fun/>**，下载 `elang-bundle-win64.zip`（约 66 MB），

解压后从其根目录运行
```bash
.\install.cmd
```
将会离线安装并配置elang命令，目标安装路径为 `%LOCALAPPDATA%\elang`。安装完成后需重启终端生效。


### 2. 安装浏览器

`uv tool install` 只建立 Python 环境，不安装浏览器二进制，因此这一步单独执行：

```bash
elang install-browser
```

命令按可用性选择，不重复劳动：

- 已有 Chromium 构建：什么都不做
- 没有构建但装了 Chrome 或 Edge：直接复用，不下载
- 两者都没有：安装 Chromium 到工具的私有缓存 `~/.elang/browsers`（约 683 MB）

`--bundled` 强制安装自带构建，`--shared` 安装到 Playwright 的共享缓存。
复用系统浏览器时 `elang doctor` 会写明用的是哪一个；想固定选择，设置
`ELANG_BROWSER=chrome`、`msedge` 或 `chromium`。

### 3. 配置凭据

```bash
elang init-env      # 在工作区根生成 .env 模板
```

然后在 `.env` 中填写：

```
CAS_USERNAME=你的学号
CAS_PASSWORD=你的密码
```

凭据仅存储于本地，不会上传。

### 4. 确认环境

```bash
elang doctor
```

该命令报告依赖、浏览器与凭据的实际状态。输出末尾为 `All good.` 时可以开始使用。

### 5. 注册 skill（可选）

```bash
elang install-skill                                   # 全局，所有检测到的 agent
elang install-skill --agent claude                    # 只装 Claude Code
elang install-skill --agent dsh,codex --scope project # 装进当前项目
elang install-skill --scope all                       # 全局与项目都装
elang install-skill --check                           # 只看状态
elang install-skill --uninstall --agent claude
```

`--agent` 取值为 `dsh`、`codex`、`claude`，逗号分隔，默认为所有检测到的宿主。
DSH 与 Codex 共享 `~/.agents/skills`，因此给两者安装只写一个目录。

`--scope` 取值：

- `global`（默认）：所有项目可用，不在仓库中留下文件
- `project`：安装在项目内，优先级高于全局（DSH 将项目根排在 100/200，全局排在 400/500）。
  由于位于项目内，可以提交给协作者
- `all`：两者都装

项目根取当前目录最近的、包含 `.git`、`pyproject.toml` 或 `SKILL.md` 的祖先目录，
也可用 `--project-root` 指定。

---

## 使用

### 作为 skill

在 agent 中说明需求，例如完成慧学外语的阅读题。

### 通过 MCP

生成注册配置：

```bash
elang setup-mcp --host <claude|dsh|codex>
```

工具以 `mcp__elang__*` 出现：

```
elang_start          打开浏览器并登录
elang_status         查看状态（不会启动浏览器）
elang_list_subjects  主题列表
elang_list_lessons   某主题的文章列表
elang_open_next      推进到下一篇，返回正文与题目
elang_submit_answers 提交答案
elang_get_captcha    获取验证码图片
elang_solve_captcha  提交验证码
elang_skip_article   原样提交
elang_stop           关闭
```

所有工具都会立即返回当前状态与可执行的下一步，不存在阻塞等待，因此不需要超时协商。

作答格式为 `[[qIndex, value], ...]`。选择题的 `value` 是从 0 开始的选项序号；
填空题的 `value` 是数组，每个空对应一个值，长度需与空格数一致。提交后的返回包含
`incomplete` 字段，列出未能回读为已答的题目，需要检查。

### 命令行

```bash
elang run batch-all                              # 全部主题（220 篇）
elang run batch 26                               # 单个主题
elang run solve "<praxis-url>"                   # 单篇
elang run batch-all --subjects-only              # 只列主题，不做改动
elang run batch-all --limit 1 --dry-run          # 安全试跑
```

首次使用建议先执行 `--subjects-only` 或 `--limit 1 --dry-run`，确认路径与登录正常
后再放开全量。

`elang run` 遇到题库未覆盖的文章时会暂停等待作答，此时由 agent 提供答案：

```bash
elang pending            # 查看题目，立即返回；--brief 只输出摘要
elang answer 0=A 1=C     # 选择题给字母；填空题每空一个值，例如 "5=A,B,C"
elang skip               # 原样提交
elang continue           # 继续（每 50 篇的断点）
elang stop               # 停止
```

`elang run` 会在后台等待。该进程的输出不需要等待，使用 `elang pending --brief`
轮询即可，该命令会立即返回。

### 其他命令

| 命令 | 作用 |
|---|---|
| `elang doctor` | 报告环境、浏览器与凭据状态 |
| `elang init-env` | 生成 `.env` 模板 |
| `elang install-browser` | 选浏览器：复用已装的 Chrome/Edge，或安装 Chromium |
| `elang install-skill` | 注册 skill |
| `elang setup-mcp` | 注册 MCP，`--host` 取 `claude`、`dsh` 或 `codex` |
| `elang pending` | 显示 `elang run` 正在等待的文章 |
| `elang answer 0=A 1=C` | 为待答文章提供答案 |
| `elang skip` / `continue` / `stop` | 配合 `elang run` 的控制命令 |
| `elang list` | 列出全部子命令 |

---

## 凭据

凭据解析只有一处实现（`scripts/config.py`），顺序如下：

```
1. $ELANG_ENV_FILE                     显式指定路径
2. <工作目录>/.env                      工作区根，约定位置
3. ~/.elang/.env                       兜底

键名两套都接受，带 ELANG_ 前缀的优先：
    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD
真实环境变量优先于以上任何文件，两套键名都适用。
```

使用工作目录作为锚点，是因为各 agent（DSH、Claude Code、Codex）执行命令时工作目录
都是工作区根。因此 `./.env` 始终是正确位置，不需要额外的探测逻辑。

环境变量优先于文件，是因为 MCP 宿主可以在启动工具时注入凭据，而陈旧的 `.env`
不应覆盖宿主提供的值。

键名有两套的原因：`.env` 中使用裸名 `CAS_USERNAME`，写法简短，且兼容本项目早期的
配置；环境变量中使用带前缀的 `ELANG_CAS_USERNAME`，避免与其他同样使用 `CAS_`
前缀的工具冲突。两个来源都接受两种写法，同时存在时带前缀的优先。

`elang doctor` 会显示实际读取的文件，以及每个值的来源
（`from file:CAS_USERNAME` 或 `from environment`）。

---

## 覆盖主题

索引页 `#/pc/read/index` 给出 11 个主题，共 220 篇：

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
├── SKILL.md                    # skill 契约，三平台共用
├── CLAUDE.md                   # 开发指引（Claude Code）
├── AGENTS.md                   # 同一份开发指引，供读取 AGENTS.md 的宿主
├── SECURITY.md                 # 凭据与登录态的存放、读取与已知风险
├── .env.example                # 凭据模板
├── .mcp.json.example           # MCP 注册模板，实际文件由 setup-mcp 生成
├── .githooks/pre-commit        # 提交前隐私检查，需手动启用
├── requirements.txt
├── src/elang/
│   ├── __init__.py             # 让平铺模块在两种布局下都能按裸名导入
│   └── cli.py                  # elang 命令的唯一入口
├── scripts/                    # 实现源，构建时打进 wheel
│   ├── config.py               # 凭据解析，全项目唯一实现
│   ├── doctor.py               # 环境、浏览器与凭据诊断
│   ├── init_env.py             # 生成 .env 模板
│   ├── install_browser.py      # 选择 / 安装浏览器
│   ├── install_skill.py        # 注册到各 agent 根目录
│   ├── setup_mcp.py            # 生成 MCP 注册
│   ├── elang_reader.py         # 浏览器自动化核心与批处理 CLI
│   ├── elang_session.py        # 显式状态机，零阻塞
│   ├── elang_mcp.py            # MCP server，10 个工具
│   └── setup.py                # 克隆本仓库后的一键安装
├── references/                 # 题库与站点接口说明，answers.json 同时打进 wheel
└── tools/                      # 仓库内的辅助工具，不随 skill 分发
    ├── bootstrap/              # 离线安装包：构建脚本与安装脚本
    ├── browser/                # 浏览器控制台脚本：人工提取答案 / 应急作答
    └── cloudflare/             # 安装入口 Worker（固定域名 / 版本解析）
```

### 从源码安装

```bash
git clone https://github.com/pirate-608/huixuewaiyu-readingpart.git
cd huixuewaiyu-readingpart
python scripts/setup.py          # 装工具、注册 skill、报告状态
```

首次克隆后建议启用提交钩子，用于阻断意外提交的隐私数据：

```bash
git config core.hooksPath .githooks
```

仓库也可以脱离工具独立运行：

```bash
python scripts/elang_reader.py batch-all
python scripts/doctor.py
```

## 依赖

- Windows 10/11（64 位）
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)，用于安装工具（推荐）
- 浏览器：`elang install-browser` 复用已装的 Chrome / Edge，或安装自带的 Chromium
- ZJU CAS 账号

不要把依赖装进系统 Python，也不要用 `--system-site-packages` 借用系统包，
否则工具换一台机器后会失效。`elang doctor` 会检测并警告这种情况。

## 常见问题

### 开启代理后无法登录慧学外语

慧学外语对访问来源有网络限制。在校园网内开启 TUN 模式、系统全局代理或浏览器代理插件后，
CAS 登录页可能无法打开，或者登录直接失败。这是站点侧的限制，与本项目无关。

本项目的两个阶段对网络的要求相反：

| 阶段 | 网络 |
|---|---|
| 安装：`uv tool install`、`elang install-browser`（需要下载时） | 需要访问 GitHub 与浏览器下载源，通常需要代理 |
| 运行：`elang run`、MCP | 需要直连慧学外语与 zjuam，不能走代理 |

处理方式是在代理软件中配置分流规则，让下列域名直连，其余流量走代理：

```
elang.zju.edu.cn
zjuam.zju.edu.cn
```

没有分流规则时，按顺序操作：开启代理完成安装，关闭代理后再运行。

反过来说，关闭代理后 `git clone`、`uv tool install`、需要下载的
`elang install-browser` 会失败。这类失败源于网络，不要反复重试；先确认代理状态再继续。

### 安装时连不上 GitHub

改用 Gitee 镜像安装，代码与 GitHub 相同，只读副本，随每次提交同步：

```bash
uv tool install git+https://gitee.com/pirate-608/huixuewaiyu-readingpart.git
```

镜像同步可能滞后几分钟。问题与 PR 仍到 GitHub 提交。

### 如何判断是网络问题还是工具问题

先在不使用代理的浏览器中打开 `https://elang.zju.edu.cn` 并尝试登录：

- 打不开或登录失败：属于网络或站点问题，与工具无关
- 能正常登录：继续排查工具侧，运行 `elang doctor`

`elang doctor` 只检查本地环境（依赖、浏览器、凭据），不会登录站点，任何时候都可以运行。

## 注意事项

- 运行期间请勿关闭浏览器窗口
- 连续做若干篇后平台会要求验证码，OCR 失败时交接给视觉模型或人工
- 应用令牌有效期约 2 小时，长时间运行会在到期前自动刷新
- 仅供学习用途，请合理使用

## 文档

| 文件 | 内容 |
|---|---|
| [`SKILL.md`](SKILL.md) | skill 契约与操作流程 |
| [`SETUP.md`](SETUP.md) | 安装与配置步骤 |
| [`CLAUDE.md`](CLAUDE.md) | 架构、依赖方向与开发命令 |
| [`AGENTS.md`](AGENTS.md) | 同一份开发指引的副本，供读取 AGENTS.md 的宿主 |
| [`SECURITY.md`](SECURITY.md) | 凭据与登录态怎么存、怎么读，以及已知风险 |
| [`DISTRIBUTION.md`](DISTRIBUTION.md) | 三平台分发与注册方式 |

## License

MIT，见 [`LICENSE`](LICENSE)。

上游项目 [shixu2026/huixuewaiyu-skill](https://gitee.com/shixu2026/huixuewaiyu-skill) 在其 README 中声明为 MIT，但仓库未附 LICENSE 文件。本项目沿用同一许可。
