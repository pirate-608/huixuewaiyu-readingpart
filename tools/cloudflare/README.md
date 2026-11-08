# 安装入口 Worker（Cloudflare）

> **读者：开发 agent。** 不随 skill 分发。面向用户的安装说明在 `SETUP.md`。

给离线安装包一个固定入口域名：用户不用记 GitHub 地址，也能把版本、下载、
安装脚本收敛到一处。

## 它做什么

| 路径 | 行为 |
|---|---|
| `/` | 说明页：两条安装路径（uv 与离线包） |
| `/latest.json` | 从 GitHub Release 解析版本、大小、下载地址（**缓存 10 分钟**） |
| `/elang-bundle-win64.zip` | 默认 **302 跳到 Release 资产**；加 `?stream=1` 由边缘转发 |
| `/install.ps1`、`/install.cmd` | 按发行标签转发仓库里的同名脚本，保证与包内一致 |
| `/elang-console.js` | 转发 `tools/browser/elang-console.js`，浏览器控制台辅助脚本 |
| `/healthz` | 探活 |

脚本类路由（`install.*` 与 `elang-console.js`）**先按发行标签取，取不到再退回默认
分支**，响应头 `x-elang-ref` 标明实际来源。加这条兜底是因为辅助脚本常常晚于最近
一次发版：`tools/browser/elang-console.js` 就是在 `v0.1.1` 之后才加的，只按标签取
会 404。

设计取向：

- **无绑定、无密钥**。只用公开的 GitHub release 信息，不需要 KV/R2/Secrets。
- **默认 302 而不是代理**。GitHub Releases 自己有 CDN 与 Range 支持，让用户直连
  最省；只有到 GitHub 不通时才用 `?stream=1` 让 Worker 承担流量。
- **必须缓存**。GitHub 未认证 API 限额 60 次/小时，10 分钟缓存把它压到可忽略。
- **API 挂掉时不编造数据**：返回 503 并附带 Release 页面兜底地址。

## 前置条件：先有一个带产物的 Release

`/latest.json` 从**最新 Release** 取资产。所以第一次部署前要先有 tag：

```bash
git tag v0.1.0
git push origin v0.1.0
```

这会触发 `.github/workflows/release-bundle.yml`，构建 `elang-bundle-win64.zip`
并附到该 Release。没有 Release 时 Worker 会返回 502/503，这是预期行为。

## 本地自测（不需要账号）

```bash
node tools/cloudflare/test_worker.mjs
```

stub 掉 `fetch` 与 Cache API，覆盖路由、缓存、302 与 `?stream=1`、
GitHub API 403 的失败分支。

## 部署：三选一

### A. 用 API Token（可交给我执行）

1. Cloudflare Dashboard → 右上头像 → **My Profile** → **API Tokens** → Create Token
2. 用 **Edit Cloudflare Workers** 模板，或自定义：
   - `Account` → `Workers Scripts` → **Edit**
   - `Account` → `Account Settings` → **Read**（用于确定 account id）
   - 若要挂自定义域名，再加 `Zone` → `Workers Routes` → **Edit**
3. 记下 token，并从 Dashboard 概览页复制 **Account ID**
4. 在本机设置后部署：

```powershell
$env:CLOUDFLARE_API_TOKEN = "<token>"
$env:CLOUDFLARE_ACCOUNT_ID = "<account id>"
npx wrangler@4 deploy --config tools/cloudflare/wrangler.toml
```

首次部署会给出 `https://elang-install.<子域>.workers.dev` 之类的地址。

### B. 用 `wrangler login`（浏览器授权）

```powershell
npx wrangler@4 login
npx wrangler@4 deploy --config tools/cloudflare/wrangler.toml
```

`login` 会开浏览器让你点授权，完成后本机留存凭据，后续部署不再需要 token。

### C. 纯 Dashboard（不装任何工具）

1. Dashboard → **Workers & Pages** → **Create application** → **Worker**
2. 起个名字，如 `elang-install`，**Deploy**
3. **Edit code**，把 `tools/cloudflare/worker.mjs` 的内容整段粘进去（替换模板），
   再 **Deploy**
4. 需要改仓库名等参数时：**Settings → Variables and Secrets**，加
   `OWNER_REPO` / `ASSET_NAME` / `PINNED_TAG`（都是纯文本变量，不是密钥）
5. 自定义域名：**Settings → Domains & Routes → Add → Custom domain**，
   填一个**已托管在 Cloudflare** 的域名（如 `elang.example.com`）。
   域名不在 Cloudflare 时，只能先用 `workers.dev` 地址，或把域名 NS 迁过来。

## 部署后自检

```bash
curl -s https://<你的域名>/healthz
curl -s https://<你的域名>/latest.json
curl -sI https://<你的域名>/elang-bundle-win64.zip     # 期望 302
```

`latest.json` 里的 `tag` 应与最新 Release 一致；`asset.size` 应约 75 MB。

## 维护

- 发新版本：打 `v*` 标签即可。Worker 不需要改动，`latest.json` 缓存过期后自动
  指向新版本。
- 想临时钉住某个版本：在 Dashboard 变量里设 `PINNED_TAG`（如 `v0.1.0`）。
- Worker 代码与 `tools/bootstrap/install.ps1` 一起演进：脚本路径若变，
  需要同步改 `worker.mjs` 里的 `installScripts` 与 `/install.ps1` 分支。