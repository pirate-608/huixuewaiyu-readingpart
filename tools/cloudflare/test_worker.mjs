/**
 * 本地自测：不需要 Cloudflare 账号，也不需要 wrangler。
 *
 * 它把 worker 的 handler 拿出来跑，stub 掉 fetch 与 Cache API，检查路由与失败
 * 分支。目的是在部署之前发现语法错误、路由写错、以及"API 挂掉时返回什么"。
 *
 * 运行：node tools/cloudflare/test_worker.mjs
 */
import worker from "./worker.mjs";

const results = [];
function check(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name}${detail ? "  " + detail : ""}`);
  results.push([name, !!cond]);
}

// ---- stubs ----------------------------------------------------------------
// The Cache API returns a NEW Response on every match, so a body can be read
// again. Storing the Response object itself (the obvious stub) makes the second
// read throw "Body is unusable" and hides that difference, so serialize instead.
const store = new Map();
globalThis.caches = {
  default: {
    async match(req) {
      const e = store.get(req.url);
      return e ? new Response(e.body, { headers: e.headers }) : undefined;
    },
    async put(req, res) {
      store.set(req.url, {
        body: await res.text(),
        headers: Object.fromEntries(res.headers.entries()),
      });
    },
  },
};

const RELEASE = {
  tag_name: "v0.1.0",
  published_at: "2026-11-08T00:00:00Z",
  assets: [
    { name: "elang-bundle-win64.zip", size: 75_600_000,
      browser_download_url: "https://github.com/o/r/releases/download/v0.1.0/elang-bundle-win64.zip",
      url: "https://api.github.com/assets/1" },
    { name: "SHA256SUMS", size: 3897,
      browser_download_url: "https://github.com/o/r/releases/download/v0.1.0/SHA256SUMS",
      url: "https://api.github.com/assets/3" },
    { name: "other.txt", size: 1, browser_download_url: "https://example/other", url: "https://api.github.com/assets/2" },
  ],
};

let githubMode = "ok";
const calls = [];
globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input.url;
  calls.push(url);
  if (url.startsWith("https://api.github.com/repos/")) {
    if (githubMode === "403") {
      return new Response("API rate limit exceeded", { status: 403 });
    }
    return new Response(JSON.stringify(RELEASE), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }
  if (url.startsWith("https://github.com/") || url.startsWith("https://raw.githubusercontent.com/")) {
    return new Response("BINARY-OR-SCRIPT", { status: 200 });
  }
  return new Response("unexpected " + url, { status: 500 });
};

function ctx() {
  const waited = [];
  return { waitUntil(p) { waited.push(p); }, _waited: waited };
}

const env = { OWNER_REPO: "o/r" };
const call = async (path, init) => {
  const c = ctx();
  const res = await worker.fetch(new Request("https://install.example" + path, init), env, c);
  await Promise.all(c._waited || []);
  return res;
};

// ---- tests ----------------------------------------------------------------
console.log("=== 基本路由 ===");
let r = await call("/healthz");
check("GET /healthz -> 200", r.status === 200);

r = await call("/");
const page = await r.text();
check("GET / -> 200 html", r.status === 200 && (r.headers.get("content-type") || "").includes("text/html"));
check("说明页含两种安装方式", page.includes("uv tool install") && page.includes("install.cmd"));
// Guard the risky shape, not the substring: "confirm dialog" also contains "irm ".
check("说明页不含 irm 管道式安装",
  !/\birm\s+https?:/i.test(page) && !page.includes("| iex"));

r = await call("/latest.json");
const info = await r.json();
check("GET /latest.json -> 200", r.status === 200);
check("版本去掉了 v 前缀", info.version === "0.1.0", info.version);
check("找到 bundle 资产", info.asset && info.asset.name === "elang-bundle-win64.zip");
check("给出脚本地址", String(info.installScripts?.ps1 || "").includes("/tools/bootstrap/install.ps1"));
check("校验清单指向 Release 资产而不是仓库 build/",
  String(info.sha256Sums || "").endsWith("/releases/download/v0.1.0/SHA256SUMS"),
  String(info.sha256Sums));

console.log("\n=== 缓存 ===");
const before = calls.length;
await call("/latest.json");
check("第二次命中缓存，不再打 GitHub API", calls.length === before, `calls +${calls.length - before}`);

console.log("\n=== 下载 ===");
r = await call("/elang-bundle-win64.zip");
check("默认 302 到 Release 资产", r.status === 302, String(r.status));
check("Location 指向资产", (r.headers.get("location") || "").endsWith("/elang-bundle-win64.zip"));

r = await call("/elang-bundle-win64.zip?stream=1");
check("?stream=1 由边缘转发", r.status === 200);
check("转发时带 attachment 文件名",
  (r.headers.get("content-disposition") || "").includes("elang-bundle-win64.zip"));

console.log("\n=== 安装脚本 ===");
r = await call("/install.ps1");
check("GET /install.ps1 -> 200 text", r.status === 200 &&
  (r.headers.get("content-type") || "").includes("text/plain"));
r = await call("/install.cmd");
check("GET /install.cmd -> 200", r.status === 200);

console.log("\n=== 控制台脚本 ===");
r = await call("/elang-console.js");
check("GET /elang-console.js -> 200 js",
  r.status === 200 && (r.headers.get("content-type") || "").includes("javascript"),
  String(r.status));
check("served from the release tag when available",
  r.headers.get("x-elang-ref") === "v0.1.0", String(r.headers.get("x-elang-ref")));
check("/latest.json advertises the console script",
  (info.consoleScript || "").endsWith("/elang-console.js"), String(info.consoleScript));

// The file was added after the newest release, so at that tag raw returns 404 and
// the worker must fall back to the default branch instead of failing.
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes("/tools/browser/elang-console.js")) {
    if (url.includes("/v0.1.0/")) return new Response("not found", { status: 404 });
    return new Response("/* console helper */", { status: 200 });
  }
  return realFetch(input, init);
};
store.clear();
r = await call("/elang-console.js");
globalThis.fetch = realFetch;
check("falls back to master when the tag predates the file", r.status === 200,
  String(r.status));
check("the fallback is marked in the response",
  r.headers.get("x-elang-ref") === "master", String(r.headers.get("x-elang-ref")));

console.log("\n=== 失败分支 ===");
githubMode = "403";
store.clear();
r = await call("/latest.json");
const err = await r.json();
check("GitHub API 403 时返回 503 而不是假数据", r.status === 503, String(r.status));
check("503 里带兜底地址", String(err.fallback || "").includes("github.com/o/r/releases/latest"));
r = await call("/elang-bundle-win64.zip");
check("下载路由在 API 失败时也不返回 302", r.status !== 302);
githubMode = "ok";

r = await call("/nope");
check("未知路径 -> 404", r.status === 404);
r = await call("/", { method: "POST" });
check("非 GET -> 405", r.status === 405);

console.log("\n" + "=".repeat(56));
const passed = results.filter(([, ok]) => ok).length;
console.log(`${passed}/${results.length} checks passed`);
if (passed !== results.length) {
  results.filter(([, ok]) => !ok).forEach(([n]) => console.log("  FAILED: " + n));
  process.exit(1);
}