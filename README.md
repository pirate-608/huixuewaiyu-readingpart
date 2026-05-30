# 慧学外语阅读自动答题

> **Claude Code Skill** — `/huixuewaiyu-readingpart` 一键刷完 ~291 篇英语阅读

[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-latest-green)](https://playwright.dev/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

Playwright 自动化 + AI 答题，批量完成[慧学外语](https://elang.zju.edu.cn)英语阅读练习。

> **致谢** — 本项目基于开源项目 [shixu2026/huixuewaiyu-skill](https://gitee.com/shixu2026/huixuewaiyu-skill) 开发，感谢原作者 [shixu2026](https://gitee.com/shixu2026) 的贡献。

## 特性

- **CAS 自动登录** — `.env` 配置学号密码，无需手动登录
- **验证码 OCR** — 4位数字验证码自动识别（ddddocr），10篇后触发
- **断点续传** — 每个主题完成后保存进度，删除 checkpoint 即可重来
- **已完成跳过** — Vue 数据 + 文本解析双重检测已学文章
- **50篇检查点** — 每完成50篇暂停确认，可随时停止
- **跨平台安装** — Linux/macOS/Windows 一键安装

## 快速开始

### 1. 安装

```bash
git clone https://gitee.com/tian_haoyuan/huixuewaiyu-readingpart.git
cd huixuewaiyu-readingpart

# Linux / macOS / Git Bash
bash install.sh

# Windows PowerShell
powershell -File install.ps1
```

`install.sh` / `install.ps1` 自动完成：检查 Python → pip install 依赖 → 安装 Chromium → 复制到 ~/.claude/skills/ → 交互式配置凭据。

### 2. 配置

安装时会引导你输入学号和密码，保存在 `.env`：

```
CAS_USERNAME=3250102110
CAS_PASSWORD=你的密码
```

也可手动复制 `.env.example` 为 `.env` 后填写。凭据仅本地存储，不上传。

### 3. 使用

在 **Claude Code** 中：

| 指令 | 效果 |
|------|------|
| `/huixuewaiyu-readingpart` | 启动技能，刷完所有主题 |
| `慧学外语刷题` | 同上，自然语言触发 |

也可以直接运行脚本：

```bash
# 全部 11 个主题（~291 篇）
python scripts/elang_reader.py batch-all

# 单个主题
python scripts/elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"

# 单篇文章
python scripts/elang_reader.py solve "<praxis-url>"
```

## 工作原理

```
┌─ CAS 自动登录 (.env 凭据) ──┐
├─ 遍历 11 个阅读主题 ────────┤
├─ 提取文章列表 (Vue 数据) ───┤
├─ 点击文章 → 提取内容 ───────┤
├─ 写入 C:/tmp/elang_current.json ─┤
├─ AI 读取、作答 ─────────────┤
├─ 写入 C:/tmp/elang_signal.json ──┤
├─ Vue check_answer() + submit() ─┤
├─ 验证码 OCR (ddddocr) ──────┤
├─ 50篇检查点 ────────────────┤
└─ 断点续传 ──────────────────┘
```

## AI 答题协议 (C:/tmp/)

| 文件 | 写入方 | 用途 |
|------|--------|------|
| `elang_current.json` | 脚本 | 当前文章（passage, questions） |
| `elang_signal.json` | AI | 答案或指令 |
| `elang_checkpoint.json` | 脚本 | 断点续传状态 |

AI 写入答案：

```json
{"status": "answers_ready", "answers": [[0,0],[1,2],[2,1],[3,3],[4,0]]}
```

- `[qIdx, optIdx]`: qIdx 为题号(0开始)，optIdx 选项(0=A,1=B,2=C,3=D)
- 跳过: `{"status": "skip"}`
- 继续: `{"status": "continue"}`
- 停止: `{"status": "stop"}`

## 覆盖主题

| # | 主题 | 文章数 |
|---|------|--------|
| 1 | 道路与交通 | 3 |
| 2 | 历史与文化 | 22 |
| 3 | 文学与艺术 | 12 |
| 4 | 职业与发展 | 18 |
| 5 | 运动与娱乐 | 6 |
| 6 | 学习与教育 | 59 |
| 7 | 商业与经济 | 26 |
| 8 | 科技与创新 | 38 |
| 9 | 社会与政治 | 36 |
| 10 | 自然与农业 | 22 |
| 11 | 家庭与生活 | 49 |
| **合计** | | **~291** |

## 目录结构

```
huixuewaiyu-readingpart/
├── README.md
├── SKILL.md                       # Claude Code 技能定义
├── requirements.txt               # Python 依赖
├── .env.example                   # 凭据模板
├── install.sh                     # Linux/macOS 安装脚本
├── install.ps1                    # Windows 安装脚本
├── scripts/
│   └── elang_reader.py            # Playwright 自动化主脚本
└── references/
    └── api_reference.md           # 慧学外语后端 API 参考
```

## 依赖

- Python 3.8+
- Edge 浏览器
- `playwright` — 浏览器自动化
- `python-dotenv` — 环境变量管理
- `ddddocr` — 验证码 OCR
- `Pillow` — 图像处理

## 注意事项

- 需要 ZJU CAS 账号
- 脚本运行期间请勿关闭浏览器窗口
- 连续刷 ~10 篇后平台弹出验证码，脚本自动 OCR 识别
- 部分特殊题型（填空等）脚本无法识别，会自动跳过
- 仅供学习用途，请合理使用

## License

MIT
