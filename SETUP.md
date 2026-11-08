# 安装与配置指引（给 agent 读）

> **读者：执行 agent**（安装 / 配置本工具）。开发 agent 看 `CLAUDE.md`。
> 第 0 步先确认你在哪个宿主（DSH / Codex / Claude Code）。


你正在帮用户安装配置 **huixuewaiyu-readingpart**（慧学外语阅读自动答题工具）。

**支持范围：Windows 10/11（64 位）。** 其他平台不在支持范围，遇到非 Windows
环境直接告诉用户，不要尝试移植。

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
**不要**手写配置文件，改用 `elang setup-mcp`，它会备份、校验并在失败时回滚。

---

## 第 0 步：确认你在哪个 agent 里

后面注册 MCP 要用。三种可能：

| agent | MCP 注册位置 | 格式 |
|---|---|---|
| **Claude Code** | `<项目>/.mcp.json` | JSON |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | YAML |
| **Codex** | `~/.codex/config.toml` | TOML |

**如果不确定，直接询问用户。** 不要猜测，猜错会写入错误的文件。

---

## 第 1 步：装工具

先确认机器上已有 `uv`。Windows 上可以用 winget 安装：

```powershell
winget install --id=astral-sh.uv -e
```

然后安装工具：

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

GitHub 访问不稳定时，把地址换成 Gitee 镜像，内容相同：

```bash
uv tool install git+https://gitee.com/pirate-608/huixuewaiyu-readingpart.git
```

### 版本约定

不加 `@` 时装的是**默认分支最新提交**，适合跟开发。想要可复现的版本就钉标签：

```bash
uv tool install "git+https://github.com/pirate-608/huixuewaiyu-readingpart.git@v0.1.0"
uv tool upgrade elang-reading        # 升到默认分支最新
uv tool install --force "git+...@v0.1.0"   # 换到指定版本
```

版本号在四个地方必须一致，发布时由 CI 强制校验：

| 位置 | 例 |
|---|---|
| `pyproject.toml` 的 `version` | `0.1.0` |
| git 标签（前面加 `v`） | `v0.1.0` |
| wheel 文件名 | `elang_reading-0.1.0-py3-none-any.whl` |
| 离线包 `VERSION` 与 `/latest.json` 的 `version` | `0.1.0` |

自查当前版本：

```bash
elang --version        # 或看 elang doctor 输出第一行
```

**验证**：

```bash
elang list
```

应列出：`doctor` `init-env` `install-browser` `setup-mcp` `install-skill` `run` `mcp`，以及答题侧动词 `pending` `answer` `skip` `continue` `stop`

### 没有 uv 时：离线安装包

机器上装不了 uv 时，
改用离线包。包里有 Python 运行时和全部依赖，**安装过程不需要联网**。

从仓库的 Releases 页面下载 `elang-bundle-win64.zip`，解压到任意目录，然后在
该目录里执行：

```powershell
.\install.cmd                    # 装到 %LOCALAPPDATA%\elang
```

常用参数：

| 参数 | 作用 |
|---|---|
| `-Target D:\elang` | 换安装位置 |
| `-Check` | 只报告状态，不改动 |
| `-Uninstall` | 卸载（只删自己加的 PATH 项，保留浏览器 profile 等用户数据） |
| `-NoPath` | 不改 PATH，用绝对路径调用 |
| `-NoDoctor` | 跳过安装后的自检 |

装完会打印启动器路径，默认 `%LOCALAPPDATA%\elang\bin\elang.cmd`。
**打开一个新终端**后 `elang` 才会出现在 PATH 里。

两条安装路径互不干扰：离线包装在 `%LOCALAPPDATA%\elang`，uv 装的那份在
`%APPDATA%\uv\tools`，`-Uninstall` 不会碰 uv 那份。

### 可选：验证码 OCR（默认不装）

`ddddocr` 是**可选依赖**，`uv tool install` 不会装它。这不是装漏了：
它带 onnxruntime + opencv，体积大，而 `elang doctor` 报 `ddddocr MISSING`
仍属正常。

装它才有自动识别：

```bash
uv tool install --with ddddocr --with Pillow git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

不装也能用，只是验证码要交给视觉模型或人工（见 `SKILL.md` 阶段三）。
**关键前提**：交给视觉模型要求运行它的 agent 真的能读图；读不了图时应当
设 `ELANG_CAPTCHA_MANUAL=1`，让用户自己输，否则那一篇会白等 600 秒。

**若 `uv` 不存在**：告诉用户，**不要擅自安装**（那是系统级决定）。
替代方案：`git clone` 后自建 venv（`python -m venv .venv`，
在 venv 里 `pip install -r requirements.txt`），从仓库运行 `scripts/elang_reader.py`。

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

- 顺序是"先复用、再下载"：已有 Chromium 构建则什么都不做；没有构建但装了
  Chrome / Edge 则直接复用，**不联网也不下载**；两者都没有时才下载约 680MB
- 强制安装自带构建用 `--bundled`；装到 Playwright 共享缓存用 `--shared`
- 需要下载时，报**网络/TLS 错误**是常见的瞬时问题 → **直接重试**即可（会续传）

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

键名两套都认（带 ELANG_ 前缀的优先）：
    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD
真实环境变量优先于以上任何文件，两套键名都适用。
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
| `browser launch: FAILED` | 没有可用浏览器 | `elang install-browser`（会先复用已装 Chrome/Edge；需要下载时报网络错误就重试） |
| `credentials ... (missing)` | 没有 `.env` | `elang init-env`，让用户填 |
| `WARNING: ... OUTSIDE this interpreter's tree` | 依赖是借来的 | 重建隔离环境（`uv tool install`） |
| MCP 注册后看不到工具 | agent 没重启 | 重启它 |
| `elang_status` 报错 | server 没连上 | 检查 `command` 路径与配置格式 |
| `elang_start` 失败但 `status` 正常 | 浏览器/沙箱问题 | 见上面的沙箱说明 |
| 登录页打不开或登录失败 | 代理/TUN 与站点网络限制冲突 | 关闭 TUN 与全局代理，或让 `elang.zju.edu.cn`、`zjuam.zju.edu.cn` 直连 |

---

## 不要做的事

- **不要**手写/手改 agent 的配置文件（用 `elang setup-mcp`）
- **不要**读取或转述用户的密码
- **不要**擅自安装 `uv`（先问）
- **不要**猜 scope（问用户）
- **不要**为了"看起来成功"而吞掉错误
