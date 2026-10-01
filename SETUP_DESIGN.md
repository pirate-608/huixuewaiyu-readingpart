# 配置流程设计：提示词一键配置

目标：用户**复制一段提示词**给 agent，agent 自己完成「装工具 → 装浏览器 → 配凭据 →
注册 skill → 注册 MCP」，用户只填密码和回答一两个偏好问题。

---

## 1. 为什么提示词方案成立

| 步骤 | 为什么适合 agent | 为什么脚本做不好 |
|---|---|---|
| 判断当前环境 | agent **知道自己是谁**（DSH / Codex / Claude Code） | 脚本要猜 |
| 跑命令 | agent 会跑、会读输出、会重试 | — |
| 处理下载失败 | agent 能看懂"TLS 错误→重试"并重试 | 脚本只能报错退出 |
| 问用户偏好 | agent 能对话 | 脚本要交互式输入 |
| 凭据 | agent 知道**不该读密码内容** | 脚本会写进日志风险 |

**但关键前提**：agent **不应该手写配置文件**（缩进/格式极易出错）。
配置文件由**工具**用解析器安全生成。

分工：

```
提示词  → 告诉 agent 顺序、每步的验证方法、如何判断环境
工具    → 提供确定性、幂等、可校验的命令
```

---

## 2. 三个 agent 的 MCP 注册方式（已实测查证）

| Agent | 文件 | 格式 | 顶层结构 |
|---|---|---|---|
| **Claude Code** | 项目 `.mcp.json` | JSON | `{"mcpServers": {...}}` |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | YAML | 顶层**数组**，每项 `{id, name, config}` |
| **Codex** | `~/.codex/config.toml` | TOML | `[mcp_servers.<name>]` 表 |

**三者格式完全不同**，所以 `setup-mcp` 必须按 host 分支。

### 各自的条目

**Claude Code**（`.mcp.json`，项目级）

```json
{"mcpServers": {"elang-reading": {"command": "<elang>", "args": ["mcp"]}}}
```

**DSH**（追加到 `cordis.patch.yml` 末尾）

```yaml
  - id: mcp-elang
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: elang
      transport: stdio
      command: '<elang>'
      args: ['mcp']
      toolCallTimeoutMs: 120000
      failOnStartupError: true
```

**Codex**（追加到 `config.toml` 末尾）

```toml
[mcp_servers.elang]
command = "<elang>"
args = ["mcp"]
startup_timeout_sec = 120
```

（`transport` 字段在 Codex 里不存在 —— 默认即 stdio；字段名参考同文件已有的
`[mcp_servers.unityMCP]`。）

---

## 3. `elang setup-mcp --host {claude,dsh,codex,all}` 契约

### 3.1 行为

```
1. 定位目标文件
   --scope project|global （claude 支持两者；dsh/codex 只有 global）
2. 读现有内容 → 解析
3. 幂等检查：已存在同名条目 → 报告并退出（--force 才覆盖）
4. 备份（<file>.bak-YYYYmmdd-HHMMSS）
5. 结构化追加（用解析器，不拼字符串）
6. **重新解析校验**；不合法 → 自动回滚备份并报错
7. 打印 diff（只打印新增部分）
```

### 3.2 安全属性（必须）

- **幂等**：重复运行不产生重复条目
- **原子**：先写临时文件再替换，避免写坏配置
- **可回滚**：校验失败自动还原
- **不打印配置内容**：`~/.codex/config.toml` 含 API key 明文，
  **只能读改指定区域，绝不整体回显**
- **`--dry-run`**：只显示将写入什么

### 3.3 依赖取舍

- **YAML**：`pyyaml` **不在** 当前 venv 里。
  两个选择：
  - (a) 把 `pyyaml` 加进 `requirements.txt`（约 800KB，成熟）
  - (b) 写一个最小 append-only YAML 片段（因为 `cordis.patch.yml` 顶层就是
    简单数组，追加即可）
  **决定 (a)** —— 要"重新解析校验"，就必须有真正的 YAML 解析器；
  手写校验器不可靠。成本可接受。

- **TOML 写**：Python 3.11+ 有 `tomllib`（**只读**）。
  写需要 `tomli-w`（很小）或手写追加。
  **决定用 `tomli-w`**（同 (a) 的理由：要能读回校验）。

---

## 4. 两个提示词

### 4.1 形态 A：极简（推荐给用户）

> 读 `https://github.com/pirate-608/huixuewaiyu-readingpart` 的 `SETUP.md`，
> 按里面的步骤帮我装好这个工具。我是 **<DSH / Codex / Claude Code>** 用户。

