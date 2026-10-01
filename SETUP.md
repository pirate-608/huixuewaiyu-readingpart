# 安装与配置指引（给 agent 读）

你正在帮用户安装配置 **huixuewaiyu-readingpart**（慧学外语阅读自动答题工具）。

**请严格按顺序执行，每步验证通过再进入下一步。**
遇到失败：把**原始错误**报告给用户，不要跳过、不要假装成功。

---

## 背景：这是什么，由什么组成

三个独立产物，边界清楚：

| 产物 | 装法 | 职责 |
|---|---|---|
| **工具** | `uv tool install` | MCP server + 求解器。自带隔离环境，提供 `elang` 命令 |
| **skill** | `elang install-skill` | 文档与契约，告诉 agent 该跑什么命令 |
| **本仓库** | `git clone` | 承载两者；开发用 |

工具的依赖在 uv 自己的环境里，**不碰用户的系统 Python**。

**你的角色**：跑确定性命令、判断环境、处理失败重试、问用户偏好。
**不要**手写配置文件 —— 用 `elang setup-mcp`（它会备份 + 校验 + 失败回滚）。

---

## 第 0 步：确认你在哪个 agent 里

后面注册 MCP 要用。三种可能：

| agent | MCP 注册位置 | 格式 |
|---|---|---|
| **Claude Code** | `<项目>/.mcp.json` | JSON |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | YAML |
| **Codex** | `~/.codex/config.toml` | TOML |

**如果不确定，直接问用户。** 不要猜 —— 猜错会写错文件。

---

## 第 1 步：装工具

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

**验证**：

```bash
elang list
```

应列出：`doctor` `init-env` `install-browser` `setup-mcp` `install-skill` `run` `mcp`

**若 `uv` 不存在**：告诉用户，**不要擅自安装 uv**（那是系统级决定）。
替代方案：`git clone` 后 `python scripts/setup.py`。

---

## 第 2 步：装浏览器

```bash
elang install-browser
```

**验证**：

```bash
elang doctor
```

`browser` 一节应显示 `launch: ok`。

**说明**：

- 这一步可能下载约 680MB
- 报**网络/TLS 错误**是常见的瞬时问题 → **直接重试**即可（会续传）
- 若已有可用构建，它会**什么都不做**（这是正常的）

---

## 第 3 步：配置凭据（需要用户参与）

```bash
elang init-env          # 在工作区根生成 .env 模板
```

然后**请用户自己**把学号和密码填进生成的 `.env`。

> **不要读取、回显、记录或转述密码内容。**
> 也不要让用户把密码发在对话里。

**验证**：

```bash
elang doctor
```

`credentials` 一节应显示 `username: set` 与 `password: set`。

**凭据解析顺序**（供你排查）：

```
1. $ELANG_ENV_FILE                     显式指定
2. <工作目录>/.env                      工作区根 ← 约定
3. ~/.elang/.env                       兜底
   另外：ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD 环境变量优先于以上任何文件
```

`doctor` 会显示**实际读取的文件**和每个值的来源。若显示 `fallback` 而不是
`workspace`，说明用户不在项目根启动。

---

## 第 4 步：注册 skill

**先问用户**：全局装（所有项目可用）还是只装当前项目？

```bash
elang install-skill --agent <第0步确认的 agent> --scope <global|project>
```

**验证**：

```bash
elang install-skill --agent <agent> --scope <scope> --check
```

应显示 `present`。

**说明**：

- **DSH 与 Codex 共享 `~/.agents/skills`**，给两者安装只写一个目录
- `project` 装到项目内，**优先级高于全局**，且可随项目提交给协作者

---

## 第 5 步：注册 MCP

```bash
elang setup-mcp --host <第0步确认的 agent>
```

**先看将写入什么**（可选，推荐首次使用）：

```bash
elang setup-mcp --host <agent> --dry-run
```

**安全保证**：脚本会先备份、用解析器结构化修改、写完**重新解析校验**，
失败自动回滚。它**只打印新增的行**，绝不整体回显配置
（`~/.codex/config.toml` 里可能有 API key 明文）。

**验证**：脚本自己会校验。成功后需要**重启/刷新 agent**：

| agent | 需要做什么 |
|---|---|
| Claude Code | 重启，或重新加载项目 |
| DSH | **重启 DSH**（profile 会重新组合） |
| Codex | 重启 Codex |

---

## 第 6 步：汇报

告诉用户：

1. 工具版本与路径
2. 浏览器状态
3. 凭据状态（只报 `set` / `missing`，**不报内容**）
4. skill 装在哪
5. MCP 是否注册成功
6. **还需要用户做什么**（通常是：重启 agent）

---

## ⚠️ 重要：MCP server 必须在文件沙箱外运行

已实测：**Playwright 无法在受限文件沙箱内启动浏览器**。

- 它的 driver 走 `asyncio.create_subprocess_exec`，在 Windows 上需要**命名**管道
- 受限沙箱拒绝 `CreateFile("\\.\pipe\...")`，报 `WinError 5`
- 同步 API 也一样（内部就是 asyncio）

**DSH 的 `failOnStartupError: true` 就是为了让这类失败显式暴露**，
而不是静默地"工具没出现"。

若注册后 `elang_status` 就报错 → server 没连上（查路径/配置）。
若 `elang_status` 正常但 `elang_start` 失败 → 浏览器起不来（多半是沙箱）。

---

## 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `elang: command not found` | 工具没装或不在 PATH | 重跑 `uv tool install`；提示用户重开终端 |
| `elang doctor` 报 `EPERM`/`mkdtemp` | 临时目录不可写 | 把 `TEMP`/`TMP` 指向可写目录 |
| `browser launch: FAILED` | 浏览器没装 | `elang install-browser`，网络错误就重试 |
| `credentials ... (missing)` | 没有 `.env` | `elang init-env`，让用户填 |
| `WARNING: ... OUTSIDE this interpreter's tree` | 依赖是借来的 | 重建隔离环境（`uv tool install`） |
| MCP 注册后看不到工具 | agent 没重启 | 重启它 |
| `elang_status` 报错 | server 没连上 | 检查 `command` 路径与配置格式 |
| `elang_start` 失败但 `status` 正常 | 浏览器/沙箱问题 | 见上面的沙箱说明 |

---

## 不要做的事

- **不要**手写/手改 agent 的配置文件（用 `elang setup-mcp`）
- **不要**读取或转述用户的密码
- **不要**擅自安装 `uv`（先问）
- **不要**猜 scope（问用户）
- **不要**为了"看起来成功"而吞掉错误
