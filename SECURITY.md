# 安全与隐私说明

> **读者：开发 agent**（修改本项目时需了解的凭据与数据边界）。
> 安装配置见 `SETUP.md`，架构见 `CLAUDE.md`。

## 范围

本工具使用凭据的唯一场景是登录浙江大学统一身份认证（`zjuam.zju.edu.cn`）：凭据以
明文保存在用户自己的 `.env`，由浏览器填入站点登录表单。本工具不含服务端，无遥测，
无上传。

## 凭据存储

密码以明文 `KEY=VALUE` 保存在 `.env`，按下列顺序查找，取第一个可用来源：

| 顺序 | 位置 | 用途 |
|---|---|---|
| 1 | `$ELANG_ENV_FILE` | 显式指定，便于并存多套凭据 |
| 2 | `<工作目录>/.env` | 约定位置；agent 的工作目录即工作区根 |
| 3 | `~/.elang/.env` | 兜底 |

键名两套并存，`ELANG_` 前缀优先：

```
ELANG_CAS_USERNAME  /  CAS_USERNAME
ELANG_CAS_PASSWORD  /  CAS_PASSWORD
```

真实环境变量优先于上述文件。原因是 MCP 宿主在 spawn 时可注入凭据，而陈旧的
`.env` 不应覆盖宿主提供的值。

`.env` 由 `.gitignore` 排除；`scripts/test_no_secrets.py` 断言其未被跟踪且被忽略，
提交钩子命中即阻断。

文件本身不加密。该取舍换取的是：工具无需操作系统密钥环即可运行。

## 凭据读取

解析逻辑集中在 `config.load_credentials()`，全项目唯一实现。

- 常规路径：解析 `.env` 与环境变量，结果保存在内存，仅在登录时使用
- 无可用凭据且处于交互终端时：提示输入一次学号与密码，写入 `.env`，
  随后尝试收紧文件权限（仅 POSIX 生效）
- 无 stdin（agent 或管道场景）时不阻塞，直接报错并提示 `elang init-env`
- 失败信息仅说明缺失项与创建方式，不回显已读取的值

## 登录过程中的密码流向

```
进程内存 → Playwright 填入 zjuam 的 #password → 浏览器发起 HTTPS 请求
```

目标仅 `zjuam.zju.edu.cn` 的站点登录表单。密码不写入日志、会话文件、IPC 文件或
MCP 工具返回值，也不经过任何第三方服务。

## 登录态存储

登录成功后会话被持久化，以在后续运行中跳过 CAS：

| 文件 | 内容 | 位置 |
|---|---|---|
| `session.json` | 站点 cookie，localStorage 中 `user` 与 `authorization`（JWT） | `~/.elang/session.json` |
| `browser-profile/` | 浏览器 profile，含 cookie 与站点存储 | `~/.elang/browser-profile` |

二者均等价于一定时间内的账号访问权：持有 `authorization` 可以该用户身份调用站点
接口，直至过期（约 2 小时）。因其敏感性，两者存放在用户主目录，而非公共临时目录。

## 日志与输出

| 输出位置 | 处理方式 |
|---|---|
| 控制台 | 学号经 `_mask_id()` 掩码（形如 `325*******`）；密码不输出 |
| `elang doctor` | 仅报告 `set` / `missing` |
| `elang doctor --json` | 经 `_redact_credentials()` 过滤，不含用户名与密码原文 |
| MCP 工具返回值 | 仅含状态与下一步动作 |

`doctor --json` 单独脱敏，因为该输出会被 agent 纳入对话记录并可能被保存或分享。

## 临时文件（IPC）

`<ipc>` 默认为 `C:/tmp`（Windows），或由 `ELANG_TMP_DIR` 指定。内容包括：

- `elang_current.json`：当前文章正文与题目
- `elang_signal.json`、`elang_checkpoint.json`：作答信号与断点
- `elang_captcha_request.json`、`elang_captcha.json`、`elang_captcha_image.png`：验证码交接

此处不含凭据，但有两点需注意：

1. `C:/tmp` 为机器共享目录，同机其他用户可能读取其中的文章与题目。
2. 这些文件驱动流程输入，可被改写者可影响提交内容。

多用户环境建议将 `ELANG_TMP_DIR` 指向私有目录。

## 风险与缓解

| 风险 | 触发条件 | 后果 | 现有缓解 |
|---|---|---|---|
| `.env` 明文 | 进程或用户可读该文件 | 获取密码 | 位于工作区并被 gitignore；交互生成时尝试 `chmod 600`（仅 POSIX）；Windows 不修改 ACL，依赖目录权限；用户自建的 `.env` 不会被改权限 |
| 工作区位于同步目录 | 仓库置于 OneDrive、iCloud 等 | `.env` 随同步上传 | 无自动检测；不应将工作区存放在同步目录 |
| 会话文件泄漏 | 可读 `session.json` 或浏览器 profile | 冒用账号至 token 过期 | 存放于用户主目录；保存时尝试 `chmod 600`（仅 POSIX）；Windows 依赖 profile ACL |
| IPC 目录共享 | 多用户机器 + 默认 `C:/tmp` | 他人可读文章、可改写提交内容 | 建议设置 `ELANG_TMP_DIR`，未强制 |
| 凭据进入终端记录 | 用户手输密码或粘贴至对话 | 超出工具控制范围 | 由用户自行填写 `.env`，agent 不代为输入 |
| 管理员权限 | 同机管理员或 SYSTEM 级访问 | 可读取全部本地数据 | 属操作系统信任边界，无法在应用层防御 |
| 安装包被替换 | 使用非官方来源的 wheel 或离线包 | 任意代码执行 | 官方 Release 附 `SHA256SUMS`，离线安装器启动时逐项校验；`?stream=1` 仅为网络中转，不提供额外保证 |

## 未实现的加固

- 无静态加密，也未集成系统密钥环
- 未收紧 Windows ACL
- 未清理浏览器 profile 中的会话数据；删除 `session.json` 不代表登录态清除
- 未阻止用户将工作区置于同步目录

## 清理

```powershell
Remove-Item ~\.elang\session.json        # 仅清除会话，保留凭据
Remove-Item ~\.elang -Recurse -Force     # 连同登录态一并清除，下次需重新登录
```

凭据通过编辑或删除工作区的 `.env` 处理。若怀疑账号被冒用，修改 CAS 密码并删除
`~/.elang`，可使现有 token 与 cookie 失效。

## 禁止的做法

- 将 `.env` 提交至版本库，或绕过提交钩子
- 将密码写入命令行参数、issue、聊天记录或截图
- 在工作区与 `~/.elang` 之外复制凭据，尤其是共享盘与同步盘