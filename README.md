# 慧学外语阅读自动答题

[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-latest-green)](https://playwright.dev/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

通过 Playwright 自动化 + AI 答题，批量完成 [慧学外语](https://elang.zju.edu.cn) 平台上的英语阅读练习。

## 工作原理

```
浏览器(Edge) -> 提取文章内容 -> AI读取并作答 -> Vue组件提交 -> 下一篇
     ^                                                        |
     +---------- 每50篇暂停确认 / 验证码人工介入 ----------------+
```

1. 打开 Edge 浏览器，用户通过 CAS 登录一次
2. 遍历11个阅读主题，提取文章列表（支持已完成检测）
3. 逐篇点击进入 -> 提取文章+题目 -> 写入 `/tmp/elang_current.json`
4. AI 读取内容生成答案 -> 写入 `/tmp/elang_signal.json`
5. 脚本调用 Vue 组件方法 `check_answer()` + `to_submit()` 提交
6. 每个主题完成后保存断点，支持随时中断续传

## 快速开始

### 安装

```bash
pip install playwright
playwright install chromium
git clone https://gitee.com/tian_haoyuan/huixuewaiyu-skill.git
cd huixuewaiyu-skill
```

### 使用

```bash
# 一键刷完所有11个主题（约291篇文章）
python scripts/elang_reader.py batch-all

# 刷单个主题
python scripts/elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"

# 刷单篇文章
python scripts/elang_reader.py solve "https://elang.zju.edu.cn/#/read/praxis?log_id=XXX&resources_id=YYY"
```

## AI 答题协议

脚本通过 `/tmp` 目录下的文件与 AI 通信：

| 文件 | 写入方 | 用途 |
|------|--------|------|
| `elang_current.json` | 脚本 | 当前文章内容（文章、题目、选项） |
| `elang_signal.json` | AI | 答案或指令 |
| `elang_checkpoint.json` | 脚本 | 断点续传状态 |

### AI 写入答案格式

```json
{
  "status": "answers_ready",
  "answers": [[0, 0], [1, 2], [2, 1], [3, 3], [4, 0]]
}
```

- `[qIdx, optIdx]`: `qIdx` 为题号（从0开始），`optIdx` 为选项（0=A, 1=B, 2=C, 3=D）
- 跳过文章: `{"status": "skip"}`
- 继续/停止检查点: `{"status": "continue"}` / `{"status": "stop"}`

## 特性

- **断点续传**: 每个主题完成后自动保存进度，删除 `/tmp/elang_checkpoint.json` 可重新开始
- **已完成跳过**: 自动识别已学文章（Vue 数据 + 文本解析双重检测）
- **填空跳过**: 无选项的填空题自动提交空答案，不阻塞流程
- **50篇检查点**: 每完成50篇暂停等待确认，防止被封
- **验证码处理**: 检测到验证码后暂停，等待人工在浏览器中解决
- **支持 Cloze（完形填空）**: 自动处理20空的完形填空题
- **支持 True/False**: 自动处理判断题

## 目录结构

```
huixuewaiyu-skill/
├── README.md                      # 本文件
├── SKILL.md                       # Claude Code 技能定义
├── scripts/
│   └── elang_reader.py            # 主脚本（Playwright 自动化）
└── references/
    └── api_reference.md           # 慧学外语后端 API 参考
```

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

## 注意事项

- 需要 ZJU CAS 账号（首次登录时手动完成）
- 需要 Edge 浏览器
- 脚本运行期间请勿关闭浏览器窗口
- 大量连续请求可能触发验证码，届时脚本会暂停等待人工解决
- 仅供学习用途，请合理使用

## License

MIT