`SETUP.md` 就是 §5 的"给 agent 看的约定"。

### 4.2 形态 B：自包含（不需要 agent 联网读仓库）

---

```
帮我安装并配置 huixuewaiyu-readingpart（慧学外语阅读自动答题工具）。

请严格按以下顺序执行，每步都要验证通过再进入下一步。

【第 0 步】先确认你运行在哪个 agent 里（DSH / Codex / Claude Code），
           后面注册 MCP 时要用。如果不确定，告诉我。

【第 1 步】装工具
  uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
  验证：`elang list` 能列出 doctor / init-env / install-browser /
        setup-mcp / install-skill / run / mcp
  若 uv 不存在，先告诉我，不要擅自装 uv。

【第 2 步】装浏览器
  elang install-browser
  验证：`elang doctor` 里 browser 一节显示 launch: ok
  说明：这一步可能会下载约 680MB；若报网络/TLS 错误，直接重试即可。

【第 3 步】配置凭据（需要我参与）
  elang init-env              # 在工作区根生成 .env 模板
  然后**让我自己**把学号和密码填进 .env。
  不要读取、回显或记录密码内容。
  验证：`elang doctor` 里 username / password 显示 set

【第 4 步】注册 skill
  先问我：全局装（所有项目可用）还是只装当前项目？
  然后：
    elang install-skill --agent <第0步确认的 agent> --scope <我选的范围>
  验证：`elang install-skill --agent <agent> --scope <scope> --check`
        应显示 present

【第 5 步】注册 MCP
  elang setup-mcp --host <第0步确认的 agent>
  说明：这会改配置文件，工具会自动备份并校验；若失败会自行回滚。
  完成后告诉我需要重启/刷新什么。

【第 6 步】总结
  报告：工具版本、浏览器状态、凭据状态、skill 装在哪、
       MCP 是否注册成功、还需要我做什么。

遇到任何一步失败：把**原始错误**告诉我，不要跳过或假装成功。
```

---

## 5. `SETUP.md`（给 agent 读的约定）

内容 = §4.2 的步骤，但要**加上 agent 需要的背景**：

- 这个工具是什么、产出什么（`elang` 命令负责什么）
- 三个产物边界（工具 / skill / 仓库）
- 凭据约定（`<cwd>/.env` → `~/.elang/.env`；环境变量优先）
- **不要**读密码内容
- **不要**手写配置文件，用 `setup-mcp`
- 沙箱注意事项：MCP server 必须在文件沙箱外运行
  （Playwright 需要命名管道，受限沙箱拒绝）
- 每步的验证命令

---

## 6. 实施顺序

| # | 任务 | 为何这个顺序 |
|---|---|---|
| 1 | 加依赖 `pyyaml`、`tomli-w` 到 `requirements.txt` 与 `pyproject.toml` | `setup-mcp` 需要 |
| 2 | 实现 `setup-mcp --host {claude,dsh,codex,all}`（含 §3.2 全部安全属性） | 提示词第 5 步的前提 |
| 3 | 用假的配置文件端到端测试三个 host（含校验失败回滚） | 不能拿真实配置冒险 |
| 4 | 写 `SETUP.md` | 给 agent 读 |
| 5 | README 顶部加"一句话提示词" | 用户入口 |
| 6 | 用一个 agent 真实走一遍 | 最终验证 |

**第 3 步是重点**：三个 host 的配置文件格式各异，而且用户的
`~/.codex/config.toml` 里有真实凭据 —— **必须**在假文件上验证通过再动真的。

---

## 7. 已知风险

| 风险 | 应对 |
|---|---|
| 改坏用户的 agent 配置 | 备份 + 临时文件原子替换 + 校验失败回滚 + `--dry-run` |
| 打印出配置里的密钥 | 只输出 diff 的**新增行**，绝不整体回显 |
| `~/.codex/config.toml` 里有 API key，误提交 | 它不在仓库里；但备份文件也应落在原目录旁或 temp，**不进仓库** |
| DSH 的 MCP server 可能受沙箱限制 | 提示词里说明；`failOnStartupError: true` 让问题显式化 |
| agent 跳过失败步骤 | 提示词明确要求"报告原始错误，不要假装成功" |
| uv 不存在时 agent 擅自安装 | 提示词要求先询问 |

---

## 8. 不做的事

- **不让 agent 手写配置文件** —— 必须走 `setup-mcp`
- **不让 agent 读密码** —— 用户自己填
- **不自动装 uv** —— 那是用户的系统级决定
- **不猜 scope** —— 问用户
- **不为了"看起来成功"而吞错误**
