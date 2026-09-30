# 三平台分发设计（DSH / Codex / Claude Code）

目标：**一份源码，三个平台可分发**，不维护三份代码。

---

## 1. 核心事实（均已在 DSH 运行时中查证，非推测）

### 1.1 三个平台共用同一个 skill 契约

`SKILL.md` + YAML frontmatter（`name`、`description`）+ 同级 `scripts/` 资源目录。
证据：DSH 自带的 `runtime/office-skills/office-docx/SKILL.md` 格式与
本仓库的 `SKILL.md` **完全一致**。

### 1.2 差异只在"扫描哪些根目录"

DSH 的 `skill-filesystem` provider 定义（源码实测）：

| Rank | Source | Path |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs` |
| 400 | `user-dsh` | `<dshHome>/skills`（跳过 `.system`） |
| 500 | `user-agents` | `<agentsHome>/skills` |

- `<dshHome>` = `$DSH_HOME` 或 `~/.dsh`
- `<agentsHome>` = `$DSH_AGENTS_HOME` 或 `~/.agents`
- `projectRoot` = 最近的含 `.git` 的祖先目录

**关键推论：DSH 的 rank 500 与 Codex 是同一个目录 `~/.agents/skills`。**
所以 **DSH 与 Codex 共享 skill 安装位置**，只需装一份。

本机实测：
- `~/.agents/skills/` —— **20 个 skill，正是本次会话的 skill 目录**
- `~/.claude/skills/` —— 另一套（5 个）
- `~/.dsh/skills/` —— 不存在（DSH 在用 `.agents` 那条）

### 1.3 发现深度为一层

只识别 `<root>/<name>/SKILL.md` 与 `<root>/<name>.md`。
**嵌套的 `**/SKILL.md` 不会被发现。**

→ 所以**不能**把仓库根直接当 skill 放进去（仓库里有 `SKILL.md` 但还有
`.git`/`temp`/`.venv`），必须装成 **`<root>/huixuewaiyu-readingpart/`**。

---

## 2. 三条分发通道

| 通道 | 形态 | 适用平台 | 状态 |
|---|---|---|---|
| **A. Skill 目录** | `SKILL.md` + `scripts/` | **三平台通用** | ✅ 已实现 |
| **B. MCP server** | `elang_mcp.py`（stdio） | DSH / Claude Code / 任何 MCP 宿主 | ✅ 已实现（Level 2） |
| **C. DSH npm 插件** | npm 包 + `cordis.patch.yml` | 仅 DSH | 待做 |

### 通道 A：单一入口，覆盖三平台

新增 `scripts/install_skill.py`，一个脚本装所有平台：

```bash
python scripts/install_skill.py --check      # 只报告
python scripts/install_skill.py --copy       # 复制（默认推荐，干净）
python scripts/install_skill.py --link       # 目录连接（开发用，改源码即生效）
python scripts/install_skill.py --hosts dsh,codex,claude
python scripts/install_skill.py --uninstall
```

**复制模式只带 payload**：`SKILL.md`、`scripts/`、`references/`、`assets/`、
`requirements.txt`、`CLAUDE.md`、`MIGRATION_CHECKPOINT.md`、`MCP_DESIGN.md`。
**不带 `.git` / `temp` / `.venv`** —— 这正是仓库根不能直接当 skill 的原因。

**链接模式**（Windows 用 junction，已实测可用）：
- `mklink /J` 无需管理员权限
- `rmdir` 只删连接本身，**不动目标**（已实测验证）
- 缺点：宿主会看到仓库里的 `.git` 等；开发期可接受

### 通道 B：MCP server（已就绪）

`scripts/elang_mcp.py`，10 个 tool。注册方式因宿主而异：
- **DSH**：配置文件里加 MCP server 条目
- **Claude Code**：`.mcp.json` / `claude mcp add`
- 通用：任何支持 stdio MCP 的宿主

⚠️ **前置条件（实测）**：server 必须在**文件沙箱之外**运行。
Playwright 与 MCP stdio 客户端都经 `asyncio` 在 Windows 创建**命名**管道，
沙箱拒绝 `CreateFile("\\.\pipe\...")` → WinError 5。
→ 需要为 `elang-mcp` **配一次 full access**，而非每次批准。

### 通道 C：DSH npm 插件（待做）

DSH 插件不是 skill，而是 **cordis npm 包**：

```
package.json
  "main": "lib/index.js"
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
cordis.patch.yml
  - insert: [{ id: <id>, name: <pkg-name> }]
lib/index.js
  export const name = '...'
  export function apply(ctx, config) { ... }
```

参考实现：`~/.dsh/profiles/desktop/node_modules/dshmarket`。

**它能做的事**（skill 做不到的）：
- 把 MCP server 注册进 profile，用户**无需手写配置**
- 参与 profile 的层组合（`cordis.yml` 是 patch 栈）
- 可带 client UI

**分发方式的限制**：DSH 插件是 **npm 包**，装法是把包名加进 profile 的
`package.json` 的 `dsh.profile.bundles`，然后 `pnpm install`。
**git 源不是 DSH 插件的原生分发方式** —— 可以 `pnpm add <git-url>`，
但需要额外一步，不如 skill 目录直接。

---

## 3. 建议的分发形态

```
仓库（一份源码）
├── SKILL.md                      ← 三平台共用
├── scripts/
│   ├── install_skill.py          ← 通道 A：一条命令装三平台
│   ├── elang_reader.py           ← solver（CLI）
│   ├── elang_session.py          ← 状态机（Level 1）
│   ├── elang_mcp.py              ← 通道 B：MCP server
│   └── review.py                 ← 文件 IPC 作答接口
├── references/
├── mcp.json.example              ← MCP 注册片段（DSH / Claude Code）
└── dsh-plugin/                   ← 通道 C（可选，仅 DSH）
    ├── package.json
    ├── cordis.patch.yml
    └── lib/index.js              ← 仅做"注册 MCP + 装 skill"，无业务逻辑
```

**优先级建议**

1. **通道 A 是主力** —— 它已经覆盖三平台，且 git clone + 一条命令即可
2. **通道 B 是加速器** —— 有 MCP 时交互质量显著更好（无超时、结构化状态）
3. **通道 C 是锦上添花** —— 只有在"希望 DSH 用户零配置"时才值得做

---

## 4. 为什么不能只做通道 C

- 通道 C 只服务 DSH，**Codex 和 Claude Code 完全不认**
- 通道 A 的 `SKILL.md` 是三平台**唯一的公共契约**
- 所以 A 必须是主路径，C 只能是包装

## 5. 已做 / 待做

| 项 | 状态 |
|---|---|
| `scripts/install_skill.py`（通道 A，含 `--check/--copy/--link/--uninstall`） | ✅ 已实现并验证链接机制 |
| `scripts/elang_mcp.py`（通道 B，10 tools） | ✅ 已实现并协议验证 |
| MCP 注册示例文件 | 待做 |
| `dsh-plugin/`（通道 C） | 待做 |
| 把 DSH 项目根（`.dsh/skills`、`.agents/skills`）纳入文档 | 待做 |
