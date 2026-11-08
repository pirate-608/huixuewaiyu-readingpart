# 离线安装包构建（开发用）

> **读者：开发 agent。** 本文不随 skill 分发，也不是给普通用户的安装说明——
> 用户视角的安装步骤写在 `SETUP.md`。

给**没有 uv** 的用户准备的离线安装包：一个 zip，解压后运行 `install.cmd`，
全程不联网，即可得到一套独立的 `elang`。

## 为什么单独做这条路

`uv tool install` 已经能一条命令装好，但它要求机器上先有 uv，而 uv 自己还要能
访问 GitHub / PyPI。目标用户的真实障碍通常不是"uv 不好用"，而是：

- 企业策略不允许装开发工具，或没有管理员权限
- 网络到 GitHub / PyPI 不稳定，装到一半失败
- 杀软拦截下载后的可执行文件

离线包把"装的时候要不要联网"这个问题整个消掉：**所有字节都在包里**。

## 包里有什么

```
elang-bundle-win64.zip              ~72 MB
├─ cpython-3.13.x+<tag>-x86_64-pc-windows-msvc-install_only_stripped.tar.gz   ~21 MB
├─ wheels/*.whl                     ~52 MB（34 个，含 playwright 1.60）
├─ install.cmd / install.ps1
├─ SHA256SUMS                       运行时 + 每个 wheel 的哈希
└─ VERSION
```

运行时不预先解压（省 zip 体积），由 `install.ps1` 调用 Windows 自带的
`tar.exe` 解开。**浏览器不进包**：`config.browser_choice()` 会优先用已装的
Chrome/Edge；OCR 也不进包，见下。

## 构建

```bash
# 1. 先出 wheel
uv build --wheel

# 2. 打 bundle（需要能访问 GitHub + PyPI 的 python 环境，带 pip）
python tools/bootstrap/build_bundle.py --wheel dist/elang_reading-0.1.0-py3-none-any.whl

# 产物
#   build/bundle/                     目录
#   build/elang-bundle-win64.zip      分发包
```

可用参数：

| 参数 | 作用 |
|---|---|
| `--out DIR` | 输出目录（默认 `build/bundle`） |
| `--python 3.13` | 运行时 CPython 次版本，必须与 wheel 的 ABI 匹配 |
| `--pba-tag 20261026` | 钉住 python-build-standalone 的发布标签 |
| `--with-ocr` | 把 `ddddocr` + `Pillow` 也打进 wheelhouse（+约 275 MB） |
| `--no-zip` | 只要目录，不压 zip |

`build/` 已在 `.gitignore` 里，产物不入库。

## 安装（用户视角，供文档引用）

```powershell
# 解压后，在解压目录里
.\install.cmd                       # 装到 %LOCALAPPDATA%\elang
.\install.cmd -Target D:\elang      # 换位置
.\install.cmd -Check                # 只看状态
.\install.cmd -Uninstall            # 卸载（只删自己加的 PATH 项，保留用户数据）
```

装出来的目录：

```
%LOCALAPPDATA%\elang\
├─ runtime\        python-build-standalone 解释器
├─ venv\           site-packages（playwright 在这里）
├─ bin\elang.cmd   启动器（-NoPath 时不改 PATH）
└─ manifest.json   本次安装记录，供 -Uninstall 使用
```

用户数据仍在 `%USERPROFILE%\.elang`（浏览器 profile、会话），卸载默认不动。

## 两个已经踩过的坑

**1. 安装脚本不能依赖 PowerShell 模块化 cmdlet**

实测：PowerShell 7 里启动 Windows PowerShell 5.1，子进程会继承 pwsh7 的
`PSModulePath`，于是 `Get-FileHash` / `Get-Content` 这类模块提供的 cmdlet
**找不到**，安装在第一次哈希校验就崩了。

所以 `install.ps1` 一律用 .NET API：
`[System.Security.Cryptography.SHA256]`、`[System.IO.File]`、
`[System.IO.Directory]`、`[System.Environment]`。改这个脚本时请遵守。

**2. 校验范围只到"防损坏"**

`SHA256SUMS` 覆盖运行时和所有 wheel，但**不覆盖脚本自身**，也不防"整包被换掉"。
真要防篡改，需要分发侧（Release 页面 / 自有域名）给出 zip 的哈希并让用户核对。
不要在文档里把它说成签名验证。

## 与 uv 安装路径的关系

两条路互不干扰：

- `uv tool install` 把工具装在 `%APPDATA%\uv\tools\elang-reading`，`elang`
  在 `%USERPROFILE%\.local\bin`
- 离线包装在 `%LOCALAPPDATA%\elang`，PATH 里加的是 `<target>\bin`

`-Uninstall` 只删自己加的那条 PATH 和 `<target>` 目录，不会碰 uv 那份。
两者的 `elang doctor` 输出里 `source` 行都会显示自己的实际路径，便于分辨。

## 发布

`.github/workflows/release-bundle.yml`：手动触发，或用 `v*` 标签触发。
它构建 wheel → 打 bundle → 上传为工作流产物；打标签时同时附到 Release。