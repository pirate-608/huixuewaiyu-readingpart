/**
 * elang 安装入口 Worker
 *
 * 只做三件事，全部无状态、无绑定、无密钥：
 *
 *   GET /                     说明页（两种安装方式）
 *   GET /latest.json          版本解析：从 GitHub Release 取出 bundle 的版本、大小、哈希
 *   GET /elang-bundle-win64.zip   下载：默认 302 到 Release 资产；?stream=1 时由边缘转发
 *   GET /install.ps1 /install.cmd 按发行标签转发仓库里的安装脚本
 *   GET /healthz              探活
 *
 * 为什么不是"代理一切"：GitHub Releases 支持 Range 与 CDN，302 让用户直连是最省的；
 * ?stream=1 只在用户到 GitHub 不通时用，代价是 Worker 承担流量。
 *
 * 部署：见同目录 README.md。需要配置的环境变量（可选）：
 *   OWNER_REPO  默认 pirate-608/huixuewaiyu-readingpart
 *   ASSET_NAME  默认 elang-bundle-win64.zip
 *   PINNED_TAG  设了就一直用这个标签，不查 GitHub API
 */

const DEFAULTS = {
  OWNER_REPO: "pirate-608/huixuewaiyu-readingpart",
  ASSET_NAME: "elang-bundle-win64.zip",
  PINNED_TAG: "",
};

const CACHE_TTL = 600; // 10 分钟；GitHub 未认证 API 是 60 次/小时，必须缓存

