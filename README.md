# 慧学外语阅读自动答题

Playwright 自动化 + AI 答题，批量完成[慧学外语](https://elang.zju.edu.cn)英语阅读练习。

> **致谢** — 本项目基于开源项目 [shixu2026/huixuewaiyu-skill](https://gitee.com/shixu2026/huixuewaiyu-skill) 开发，感谢原作者 [shixu2026](https://gitee.com/shixu2026) 的贡献。

## 特性

- **CAS 自动登录** — 凭据放在工作区 `.env`，无需手动登录
- **验证码 OCR** — ddddocr 自动识别；识别不出时交接给视觉模型或人工
- **断点续传** — 每个主题完成后保存进度
- **已完成跳过** — 用应用自己的 `normalizeStatus` 判断，与界面一致
- **两种使用方式** — 作为 skill 使用（文档驱动），或接入 MCP（结构化 tool 调用）
- **跨平台** — Windows / Linux / macOS

## 快速开始

### 1. 安装

```bash
git clone https://github.com/pirate-608/huixuewaiyu-readingpart.git
cd huixuewaiyu-readingpart
python scripts/setup.py
```

`setup.py` 会：

1. 建一个**隔离的**虚拟环境并安装依赖（优先用 `uv`）
2. 把 skill 注册到各 agent 根目录（DSH / Codex / Claude Code）
3. 用 `doctor.py` 报告依赖、浏览器、凭据的状态

**浏览器单独装**（`uv tool install` 只管 Python 环境，不管浏览器二进制）：

```bash
elang install-browser     # 装到工具私有缓存 ~/.elang/browsers
```

`elang install-browser` 会先检查是否已有可用构建，有就什么都不做。
这是因为需要哪个浏览器构建取决于 Playwright 版本，写死会过时。

### 2. 配置凭据

```bash
python scripts/init_env.py     # 在正确位置生成 .env 模板
```

然后在生成的 `.env` 里填写：

```
CAS_USERNAME=你的学号
CAS_PASSWORD=你的密码
```

**凭据解析顺序**（全项目统一，实现见 `scripts/config.py`）：

```
1. $ELANG_ENV_FILE          显式指定路径
2. <工作目录>/.env            工作区根（推荐）
3. ~/.elang/.env            兜底
   —— 另外：真实环境变量 ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 优先于以上任何文件
```

为什么是"工作目录"而不是某种探测：**所有 agent（DSH / Claude Code / Codex）
运行命令时的工作目录都是工作区根**，这是它们的共同契约。
所以 `./.env` 天然就是正确位置，不需要任何 agent 特定逻辑。

凭据仅本地存储，不会上传。

### 3. 使用

#### 方式 A：作为 skill

在 agent 里说"慧学外语刷题"或 `/huixuewaiyu-readingpart`。

#### 方式 B：通过 MCP

```bash
python scripts/setup_mcp.py     # 生成 .mcp.json，并打印各宿主的注册说明
```

工具会以 `mcp__elang__*` 出现。调用顺序：

```
elang_start          → 打开浏览器并登录
elang_open_next      → 推进到下一篇文章（返回正文与题目）
elang_submit_answers → 提交答案
elang_stop           → 关闭
```

**没有任何 tool 会阻塞等待** —— 每步立即返回当前状态与可执行的下一步，
所以不需要超时协商。

#### 方式 C：命令行直接跑

```bash
# 全部主题
python scripts/elang_reader.py batch-all

# 单个主题（subject_id 或完整 URL）
python scripts/elang_reader.py batch 26

# 单篇文章
python scripts/elang_reader.py solve "<praxis-url>"

# 只列出主题，不做任何答题
python scripts/elang_reader.py batch-all --subjects-only

# 本次最多处理 1 篇（安全试跑）
python scripts/elang_reader.py batch-all --limit 1 --dry-run
```

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
├── README.md
├── SKILL.md                    # skill 定义（三平台共用）
├── CLAUDE.md                   # 面向 agent 的项目指引
├── requirements.txt
├── .env.example
├── .mcp.json.example           # MCP 注册模板（实际文件由 setup_mcp.py 生成）
├── scripts/
│   ├── setup.py                # 一键安装（建 venv + 注册 skill + 报告状态）
│   ├── doctor.py               # 报告依赖/浏览器/凭据状态并给出修复命令
│   ├── init_env.py             # 生成 .env 模板
│   ├── config.py               # 凭据解析（全项目唯一实现）
│   ├── install_skill.py        # 注册到各 agent 根目录
│   ├── setup_mcp.py            # 生成 .mcp.json
│   ├── elang_reader.py         # 批处理驱动（CLI）
│   ├── elang_session.py        # 显式状态机（MCP Level 1）
│   ├── elang_mcp.py            # MCP server（10 个 tool）
│   └── test_*.py               # 验证脚本
├── references/
│   ├── answers.json            # 题库
│   ├── answers.raw
│   └── parse_answers.py
└── archive/                    # 已过时的实现与文档（见 archive/README.md）
```

## 依赖

- Python 3.11+
- `uv`（推荐，用于建隔离环境；可选）
- 已安装的 Chromium（`doctor.py` 会告诉你缺不缺）
- ZJU CAS 账号

## 注意事项

- 需要 ZJU CAS 账号
- 运行期间请勿关闭浏览器窗口
- 连续做若干篇后平台会弹验证码；OCR 失败时会交接给视觉模型或人工
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
