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
  // The checksum manifest is published as its OWN release asset. It used to be
  // linked as build/SHA256SUMS in the repo, which is a 404: build/ is gitignored,
  // so that file never exists in git.
  const sums = (rel.assets || []).find((a) => a.name === "SHA256SUMS");
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
    sha256Sums: sums ? sums.browser_download_url : null,
    // 校验清单和脚本都随仓库标签走，版本天然对齐
    installScripts: {
      ps1: `https://raw.githubusercontent.com/${c.repo}/${rel.tag_name}/tools/bootstrap/install.ps1`,
      cmd: `https://raw.githubusercontent.com/${c.repo}/${rel.tag_name}/tools/bootstrap/install.cmd`,
    },
    // Served by this Worker; falls back to the default branch when the tag
    // predates the file.
    consoleScript: "/elang-console.js",
  };

  const put = new Response(JSON.stringify(info), {
    headers: { "content-type": "application/json", "cache-control": `max-age=${CACHE_TTL}` },
  });
  ctx.waitUntil(cache.put(key, put));
  return { info, cached: false };
}

const PAGE = (host) => `<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>elang — install</title>
<style>
  body{font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:42rem;margin:3rem auto;padding:0 1.2rem;color:#1b1f24}
  code,pre{font-family:ui-monospace,Consolas,monospace;background:#f4f5f7;border-radius:6px}
  code{padding:.12em .38em}
  pre{padding:.85rem 1rem;overflow:auto;font-size:.92rem}
  h1{font-size:1.55rem;margin-bottom:.3rem}
  h2{font-size:1.05rem;margin-top:2.2rem;text-transform:uppercase;letter-spacing:.04em;color:#48525c}
  .muted{color:#5b6570;font-size:.92rem}
  ul{padding-left:1.2rem}
</style>
<h1>elang</h1>
<p class="muted">Reading-practice automation for ZJU 慧学外语. Windows 10/11 x64.</p>

<h2>Option 1 — with uv</h2>
<pre>winget install --id=astral-sh.uv -e
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git</pre>
<p class="muted">Pin a release: append <code>@v0.1.1</code>. Check: <code>elang --version</code>.</p>

<h2>Option 2 — without uv (offline)</h2>
<ol>
  <li>Download <a href="/elang-bundle-win64.zip">elang-bundle-win64.zip</a> (about 66 MB).</li>
  <li>Unzip anywhere.</li>
  <li>Run <code>install.cmd</code> in that folder.</li>
</ol>
<p class="muted">No network is used during install. The tool goes to
<code>%LOCALAPPDATA%\\elang</code>; open a new terminal afterwards.
Remove it later with <code>install.cmd -Uninstall</code>.</p>

<h2>Files</h2>
<ul>
  <li><a href="/latest.json">latest.json</a> — version, size, download URL</li>
  <li><a href="/elang-bundle-win64.zip">elang-bundle-win64.zip</a> — offline bundle</li>
  <li><a href="/install.ps1">install.ps1</a> — the installer (read it first)</li>
  <li><a href="/install.cmd">install.cmd</a> — wrapper</li>
  <li><a href="/elang-console.js">elang-console.js</a> — browser console helper</li>
</ul>
<p class="muted">Slow connection to GitHub? Append <code>?stream=1</code> to the
download URL to relay it through this host.</p>

<h2>Already on a question page?</h2>
<p class="muted">Open <a href="/elang-console.js">elang-console.js</a>, copy all of it,
paste it into DevTools on the article page, then in the console:</p>
<pre>elang.status()      // question types, answer-key coverage, read guard
elang.extract()     // answers only, nothing changes
elang.answer()      // fill the answers in
elang.submit()      // open the confirm dialog (does not post)
elang.submit(true)  // post it</pre>
`;

// Serve a repo file, preferring the release tag so it matches the published
// bundle. The tag is not always enough: tools/browser/elang-console.js was added
// AFTER the newest release, so asking for it at that tag returns 404. Falling back
// to the default branch keeps such helpers available without waiting for a release.
async function rawFile(c, tag, path) {
  const refs = tag ? [tag, "master"] : ["master"];
  let lastStatus = 0;
  for (const ref of refs) {
    const upstream = await fetch(
      `https://raw.githubusercontent.com/${c.repo}/${ref}/${path}`,
      { cf: { cacheEverything: true, cacheTtl: 600 },
        headers: { "user-agent": "elang-install-worker" } });
    if (upstream.ok) return { res: upstream, ref };
    lastStatus = upstream.status;
  }
  return { res: null, status: lastStatus };
}

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
      const got = await rawFile(c, info.tag, `tools/bootstrap/${file}`);
      if (!got.res) {
        return json({ error: `raw ${got.status} for ${file}` }, 502);
      }
      return new Response(got.res.body, {
        status: 200,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "public, max-age=300",
          "x-elang-ref": got.ref,
        },
      });
    }

    // 浏览器控制台脚本：粘进 DevTools 用。用 text/javascript 便于在浏览器里直接
    // 打开查看或另存，不做强制附件下载。
    if (path === "/elang-console.js") {
      const { info } = await releaseInfo(c, ctx).catch(() => ({ info: {} }));
      const got = await rawFile(c, info && info.tag, "tools/browser/elang-console.js");
      if (!got.res) {
        return json({ error: `console script unavailable (raw ${got.status})` }, 502);
      }
      return new Response(got.res.body, {
        status: 200,
        headers: {
          "content-type": "text/javascript; charset=utf-8",
          "cache-control": "public, max-age=300",
          "x-elang-ref": got.ref,
        },
      });
    }

    return json({ error: "not found", paths: ["/", "/latest.json", "/elang-bundle-win64.zip", "/install.ps1", "/install.cmd", "/elang-console.js", "/healthz"] }, 404);
  },
};