function cfg(env) {
  const pick = (k) => (env && env[k] !== undefined && env[k] !== "" ? env[k] : DEFAULTS[k]);
  return {
    repo: pick("OWNER_REPO"),
    asset: pick("ASSET_NAME"),
    pinned: pick("PINNED_TAG"),
  };
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2) + "\n", {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function releaseInfo(c, ctx) {
  const key = new Request(`https://cache.internal/release/${c.repo}`, { method: "GET" });
  const cache = caches.default;
  const hit = await cache.match(key);
  if (hit) return { info: await hit.json(), cached: true };

  const wantTag = c.pinned;
  const api = wantTag
    ? `https://api.github.com/repos/${c.repo}/releases/tags/${encodeURIComponent(wantTag)}`
    : `https://api.github.com/repos/${c.repo}/releases/latest`;

  const r = await fetch(api, {
    headers: {
      "user-agent": "elang-install-worker",
      accept: "application/vnd.github+json",
    },
  });
  if (!r.ok) {
    const text = (await r.text()).slice(0, 300);
    return { error: `github api ${r.status}: ${text}`, status: r.status };
  }
  const rel = await r.json();
  const asset = (rel.assets || []).find((a) => a.name === c.asset);
  const info = {
    tag: rel.tag_name,
    version: String(rel.tag_name || "").replace(/^v/, ""),
    publishedAt: rel.published_at,
    asset: asset
      ? {
          name: asset.name,
          size: asset.size,
          downloadUrl: asset.browser_download_url,
          apiUrl: asset.url,
        }
      : null,
    // 校验清单和脚本都随仓库标签走，版本天然对齐
    sha256Sums: `https://raw.githubusercontent.com/${c.repo}/${rel.tag_name}/build/SHA256SUMS`,
    installScripts: {
      ps1: `https://raw.githubusercontent.com/${c.repo}/${rel.tag_name}/tools/bootstrap/install.ps1`,
      cmd: `https://raw.githubusercontent.com/${c.repo}/${rel.tag_name}/tools/bootstrap/install.cmd`,
    },
  };

  const put = new Response(JSON.stringify(info), {
    headers: { "content-type": "application/json", "cache-control": `max-age=${CACHE_TTL}` },
  });
  ctx.waitUntil(cache.put(key, put));
  return { info, cached: false };
}

const PAGE = (host) => `<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>elang 安装</title>
<style>
  body{font:16px/1.7 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:44rem;margin:3rem auto;padding:0 1.2rem;color:#1b1f24}
  code,pre{font-family:ui-monospace,Consolas,monospace;background:#f4f5f7;border-radius:6px}
  code{padding:.12em .38em}
  pre{padding:.9rem 1rem;overflow:auto}
  h1{font-size:1.6rem;margin-bottom:.4rem}
  h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #e6e8eb;padding-bottom:.3rem}
  .muted{color:#5b6570;font-size:.92rem}
  table{border-collapse:collapse;width:100%;font-size:.95rem}
  td,th{border-bottom:1px solid #e6e8eb;padding:.45rem .3rem;text-align:left}
</style>
<h1>elang 安装入口</h1>
<p class="muted">慧学外语阅读练习工具。两种安装方式，任选其一。</p>

<h2>方式一：已有 uv（推荐）</h2>
<pre>winget install --id=astral-sh.uv -e
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git</pre>

<h2>方式二：没有 uv / 装的时候连不上网</h2>
<p>下载离线包，解压后在该目录运行 <code>install.cmd</code>。安装过程不联网。</p>
<pre># 直接下载
${host}/elang-bundle-win64.zip

# 或先看版本与大小
${host}/latest.json</pre>
<table>
<tr><th>文件</th><th>用途</th></tr>
<tr><td><a href="/elang-bundle-win64.zip">elang-bundle-win64.zip</a></td><td>离线安装包（约 72 MB）</td></tr>
<tr><td><a href="/latest.json">latest.json</a></td><td>当前版本、大小、下载地址</td></tr>
<tr><td><a href="/install.ps1">install.ps1</a></td><td>安装脚本（可先自己看一遍）</td></tr>
<tr><td><a href="/install.cmd">install.cmd</a></td><td>双击运行的包装</td></tr>
</table>
<p class="muted">安装会把工具放进 <code>%LOCALAPPDATA%\\elang</code>，不改动系统 Python，
卸载用 <code>install.cmd -Uninstall</code>。装完需要重开一个终端。</p>
<p class="muted">如果到 GitHub 的连接不稳，给下载地址加 <code>?stream=1</code>，由本入口中转。</p>
`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const c = cfg(env);

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed\n", { status: 405, headers: { allow: "GET, HEAD" } });
    }

    if (path === "/healthz") {
      return new Response("ok\n", { headers: { "content-type": "text/plain; charset=utf-8" } });
    }

    if (path === "/") {
      return new Response(PAGE(url.origin), {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=300" },
      });
    }

    if (path === "/latest.json") {
      const { info, error, status } = await releaseInfo(c, ctx);
      if (error) {
        return json({
          error,
          hint: "GitHub API 不可用时，直接从 Release 页面下载同样的文件",
          fallback: `https://github.com/${c.repo}/releases/latest`,
        }, status === 403 ? 503 : 502);
      }
      return json(info);
    }

    // 安装包：默认 302，?stream=1 走边缘转发
    if (path === "/elang-bundle-win64.zip" || path === `/assets/${c.asset}`) {
      const { info, error, status } = await releaseInfo(c, ctx);
      if (error || !info.asset) {
        return json({
          error: error || `release has no asset named ${c.asset}`,
          fallback: `https://github.com/${c.repo}/releases/latest`,
        }, status === 403 ? 503 : 502);
      }
      if (url.searchParams.get("stream") !== "1") {
        return new Response(null, {
          status: 302,
          headers: { location: info.asset.downloadUrl, "cache-control": "no-store" },
        });
      }
      const upstream = await fetch(info.asset.downloadUrl, {
        cf: { cacheEverything: true, cacheTtl: 86400 },
        headers: { "user-agent": "elang-install-worker" },
      });
      const headers = new Headers(upstream.headers);
      headers.set("content-disposition", `attachment; filename="${c.asset}"`);
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    // 安装脚本：按发行标签取仓库里的同名文件，保证与包内版本一致
    if (path === "/install.ps1" || path === "/install.cmd") {
      const file = path.slice(1);
      const { info, error, status } = await releaseInfo(c, ctx);
      if (error) {
        return json({ error, fallback: `https://github.com/${c.repo}/releases/latest` },
          status === 403 ? 503 : 502);
      }
      const tag = info.tag;
      const raw = `https://raw.githubusercontent.com/${c.repo}/${tag}/tools/bootstrap/${file}`;
      const upstream = await fetch(raw, {
        cf: { cacheEverything: true, cacheTtl: 600 },
        headers: { "user-agent": "elang-install-worker" },
      });
      if (!upstream.ok) {
        return json({ error: `raw ${upstream.status} for ${file} at ${tag}` }, 502);
      }
      return new Response(upstream.body, {
        status: 200,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "public, max-age=300",
        },
      });
    }

    return json({ error: "not found", paths: ["/", "/latest.json", "/elang-bundle-win64.zip", "/install.ps1", "/install.cmd", "/healthz"] }, 404);
  },
};