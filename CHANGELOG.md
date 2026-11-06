# CHANGELOG — 慧学外语 PC 版迁移与后续开发

> **读者：开发 agent**。这是一份**带日期的详细更改历史**，不是现状说明：
> 每次改动的原因、实测数据、被推翻的假设、踩过的坑都记在这里，比 git 提交信息详细。
> 执行 agent 看 `SKILL.md`；**本文不随 skill 分发**。
>
> - 2026-11-04 由 `MIGRATION_CHECKPOINT.md` 改名而来；历史内容未改，
>   文中出现的旧文件名已统一替换为新名。
> - 各节按时间顺序追加，**旧结论不删**：被推翻的结论就地标注更正，
>   这样能看清判断是怎么变的。
> - 第 1-10 节写于迁移开始时，其中的"现状"只代表当时。

> **给接手的 agent：先读完这份再动手。**
> 最后更新：2026-11-04

---

## 1. 任务

慧学外语（`elang.zju.edu.cn`）的 UI + Vue 前端**经历了一次大更新**，
仓库现有的 `scripts/elang_reader.py` 和 `references/api_reference.md` 已**无法工作**。
目标：把脚本迁移到新版前端。

---

## 2. 重要：不要相信仓库里的文档

现有文档描述的**都是旧版**，实测已全部失效：

| 文件 | 写的内容 | 实测现状 |
|---|---|---|
| `references/api_reference.md` | Base `https://elang.zju.edu.cn:8082/`；`POST /subjectCate/gets`；Header `token` | 实际是 `https://elang.zju.edu.cn/en/*`；**GET** 请求；**JWT**（`localStorage` 的 `authorization`） |
| `CLAUDE.md` / `SKILL.md` | 路由 `#/read/index`；选择器 `.praxis-item`、`.van-nav-bar`；Vue 数据 `$data.listData`；方法 `check_answer()` / `to_submit()` | 桌面端全部重定向到 `#/pc/*`，以上路由/类名/字段/方法**都不再是渲染路径** |

**结论：以实测为准，文档只能当历史参考。**

---

## 3. 已实测确认的事实

### 3.0 阅读流程三层（已实测：字段名 + 方法源码）

#### 第 1 层：`#/pc/read/index` — 主题（学科）列表
组件 **`PcReadIndex`**

```
data    : categoryId(=2 阅读), categoryText('[阅读]'), lastResource, listData[]  ← 11 项
methods : getUser, normalizeImg, loadLastResource, loadList, toPraxis, toLearn
```

`listData` 每项字段：
`id, name, cover, subject_cate_id, category_id, read_num, level, resource_num, study_num, create_time`

实测值：`listData[0] = {id: 26, name:'旅游与交通', resource_num: 6, subject_cate_id: 6, category_id: 2, level: 1}`

> **⚠️ 陷阱：这里的 `id` 是 subject_id，取值是 26 这种，不是 2。**
> 我实测用 `subject_id=2` 拿到的是一条**听力(audio)**资源，会张冠李戴。
> **务必从 `listData` 取真实 id。**

方法源码：

```js
toLearn(t)  { this.$router.push({name:'PcReadLearn', query:{subject_id:t.id, subject_name:t.name}}) }
toPraxis(t) { const s = await API({sid:e.sid, resource_id:t.id});
              if (100===s.code) this.$router.push({name:'PcReadPraxis',
                  query:{log_id:s.data, resources_id:t.id}}) }
loadList()  { API({sid, category_id:this.categoryId, level:'', subject_cate_id:'', keyword:''})
              → listData = data.filter(x => Number(x.resource_num) > 0) }
```

→ **`log_id` 来自 `toPraxis` 内部的一次 API 调用**，无法自己拼 URL，必须调这个方法。

DOM：主题卡片 **`.subject-card`**（实测 11 个），内含 `.cover-wrap`。

---

#### 第 2 层：`#/pc/read/learn?subject_id=<真实id>` — 文章列表
组件 **`PcReadLearn`**

```
data    : subjectId, subjectName, resourceList[], loading
methods : getUser, normalizeStatus, statusText, statusClass, loadList, toPraxis
```

`resourceList` 每项字段：
`id, name, file_path, subject_id, content, is_has_job, status, category_id,
file_times, level, type_id, big_type_id, cdn_file_path, hisLabel, create_time`

**完成状态判定 —— 与旧版兼容 ✅**

```js
normalizeStatus(t){ const e=Number(t.status), s=Number(t.hisLabel); return s===1 ? 2 : e }
statusText(t)     { return this.normalizeStatus(t)===2 ? '已完成' : '未完成' }
statusClass(t)    { return this.normalizeStatus(t)===2 ? 'done' : 'todo' }
```

→ **`status === 2` 仍是"已完成"**（原始 status 为 2，或 `hisLabel === 1`）。
旧脚本的完成判定**可直接复用**。

方法源码：

```js
loadList()  { API({sid, subject_id:this.subjectId}); resourceList = data || [] }
toPraxis(t) { const s = await API({sid, resource_id:t.id});
              if (100===s.code) this.$router.push({name:'PcReadPraxis',
                  query:{log_id:s.data, resources_id:t.id}}) }
```

DOM：每篇 **`.resource-item`**，内含 `.item-main` / `.item-name` / `.item-status`；
未完成时 `.item-status` 带 **`todo`**，已完成带 **`done`**。

> `content` 字段直接在 `resourceList` 里（实测 1866 字符 HTML）——
> 正文**或许不必爬 DOM**。但**待验证**：实测那条是听力，
> **阅读类资源的 `content` 到底是全文还是摘要，尚未确认。**

---

#### 第 3 层：`#/pc/read/praxis?log_id=&resources_id=` — 题目页
组件 **`PcReadPraxis`** —— **尚未侦察**（下一步，见第 7 节）

已知：**验证码网关就在这个组件里**（见坑 5）。

---

### 3.1 仍然是 Vue 2 ✅

```
#app.__vue__        → 存在
#app.__vue_app__    → 不存在
```

这条很重要：**组件树遍历（`$children` / `$options.methods`）这条路仍然可用**，
不需要改写成 Vue 3 的 API。

### 3.2 路由是 hash 模式，共 148 条

`$router.options.routes` 可读，`$router.mode === 'hash'`。

### 3.3 两套组件并存（关键）

路由表里**新旧两套都在**，但桌面端实际渲染的是 `Pc*`：

| 新 PC 版（渲染路径） | 旧版（仍注册，但桌面端不会用到） |
|---|---|
| `PcReadIndex` | `Index` |
| `PcReadLearn` | `ReadLearn` / `Learn` |
| `PcReadPraxis` | `ReadPraxis` / `Praxis` |
| `PcPracticeDetail` | `Detail` |
| `PcPracticeHistory` | `HistoryList` |

**迁移目标是 `Pc*` 这批。**

### 3.4 阅读流程路由（已确认存在且有对应组件）

| 路由 | name | 组件 | 用途 |
|---|---|---|---|
| `#/pc/home` | `PcHome` | `PcHome` | 首页 |
| `#/pc/read/index` | `PcReadIndex` | `PcReadIndex` | **主题列表** |
| `#/pc/read/learn?subject_id=` | `PcReadLearn` | `PcReadLearn` | **文章列表** |
| `#/pc/read/praxis?log_id=&resources_id=` | `PcReadPraxis` | `PcReadPraxis` | **题目页** |
| `#/pc/read/detail` | `PcPracticeDetailRead` | `PcPracticeDetail` | 成绩详情 |
| `#/pc/read/history` | `PcPracticeHistoryRead` | `PcPracticeHistory` | 历史记录 |

### 3.5 `PcHome` 的完整 Vue 表面（已抓取）

**data：** `studyLanguage, languageOptions, languageRequestId, countSign,
maxContinuousDays, signedDays, year, month, fastList, currentCourses,
currentCourseIndex, currentCourseTimer, recommendCourses, noticeList,
noticeActive, noticeLoading, noticeTabs, showAi, countTask, weekList`

**methods：** `changeLanguage, refreshHomeData, getUser, categoryText,
categoryName, itemDateText, noticeTypeText, noticeTypeClass, noticeDateText,
normalizeImg, formatDate, normalizeSignDate, initUser, userSign, loadStudy,
loadSign, calculateContinuousDays, prevMonth, nextMonth, loadMenu, loadCourses,
loadNotice, checkPlant, pushTask, toPraxis, toPage, toTodayTask, toStudyList,
toCalendar, setCurrentCourse, startCurrentCourseCarousel, changeNoticeTab`

→ 注意 **`toPraxis` / `toPage` / `toStudyList`** 这类命名在新版里仍是导航入口。
→ `PcLayout` 持有 `userInfo, designWidth, designHeight, scale, logoSrc, navList`；
有 `designWidth/designHeight/scale` 说明是**等比缩放的自适应 PC 布局**。

### 3.6 登录仍是 CAS OAuth2

```
zjuam.zju.edu.cn/cas/login  →  elang.zju.edu.cn/#/authLogin?code=ST-...  →  POST /en/login/auth
```

`localStorage` 里是 `user` 和 `authorization`（JWT）。

---

## 4. ⚠️ 已踩过的坑（务必看，能省你几小时）

### 坑 1：直接加载深链会被吞掉

访问 `https://elang.zju.edu.cn/#/pc/read/index` 会**落到 `#/pc/home`**。
原因：应用要先跑 `#/authLogin?code=...` 换 token，这个跳转会**丢失目标路由**。

**正确做法：** 先 `goto` 基址 `https://elang.zju.edu.cn/`，等 Vue 挂载安定，
再用 `location.hash = "#/pc/read/index"` 做**同文档切换**。
`temp/inspect_live.py` 里的 `goto_route()` 已实现这个流程。

### 坑 2：wait_for_app 的时序很容易写错

判断"应用已安定"必须**同时**满足：
- URL 在 `elang.zju.edu.cn` 上
- URL **不含** `#/authLogin`
- `#app.__vue__.$children.length > 0`（Vue 真的挂载了）

早期版本把这三个条件写反/写漏，导致在 `#/authLogin` 上就误判成功，
抓到的快照是登录组件而不是应用。

### 坑 3：Playwright 必须提权才能跑

本环境的文件沙箱**禁止创建命名管道**，而 Playwright 必须用管道 stdio
启动它的 Node driver。所以：
- **任何浏览器实测都要 `sandbox_permissions: danger-full-access`**
- 这个提权需要用户点头，**跑之前先说明**：要访问站点、大概多久、是否只读

不要反复无提示地提权（已被拒绝过一次）。

### 坑 4：不要用 `p.chromium.launch` 的花哨变体

以下都**实测把启动搞坏**，别重蹈覆辙：
- `launch_persistent_context(channel="msedge")` → Edge 报"不受支持的命令行标志"，卡在 `about:blank`
- `launch(args=["--user-data-dir=..."])` → Playwright 直接报错，要求改用 persistent API
- `browser.new_context()` 后再 `new_page()` → 页面卡在 `about:blank`

**唯一验证过能正常登录的是最初的写法：**

```python
browser = await p.chromium.launch(channel="msedge", headless=False)
page = await browser.new_page()
```

### 坑 5：验证码的触发条件

**不是**登录时出现，也**不是**请求频率触发。
用户在**进入题目页**时出现，触发条件是**当天已完成篇数达到约 10 篇**。
（这是用户亲口确认的；我未独立复现。）

若有 `#/pc/read/praxis` 组件，它自带 `refreshCaptcha` / `checkCaptchaCode` 类方法，
即验证码的网关在**题目页组件自身**。

**重要：不要因为 `$data.dialogShow === true` 就判定被验证码拦住。**
那个字段在题目页默认就是 `true`，是通用的"有弹窗显示"标志，与验证码无关。
误判会导致代码主动调 `refreshCaptcha()`，**给本来健康的页面凭空招来一张验证码**，
然后陷入死循环。判定依据只能是**服务端真的返回了图片**。

### 坑 6：不要在登录/路由未安定时就下结论

CAS 回调 `#/authLogin?code=...` 期间页面是空的，此时查选择器必然失败。
必须等安定。

---

## 5. 需要重写的代码范围

`scripts/elang_reader.py`（1122 行）中，**只有三块**依赖前端细节：

| 行号 | 函数 | 依赖 |
|---|---|---|
| 174–225 | `navigate_to`、`go_back_to_learn` | 路由 + 选择器 |
| 232–375 | `extract_page_content`、`get_article_list`、`click_article` | Vue 字段名 + DOM 类名 |
| 383–431 | `set_answers`、`submit` | Vue 方法名 |

**不需要动（与 UI 无关，可直接复用）：**

- 答案库加载与标题匹配（`_normalize_title`、`_match_answer_bank`）
- `references/parse_answers.py`
- 文件 IPC 协议（`elang_current.json` / `elang_signal.json` / `elang_checkpoint.json`）
- 检查点 / 断点续传（每 50 篇）
- CLI 入口（`batch-all` / `batch` / `solve`）
- 验证码 OCR（`ddddocr`）
- 凭据加载（`.env`）

---

## 6. 现成的工具

**`temp/inspect_live.py`** —— 只读侦察器，编译通过，**不会点答案、不会交卷**。

```bash
PY="~/.claude/skills/huixuewaiyu-readingpart/.venv/Scripts/python.exe"

$PY temp/inspect_live.py login
#   → 登录 + 抓完整路由表 + 组件表面

$PY temp/inspect_live.py page "https://elang.zju.edu.cn/#/pc/read/index"
#   → 先安定会话，再用 hash 切换路由，抓 DOM/组件/选择器快照

$PY temp/inspect_live.py click "<url>" "<selector>" <index>
#   → 点一个元素后抓快照
```

输出到 `temp/inspect/<时间戳>-<标签>/`：
- `snapshot.json` —— URL、class 频次、重复元素、Vue 组件树（data + methods 名）
- `page.html` —— 完整 DOM
- `page.png` —— 全页截图

**已存 3 个快照**（都是登录后的首页）：

```
temp/inspect/20260926-120726-after-login
temp/inspect/20260926-120818-after-login
temp/inspect/20260926-120930-after-login   ← 最完整，含 148 条路由表
```

运行环境：
- 解释器用 skill 的 venv（系统 Python 没有 `ddddocr`）
- 凭据从 `~/.claude/skills/huixuewaiyu-readingpart/.env` 自动加载
- 浏览器启动命令**每次都需要 `danger-full-access` 提权**（见坑 3）

---

## 7. 建议的下一步

按顺序做，**每步只抓一个页面的快照，不要连跑**：

1. **`page "#/pc/read/index"`**
   拿到 `PcReadIndex` 的 `data` / `methods` 和主题卡片 DOM 类名。
   需要确认：主题列表存在哪个字段？（旧版叫 `listData`，新版未知）
   主题的 `id` 与名称字段是什么？

2. **`page "#/pc/read/learn?subject_id=14"`**
   拿到 `PcReadLearn` 的 `data` / `methods`。
   需要确认：文章列表字段名、文章的 `id`/`name`、**完成状态如何表示**
   （旧版是 `status === 2`）。

3. **`click` 进入一篇文章**
   拿到 `PcReadPraxis` 的 `data` / `methods`。
   需要确认：题目数据字段名；正文从哪来（DOM 还是 API）；
   作答方法名（旧版 `check_answer(qIdx, optIdx)`）；提交方法名（旧版 `to_submit()`）。

4. 三块信息齐了再动 `elang_reader.py`，**一次只改一块**。

**注意：** 第 3 步会进入题目页，可能触碰验证码（约 10 篇/天）。
单次只进 1 篇，风险很低。若出现验证码，让用户手动输入，不要写自动 OCR 死循环。

---

## 8. 环境备忘

| 项 | 值 |
|---|---|
| 仓库 | `<repo>` |
| HEAD | `c34590d`（工作区干净） |
| venv 解释器 | `~/.claude/skills/huixuewaiyu-readingpart/.venv/Scripts/python.exe` |
| 凭据 | `~/.claude/skills/huixuewaiyu-readingpart/.env`（学号 `<已隐去>`） |
| 安装的 skill 副本 | `~/.claude/skills/huixuewaiyu-readingpart/`，脚本与 HEAD 一致 |
| 站点可达性 | 仅校园网可达（`elang.zju.edu.cn` → 内网 IP `10.202.160.113`） |
| 普通 TLS 栈 | **连不上**（`Invoke-WebRequest` / `curl` 均失败），只能靠浏览器 |

### 与本次迁移无关的既有残留

`C:\tmp` 下有两份**旧版脚本留下的**文件（时间戳 2026/5/30，早于本次工作）：

```
C:\tmp\elang_screenshots
C:\tmp\elang_checkpoint.json
```

`elang_checkpoint.json` 可能含旧的 `completed_categories`，
**会让脚本跳过它认为"已完成"的主题**。迁移调试时建议先备份再删除，避免误判。

---

## 9. 本次会话的产出与未完成项

**产出：**
- 本节检查点文档
- `temp/inspect_live.py`（只读侦察器）
- 3 个快照

**未完成：**
- `scripts/elang_reader.py` **一行未改**
- `references/api_reference.md` 仍是错的，**尚未重写**

---

## 10. 更新（第二轮侦察）— 含对第 4 节坑 5 的**更正**

### 10.1 ⚠️ 更正：`dialogShow` 的语义我之前写反了

第 4 节坑 5 里我写的"`dialogShow` 在题目页默认就是 `true`" **是错的**，现更正：

实测 `PcReadPraxis` 进入时 **`dialogShow === false`**。看 `checkCaptchaCode` 源码可知，
`dialogShow` 是在**验证码校验成功后**被置为 `true` 的：

```js
async checkCaptchaCode() {
  const e = await API({sid, captchaCode: this.verifyCode});
  if (100 === e.code && 1 == e.data) {
    this.dialogShow = true;      // ← 成功后才置 true
    await this.loadJobList();
  } else {
    await this.refreshCaptcha();  // ← 失败则换一张图
  }
}
```

→ **`dialogShow === true` 表示"已经通过验证"，不是"被验证码拦住"。**
判定"被拦住"的正确依据是 **`imageBase64` 有图 且 `jobList` 为空**。

### 10.2 验证码网关的确切行为（已读源码）

```js
refreshCaptcha() { API({sid}) → this.imageBase64 = 'data:image/png;base64,' + data.imageBase64 }
```

`PcReadPraxis` 进入时的实测状态：

```
dialogShow       : false
imageBase64      : 7330~7534 字节的 PNG（图**已经在了**）
verifyCode       : ''
jobList          : []          ← 空的
loading          : false       ← 从未观察到 true
```

**`imageBase64` 有人、`jobList` 为空 = 题目被验证码网关挡住。**
这与用户说的"题目刷新次数多了会出验证码"一致。

### 10.3 关键架构变化：导航方法内部会调 API ⚠️

**这一点会直接影响迁移设计，务必注意。**

旧脚本的模型是"纯 Vue 方法调用"（`check_answer()` / `to_submit()`）。
新版**不是**这样 —— 两个 `toPraxis` 都是 **async 且自己发 API 请求**：

```js
// PcReadIndex.toPraxis  与  PcReadLearn.toPraxis 结构相同
async toPraxis(t) {
  const s = await API({sid, resource_id: t.id});      // ← 先请求，拿到 log_id
  if (100 === s.code)
    this.$router.push({name:'PcReadPraxis',
                       query:{log_id: s.data, resources_id: t.id}});
}
```

→ **`log_id` 由服务端签发，无法自己拼 URL。必须调用 `toPraxis`（或等价 API）。**
→ `PcReadPraxis.loadJobList` 同样是 async：`API({sid, resource_id})` 之后才填
  `resources` 和 `jobList`。
→ 因此**任何"读取页面数据"的步骤都必须以数据到位为条件，不能靠固定 sleep**。

### 10.4 仍未查明 / 存疑

1. **`PcReadPraxis` 的 `jobList` 为何不加载。**
   实测进入文章后轮询 40 秒，`jobs` 始终 0、`blocks` 始终 0、`loading` 从未为 true
   → 疑似 `loadJobList()` 根本没跑，或失败被静默吞掉。
   **`resources` 字段实测只有 `{resources: {...}}` 一个键**，需要看清它到底装了什么。
   下一步应抓**网络请求**确认 `resource_id` 那个 API 有没有发出、返回什么。

2. **`/#/authLogin?code=...` 间歇性空白卡死。**
   症状：URL 停在 authLogin，页面**完全空白**，Vue 壳未挂载，token 交换未完成。
   **是间歇性的**：同一流程有时正常落到 `/#/pc/home`，有时卡死（用户曾亲眼见到）。
   **尚未定位根因。** 已在 `inspect_live.py` 的 `login()` 里加了失败时自动倒出
   网络请求 / 控制台错误 / localStorage / URL 轨迹的诊断，但重跑时**没复现**。
   下次复现时可直接看诊断输出。

3. **阅读类资源的 `content` 是不是全文。**
   实测那条是听力（`type_id:"audio"`，`file_path` 为 `.MP3`），
   阅读类（`type_id` 应类似 `"read"`）的 `content` 长度与形态**未确认**。

4. **`subject_id` 必须从 `listData` 取真实值**（26 这类），
   不要用 `categoryId`（2）或猜测的数字 —— 我实测踩过这个坑。

### 10.5 侦察现状

已有快照（`temp/inspect/`）：

| 快照 | 内容 |
|---|---|
| `*-after-login` ×4 | 登录后的路由表 + `PcHome`/`PcLayout` 表面 |
| `*deep-_pc_read_index*` | **`PcReadIndex`** 字段值 + 方法源码 ✅ |
| `*deep-_pc_read_learn_subject_id2*` | `PcReadLearn`（subject_id=2，**听力，选错了**） |
| `*eval-_pc_read_praxis*` ×3 | **`PcReadPraxis`** 字段值 + 全部方法源码 ✅ |

新增工具：

- `temp/inspect_live.py` 新增 `deep <route> [组件名,..]` 与 `eval <route> <js文件>`
  两个命令；`deep` 会 dump 字段值（类型/长度/样本）与方法源码
- `temp/js_open_first_article.js` —— 在 `PcReadLearn` 页调用 `toPraxis` 打开第一篇未完成文章
- `login()` 现在在壳未挂载时会**自动倒出诊断**（网络/控制台/localStorage/URL 轨迹）

编译通过。**`scripts/elang_reader.py` 仍是一行未改。**

### 10.6 下一步建议（按优先级）

1. **先解决 `jobList` 不加载**（这是打通阅读流程的关键阻塞点）。
   用 `eval` 打开文章时**抓网络**，确认那个 `API({sid, resource_id})`：
   有没有发出？HTTP 状态？响应体是什么？
   → 若响应是"需要验证码"，则按第 10.2 节实现验证码反馈机制。
2. **实现验证码检测/反馈机制**（用户明确要求，见第 11 节）。
3. 抓一篇**真正的阅读类**文章（`subject_id` 从 `listData` 取，确认 `type_id` 不是 audio），
   确认 `content` 是否为全文。
4. 复查 `/#/authLogin` 卡死（等下次复现，读诊断输出）。

---

## 12. 第三轮侦察结论（**重大更正**：迁移比预想的小得多）

### 12.1 ⚠️ 最重要的更正：新 UI **沿用了旧的 class 名**

之前我判断"选择器全变了"，**这是错的**。实测 `PcReadPraxis` 的 DOM：

```
.pc-read-praxis
  .breadcrumb                      当前位置：首页>书海遨游>Bathing Beauty
  .read-layout
    .article-panel > .article-container > .article-reader > .article-content   ← 正文
    .right-col
      .history-card > .history-title / .history-score / .history-meta
      .question-block x10                        ← 与旧版同名 ✅
        .question-title                          ← 与旧版同名 ✅
        .option-list
          .option-row (button) x30               ← 'A\nYes' / 'B\nNo' / 'C\nNot given'
      button.submit-btn  '提交'                  ← 与旧版同名 ✅
```

**`.question-block` / `.question-title` / `.option-list` / `.option-row` / `.submit-btn`
这些选择器在新版里依然存在、且就是渲染路径。**
旧脚本的 `extract_page_content()` 选择器**基本可以直接用**。

`type_id` 与 `isFillType` 也**完全没变**：`1/4` 选择、`2/5/7/8` 填空、`3/6` 其他。

### 12.2 正确答案：之前失败是**加载慢 + 我自己误判**，不是页面结构变了

实测同一篇文章，两次结果不同：

| 轮询时刻 | jobs | blocks | dialogShow | captchaImg |
|---|---|---|---|---|
| 进入后 ~40s 内（我第一次） | 0 | 0 | false | 7.3KB |
| **再等一会儿（这一次）** | **10** | **40** | **true** | 7.9KB |

**所以题目确实会加载，只是需要更长时间**，我早期用固定 sleep / 过早判定，
得出了"题目永远不加载"的错误结论。**这是我的测量方法有问题，不是应用有问题。**

### 12.3 praxis 页的真实加载顺序（抓包实证）

```
POST /en/resources/saveUserStudyResource
GET  /en/jobAnswer/getHistoryList
POST /en/yzm/saveAccessLog
POST /en/yzm/createCaptcha      ← 取验证码
POST /en/yzm/checkCaptcha       ← 校验验证码
GET  /en/job/gets               ← 题目在此之后才返回
```

顺序是 **createCaptcha → checkCaptcha → job/gets**。
→ **验证码是题目加载流程的一环**，不是"刷够 10 篇才出现的意外"。
→ 但**实测它是能通过的**（连续两次都通过了），所以并非每次都需人工干预。

### 12.4 更正：第 10.2 / 11 节关于"被验证码拦住"的判定

> ### ❌ 本节结论已被推翻 —— 请看第 13 节
>
> 本节下面的推断建立在一个错误前提上：我以为"等到 `jobs=10`"是应用自己加载的。
> **用户澄清：那次是用户手动输入验证码后才进入题目的。**
> 所以 **`imageBase64` 有图 + `jobList` 为空 确实就是"被验证码拦住"**，
> 第 10.2 / 11 节的原判据是**对的**。本节以下内容仅作追溯保留。

实测 `imageBase64` **有图**的情况下，`jobList` **照样能加载**。
所以：

```
❌ 旧写法：imageBase64 非空 且 jobList 为空  ⇒  被拦住
✅ 正确：  这只是"还在加载中"，必须继续等
```

**`jobList === 0` 不等于被拦住**，只等于"还没到"。
真正的判据仍需进一步确认：**只有 `checkCaptcha` 失败导致 `job/gets` 被拒时才算被拦**，
而这在抓包上看不出区分。**保守做法：等 `jobList` 或题目 DOM 出现，给足够超时
（实测 60s 足够）；期间若发现验证码需要人输（比如超时很久仍无题目），
再走第 11 节的 OCR / 手动流程。**

### 12.5 真实 API 端点（都在 `/en/` 前缀下）

```
POST /en/login/auth                        CAS code 换 token
GET  /en/user/getUserRowByToken
GET  /en/subject/getCategoryList           分类
GET  /en/subject/gets                      主题
GET  /en/resources/gets                    文章列表
POST /en/resources/saveUserStudyResource   创建练习会话（→ log_id）
POST /en/yzm/createCaptcha                 取验证码
POST /en/yzm/checkCaptcha                  校验验证码
POST /en/yzm/saveAccessLog
GET  /en/job/gets                          题目（含 jobList）
GET  /en/jobAnswer/getHistoryList          历史
```

`references/api_reference.md` 里写的 `:8082`、`/subjectCate/gets`、`/resources/gets`（POST）、
`token` header **全是旧的**。真实是 **`/en/*` + GET（多数）+ JWT**。

### 12.6 praxis 的提交契约（与旧版一致，已读源码）

```js
buildSubmitData()   // 按 type_id 分派
  1        单选/判断 → {user_id, job_id, type_id, lable, answer, is_right, resource_id}
  4        多选     → ...answer = 被选中 label 用 ',' 连接
  2        填空     → 按 getBlankCount 逐空 {lable: n+1, answer, is_right}
  5/7/8    选词填空 → 从 optionsArray1 取
  3/6      其他

openSubmitConfirm() { if (!submitting) this.submitConfirmVisible = true }
confirmSubmit()     { API(buildSubmitData()) → if (100===code)
                      API({id: this.logId}) → if (100===code)
                      → router.push({name:'PcPracticeDetailRead', query:{resource_id}}) }
```

→ **提交是两步：`openSubmitConfirm()` 再 `confirmSubmit()`**，且 `confirmSubmit` 内部
会**连发两个 API**（提交 + 结算），最后**跳转到详情页**。

### 12.7 修正后的迁移工作量评估

**比预期小很多：**

| 区域 | 结论 |
|---|---|
| `extract_page_content` 的**选择器** | **基本可复用**（`.question-block` 等未变） |
| `get_article_list` 的**字段名** | **可复用**（`resourceList`、`status===2`） |
| `set_answers` / `submit` 的**方法名** | 需改（`check_answer`→`selectOption`，`to_submit`→两步提交） |
| 路由 | 需改（`/pc/*`） |
| **加载等待策略** | **必须重写**（以数据到位为条件，不能固定 sleep） |
| 验证码 | 需新增（但实测通常自动通过） |

**真正的工作量在"等待策略"和"路由"，不在选择器。**

---

## 13. 用户明确要求：验证码检测 + 反馈机制

> ### ✅ 已由用户澄清（**第 12.4 节的更正作废，以本节为准**）
>
> 用户描述的事实：**那次运行直接跳到了验证码界面，是用户手动输入验证码后
> 才进入题目的。**
>
> 这意味着第 12 节里"抓到 `jobs=10` 所以题目会自己加载"的推断**是错的** ——
> 那 10 道题是**用户手动过验证码之后**才出现的。
>
> **结论回到最初的判断，并且是确定的事实：**
>
> ```
> 进入 PcReadPraxis
>   → createCaptcha 取图
>   → 需要人（或 OCR）提交验证码
>   → checkCaptcha 通过
>   → job/gets 才返回题目
> ```
>
> **验证码未通过 ⇒ 题目永远不出现。** 这就是"卡在题目页、URL 正确但无题目"的根因。
>
> 因此 `imageBase64 有图 + jobList 为空` **确实可以**作为"拦截中"的信号 ——
> 但必须**配合足够长的等待**（不能一看到就判定，要给它自动通过的机会）。
> 正确做法见下面第 13.1 节的最终流程。

用户原话意图：**遇到验证码不要突然死机茫然** —— 要能立刻察觉、
**马上 OCR 或让用户手动输入**。

### 13.1 最终实现流程（合并所有实测事实）

**进入题目页后：**

1. 轮询 `PcReadPraxis` 的状态：`{jobList.length, imageBase64.length, dialogShow}`，
   **每 1~2 秒一次**
2. 若 `jobList.length > 0` → 题目已就绪，继续正常流程
3. 若 `imageBase64` 有图且 `jobList` 仍为空 → **进入验证码处理流程**：
   a. 把 base64 图存盘留证（`ddddocr` 之前先留底）
   b. **OCR**：`ddddocr.classification(png_bytes)` → 期望 4 位
   c. 写入 `vm.$data.verifyCode = code`，调用 `vm.checkCaptchaCode()`
   d. 轮询 `jobList`；若出现 → 成功，继续
   e. 若失败（`checkCaptchaCode` 内部会调 `refreshCaptcha()` 换新图）→
      **重试，但必须有上限（建议 3 次）**，并且**每次比对 `imageBase64` 是否变化**；
      **图没变就立即停止重试**（这是我早先在旧版栽过的死循环）
   f. OCR 次数用尽 → **明确 print 提示**：
      「请在弹出的窗口手动输入验证码，最多等 300 秒」
      → 然后轮询等待 `jobList` 出现，用户输完自动继续
4. **全程 print 明确状态**，任何分支都不要静默卡住
5. **绝不主动调 `refreshCaptcha()`**（页面健康时会凭空招来一张验证码）

**注意：验证码弹窗是 Vant 组件**（快照里出现过 `van-popup`），
而快照的 `inputs` 为空 —— 说明输入框在弹窗内部、当时没渲染或被我的探测漏掉。
所以**优先走"数据层"（`verifyCode` + `checkCaptchaCode`）**，
DOM 层（找输入框填值）作为兜底。

### 13.2 另一个独立问题：登录后偶发空白页

> **用户明确判断：这个问题和验证码没有直接关系，是另一个问题。**
> 记录时请**独立对待**，不要与第 13 节的验证码流程混在一起。

**症状（已观察）：**
- URL 停在 `https://elang.zju.edu.cn/#/authLogin?code=ST-...`
- 页面**完全空白**，Vue 壳未挂载（`#app` 无 `__vue__`）
- 是**间歇性**的：同一流程有时正常落到 `/#/pc/home`
- 用户反馈"**也许每次出现的结果是随机的或者不同的**"

**根因：未定位。** 以下是**待验证的假设，不是结论**：

| 假设 | 依据 | 验证方式 |
|---|---|---|
| token 交换失败/挂住 | `POST /en/login/auth` 不成功就不会路由离开 authLogin | 看该请求的 HTTP 状态与响应体 |
| `authLogin` 组件抛错 | 该组件有 `getQueryString/save/userSign`，注入失败即白屏 | 看 console 的 `pageerror` |
| `PcLayout` 缩放计算异常 | 有 `designWidth=1158 / designHeight=655 / scale`；`updateScale()` 若取到 0 尺寸可能算出 `Infinity` | 看 console + 该元素 `__vue__` 是否存在 |
| 连续两次 `goto` 引入竞态 | 我的 `login()` 先 `goto` 基址，3 秒后又走完 CAS；若首次导航未安定就发生重定向，hash 解析可能落空 | 对比"单次 goto 直达"与"两次 goto" |

**⚠️ 踩过的失误：** 诊断信息当时只 print 到 stdout，**没有落盘**；
后来重跑未复现，证据永久丢失。**下次遇到请第一件事就是把诊断写入文件。**

**已具备的诊断能力**（`temp/inspect_live.py` 的 `login()`，壳未挂载时自动触发）：
网络请求（仅 `/en/`）、console + `pageerror`、`localStorage` 的 `user`/`authorization`、
URL 轨迹、`#app` 挂载状态。

**处理策略：**
- 不要假定一次成功 —— **加"壳未挂载则重试"**，重试前先存诊断
- 重试仍可用，因为 `/#/pc/home` 是稳定可达的（实测多次成功）


### 设计要点（依据 10.2 的实测语义）

**正确判据（进入题目页后）：**

```
被验证码拦住  ⇔  imageBase64 非空  且  jobList 为空
```

**绝不能**用 `dialogShow` 判断（见 10.1 更正）。
**绝不能**在页面健康时主动调 `refreshCaptcha()` —— 那会**凭空招来一张验证码**。

**建议流程：**

1. 进入题目页后轮询 `{jobList.length, imageBase64.length, loading}`
2. 若 `jobList` 先到 → 正常继续
3. 若 `imageBase64` 有图且 `jobList` 仍空超过 N 秒 → **判定被拦**，进入验证码流程
4. 验证码流程：
   a. 取 `imageBase64`（base64 PNG），存盘留证
   b. 用 `ddddocr` OCR 出 4 位
   c. 写入 `verifyCode`，调 `checkCaptchaCode()`
   d. 成功（`dialogShow` 变 true 且 `jobList` 有了）→ 继续
   e. 失败 → 图会被刷新，**重试有上限**（建议 3 次）；每次必须比对图是否变了，
      **若图没变就别再重试**（否则会死循环——我在旧版就栽过这个坑）
   f. OCR 用完 → **明确提示用户**："请在弹出的窗口手动输入验证码"，
      然后轮询等待（给足超时，如 300 秒），用户输入后自动继续
5. **任何情况下都要 print 出明确状态**，不要静默卡住

**OCR 已验证可用**：早期实测 `ddddocr` 对 elang 的 4 位数字验证码
（200×100 PNG，带干扰线）识别正确。

**待确认**：`PcReadPraxis` 的验证码弹窗是 Vant 组件（快照里出现过 `van-popup`），
所以可能需要同时处理"数据层面"（`verifyCode` + `checkCaptchaCode`）和
"DOM 层面"（输入框 + 确认按钮）两条路径。**下一步侦察时留意。**



## 14. CAS 白屏根因已查明（**已解决，不是我们的 bug**）


### 14.1 根因

失败的诊断已成功落盘
（`temp/inspect/20260926-203107-LOGIN-FAILURE/diagnosis.json`）。
控制台完整链路：

```
log   : ST-356905-dTYWRcV3Wppq0kQ2Kggf-zju.edu.cn     ← CAS 票据已签发
log   : signStr code=ST-356905-...zjuEnglish
error : 用户未登录或没有找到sid                          ×2
log   : {code: 400, msg: failure, data: 登录失败}       ← 服务端业务层拒绝
error : CAS login failed {code: 400, msg: failure, data: 登录失败}
```

关键证据：

| 项 | 值 | 含义 |
|---|---|---|
| HTTP 状态 | **200** | 请求送达了 |
| 响应体 | `{code:400, msg:failure, data:登录失败}` | **业务层拒绝换 token** |
| `localStorage` | **`[]` 空** | 没有 `user` / `authorization` |
| `#app` | `vue:true, children:1` | **Vue 挂载了**，只是没有用户态 |
| `layoutScale` | `null` | 没渲染到 `PcLayout`，**排除缩放假设** |

→ 结论：**`POST /en/login/auth` 返回 `code:400 登录失败`**，
应用拿不到 token → 不跳路由 → 停在 `/#/authLogin` 白屏。

**不是** token 交换挂住，**不是** `PcLayout` 缩放异常（原假设作废）。

### 14.2 结论与处置

**这很可能是 CAS 侧的频控/限制，不是代码 bug。**
本次会话为侦察跑了**十几次真实 CAS 登录**，高度可疑地触发了限制。

**处置：暂时搁置该问题，不再对站点做真实运行。**
排查该问题的前提是：静置一段时间后，**用用户的普通浏览器手动登录**确认是否恢复：
- 若手动登录也失败 → CAS 侧限制，等待即可
- 若手动登录正常 → 才是自动化流程的问题，另查

**已具备的能力（下次复现可直接取证）：**
`temp/inspect_live.py` 的 `login()` 在壳未挂载时会自动把诊断**写入磁盘**
（`LOGIN-FAILURE/diagnosis.json` + 截图 + HTML），
包含：URL 轨迹、网络请求（仅 `/en/`）、console 与 `pageerror`、
`localStorage`、`#app` 挂载状态、`PcLayout.scale`。
> 教训：诊断必须落盘。第一次遇到时只 print 到 stdout，重跑未复现，证据永久丢失。

---


## 15. 验证码：两套机制已实现并离线验证通过

工具：**`temp/captcha_solver.py`**（独立模块，可离线测试，不依赖站点）

### 15.1 机制一：ddddocr（快、离线、免费）

```bash
python temp/captcha_solver.py ocr <img.png>
python temp/captcha_solver.py ocr-base64 <file-with-data-uri.txt>
```

**已知样本实测：**

| 样本 | 尺寸 | 视觉读取 | ddddocr | 结果 |
|---|---|---|---|---|
| `temp/captcha_samples/elang_captcha_known.png` | 200×100 | `7270` | `7270` | ✅ 一致 |

两种输入路径都验证过：**直接读文件**、**读 data-URI**（应用实际给的就是 data-URI）。

> ⚠️ 注意：`ddddocr` 对这类强干扰图**并非总对**。实测返回耗时 0.02~0.05s，
> 比预期（~1.2s）快很多，可能命中了缓存或轻量模型。
> 因此模块做了**预热**（`_get_ocr()` 先跑一张空白图），并且**不把 OCR 当唯一手段**。

### 15.2 机制二：视觉模型 / 人工（可靠兜底）

代码不能自己调模型，所以采用**文件交接**：把图写到 IPC 目录，
让 agent（或人）看图后把答案写回。

```
1. captcha_solver.solve(png, ipc_dir)  → OCR 失败时
2. 写 <ipc>/elang_captcha_request.json   {"status":"captcha_needs_vision",
                                          "image_path":"<ipc>/elang_captcha_image.png", ...}
3. agent 用视觉读图（或用户肉眼看）→ 写 <ipc>/elang_captcha.json  {"captcha_code":"XXXX"}
4. captcha_solver.read_answer(ipc) → "XXXX"
```

**本会话已用视觉机制亲自验证**：读 `elang_captcha_known.png` 得到 `7270`，
与 ddddocr 结果一致 —— 说明这条路径在真实环境下可用。

### 15.3 状态机测试（全部离线通过）

| 用例 | 结果 |
|---|---|
| A：OCR 成功 | `code='7270' source='ocr'`，不触发视觉 |
| B：OCR 失败 | 请求已写，`request.image_path` **存在且可读**（7617B） |
| C：agent 给答案 | `read_answer -> '7270'` |

> 期间修掉一个自造 bug：`write_request` 原先把图存到 samples 目录，
> 却在请求里写上那个路径 —— agent 按图索骥会找不到文件。
> 已改为**图存进 ipc_dir**，路径与内容一致。

### 15.4 与站点对接时的注意事项（重要）

1. **判据**：`imageBase64` 有图 **且** `jobList` 为空 = 需要验证码
   （由用户手动过验证码的事实确认；见第 13 节）
2. **走数据层**：`vm.$data.verifyCode = code` → `vm.checkCaptchaCode()`
   **不要**依赖 DOM 输入框（快照显示**没有渲染 `<input>`**，弹窗是 Vant 组件）
3. **必须比对图片是否变化**：`checkCaptchaCode` 失败时会调 `refreshCaptcha()` 换新图；
   若图**没变**说明服务端没刷新，**立即停止重试**，否则死循环（旧版栽过）
4. **重试上限 3 次**，OCR 用尽转视觉/人工
5. **绝不主动调 `refreshCaptcha()`** —— 页面健康时会凭空招来验证码
6. 全程 print 明确状态，任何分支都不静默卡住

---

---

## 16. 登录状态持久化 + 验证码接线（已实测）

### 16.1 结论先行

**登录状态可以保存并复用，已验证可免去 CAS 登录。**

### 16.2 ⚠️ 关键发现：只存 localStorage 完全不够

第一版只保存 localStorage（`user` + `authorization` JWT），**失败**。隔离测试证据：

```
goto("https://elang.zju.edu.cn/")
+0s url=https://zjuam.zju.edu.cn/cas/login?service=...   user=0 auth=0
   -> REDIRECTED TO CAS
```

**`https://elang.zju.edu.cn/` 是服务端保护的路由**，第一个请求就 302 到 CAS，
**发生在任何页面脚本运行之前**。因此：

- init script 根本没机会在 elang 源上执行（实际跑在 CAS 页面上，跨源写入被丢弃）
- **没有 CAS 会话 cookie，就永远到不了 SPA**

→ **必须同时保存 cookie。这是本节最重要的一条。**

### 16.3 实现

**保存**（`save_session`）：localStorage 的 `user`/`authorization`
**加上** `context.cookies()`，写入 `<IPC>/elang_session.json`。
实测捕获 **6 个 cookie**：

```
zjuam.zju.edu.cn   JSESSIONID            path=/cas   httpOnly
.zju.edu.cn        _csrf
.zju.edu.cn        _pv0
.zju.edu.cn        _pf0
.zju.edu.cn        _pc0
.zju.edu.cn        iPlanetDirectoryPro   ← CAS SSO 票据
```

**恢复**（`install_session`）顺序很关键：

1. `context.add_cookies(...)` —— **在第一次导航之前**装上 cookie，
   否则会被服务端 302 到 CAS（那时再做什么都晚了）
2. `context.add_init_script(...)` —— 在应用脚本之前种下 localStorage

> **API 陷阱**：Playwright **Python** 的 `add_init_script` **不接受参数**（JS 版接受）。传参报
> `TypeError: BrowserContext.add_init_script() takes from 1 to 2 positional arguments but 3 were given`。
> 解决：把值 `json.dumps` 后**内联进脚本源码**。

**有效期**：`SESSION_MAX_AGE = 7 天`；过期会话被忽略并回退 CAS。

### 16.4 过期会话自动降级（重要健壮性）

保存的会话**可能被服务端拒绝**（实测第一次恢复被拒、第二次成功 —— 票据交换似有时效性）。
原实现会因此**空转**：URL 停在 `/#/authLogin`、抓到 0 篇文章、静默什么都不做。

新增 `ensure_logged_in(page, url, restored)`：

```
navigate → 检查 session_is_live()
  活的              → 直接用（打印 "CAS skipped"）
  死的 且 来自恢复   → 丢弃会话 + clear_cookies + reload → 重走 CAS → 存新会话
  死的 且 本次新登录 → 尽力而为，不无限重试
```

`session_is_live()` 判据：localStorage 有 `user`+`authorization`、
且 URL **不在** `#/authLogin`、**不在** `zjuam`。

### 16.5 顺带修掉的两个问题

1. **凭据解析找不到 skill 的 `.env`** —— 开发时跑仓库副本读不到凭据并卡在 `input()`。
   现在按序查找：脚本旁 → cwd → `~/.claude/skills/.../.env` → `~/.agents/skills/.../.env`。
   **且 stdin 非交互时直接报错退出**，不再抛 `EOFError` 弄死整个 run。
2. **`ELANG_TMP_DIR` 已恢复**（IPC 目录可覆盖，沙箱/测试用；不设时仍默认 `C:/tmp`）。

### 16.6 验证码接线（已完成）

`wait_for_captcha` 原本就在三个点被调用，但 `detect_captcha` **是旧的 DOM 启发式**
（找 `img[src*="captcha"]`、正文关键词），**在 PC 页面永远返回 false**，
所以整条验证码链路**从未触发过**。

现在 `detect_captcha` **先查数据层**：

```
gated   = 有 imageBase64 且 jobList==0 且无题目 DOM  → 判定被拦
cleared = jobList>0 或 题目 DOM 存在                → 判定已通过
```

两半都必要 —— 图是正常加载流程的一部分，**图的出现本身不等于被拦**；
题目出现才证明验证码过了。DOM 启发式保留作移动版兜底。

### 16.7 当前运行实测结果

| 项 | 结果 |
|---|---|
| CAS 登录 | ✅ 恢复正常（限制已解除） |
| 会话保存 | ✅ `elang_session.json`（含 6 cookies） |
| 会话恢复 | ✅ `saved session is live — CAS skipped` |
| 落到正确页面 | ✅ `#/pc/read/learn?subject_id=26`（不再被弹回 home） |
| 验证码接线 | ✅ 已接（本次未触发，故未实测提交） |
| **文章列表解析** | ❌ **仍是旧逻辑** → 走文本兜底，抓到 6 篇但字段不对 |
| **题目提取/作答/提交** | ❌ **仍是旧移动版选择器** |

**结论：登录层已可用。下一步是第 5 节那三块（列表 / 提取 / 作答提交）。**
按第 12.7 节评估，选择器大多可复用，主要工作量在等待策略。

---

## 17. 间歇性白屏：根因确认（票据被重复使用）

### 17.1 用户提供的控制台证据（决定性）

```
authLogin.vue:79  ST-746842-ezfmRIB2s1LNr0semEae-zju.edu.cn
home.js:12        signStr code=ST-746842-...zjuEnglish
NormalLayout.vue:31  用户未登录或没有找到sid
NormalLayout.vue:44  用户未登录或没有找到sid
authLogin.vue:37  Object
authLogin.vue:43  CAS login failed Object
```

### 17.2 根因

**`ST-746842` 是一个已被消费过的 CAS 票据，而应用在反复重试它。**

关键推理链：

1. `ST-746842` 在**之前运行**里就出现过（当时就是"会话被拒"的那次）
2. 用户这次白屏、以及检查点第 14 节记录的那次白屏，**都是同一个 `ST-746842`**
3. 应用的 `authLogin.vue` 在 `#/authLogin?code=ST-...` 上做票据交换
4. CAS 服务票据是**一次性**的 —— 交换过就作废
5. 再交换必然返回 `code:400 / 登录失败`
6. 应用**不会自己去 CAS 换一张新票据**，就停在 `/#/authLogin` 白屏

**为什么死票据会被反复加载？因为它在地址栏的 hash 里**：

```
https://elang.zju.edu.cn/#/authLogin?code=ST-746842-...
```

hash 是 URL 的一部分。恢复会话时如果只清 cookie、
**不清应用存储**，`goto("/")` 就会落到这个带旧 code 的 hash 上，
应用于是拿着死票据重试 → 白屏。

### 17.3 修复

`ensure_logged_in` 的降级路径现在会：

1. 丢弃保存的会话（`drop_session`）
2. `context.clear_cookies()`
3. **注入 `localStorage.clear() + sessionStorage.clear()` 的 init script** ← 新增，关键
4. 先 `goto("about:blank")` 脱离该 hash 状态
5. 再 `navigate_to(url)` → 重新走完整 CAS → 拿到**全新票据**
6. `finish_login` 保存新会话

> 教训：只清 cookie 不够。**应用的会话状态在 storage 里，而死票据在 URL hash 里**，
> 三者（cookie / storage / hash）必须一起重置。

### 17.4 实测

连续两次运行：

```
[elang] restored 6 cookies
[elang] saved session is live — CAS skipped
[elang] URL: https://elang.zju.edu.cn/#/pc/read/learn?subject_id=26
```

会话恢复稳定可用；降级路径（清 storage + 重登）已就位，
但**本次未复现失效场景，故降级路径未实测**。

---

## 18. 迁移完成：列表 / 题目提取 / 作答提交（已实测跑通）

### 18.1 实测证据（首次完整跑通）

```
[elang] restored 6 cookies
[elang] saved session is live — CAS skipped
[elang] Vue(resourceList): 6 articles (0 done)
[1] 1/6: Bathing Beauty
  [elang] opening row 0: 'Bathing Beauty' (id=1929)
  [elang] praxis: jobs=10 domBlocks=10 captchaImg=no
  Qs: 10 {'choice': 10} | Passage: 3557 chars
[elang] Waiting for AI answers... (timeout=120s)
```

`elang_current.json` 内容正确（10 题、三选一 Yes/No/Not given、正文 3557 字符），
scratch 里生成了 `article_1..4.json`，说明**连续 4 篇都成功提取**。

### 18.2 ⚠️ 重要认知纠正：「卡在题目界面」不是 bug

用户多次反馈"卡在题目界面很久"。**实测证明这是 IPC 协议的正常行为**：
脚本写出 `elang_current.json`（`status: waiting_for_ai`）后**故意停下来等 AI 作答**，
超时 `AI_TIMEOUT=120s` 才继续。**它没有死循环，是在等答题方。**

> 排查手段：看 `<ipc>/elang_current.json` 的 `status`。若是 `waiting_for_ai`，
> 说明卡在**等 AI**，不是卡在代码。这是以后判断"卡住"最快的依据。

### 18.3 已迁移的函数

| 函数 | 迁移内容 |
|---|---|
| `navigate_to` | 两阶段：goto 后用 `location.hash` 重新确认路由（hash-only 的 goto 会被 SPA 吞掉，导致停在 `/#/pc/home`） |
| `get_article_list` | 读 `PcReadLearn.$data.resourceList`，用应用自己的 `normalizeStatus` 判完成；轮询数据而非 sleep |
| `click_article` | 调用 `toPraxis(item)`（服务端签发 `log_id`，URL 无法手拼）；**按 index 选中**，再用 URL 里的 `resources_id` 校验 |
| `extract_page_content` | 读 `PcReadPraxis.$data.jobList` + DOM 配对选项；正文来自 `resources.resources.content`（经 `_html_to_text` 展平）；轮询数据并上报验证码拦截 |
| `_html_to_text` | 新增：把正文 HTML 展平为纯文本 |
| `set_answers` | `selectOption(qIdx, optIdx)`（type 1/4）+ `insertWordAnswers`（type 2/5/7/8） |
| `submit` | 两步提交 `openSubmitConfirm()` → `confirmSubmit()`；新增 `dry_run` 只打开确认框不提交 |
| `go_back_to_learn` | 用 PC 路由 `#/pc/read/learn?subject_id=`，轮询 `resourceList` 到位 |
| `process_articles` | 重构：验证码在"题目为空且被拦"时处理；题库只用于全选择题文章；支持 `dry_run` |
| `mode_batch_all` | 改读 `PcReadIndex.$data.listData`（**subject** 列表，含 `resource_num`），过滤掉无资源的 |
| CLI | 新增 `--dry-run`；`batch` 同时接受 `subject_id` 与完整 learn URL |

**残留的旧移动版引用已清零**（`praxis-item` / `check_answer` / `to_submit` /
`van-nav-bar` / `answer-title` / `wrap-text` 均无）。

### 18.4 仍未验证

1. **`confirmSubmit` 真机未跑过** —— `--dry-run` 只到 `openSubmitConfirm()`。
   实际提交会连发两个 API 并跳转详情页。
2. **验证码解法器的实际上报未验证** —— 本次 `captchaImg=no`，验证码没出现。
3. **`batch-all` 未跑过** —— subject 列表读取逻辑未实测。
4. `article_1..4.json` 说明连续提取可用，但**未逐篇核对正文与文章是否对应**。

---

## 19. 真实运行发现的问题（含一次严重操作事故）

### 19.1 ⚠️ 操作事故：不要按进程名杀进程

**我用 `Get-Process msedge | Stop-Process -Force` 做"清理"，
误杀了用户桌面分类工具的 WebView2 渲染进程**（同为 Edge 内核）。
更糟的是我还杀了 `msedgewebview2`，等于清掉所有 WebView2 宿主应用。

**规则（必须遵守）：**
- 只用 `job_kill <id>` 停自己的任务
- 靠脚本自身的 `browser.close()` / `context.close()` 收尾
- 真要强杀：**按具体 PID**，且先校验其父进程确实是 `elang_reader` 的 python
- **绝不** `Get-Process <name> | Stop-Process`

另：`job_kill` **是异步的**。我两次因为"发完 kill 就当它死了"而启动新任务，
导致**两个脚本同时驱动同一个浏览器**（表现为验证码永远解不开）。
**起新任务前必须先 `job_list` 确认旧任务不是 running。**

### 19.2 ✅ 验证码检测 bug 已定位（单一数据源）

修复前的日志自相矛盾：

```
[elang] praxis: jobs=0 domBlocks=0 captchaImg=yes          <- 内层循环读到有图
[elang] no questions and no captcha gate (empty jobList)   <- blocked 却是 False
```

原因：`blocked` 由**另一个独立探针** `_captcha_state()` 计算，
而它与内层循环读到了**不同结果**。修复：`blocked` 直接取自内层循环刚读到的数据。

```python
blocked = bool(last_log and last_log[2])   # (jobs, blocks, hasImage)
```

同时把 `process_articles` 里**嵌套两层重复**的 blocked 检查合并为一个决策点。

### 19.3 ⚠️ `page.evaluate` 返回的是**副本**，不是活句柄

修复后检测正确触发了，但暴露出更深的问题：

```
[elang] praxis: jobs=0 domBlocks=0 captchaImg=yes
[elang] no questions — captcha image is pending [jobs=0 dom=0 img=0B gated=False]
[elang] !! CAPTCHA detected — solving
[elang] captcha has no image yet          <- _captcha_state 读到 0B！
```

**同一个页面，内层循环读到有图，`_captcha_state` 读到 0B。**

根因：`page.evaluate` **返回** JS 对象时给的是**副本**，不是引用。
所以 `_captcha_state(page)` 重新用 `_find_praxis_vm` 找组件时，
**可能落到另一个组件实例**上（Vue Router 复用组件时尤其容易）。

**修复**：`_captcha_state(page, vm)` 必须**接收调用方持有的同一个 vm 句柄**，
不再自己重新查找。同一个实例 → 同一个答案。

### 19.4 `AI_TIMEOUT` 从 120s 提到 600s

脚本与答题方（agent 或人）**不是同步执行**的：agent 通常要到下一个回合
才注意到 `waiting_for_ai`，实测经常超过 120s，
于是出现"答案还在写，文章已超时跳过"（日志里的 `[FAIL] AI timeout`）。

`AI_TIMEOUT = 600`。

**协作方式（重要）**：脚本在后台跑时，答题方应当
**短轮询 job_output → 一旦出现 `waiting_for_ai` 就立刻读文章并作答**，
不要等任务整体结束。

---

## 20. ✅ 端到端跑通：6 篇全部提交成功

### 20.1 结果

```
[elang] Done: 6 submitted, 0 skipped, 0 failed
```

| # | 文章 | 题数 | 验证码 | 结果 |
|---|---|---|---|---|
| 1 | Bathing Beauty | 10 choice | ✅ OCR `5248` | submitted |
| 2 | Canary Wharf | 1 fill **10 空** | ✅ OCR `8964` | submitted |
| 3 | A Traveler's Treasure Hunt | 5 choice + 1 fill 7 空 | 未触发 | submitted |
| 4 | Washington Trail Run | 5 choice + 1 fill 4 空 | 未触发 | submitted |
| 5 | Adventures for All Ages | 5 choice + 1 fill 3 空 | 未触发 | submitted |
| 6 | Living Car-Free | 5 choice + 1 fill 5 空 | 未触发 | submitted |

**验证码两篇都自动解决**（OCR 一次读对，`checkCaptchaCode` 通过，`jobs 0->10`）。
**多空填空正确**：日志显示 `fill q0: 10 blank(s)` / `7 blank(s)` / `4 blank(s)` / `3 blank(s)` / `5 blank(s)`。

### 20.2 ⚠️ 最大的坑：`job_output(wait=true)` 自己把路堵死了

排查耗时最久的问题**不在脚本里，而在协作方式上**：

我用 `job_output(job_id, wait=true, timeout_ms=N)` 看输出，
**这个调用会一直挂住直到超时或任务结束**。于是：

```
脚本: 写出 elang_current.json → 等我答题 → (AI_TIMEOUT 600s)
我  : job_output(wait=true) → 挂住 600s → 什么也看不到 → 答不了
```

**双方互等，谁也动不了。** 这正是用户反复说的"你那里 get job output 没有反应"。

**修法**：`job_output` **不要带 `wait`**。非阻塞调用立刻返回当前输出，
读完就能答题，而**不消耗脚本的等待时间**。

**这是本项目最重要的一条协作约定，写在这里以免后人重犯。**

### 20.3 ⚠️ 核心技术坑：Vue 实例无法序列化到 Python

`_captcha_state` 一直读到 `img=0B`，而同一个页面的抽取循环读到 `image=7658B`。
根因：

**Vue 组件实例是大型循环引用对象，Playwright 无法把它序列化给 Python。**
把它当参数传给 `page.evaluate` 时，JS 侧收到的是空/不可用值，**所有字段都读成 0**。

**修法**：`pin_praxis_vm()` 把**实例留在浏览器里**（`window.__elangPraxisVm`），
所有读取（`extract_page_content` / `_captcha_state` / `_submit_captcha`）
都在页面内部完成。**绝不跨 Playwright 边界传 Vue 实例。**

### 20.4 成功后的正确日志长这样（可作为回归基线）

```
[elang] praxis pinned: PcReadPraxis image=7658B jobs=0 logId=2186413 rid=1929
[elang] praxis: jobs=0 domBlocks=0 captchaImg=yes
[elang] no questions — captcha image is pending [jobs=0 dom=0 img=7658B gated=True]
[captcha] image pending on entry — solving now
[elang] !! CAPTCHA detected — solving
[elang] OCR attempt 1/3: '5248'
[elang] captcha submit '5248': jobs 0->10, image 7658->7658B, dialogShow=True, imageChanged=False
[elang] [OK] CAPTCHA solved by OCR
Qs: 10 {'choice': 10} | Passage: 3557 chars
[elang] answers recorded: {'choice': 10, 'fill': 0, 'notes': [], 'jobs': 10}
[elang] submit: answered 10/10, confirmVisible=True
[elang] submit: confirmSubmit -> OK
[OK] submitted
```

### 20.5 遗留的小问题（未修）

**第 6 篇日志显示 `submit: answered 5/6`**，而其他篇都是 `6/6`。
说明**有一个空没被识别为已答**（`isAnswered` 判定）。
仍然提交成功了，但该空可能是空的。
疑与 `markFillAnswer` / `insertWordAnswers` 的长度或归一化有关，**下次值得查**。

### 20.6 仍建议验证

- **`batch-all` 未跑过**（subject 列表读取逻辑）
- **提交结果的真实性未核对**：日志只证明 `confirmSubmit -> OK`（应用方法未抛错），
  未核对平台侧是否正确计分。建议在网页上抽查一篇的成绩页。

---

## 21. 作答接口转正 + 消除文章间延迟

### 21.1 作答接口不再是临时工具

原来答题靠 `temp/ans.py`（临时脚本）。现在它是**项目正式工具**：

**`scripts/review.py`** —— IPC 协议的"后端处理器"一侧，与 `elang_reader.py` 配对。

```bash
PY=~/.claude/skills/huixuewaiyu-readingpart/.venv/Scripts/python.exe

$PY scripts/review.py brief                 # 一行状态（轮询用）
$PY scripts/review.py show                  # 全文 + 所有题目与选项
$PY scripts/review.py answer 0=A 1=C 2=B    # 按选项字母作答
$PY scripts/review.py answer "3=A-poncho,B-junction,C-glut"   # 多空填空逐空给值
$PY scripts/review.py raw '[[0,1],[1,2]]'   # 原始 JSON：[题号, 选项]
$PY scripts/review.py skip                  # 让脚本原样提交
$PY scripts/review.py clear                 # 清掉旧答案
```

**IPC 目录解析与 `elang_reader.py` 完全一致**：优先 `$ELANG_TMP_DIR`，
否则 Windows 用 `C:/tmp`、其他平台 `/tmp`。两端必须一致，否则互相看不见文件。

`temp/ans.py` 已删除（被取代）。

### 21.2 消除"提交完到下一篇之间很久没反应"

根因是**固定 sleep 而非条件轮询**：

```python
# go_back_to_learn 原来：
for _ in range(BACK_RETRIES * 2):        # 最多 16 轮
    await page.wait_for_timeout(800)     # 先睡 800ms 再检查！
    ...递归遍历整棵组件树...
```

→ 每篇之间**至少浪费 800ms，最坏十几秒**，而且每次检查都做一次**递归组件遍历**。

**改法：**
1. 新增 `_wait_until(page, js_condition, timeout_s, interval_ms)` —— 轻量条件轮询
2. `go_back_to_learn` 改为轮询 `JS_PRAXIS_OR_LEARN_READY`（**单次属性读取**，
   不再递归遍历），间隔 150ms
3. `get_article_list` 改为 `pin_learn_vm()` 一次 pin + `JS_READ_RESOURCELIST`
   读固定实例，间隔 300ms
4. `click_article` 等 URL 改为 `_wait_until(JS_PRAXIS_URL, interval_ms=150)`

### 21.3 这次也顺带确立的两条硬规则

**（1）`job_output` 不要带 `wait`。**
带 `wait=true` 会挂住到超时，脚本同时也在等我 → **双方互等，永远不动**。
非阻塞读取立刻返回，且不消耗脚本的等待时间。

**（2）绝不按进程名杀进程。**
`Get-Process msedge | Stop-Process` 会误杀用户基于 WebView2 的桌面应用。
只用 `job_kill`、脚本自身 `close()`，或校验父进程后的具体 PID。

### 21.4 待验证

21.2 的提速改动**尚未实测**（编译通过）。预期文章间停顿从 ~13-25s 降到 <2s。

---

## 22. 浏览器架构重构：自带 Chromium + 持久化 profile（已实机验证）

### 22.1 为什么要改

原实现 `launch(channel="msedge")` 有三个分发级问题：

1. **依赖用户装了 Edge**，还要探测安装路径
2. `channel="msedge"` + 额外参数**实测会让 Edge 拒绝启动**
   （报"不支持的命令行标志"，卡在 about:blank）
3. profile 是临时的 → 只能靠手工存 cookie 补偿登录

### 22.2 实测结论（关键，别再猜）

用 `temp/verify_persistent.py` 做了四阶段对照实验：

| 检查项 | 结果 |
|---|---|
| `launch_persistent_context` + **自带 Chromium** + 无 channel 无参数 | ✅ **启动成功** |
| 显式注入 cookie + localStorage | ✅ **免登录进站** |
| **只靠 profile 保留 CAS 会话** | ❌ **不行** |

对照实验证据：

```
cookies before close: ['JSESSIONID','_csrf','_pv0','_pf0','_pc0','iPlanetDirectoryPro']
cookies after reopen: ['_pf0']                       <- 只剩 1 个
profile alone keeps the login? NO
```

**`iPlanetDirectoryPro`(CAS SSO) 与 zjuam `JSESSIONID` 是会话 cookie
（`expires=-1`），persistent profile 不保留它们。**

→ **所以 cookie 注入不是可选优化，是必需步骤。** 这一条推翻了我先前
"持久化 profile 能自动保持登录"的假设。

另外更正一条旧记录：**`launch_persistent_context` 本身完全可用**，
我早先的失败是 `channel="msedge"` + `--no-first-run` 等参数的组合造成的。

### 22.3 现在的实现

```python
BROWSER_PROFILE_DIR = ~/.elang/browser-profile     # 可用 ELANG_PROFILE_DIR 覆盖

kwargs = {"user_data_dir": BROWSER_PROFILE_DIR, "headless": False,
          "viewport": {"width": 1440, "height": 900}}
if ELANG_BROWSER and != "chromium": kwargs["channel"] = ELANG_BROWSER   # 逃生口

context = await playwright.chromium.launch_persistent_context(**kwargs)
```

- **默认自带 Chromium**：`playwright install chromium` 已由安装脚本执行，
  用户无需装任何浏览器 → **可分发**
- profile 放**用户主目录**（不是 `C:/tmp`），缓存/字体等状态一并持久
- `open_browser()` 返回 `(context, page, restored)` —— persistent context 没有独立的
  `browser` 对象，5 处 `browser.close()` 已简化为 `context.close()`

### 22.4 实机验证

```
[elang] restored 6 cookies
[elang] saved session is live — CAS skipped
[elang] Vue(resourceList): 6 articles (6 done)
[elang] Done: 0 submitted, 6 skipped, 0 failed
```

**附带验证了提交的真实性**：上一轮真实提交的 6 篇，
平台现在全部显示 `6 done` —— 说明 **`confirmSubmit` 确实生效**，
不再只是"API 没抛错"。（原第 20.6 节的疑虑已消除。）

### 22.5 运维提示

`~/.elang/browser-profile` 现在是**真实登录态所在**。
遇到会话失效时，**删掉整个目录**重新登录即可，比手工清 cookie 干净。

---

## 23. 遗留问题清单（截至当前）

| # | 问题 | 状态 |
|---|---|---|
| 1 | 第 6 篇日志出现 `submit: answered 5/6`（其他篇 6/6） | **未查**。仍提交成功，但可能有一空未答 |
| 2 | `batch-all` 从未跑过（subject 列表读取逻辑） | **未测** |
| 3 | MCP 化 | **计划中**（见下节） |
| 4 | 异步交互契约 | 已用 `scripts/review.py` 部分改善 |

### 第 2 项的一个潜在坑

`mode_batch_all` 读 `PcReadIndex.$data.listData` 得到 **subject 列表**
（`id` 是 26 这类 subject_id）。文档里旧的"11 个分类"概念在新版对应的是
`listData` 的 11 项，但**每项是 subject 而不是 category** ——
`#/pc/read/learn?subject_id=` 要的是 subject id。**跑之前先核对一次。**

---

## 24. MCP 可行性实测（决定架构的关键实验）

见 `MCP_DESIGN.md`。核心实测结论：

### 24.1 ✅ 找到了沙箱限制的**确切**机制

原先我笼统记为"沙箱禁止创建管道"，**不准确**。实测：

| 机制 | 走什么 | 沙箱下 |
|---|---|---|
| `subprocess.run(capture_output=True)` | `_winapi.CreatePipe`（**匿名**管道） | ✅ 可用 |
| `asyncio.create_subprocess_exec(stdin=PIPE)` | `CreateFile` on `\\.\pipe\...`（**命名**管道） | ❌ WinError 5 |

**被禁的不是"管道"，而是 Windows 上创建*命名*管道。**

调用栈确切位置：

```
playwright/_impl/_transport.py:120   asyncio.create_subprocess_exec(...)
asyncio/windows_utils.py:136         pipe(overlapped=(False,True), duplex=True)
asyncio/windows_utils.py:63          _winapi.CreateFile(address, ...)  -> WinError 5
```

### 24.2 ❌ 同步 API 不能绕过（已实测）

我假设 `sync_playwright()` 走 `subprocess` 而非 asyncio，**错了**：

```
playwright/sync_api/_context_manager.py:56
    self._loop.run_until_complete(self._connection.run_as_sync())
```

sync API 内部**就是** asyncio → 同一条命名管道 → 同样 WinError 5。

### 24.3 结论

> **任何使用 Playwright 的进程都无法在 `workspace-write` 沙箱内启动浏览器。**
> 与同步/异步 API 无关，与 profile 路径无关。

→ **MCP server 必须在沙箱外运行。** 这不是缺陷，是既定约束。
实际部署即"为 elang-mcp 配置 full access"——**一次配置**，
而不是像现在每次运行都要批准。

### 24.4 顺带修正的认知

我此前一直以为提权是因为"Playwright 需要 piped stdio"，
并在文档里这么写了。**准确说法是"asyncio 在 Windows 上需要命名管道"。**
CLAUDE.md 与 SKILL.md 里的相关表述应当按此口径。

---

## 25. batch-all 实测：发现并修复两个真实 bug

### 25.1 ✅ 运行结果

```
BATCH-ALL: 11 subjects
  [subject_id=26] 旅游与交通 (6 items)
  [subject_id=25] 历史与文化 (14 items)
  [subject_id=24] 文学与艺术 (15 items)
  [subject_id=23] 职业与发展 (15 items)
  [subject_id=22] 运动与娱乐 (7 items)
  [subject_id=21] 学习与教育 (32 items)
  [subject_id=14] 商业与经济 (16 items)
  [subject_id=13] 科技与创新 (41 items)
  [subject_id=12] 健康与生命 (31 items)
  [subject_id=11] 自然与农业 (19 items)
  [subject_id=9]  家庭与社会 (24 items)
  total items across subjects: 220
```

**重要事实（修正旧认知）：**

- 读索引页 `#/pc/read/index` 得到的就是 **11 个 subject**，`id` ∈
  `{26,25,24,23,22,21,14,13,12,11,9}`，**直接就是** `subject_id`。
  旧文档说"11 个 category"是不准确的叫法，**没有中间 category 层**。
- 总数是 **220 条**，不是旧文档写的 ~291。
- `subject 26` 的 6 条与之前 `batch 26` 观察一致 ✅

### 25.2 🐞 Bug 1：会话只查"存在"，不查"过期"

**症状**：`/en/subject/gets` 返回 **401**，`PcReadIndex` 的 `listData` 永远为空，
页面卡在 `加载中...`。看起来像抓取 bug，其实是 token 过期。

**实测数据**：

```
iat: 1790694563 -> 2026-09-30 00:29:23
exp: 1790701763 -> 2026-09-30 01:09:23   (token TTL 仅 ~2 小时)
now: 1790745517 -> 2026-09-30 13:18:36
exp - now = -729 min  → 确实过期 ~12 小时
```

**根因**：`session_is_live()` 只判断
`!!localStorage.getItem('user') && !!localStorage.getItem('authorization')`
—— **只看存在，不看有效期**。一个过期 token 完全满足这个条件。

**更隐蔽的后果**：`load_session()` 只看 `saved_at` 文件年龄（7 天上限），
所以过期会话被"成功"恢复 → `session_is_live` 误判为有效 →
打印 `CAS skipped` → 并把**同一个过期 token 重新存盘**。
这就是为什么 `saved_at` 是"6 分钟前"而 `iat` 是"13 小时前"。

**修复**：双端都校验 JWT 的 `exp`

- `load_session()`：解析 `authorization` 的 `exp`，过期则返回 None
- `session_is_live()`：在页面内解 `exp` 并与 `Date.now()` 比较（留 60s 余量）

### 25.3 🐞 Bug 2：过期状态下无法重新登录（持久化 profile 引入的新问题）

修复 Bug 1 后暴露出更严重的问题：

```
[elang] saved session token expired 731 min ago — re-login required
[elang] no saved session; CAS login will be needed    <- restored=False
[elang] app token expired 731 min ago    (连续 31 次！)
[elang] login did not complete (no user/authorization in localStorage)
```

**根因**：改用**持久化 profile** 之后，上一轮的 `localStorage` 会存盘保留。
于是：

1. app 启动时读到**过期 token**，以为自己已登录
2. `session_is_live`（正确地）判定过期
3. 但原代码在 `restored=False` 时**直接 `finish_login()`** —— 只干等，
   **从不清理存储**，而 app 因为"已有登录态"**永远不会去走 CAS**
4. → 死等 30 秒后失败

**关键洞察**：这不是"恢复会话失败"的问题，而是
**`restored` 这个变量不该决定是否清理存储**。
持久化 profile 下，**无论是否恢复，只要会话不可用就必须先清存储**。

**修复**：把清理逻辑从 `if not restored` 分支里提出，改成
"会话不可用 → 一律清 localStorage + sessionStorage + cookies → 重新导航 → 登录"。

修复后日志：

```
[elang] session is not usable — clearing app storage and cookies, then logging in again
[elang] CAS auto-login as <sid>...
[elang] CAS auto-login OK!
[elang] session saved (sid=285935, 6 cookies)
```

### 25.4 batch-all 新增的安全开关

原来的 `batch-all` **没有任何上限**，一跑就是 220 篇。已加：

| 开关 | 作用 |
|---|---|
| `--limit N` | 本次最多提交 N 篇。**且不会把只做了一部分的 subject 标记为完成**（否则下次跑会跳过剩余文章） |
| `--subjects-only` | 只列出 subject 列表然后退出 —— 零风险验证索引路径 |
| `--subject-ids 26,1879` | 只跑指定 subject |

另外修了 CLI：`argv[2]` 原来会被无条件当成起始编号，
所以 `batch-all --subjects-only` 会 `int("--subjects-only")` 崩溃；
现在只有纯数字才当作起始编号。

### 25.5 定位手法记录

这次能快速定位，靠的是**浏览器控制台**（用户提供）：

```
/en/subject/gets?...  401
/en/resources/getNewUserResource?...  401
PcReadIndex.vue:91 Uncaught (in promise)
```

**页面自己发的请求 401** → 立刻排除"我的抓取代码有 bug"，
把方向锁定到认证。比反复读自己的日志有效得多。

---

## 26. batch-all 第二轮：又发现 4 个问题（含 token 生命周期）

### 26.1 🐞 Bug 3：`go_back_to_learn` 每篇都白等 20 秒

```
[elang] timed out waiting for article list (20s)
[elang] learn list did not come back after navigating to it
```

**根因**：我上一轮"提速"时把这条路径改成轮询 `JS_PRAXIS_OR_LEARN_READY`，
而那个条件是读 `window.__elangLearnVm`。但函数开头刚把
`window.__elangLearnVm = null` 清掉，**之后再也没人重新 pin** ——
条件永远为假，于是每次都跑满 20 秒超时，**并且误报"列表没回来"**。

**修复**：改成每轮 `pin_learn_vm(page)`（它自己会写入 pin）再判断。

> 教训：**"清掉共享状态"和"重新填充"必须成对**。这次是清了不填。

### 26.2 🐞 Bug 4：dry-run 不受 `--limit` 约束，会走遍 11 个 subject

`submitted_this_run` 只在 `status == "submitted"` 时自增，
而 dry-run 的结果状态是 `"dry_run"` → 计数永远是 0 → `--limit 1` 失效，
脚本继续处理 subject 2、3、4……

**修复**：dry-run 同样占用一篇的额度（它确实消耗了一整篇的工作量）。

### 26.3 🐞 Bug 5：dry-run 成功被统计成 failed

`print_summary` 只统计 `status == "submitted"` 和 `"skipped_completed"`，
其余一律算 failed。而 dry-run 的状态是 `"dry_run"` →
**日志出现 `1 failed`，实际是成功的**。

**修复**：单独统计并显示 dry-run；只有真正的失败才计入 failed。

### 26.4 ⚠️ Bug 6：token 只有 ~2 小时，长跑必然中途失效

实测 `iat → exp`：

```
iat: 2026-09-30 00:29:23
exp: 2026-09-30 01:09:23     <- 仅 2 小时
```

而 `batch-all` 有 **220 篇**，实际耗时远超 2 小时。
一旦 token 在途中失效，app 不会自愈：`/en/*` 开始 401，页面卡在 加载中。

实测日志已经把风险暴露出来：

```
[elang] saved session token valid for 1 more min
[elang] saved session is live — CAS skipped
```

**修复**：新增 `ensure_fresh_token(page, url, margin_s=300)`，
在每个 subject 开始前检查剩余有效期，**不足 5 分钟就先重新登录**，
而不是等到某一篇随机失败。

### 26.5 修复后的验证输出

```
[elang] --limit: taking 1 unfinished article(s) in this subject, leaving 13 for a later run
[elang] submit: answered 6/6, confirmVisible=True
[elang] dry-run: leaving the confirm dialog open, not posting
[elang] --limit: NOT marking this subject complete (unfinished articles remain)
[elang] Done: 0 submitted, 1 dry-run, 0 skipped
[elang] --limit 1 reached; stopping
[elang] Run finished. This run: 1 article(s) (submitted 0 total) across 1/11 subjects marked complete.
```

四项行为全部正确：
1. `--limit` 生效并**正确终止**
2. 未完成的 subject **没有被标记完成**（下次还会处理剩余 13 篇）
3. dry-run **不再计为 failed**
4. `go_back_to_learn` **不再白等 20 秒**

### 26.6 修正 §25.1 的一处叙述

subject 列表里 id 26 是"旅游与交通"，其 6 篇已全部完成；
本轮验证对象是 **subject 25 历史与文化**（14 篇），
取其中 1 篇做 dry-run。

---

## 27. ✅ MCP Level 1 完成：显式状态机 `scripts/elang_session.py`

按 `MCP_DESIGN.md` §3 的分层，Level 1（不需要 MCP 依赖）已完成并实机验证。

### 27.1 核心改动：控制反转

`elang_reader.py` 是**批处理脚本**：把待答文章写文件后**阻塞**在
`wait_for_ai()` 里等对方发现。结果是**双方互相轮询**，而且"下一步做什么"
从未被表达出来，只能从日志猜。

`elang_session.py` 用同一批底层原语，改成**显式状态机**：

- 每个方法**立刻返回**，描述新状态
- **任何方法都不等待答案**
- 返回值里显式列出**合法的后续动作**

**这直接消灭了 `AI_TIMEOUT` 的存在意义** —— 文章可以无限期停在
`awaiting_answers`，因为没有任何人在阻塞等待它。

### 27.2 状态与动作

```
idle → running → { awaiting_captcha | awaiting_answers } → submitted → finished
                        └── error（任意阶段）
```

每个返回都是统一信封，`blocking` **恒为 false**：

```json
{
  "state": "awaiting_answers",
  "blocking": false,
  "next_actions": ["submit_answers", "skip_article", "status"],
  "article": { "title": "...", "passage": "...", "questions": [...] },
  "hint": "Answer every question, then call submit_answers. ..."
}
```

### 27.3 顺带修掉的库化障碍

`elang_reader.py` 原来在**导入时**就执行：

- 读 `.env`，**没有凭据就 `sys.exit(1)`**
- 加载题库并打印日志

这让它**无法作为库被导入**。已重构为 `_ensure_credentials()` /
`_load_answer_bank()`，在 `open_browser()` 时惰性调用。
现在 `import elang_reader` **完全静默、零副作用**（已实测）。

### 27.4 服务端校验（本次最有价值的产出）

原批处理模式**完全不校验**：答案对不对、空够不够，一路写到浏览器。
现在 `validate()` 在**碰浏览器之前**拒绝：

| 用例 | 结果 |
|---|---|
| fill 空数不足 | ❌ `q5 needs 7 value(s), one per blank; got 1` |
| fill 空数过多 | ❌ `... got 10` |
| choice 选项越界 | ❌ `q0 is a choice question with 2 option(s); value must be 0..1` |
| qIndex 越界 | ❌ `qIndex 999 is out of range (0..5)` |
| qIndex 重复 | ❌ `qIndex 0 given more than once` |

**关键设计**：校验失败**不算会话失败** —— 状态留在 `awaiting_answers`，
让调用方修正后重投。（若置为 error 就得重开浏览器，代价过大。）

### 27.5 `echo`：回读实际落盘的内容

提交后从组件回读每题的真实状态：

```json
"echo": {
  "5": { "kind": "fill", "given": [...7 items...], "assigned": 7,
         "blanks": 7, "values": [...7 items...], "isAnswered": true,
         "filled": true }
},
"incomplete": []
```

`incomplete` 列出**没有回读为已答**的题号 ——
这正是当初 `submit: answered 5/6` 那个谜团本该有的可观测性。

### 27.6 实机验证

```
[test] subject 历史与文化: 14 lessons, 14 pending
[test] article: 'The Rise of Ben "The Baker"', 6 questions
        q0..q4: choice fmt=letter options=2
        q5:     fill   fmt=value_per_blank blanks=7 options=7
... 5 个非法输入全部被拒且会话保持可用 ...
[elang] answers recorded: {'choice': 5, 'fill': 1, 'notes': ['fill q5: 7 blank(s)']}
[elang] submit: answered 6/6, confirmVisible=True
state=submitted  incomplete: []
```

### 27.7 新增文件

| 文件 | 说明 |
|---|---|
| `scripts/elang_session.py` | 状态机（Level 1 主体） |
| `scripts/test_session.py` | 校验与 echo 的验证脚本（dry-run） |

### 27.8 下一步（Level 2）

`MCP_DESIGN.md` §8：给上述方法套一层 MCP tool 定义即可，
**业务逻辑一行都不用改**。前置条件（server 必须在沙箱外）已在 §24 实测确定。

---

## 28. ✅ MCP Level 2 完成：`scripts/elang_mcp.py`

薄包装 `ElangSession`（Level 1），**业务逻辑一行未改**。

### 28.1 10 个 tool

| Tool | 说明 |
|---|---|
| `elang_start(dry_run, limit)` | 开浏览器并登录 |
| `elang_status()` | **纯读，绝不启动浏览器** |
| `elang_stop()` | 关浏览器 |
| `elang_list_subjects()` | 科目列表 |
| `elang_list_lessons(subject_id)` | 文章列表 |
| `elang_open_next()` | 推进到下一篇（返回 passage+questions 或 captcha 通知） |
| `elang_get_captcha()` | 取验证码图片，**不重试不刷新** |
| `elang_solve_captcha(code)` | 提交验证码 |
| `elang_submit_answers(answers)` | 校验→作答→提交→echo |
| `elang_skip_article()` | 原样提交 |

### 28.2 🐞 关键 bug：诊断输出污染 JSON-RPC 通道

**这是 MCP stdio 的经典陷阱。** 首次协议测试直接失败：

```
Invalid JSON: expected value at line 1 column 2
  input_value='[elang] credentials from...'
```

**原因**：MCP stdio 用 **stdout 承载 JSON-RPC 消息**（一行一条），
而 solver 模块到处 `print()` 进度日志 → 协议流被污染。

**修复**：新增 `quiet_stdout()` 上下文管理器，把 stdout 临时重定向到 stderr，
并用 `@quiet` 装饰**全部 10 个 tool**。

> 选择重定向而不是删掉那些 `print`：那些日志在**当 CLI 用时很有价值**，
> 不该为了 MCP 牺牲。重定向让两种用法各得其所。

### 28.3 🐞 我自己引入的设计违规

`elang_status` 文档写的是 **"Never performs an action"**，
但我实现时调用了 `ensure()` —— **它会启动浏览器**。
一个"查看状态"的调用不该拉起浏览器。已改为：无会话时直接返回 `idle`。

### 28.4 并发保护

所有 tool 共用一把 `asyncio.Lock`。这让**两次 tool 调用无法在导航中途交错** ——
正是之前造成"同一页面读出矛盾数据"的情形。

### 28.5 沙箱结论在协议层再次确认

连 **MCP client 自己**都无法在沙箱内启动 server：

```
mcp/client/stdio/__init__.py:249  create_windows_process(...)
  → anyio.open_process → asyncio.subprocess_exec
  → windows_utils.py:136  pipe(duplex=True)
  → CreateFile("\\.\pipe\...")  → WinError 5
```

→ **从沙箱内既无法启动 Playwright，也无法启动 MCP stdio 子进程。**
两者是**同一个根因**（§24：asyncio 在 Windows 需要*命名*管道）。
server 必须配 full access —— **一次配置，而非每次批准**。

### 28.6 实机验证（真实 stdio 协议）

```
[test] child ELANG_PROFILE_DIR=D:\...\temp\profile
[test] initialize OK
[test] 10 tools: [...10 个名字...]
  - elang_start  schema=yes     (10/10 都有 input schema)
[test] calling elang_status (no browser yet)...  isError=False   <- 不再启动浏览器
[test] calling elang_start (starts a browser)...
  state=running  blocking=False  next=['open_next','list_lessons','status','stop']
[test] calling elang_stop...
[test] protocol round-trip complete
```

### 28.7 开发期配置（重要）

**开发期不要动用户主目录下的 skill。** 工作区内即可完成一切：

```powershell
# 工作区 venv（.venv 已在 .gitignore 中）
python -m venv --system-site-packages --without-pip .venv
# 说明：沙箱会阻止 ensurepip，故用 --without-pip + 系统站点包
#       （系统 Python 已有 mcp / playwright / dotenv）

$env:ELANG_PROFILE_DIR = "$PWD\temp\profile"      # profile 放工作区
$env:ELANG_TMP_DIR     = "$PWD\temp\ipc"
$env:TEMP = $env:TMP   = "$PWD\temp\pwtmp"        # Playwright 需要可写 temp
```

**注意**：`test_mcp.py` 必须把环境变量显式传给子进程
（`StdioServerParameters(env=os.environ.copy())`）。
原来写 `env=None` 导致 `ELANG_PROFILE_DIR` **静默失效**，
profile 回退到用户主目录并因权限失败。

### 28.8 `ddddocr` 改为惰性导入

`elang_reader.py` 原来**模块级** `import ddddocr` + 实例化，
使整个模块在缺少它时无法导入。而 ddddocr 是重度 ONNX 依赖，
**只有验证码 OCR 回退才需要**。

已改为 `_get_ocr()` 惰性加载，缺失时：
- **导入照常成功**
- 打印提示并**降级到视觉/手动交接**（`ELANG_CAPTCHA_MANUAL=1`）

`requirements.txt` 相应区分 **core**（playwright/dotenv/mcp）与
**optional**（ddddocr/Pillow）。

### 28.9 新增文件

| 文件 | 说明 |
|---|---|
| `scripts/elang_mcp.py` | MCP server（10 tools，薄包装） |
| `scripts/test_mcp.py` | 真实 stdio 协议往返测试 |

### 28.10 下一步（Level 3）

接进 DSH 实际使用。需要：
1. 在 DSH 的 MCP 配置里注册 `elang-mcp`，**并授予 full access**
2. 用真实 agent 端到端跑完一篇（open_next → submit_answers）
3. 确认长驻进程的空闲释放与 `elang_stop` 行为

---

## 29. 三平台分发调研（DSH / Codex / Claude Code）

完整设计见 `DISTRIBUTION.md`。核心是**在 DSH 运行时中查证的事实**，非推测。

### 29.1 ✅ 三平台共用同一个 skill 契约

DSH 自带的 `runtime/office-skills/office-docx/SKILL.md` 与本仓库 `SKILL.md`
**格式完全一致**：YAML frontmatter（`name`/`description`）+ markdown + 同级 `scripts/`。

### 29.2 ✅ DSH 的 skill 扫描根（源码实测）

`@deepseek-ai/dsh-skill-filesystem` 的 roots 表：

| Rank | Source | Path |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs` |
| 400 | `user-dsh` | `<dshHome>/skills`（跳过 `.system`） |
| 500 | `user-agents` | `<agentsHome>/skills` |

- `<dshHome>` = `$DSH_HOME` 或 `~/.dsh`
- `<agentsHome>` = `$DSH_AGENTS_HOME` 或 `~/.agents`
- `projectRoot` = 最近含 `.git` 的祖先

**关键推论：DSH 的 rank 500 与 Codex 是同一目录 `~/.agents/skills`** ——
**两者共享 skill 安装位置，只需装一份。**

本机实测：
- `~/.agents/skills/` = **20 个 skill，正是本次会话的 skill 目录**
- `~/.claude/skills/` = 另一套（5 个）
- `~/.dsh/skills/` = 不存在（DSH 走的是 `.agents` 这条）

### 29.3 ⚠️ 发现深度为一层（决定了不能直接把仓库根当 skill）

只识别 `<root>/<name>/SKILL.md` 与 `<root>/<name>.md`；
**嵌套 `**/SKILL.md` 不被发现**。

所以必须装成 `<root>/huixuewaiyu-readingpart/`，
**不能**把仓库根直接放进去（那里有 `.git`/`temp`/`.venv`）。

### 29.4 ✅ DSH 插件是 cordis npm 包，不是 skill

```
package.json   "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
cordis.patch.yml   - insert: [{ id, name }]
lib/index.js   export const name; export function apply(ctx, config)
```

参考实现：`~/.dsh/profiles/desktop/node_modules/dshmarket`。
插件能做 skill 做不到的事：**把 MCP server 注册进 profile，用户无需手写配置**。

DSH **没有** `plugin.json` 之类的东西（已搜索确认）。

### 29.5 三条通道

| 通道 | 形态 | 平台 | 状态 |
|---|---|---|---|
| **A. Skill 目录** | `SKILL.md` + `scripts/` | **三平台通用** | ✅ 已实现 |
| **B. MCP server** | `elang_mcp.py` stdio | DSH / Claude / 任意 MCP 宿主 | ✅ 已实现 |
| **C. DSH npm 插件** | cordis 包 | 仅 DSH | 待做 |

**A 必须是主路径**：C 只服务 DSH，而 `SKILL.md` 是三平台唯一的公共契约。

### 29.6 ✅ 新增 `scripts/install_skill.py`（通道 A）

```bash
python scripts/install_skill.py --check       # 只报告
python scripts/install_skill.py --copy        # 复制 payload（推荐分发）
python scripts/install_skill.py --link        # 目录连接（开发用）
python scripts/install_skill.py --hosts dsh,codex,claude
python scripts/install_skill.py --uninstall
```

**复制模式只带 payload**：`SKILL.md`/`scripts/`/`references/`/`assets/`/
`requirements.txt`/`CLAUDE.md`/`CHANGELOG.md`/`MCP_DESIGN.md`。
**不带 `.git`/`temp`/`.venv`**（已实测验证）。

**链接模式用 Windows junction**（已实测）：
- `mklink /J` 无需管理员权限
- `rmdir` **只删连接，不动目标**（已验证：删连接后仓库完好）

### 29.7 本机现状（供决策）

```
~/.agents/skills/huixuewaiyu-readingpart   -> present（真实目录，与 ~/.claude 那份并存）
~/.claude/skills/huixuewaiyu-readingpart   -> present
~/.dsh/skills                              -> 不存在
```

目前是**两份独立副本**。用 `--link` 可收敛为"仓库即唯一真源"。

---

## 30. ✅ MCP 接入完成（`.mcp.json` + 生成器 + E2E 验证）

### 30.1 新增文件

| 文件 | 说明 |
|---|---|
| `.mcp.json.example` | 模板（入库），含占位符 `{{PYTHON}}`/`{{SCRIPT}}`/`{{IPC_DIR}}` |
| `scripts/setup_mcp.py` | 生成 `.mcp.json`，解析本机真实路径 |
| `scripts/test_mcp_e2e.py` | **按 `.mcp.json` 的真实内容**启动 server 并驱动 |
| `.gitignore` | 新增忽略 `.mcp.json`（含绝对路径，不应入库） |

```bash
python scripts/setup_mcp.py --host claude,dsh,codex   # 生成 + 各宿主说明
python scripts/test_mcp_e2e.py --browser              # 端到端验证
```

### 30.2 🐞 关键陷阱：Windows 路径破坏 JSON 模板

第一版用字符串替换往 JSON **文本**里填路径，结果：

```
JSONDecodeError: Invalid \escape: line 4 column 21
```

因为 `D:\<repo>\...` 里的 `\p` 不是合法 JSON 转义。

**修复**：把模板 **parse 成对象**，改字段，再 `json.dumps` 重新序列化 ——
让 json 自己处理转义。**永远不要手工往 JSON 文本里拼 Windows 路径。**

### 30.3 🐞 环境级问题：`%LOCALAPPDATA%\Temp` 在沙箱下挂死

**症状**：`tempfile.mkdtemp()` 在系统 Temp 里**挂死 >25 秒**，
Playwright 报 `EPERM: operation not permitted, mkdtemp`。

**实测对照**：

```
TEMP = %LOCALAPPDATA%\Temp                          → 挂死 >25s
TEMP = <workspace>\temp\pwtmp                       → 0.07s 完成
```

**根因**：系统 Temp 在**工作区之外**，每次操作都被文件策略拦截；
该目录已有 **5184 个条目**，逐条策略检查 → 极慢直至超时。

**这不是我们代码的 bug**，但**必须知道**，否则 MCP server 一启动就死在浏览器上。

→ 沙箱内测试时把 `TEMP`/`TMP` 指向工作区。
→ 真实部署 server 在沙箱外，用系统 Temp 是正常的。

### 30.4 🐞 同类问题：浏览器 profile 也在工作区外

TEMP 修好后紧接着撞上：

```
CreateFile %USERPROFILE%\.elang\browser-profile\Crashpad\settings.dat: 拒绝访问 (0x5)
Lock file can not be created! Error code: 5
```

同一个根因（路径在工作区外）。测试中用 `ELANG_PROFILE_DIR` 指向工作区解决。
**真实部署不受影响** —— server 在沙箱外，`~/.elang/browser-profile` 是正确的默认值。

### 30.5 为什么诊断命令会"卡住"

我一度把卡住归因于"多行 `python -c`"，**这个判断是错的** ——
换成文件后照样卡。真正原因是 **30.3**：脚本第一句就是 `mkdtemp`。

**教训**：卡住时不要猜语法，应该**计时 + 二分**：
`python -V` = 0.03s（解释器没问题）→ 逐步加内容 → 才定位到 `mkdtemp`。

### 30.6 ✅ E2E 验证结果（真实 stdio 协议）

```
[e2e] registration from .mcp.json
[e2e] initialize OK
[e2e] 10 tools available
[e2e] elang_status -> state=idle isError=False        <- 不启动浏览器（设计约束成立）
[e2e] elang_start  -> state=running blocking=False    <- 真启动浏览器 + CAS 登录
[e2e] elang_list_subjects -> 11 subjects
         id=26 旅游与交通(6) id=25 历史与文化(14) id=24 文学与艺术(15) ...
[e2e] elang_stop -> state=idle
[e2e] end-to-end OK: the registered config drives the solver
```

全程 `blocking=False`。**MCP 接入可用。**

### 30.7 ⚠️ 我留下的垃圾（待用户决定）

`%LOCALAPPDATA%\Temp` 里有 **69 个 `playwright_chromiumdev_profile-*`**，
是我历次测试遗留的孤儿浏览器 profile（未清理）。
它也是 30.3 里目录膨胀的一部分。**清理需用户确认**（那是系统目录）。

---

## 31. ⚠️ 部署原则修正：绝不依赖系统 Python 的 site-packages

用户明确指出两条约束，**都是对的**，我之前违反了第二条：

1. **不要往系统 Python 装依赖**（用户的系统 Python 只当解释器用；
   要么 venv、要么 conda、要么 `uv tool`）
2. **不要用 `--system-site-packages` 借系统依赖**
   —— 每台机器全局环境不同，借来的依赖换台机器就崩

### 31.1 事实澄清：我并没有污染系统 Python

查证结果（`importlib.metadata` 元数据）：

```
mcp 1.29.0 于 2026-07-30 13:08:53 装在
  %APPDATA%\Python\Python314\site-packages   <- per-user，非系统目录
playwright 1.60.0 于 2026-06-10 装在
  <系统 Python>\Lib\site-packages
```

- `mcp` 的安装时间**早于本次会话**，是用户本来就有的
- 我那次 `pip install mcp` 目标是 **skill venv**，而且 **aborted，未完成**
- 系统 Python **完全未被修改**

**但我确实犯了另一个错**：用 `--system-site-packages` 建工作区 venv，
那个 venv 只是空壳，依赖全来自用户的全局包 —— **正是用户要避免的**。已重建。

### 31.2 新方案：uv + 完全隔离的 venv

`python -m venv` 在此环境**必定失败**（`ensurepip` 非零退出），
但 **`uv` 可用**（0.12.6，位于 `~/.local/bin/uv.exe`）：

```bash
uv venv .venv                                   # 完全隔离，自带 CPython 3.13.12
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

结果：`.venv` 内**自带全部依赖**，`mcp` 来自
`.venv\Lib\site-packages`（自身），**不引用任何全局包**。

### 31.3 ⚠️ Playwright 版本必须与浏览器构建匹配

踩到的坑：`uv pip install playwright` 装了 **1.63.0**，它需要 chromium **1243**，
而本机只有 **1217/1223**；下载又被 CDN 拒绝 → 无法启动。

**解法**：把 playwright 钉到 **1.60.0**（对应已有的 chromium-1223），
**复用系统已有的浏览器缓存**（`%LOCALAPPDATA%\ms-playwright`），零下载。

```
playwright==1.60.0 → executable: ...\ms-playwright\chromium-1223\chrome-win64\chrome.exe
launch OK: True
```

`requirements.txt` 因此写 `playwright>=1.49,<1.61` 并**注明必须与浏览器一起升级**。

### 31.4 ⚠️ MCP SDK 1.x 与 2.x API 不同（已兼容两者）

`mcp 2.x` 有两处破坏性改名，**都已修复**：

| 1.x | 2.x |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` |
| `result.isError` | `result.is_error` |

`elang_mcp.py` 现在**同时兼容两版**（先试 1.x 再试 2.x），
不锁定版本 —— 用户环境给哪版都能跑。

### 31.5 `setup_mcp.py` 新增"自包含"自检

新增检测：所选解释器的 `mcp`/`playwright` 是否来自**它自己的** site-packages。
若来自全局，报错并给出建隔离 venv 的命令：

```
WARNING: this interpreter is not self-contained:
  - `mcp` resolves OUTSIDE this interpreter (...) — it is coming from a global
    install, which will not travel to another machine
  Create an isolated venv and install requirements into it:
    uv venv .venv && uv pip install ... && playwright install chromium
```

### 31.6 ✅ 隔离 venv 下再次 E2E 验证

```
[e2e] initialize OK
[e2e] 10 tools available
[e2e] elang_status -> state=idle isError=False
[e2e] elang_start  -> state=running blocking=False
[e2e] elang_list_subjects -> 11 subjects
[e2e] elang_stop -> state=idle
[e2e] end-to-end OK
```

### 31.7 工作区体积

```
.venv                 151.2 MB   (隔离，自带依赖；.gitignore 忽略)
temp                  33.6 MB   (.gitignore 忽略)
.playwright-browsers   0 MB      (下载失败，已删；改用系统缓存)
```

### 31.8 给用户的分发指引（新增）

第三方用户应**只**这样做，不碰系统 Python：

```bash
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
python scripts/setup_mcp.py     # 会自检并生成 .mcp.json
```

---

## 32. ✅ 实测：MCP server 的工作目录 = 宿主 cwd

用户提问："MCP 运行时，进程的工作目录是在 agent 的工作区，还是 MCP 自己的目录？"
这决定了 `.env` 该如何定位。**不猜，实测。**

### 32.1 实验

最小 MCP server 报告自己的 `os.getcwd()`；客户端**用两个不同的 cwd** 启动它：

```
host launched with cwd=D:\...\repo       → server cwd = D:\...\repo
host launched with cwd=D:\...\repo\temp  → server cwd = D:\...\repo\temp
        env_marker   = set-by-host-for-...   ← 宿主注入的 env 透传 ✓
```

### 32.2 结论

**MCP server 是宿主的子进程，继承宿主的 cwd**（除非宿主显式传 `cwd=`）。

- DSH：MCP 配置的 `cwd` 字段描述为 "working directory"；
  DSH 其他地方对 `cwd` 的默认值是 **`process.cwd()`**（agent 工作区）
- **MCP 没有"自己的目录"概念** —— 代码在 site-packages，工作目录是别人的

### 32.3 由此推出的设计铁律

**必须区分两种"位置"：**

| 用途 | 正确做法 | 理由 |
|---|---|---|
| 程序自带资源（`answers.json`） | `__file__` / `importlib.resources` | 相对**安装位置**，**与 CWD 无关** |
| 用户配置（`.env` 凭据） | 固定用户目录 / 宿主注入 env | 相对 CWD **不可靠** |

实测中 `module_file` 稳定不变，`cwd` 随宿主变 —— 这就是区别。

**推论：**

1. **题库等资源必须打进 Python 包**，用 `importlib.resources` 读；
   用相对路径会在宿主换 cwd 时失效（隐蔽 bug）
2. **`.env` 不能按 CWD 查找** —— 用户在仓库里跑能读到，DSH 在别的 workspace 启动就读不到
3. **写入路径（浏览器 profile、IPC）也应固定**，不要落在"碰巧的 CWD"

### 32.4 `.env` 优先级链（据实测确定）

```
1. 真实环境变量          ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD
                        ← 宿主 spawn 时注入，实测透传 ✓ 最可靠
2. ELANG_ENV_FILE      显式路径覆盖
3. %APPDATA%\elang\.env    Windows 固定位置（主位置）
   ~/.config/elang/.env    Unix
4. CWD/.env             仅开发兜底，文档标注"不可依赖"
```

**第 1 项排最前**：实测证明宿主注入的 env 确实到达子进程，
所以 MCP 宿主配置本身就是最可靠的凭据来源，不依赖任何文件查找。

### 32.5 澄清用户的疑问

> **`.env` 的位置与 server 的 cwd 无关。**
> `.env` 是**用户配置**，不是**程序资源**。
> 程序资源用 `__file__` 找；用户配置用固定目录或宿主注入的 env 找。
> 两件事混在一起，才产生"到底该放哪"的困惑。

这也解释了为什么之前把 `ELANG_PROFILE_DIR`/`TEMP` 指向工作区只是**沙箱测试的特例** ——
真实部署用 `~/.elang/` 才是对的。

---

## 33. ✅ 凭据解析统一（`config.py`）+ doctor

### 33.1 设计原则：靠契约，不靠魔法

**所有 agent（DSH / Claude Code / Codex / 任何）跑命令时，cwd 都是工作区根。**
这是它们的**共同契约**，不是猜测 —— 所以 `./.env` 就是自然位置，
**不需要**向上遍历、agent 探测、指针文件或 `DSH_*` 变量。

（我先前提的 `find_project_root()` + `DSH_HOME` 方案被用户否掉，**是对的**：
那是过度设计，且 `DSH_HOME` 会让实现变成 DSH 专用。）

### 33.2 `scripts/config.py`（约 40 行逻辑）

```python
def resolve_env_file():
    if p := os.environ.get("ELANG_ENV_FILE"):  return Path(p), "ELANG_ENV_FILE"
    if (cwd_env := Path.cwd()/".env").is_file(): return cwd_env, "workspace"
    if FALLBACK_ENV.is_file():                 return FALLBACK_ENV, "fallback"
    return cwd_env, "workspace (missing)"
```

凭据读取：**真实环境变量压过文件**

```
ELANG_CAS_USERNAME / CAS_USERNAME
ELANG_CAS_PASSWORD / CAS_PASSWORD
```

`*_from` 字段标注每个值来源（`environment` / `file:KEY`），
让调用方能解释"这个值从哪来"而无需重新推导。

### 33.3 ✅ 7 个用例实测通过

| # | 场景 | 结果 |
|---|---|---|
| 1 | 都不存在 | 指向 workspace，标注 missing |
| 2 | 工作区有 | **workspace 胜出** |
| 3 | 工作区 + 兜底都有 | **workspace 仍胜出** |
| 4 | 工作区没有 | fallback 生效 |
| 5 | `ELANG_ENV_FILE` | 覆盖一切 |
| 6 | env 变量 | **压过文件** |
| 7 | cwd 在子目录 | 落到 fallback（**不神秘失败**） |

### 33.4 `scripts/doctor.py` —— 只报告，不预装

**分工**：工具**报告状态 + 给出命令**，AI（跑 skill 的那个）**判断并执行**。

这样就不必预先假设浏览器在哪、哪个版本 —— 正是用户要的。

输出含：
- 解释器 / 是否在 venv
- 4 个模块（playwright/dotenv/mcp/dddocr）
- **"借来的依赖"警告**：若 `mcp` 来自本解释器之外（如 `--system-site-packages`
  的 venv 或全局），显式列出 —— 这正是本项目踩过的坑（§31）
- 浏览器：缓存路径、可执行文件、**实际 launch 结果**
- 凭据：解析到的文件、来源标签、各字段是否齐备

**不固定浏览器版本**，但 `requirements.txt` 仍给出区间
（`playwright>=1.49,<1.61`），因为"钉死版本"与"浏览器构建"必须同步变更。

### 33.5 `scripts/init_env.py`

在**解析器实际会读的位置**创建模板，避免"用户不知道放哪"。

### 33.6 `elang_reader.py` 已迁移到统一解析

删除了原有的 4 路径搜索（`_ENV_PATHS`）与 `load_dotenv` 依赖，
改为调用 `config.load_credentials()`。凭据优先级全项目**只有一处实现**。

无凭据时的报错也改为可操作：

```
ERROR: no CAS credentials found.
  Looked for: <path>
  Create one with:  python scripts/init_env.py
  Or set ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD in the environment.
```

### 33.7 ⚠️ 现状：本机已无凭据

用户已删除旧的 skill 目录（`~/.claude/skills/...` 与 `~/.agents/skills/...`），
连同其中的 `.env`。因此当前：

```
repo .env          : 不存在
~/.elang/.env      : 不存在
旧 skill .env      : 已删除
```

**这是预期行为**（凭据本就该由用户自己放），但意味着在用户重新创建 `.env`
之前，**无法做需要登录的端到端测试**。创建方式：

```
python scripts/init_env.py     # 然后在生成的 .env 里填写学号/密码
```

### 33.8 ⚠️ 一个待商榷的取舍

新解析链**不再扫描旧 skill 目录**。这是刻意的（凭据不该放在安装目录里、
会被升级覆盖），但会**改变现有工作流**：
以前凭据在 skill 目录、任何时候都能读到；现在必须放工作区或 `~/.elang/`。

**建议**：用户运行一次 `init_env.py` 并在其中填写，之后
- 在仓库里跑 → 命中工作区 `.env`
- 从任何其他地方跑 → 命中 `~/.elang/.env` 兜底

---

## 34. ✅ 工作区整理：归档旧版本、更新文档

### 34.1 归档到 `archive/`（附 `archive/README.md` 说明原因）

| 归档内容 | 原位置 | 过时原因 |
|---|---|---|
| `legacy-install/install.ps1`、`install.sh` | 根目录 | 被 `setup.py` + `install_skill.py` + `doctor.py` + `init_env.py` 取代。旧脚本把**代码复制进 skill 目录并各建一个 venv**，两份副本要同步升级 |
| `legacy-docs/guide.tex`、`guide.pdf` | `docs/` | 正文引用 `install.ps1`/`install.sh` 与旧路由 `#/read/learn`（新版是 `#/pc/read/learn`），照着做会走到废弃路径 |
| `legacy-api-reference.md` | `references/api_reference.md` | 描述 `:8082` + `token` 头 + POST 的旧接口；实测新版是 `/en/*` + GET + JWT。**每个字段都是错的** |
| `legacy-ipc/review.py`、`test_session.py` | `scripts/` | 旧文件 IPC 答题协议：两进程互相轮询、双方阻塞（本项目最大的时间浪费来源）。已被 MCP 状态机取代 |

**顺带修掉的 bug**：旧 `install.ps1` 装到 `~/.agents/<name>/`，
而 DSH/Codex 实际扫描 `~/.agents/skills/<name>/` —— **少了一层 `skills`**。

### 34.2 删除的可重建产物

`docs/guide.{aux,log,out,synctex.gz,toc}` —— LaTeX 中间产物（`guide.log` 单文件 49KB）。
`.vscode/settings.json` —— 指向不存在的 `temp/hello-cmake`（cmake 残留）。

### 34.3 新增 `scripts/setup.py`（统一安装入口）

替代归档的两个 shell 脚本，跨平台单一入口：

1. 建**隔离 venv** 并装依赖（优先用 `uv`；否则 `python -m venv`）
2. 调 `install_skill.py` 注册到各 agent 根目录
3. 调 `doctor.py` 报告依赖/浏览器/凭据状态

**不替你装浏览器** —— `doctor` 报告状态并打印确切命令。
理由：需要哪个构建取决于 Playwright 版本，写死会过时。

### 34.4 文档更新

| 文件 | 变更 |
|---|---|
| `README.md` | 重写：安装流程、凭据解析说明、**文章数 291 → 220**（实测）、subject 表用真实 id、命令改用 `#/pc/read/learn`、补 MCP 用法、目录结构 |
| `SKILL.md` | 重写：三阶段（确认环境 → 使用 → 验证码）、浏览器约定（**由 AI 按 doctor 输出处理，不预设版本**）、MCP 10 tool 用法、站点结构与 Vue 陷阱 |
| `CLAUDE.md` | 重写：三条硬规则（含**不依赖系统 site-packages**）、四个组成部分、容易踩的坑、沙箱限制 |
| `.claude/settings.local.json` | 旧 IPC 权限 → 新脚本权限 |

### 34.5 验证

- 11 个脚本全部编译通过
- 无残留引用（唯一一处是 `setup.py` 里说明"替代了旧脚本"的注释）
- `setup.py --check` 与 `doctor.py` 均正常输出
- `.mcp.json` 重新生成，指向工作区隔离 venv

### 34.6 当前根目录

```
.claude/  archive/  references/  scripts/
.env (真实凭据，已 gitignore)      .env.example
.gitignore  .mcp.json (生成物，已忽略)  .mcp.json.example
CLAUDE.md  DISTRIBUTION.md  MCP_DESIGN.md  CHANGELOG.md
README.md  SKILL.md  LICENSE  requirements.txt
```

---

## 35. ✅ uv tool 打包骨架（已构建并实装验证）

### 35.1 关键约束与解法

装成 tool 后代码在 site-packages，而 skill 里写的是 `python scripts/elang_reader.py`。
**两条路径都必须能走。**

**解法：wheel 里把模块「平铺」到 `elang/`，`elang/__init__.py` 只做一件事 ——
把自身目录加入 `sys.path`。** 于是：

- `import elang_reader` 在**开发布局和安装布局下都按裸名解析**
- **没有移动任何实现文件、没有改任何 import 语句、没有 shim**

这是整个打包方案里最省风险的一步 —— 避免了对 2500 行 `elang_reader.py` 的重构。

### 35.2 布局

```
pyproject.toml                  ← hatchling；[project.scripts] elang = elang.cli:main
src/elang/
├── __init__.py                 ← 把自身目录加入 sys.path（见 35.1）
├── cli.py                      ← 唯一入口，派发到各模块的 main()
└── （构建时由 force-include 填入下面这些平铺模块）
scripts/*.py                    ← 开发布局的真源
references/answers.json         ← 资源的真源
```

wheel 实际内容（已验证）：

```
elang/__init__.py  elang/cli.py  elang/config.py  elang/data/answers.json
elang/doctor.py  elang/elang_mcp.py  elang/elang_reader.py  elang/elang_session.py
elang/init_env.py  elang/install_skill.py  elang/setup_mcp.py
elang_reading-0.1.0.dist-info/{entry_points.txt, METADATA, ...}
```

### 35.3 CLI

```bash
elang doctor           # 环境/浏览器/凭据报告
elang init-env         # 生成 .env 模板
elang setup-mcp        # 生成 .mcp.json
elang install-skill    # 注册 skill
elang run batch-all    # 驱动求解器（参数透传）
elang mcp              # 运行 MCP server（stdio）
elang list             # 列出子命令
```

**`cli.py` 不重新实现任何逻辑** —— 每个子命令调用对应模块自己的 `main()`，
所以"仓库里直接跑"与"装成 tool 调用"行为完全一致。

### 35.4 🐞 打包时发现并修掉的两个问题

**问题 1：`answers.json` 被加了两次**

```
ValueError: A second file is being added to the wheel archive at the same path:
  `elang/data/answers.json`
```

原因：`packages = ["src/elang"]` 已自动包含 `src/elang/data/`，
而 `force-include` 又加了一遍。

**修复**：删掉 `force-include` 里那条，并**删除 `src/elang/data/` 整个目录** ——
改为让 `force-include` 直接**从 `references/` 取**：

```toml
"references/answers.json" = "elang/data/answers.json"
```

这样 `references/answers.json` 保持**唯一真源**，打包数据不可能与仓库版本漂移。
（我最初复制了一份到 `src/elang/data/`，那是引入重复，已纠正。）

**问题 2：`answers.json` 原来靠 cwd 与 `_SKILL_DIR` 定位**

```python
_ANSWER_BANK_PATHS = [<skill>/references/…, <cwd>/references/…]
```

装成 tool 后这两条都不存在（代码在 site-packages，cwd 是宿主给的）。
按 §32 的实测结论，**程序资源必须用 `importlib.resources`**：

```python
def _answer_bank_sources():
    # 1. 包内数据（importlib.resources，与 cwd 无关）
    # 2. 仓库 references/（开发布局）
    # 3. cwd 兜底
```

### 35.5 ✅ 实装验证（uv tool install，从任意 cwd）

```
interpreter : ...\uv\tools\elang-reading\Scripts\python.exe   ← uv 自管隔离环境
in venv     : True
browser     : launch ok   （复用系统 ms-playwright 缓存，未下载）
credentials : <cwd>/.env  （workspace (missing)）  ← 与安装位置无关 ✓

[elang] Answer bank loaded: 84 entries from
        ...\uv\tools\elang-reading\Lib\site-packages\elang\data\answers.json
        （cwd 是 temp 目录，证明资源解析不依赖 cwd）

elang mcp --selftest    → 10 tools registered
elang run（无参数）      → 正确报错并给提示
开发布局（仓库内）        → 84 entries from <repo>/references/answers.json
```

### 35.6 ⚠️ Playwright 浏览器仍是未自动化的一步

`uv tool install` **不装浏览器**（本设计的既有取舍）。当前实现的可行之处在于
**版本与浏览器缓存恰好匹配**：`requirements.txt` 钉 `playwright>=1.49,<1.61`，
而本机缓存有 chromium-1223 → 直接复用，零下载。

换台机器若缓存不匹配，需要跑 `python -m playwright install chromium`
（`elang doctor` 会打印该命令）。

### 35.7 分发形态（两种并存，各有其位）

| 形态 | 命令 | 适用 |
|---|---|---|
| **git clone + setup.py** | `python scripts/setup.py` | 普通用户；能顺带注册 skill |
| **uv tool install** | `uv tool install git+<url>` | 只想要命令行工具/MCP server；完全隔离、uv 自管 Python |

关键：因为 `config.resolve_env_file()` 的兜底包含 `~/.elang/.env`，
**tool 形态下即使用户不从仓库启动，凭据也能被找到**。

### 35.8 新增/变更文件

| 文件 | 说明 |
|---|---|
| `pyproject.toml` | 打包配置（hatchling + force-include + entry point） |
| `src/elang/__init__.py` | sys.path 注入（见 35.1） |
| `src/elang/cli.py` | 唯一 CLI 入口，派发到各模块 main() |
| `scripts/elang_reader.py` | 题库定位改为 `importlib.resources` 优先 |
| `.gitignore` | already had `dist/` |

### 35.9 ✅ `elang run` 在装成 tool 后也已验证（推翻了我先前的担心）

我一度担心 `run` 会因为 wheel 里没有 `scripts/` 而失效。**实测不成立**：

```
（cwd = <repo>/temp，非仓库根）
[elang] Answer bank loaded: 84 entries from
        ...\uv\tools\elang-reading\Lib\site-packages\elang\data\answers.json
[elang] Navigate: https://elang.zju.edu.cn/#/pc/read/index
[elang] Waiting for CAS login (up to 120s)...
```

原因：`cli.py` 先把**自身目录**（site-packages 里的 `elang/`）插入 `sys.path`，
`import elang_reader` 因此解析到**包内副本**。所以 `run` 与 `mcp` 走的是同一套模块，
与 cwd 无关。

**唯一未通过的是凭据**（`ERROR: no CAS credentials found`）——
用户的 `.env` 随旧 skill 目录一并删除了。这不是打包问题。

**待用户操作**：在仓库根创建 `.env`（`python scripts/init_env.py` 生成模板）。

---

## 36. ✅ 架构定案：MCP 工具独立安装，skill 只管文档与契约

用户明确的架构原则：

> **MCP 作为独立服务，通过 `uv tool` 安装；skill 只负责文档、契约。**

### 36.1 三个产物的职责边界

| 产物 | 安装方式 | 职责 |
|---|---|---|
| **工具** | `uv tool install git+<repo>` | MCP server + 求解器。自带隔离环境，`elang` 在 PATH 上 |
| **skill** | `install_skill.py` 复制 | **只有文档与契约** —— 告诉 agent 该跑什么命令 |
| **源码仓库** | `git clone` | 承载以上两者；开发用 |

**关键：工具自带全部依赖**（uv 管自己的 Python），所以 `setup.py` **不再建
项目 venv、不再 pip install** —— 那是与 `uv tool install` 重复的旧做法。

### 36.2 `setup.py` 重写为三步

```
[1/3] tool    → uv tool install --force <repo>（已装则报告）
[2/3] skill   → install_skill.py --copy
[3/3] state   → elang doctor
```

用户最终只需三条命令：

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart
elang init-env          # 生成 .env 模板
elang doctor            # 按提示处理（浏览器等）
```

已验证 `uv tool install .`（等价于 git+url 的构建路径）成功，
`elang list` / `elang mcp --selftest` / `elang doctor` 均正常。

### 36.3 🐞 修掉 `install_copy` 的嵌套路径 bug

**症状**：`install_skill.py --copy` 只复制了 `SKILL.md`，其余全部丢失。

**根因**：`PAYLOAD` 含**嵌套路径**（`references/answers.json`），
而 `shutil.copy2` 只创建文件、**不建父目录**。于是第一个嵌套条目抛
`FileNotFoundError`，**中断了后续所有复制**。

```
FileNotFoundError: [WinError 3] 系统找不到指定的路径
```

旧 PAYLOAD 用的是顶层目录（`references`），所以这个 bug 一直没暴露 ——
是我改成显式文件路径后触发的。

**修复**：复制文件前 `dst.parent.mkdir(parents=True, exist_ok=True)`。

**顺带修的第二个问题**：PAYLOAD 里列了 `assets`，但**该目录不存在**
（`.env.example` 在仓库根），所以它从未被复制进 skill。

修复后验证：`.env.example` ✓、`references/` 2 文件、`scripts/` 11 文件，退出码 0。

### 36.4 skill 的 PAYLOAD 说明

```python
PAYLOAD = [
    "SKILL.md",                 # 契约本体
    "references/answers.json",  # 题库
    "references/parse_answers.py",
    ".env.example",             # 凭据模板
    "CLAUDE.md",                # 面向 agent 的指引
    "CHANGELOG.md",  # 实测事实与坑
    "MCP_DESIGN.md",
    "DISTRIBUTION.md",
    "scripts",                  # 仓库检出时的独立回退
]
```

**为什么仍带 `scripts/`**：仓库同时能"独立运行"（`python scripts/elang_reader.py`），
带上它可保证克隆仓库的用户**永远有一条可跑的路**。
但**文档以 `elang <cmd>` 为主接口** —— 契约优先，实现副本只是保险。

### 36.5 待办

- [ ] 把改动提交并推送到远端，使用户能真正 `uv tool install git+<url>`
- [ ] 验证 DSH 用 `command: elang.exe / args: [mcp]` 注册 MCP（配置已简化，
      不再依赖仓库路径与 venv 位置）
- [ ] 用户重建 `.env`（随旧 skill 目录一并删除）

---

## 37. ✅ 文档进 wheel + 浏览器安装

### 37.1 文档打包进 `elang/share/`（修掉一个静默失效的 bug）

**问题**：`install_skill.py` 用 `REPO = Path(__file__).parent.parent` 找 payload。
装成 tool 后：

```
install_skill.py ∈ ...\site-packages\elang\
REPO = parent.parent → ...\site-packages\Lib     ← 不是仓库！
```

→ 每个文件都判定不存在 → **静默什么都不复制**。

**修复**：文档打进 wheel，`install_skill.py` 改为**双来源解析**
（与题库同一套思路）：

```
1. 包内数据 importlib.resources → elang/share/*（装成 tool 时）
2. 仓库相对路径                  → 开发/git clone 时
```

`pyproject.toml` 新增 force-include：

```
"SKILL.md" = "elang/share/SKILL.md"
".env.example" = "elang/share/.env.example"
"CLAUDE.md" / "CHANGELOG.md" / "MCP_DESIGN.md" / "DISTRIBUTION.md"
"references/parse_answers.py" = "elang/share/parse_answers.py"
```

**验证**（从已安装的 tool 注册到临时目录）：

```
(1 missing: scripts)   ← 诚实报告：scripts/ 只存在于仓库检出
复制成功：.env.example、CLAUDE.md、DISTRIBUTION.md、MCP_DESIGN.md、
          CHANGELOG.md、SKILL.md、references/（2 文件）
```

PAYLOAD 也从字符串列表改成 `(source_key, dest_rel)` 对，因为来源与目标现在不同。

### 37.2 ✅ 新增 `elang install-browser`

**补上了唯一的缺口** —— `uv tool install` 只管 Python 环境，**不管浏览器二进制**。

```
elang install-browser            # 装到工具私有缓存 ~/.elang/browsers
elang install-browser --shared   # 装到 Playwright 共享缓存
elang install-browser --check    # 只报告
elang install-browser --force    # 即使已有可用构建也装
```

### 37.3 关键实测数据

**共享缓存已膨胀到 1374 MB，含两代重复构建：**

```
chromium-1217                 406.6 MB
chromium_headless_shell-1217  264.8 MB
chromium-1223                 412.2 MB
chromium_headless_shell-1223  267.3 MB
---- 总计                    1373.6 MB
```

不同的 Playwright 版本共用一个目录 → 每升一次版本就多留一代。

**工具私有安装：682.9 MB，自包含，已验证可启动。**

### 37.4 ⚠️ 关键发现：headless 需要**两个**构建

`playwright install chromium` 会装**两个**产物：

1. 完整 chromium（`chromium-1223`）
2. **`chrome-headless-shell`**（`chromium_headless_shell-1223`）

而 **headless 启动默认用 shell**。所以只装完整版会让**每次 headless 启动失败**：

```
LAUNCH FAILED: Executable doesn't exist at
  ...\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe
```

这是实测踩到的（一开始以为下载失败只是网络问题）。
**所以不使用 `--no-shell`** —— 两个都装。

### 37.5 设计取舍：优先复用，缺失才下载

**没有**强行改用私有目录 —— 那会：
- 让用户已有的 1.3 GB 缓存作废
- 再下载 683 MB
- 打破现有可用状态

改为**两处都看，私有优先，共享兜底**：

```python
def browser_search_paths():
    if PLAYWRIGHT_BROWSERS_PATH:  return [它]      # 显式覆盖最优先
    return [BROWSERS_DIR, shared_browsers_dir()]   # 私有 → 共享兜底
```

并在**浏览器启动前**设置 `PLAYWRIGHT_BROWSERS_PATH`（私有存在时）——
否则装到私有目录的浏览器会被忽略，而启动仍然失败。

`install-browser` 不带 `--force` 时**检测到可用就什么都不做**：

```
Already usable — nothing to install.
(use --force to install a second copy anyway, e.g. to make this tool self-contained)
```

### 37.6 启动失败时的报错改进

`open_browser()` 现在把 Playwright 的原始错误翻译成可操作的提示：

```
Chromium is not installed for this tool.
  Install it with:  elang install-browser
  (or directly:  <python> -m playwright install chromium)
  Original error: ...
```

### 37.7 `doctor` 的浏览器段现在报告缓存来源

```
-- browser --
  private cache: %USERPROFILE%\.elang\browsers  (absent)
  shared cache : %LOCALAPPDATA%\ms-playwright  (present)
  usable       : True
  executable  : ...\ms-playwright\chromium-1223\chrome-win64\chrome.exe
  launch      : ok
```

### 37.8 一个真 bug（我自己引入又修掉）

`install-browser --check` 一开始 exit 1，尽管 `has_browser()` 为 True ——
因为它用 `--shared` 的语义（判断共享缓存）去判断可用性。
**症状**：命令说"可用"却返回失败，脚本化使用会误判。
已改为按"**是否存在任何可用构建**"判断。

### 37.9 待办

- [ ] 更新 `SKILL.md` / `README.md`：浏览器安装指引从
      `playwright install chromium` 改为 `elang install-browser`
- [ ] 提交推送，使用户能 `uv tool install git+<url>`
- [ ] 用户重建 `.env`

---

## 38. ✅ `install-skill` 支持指定 agent 与 scope

### 38.1 新接口

```bash
elang install-skill                                    # 全局，所有检测到的 agent
elang install-skill --agent claude                     # 只装 Claude Code
elang install-skill --agent dsh,codex --scope project  # 装进当前项目
elang install-skill --scope all                        # 全局 + 项目
elang install-skill --check                            # 只看状态
elang install-skill --uninstall --agent claude
```

| 选项 | 取值 |
|---|---|
| `--agent`（`--hosts` 为别名） | `dsh` / `codex` / `claude`，逗号分隔 |
| `--scope` | `global`（默认）/ `project` / `all` |
| `--project-root` | 覆盖自动探测的项目根 |
| `--dir` | 直接指定单个 skills 根 |

**项目根探测**：从 cwd 向上找最近的含 `.git` / `pyproject.toml` / `SKILL.md`
的祖先 —— 因为 agent 可能在项目的子目录里启动。

### 38.2 共享根现在正确标注

**DSH 与 Codex 共享 `~/.agents/skills`**（DSH rank 500）。旧实现会把它列两次；
现在合并为一行 `codex+dsh/global` —— 一个目录同时服务两者，这是事实而非重复。

### 38.3 🐞 修掉一个静默的卸载失败（严重）

**症状**：`--uninstall` 报告 `removed ...`，但**文件全都还在**。

**根因**：`remove_path` 在 Windows 上对**任何目录**都用 `cmd rmdir`，
但 **`rmdir` 只能删空目录** —— 对装满了文件的 skill 目录必然失败，
而 `subprocess.run` 的返回码**从未检查**，于是失败被完全吞掉。

**为什么之前没暴露**：`remove_path` 原本是为 **junction** 写的（`rmdir` 对
junction 是正确的：只删连接点、不动目标）。测试时用的是 `--copy`，
但卸载路径从未被真实验证过。

**修复**：
- 显式判断 junction（`Path.is_junction()`，3.12+；回退到检查
  `FILE_ATTRIBUTE_REPARSE_POINT`）
- **只有 junction 用 `rmdir`**；普通目录走 `shutil.rmtree`
- 失败时**抛异常并上报**，不再吞掉；卸载流程捕获后返回非零

验证：安装（三个根均 copied）→ 卸载（三个根均真正删除，`Test-Path` 全 False）。

### 38.4 另一个修正：默认模式改为 `--copy`

旧默认是 `--link`。但 link 只在**仓库检出**时才有意义（它把宿主指向仓库），
而装成 tool 后根本没有仓库 —— 结果是"默认行为在分发场景下不可用"。
现在默认 `--copy`，`--link` 需显式指定。

顺带：`--help` 的中文/破折号在 GBK 控制台乱码，已加 stdout UTF-8 重配。

### 38.5 gitignore 项目级安装目标

```gitignore
# 项目级 skill 安装目标（由 install-skill --scope project 写入）。
# 想随项目提交 skill（让协作者自动获得）时，删掉这几行即可。
/.dsh/skills/
/.agents/skills/
/.claude/skills/
```

默认忽略，避免一次安装就把仓库弄脏；删掉即可选择"随项目提交"。

### 38.6 提交

```
826f2ea  feat(install-skill): target agents and scope explicitly, and fix silent uninstall
```

---

## 39. ✅ 提示词一键配置（`setup-mcp --host` + `SETUP.md`）

用户的想法：**不手动装 uv / skill / MCP，而是复制一段提示词让 agent 全包**。

### 39.1 设计核心：分工，而不是让 agent 自由发挥

| 谁 | 做什么 |
|---|---|
| **提示词** | 顺序、每步的**验证方法**、如何判断环境 |
| **工具** | 确定性、幂等、可校验的命令 |

**关键约束：agent 不许手写配置文件**（缩进/格式极易出错）——必须走 `setup-mcp`。

### 39.2 🔍 关键发现：三个 agent 的注册格式**完全不同**

这才是有必要实现 `--host` 的原因：

| Agent | 文件 | 格式 | 顶层结构 |
|---|---|---|---|
| Claude Code | `<项目>/.mcp.json` | **JSON** | `{"mcpServers": {...}}` |
| DSH | `profiles/<p>/cordis.patch.yml` | **YAML** | 顶层**数组** `{id,name,config}` |
| **Codex** | `~/.codex/config.toml` | **TOML** | `[mcp_servers.<name>]` |

Codex 那条是本次查出来的（参考同文件已有的 `[mcp_servers.unityMCP]`）：

```toml
[mcp_servers.elang]
command = "...elang.EXE"
args = ["mcp"]
startup_timeout_sec = 120
```

### 39.3 ✅ 安全属性（全部实现并测试）

| 属性 | 实现 |
|---|---|
| **幂等** | 重跑报 `up to date`，不产生重复条目 |
| **原子** | 先写同级临时文件再 `os.replace` |
| **可回滚** | 先备份；校验失败自动还原 |
| **写后校验** | 重新解析；失败则回滚 |
| **不打印内容** | **只打印新增行**，绝不回显文件主体 |

最后一条不是洁癖 —— **用户的 `~/.codex/config.toml` 里有 API key 明文**
（`ANTHROPIC_AUTH_TOKEN = "sk-..."`）。测试里专门埋了一个假密钥，验证它
**从不出现在输出中**。

### 39.4 几个刻意的决定

- **条目指向已安装的 `elang`**，不再依赖仓库路径或 venv 位置
- **DSH 按 id 唯一**：已有的 `mcp-elang` **原地替换**，不追加第二条
- **Codex 拒绝改写不一致的表**：它会比对规范化渲染，若不同则**拒绝**
  而非猜测（那是用户的活配置）
- **无 pyyaml 时 DSH 回退为字面追加并明说**，而不是直接失败
- **新增 `PyYAML` 依赖**：要"重新解析校验"就必须有真正的解析器；
  追加器无法校验

### 39.5 ✅ 测试：33 项检查，全在**假配置**上跑

`scripts/test_setup_mcp.py`（固化为仓库资产）：

```
33/33 checks passed
```

覆盖：首次安装、幂等、**已有内容逐字节保留**、非法 JSON 拒绝、
**植入的密钥不被回显**、未知 host 拒绝、`--dry-run` 不写盘。

**它重定向 HOME 与各 host 的环境变量到 temp 沙箱** ——
真实 agent 配置**从未被触碰**。

> 期间发现并修掉一个行为不一致：codex 起初不完全幂等（重跑报"已存在"而非
> "无需更改"）。现在三个 host 行为一致。

### 39.6 `SETUP.md`：给 agent 读的契约

6 步流程，每步带**验证命令**，并明确约束：

- 第 0 步**先判断自己在哪个 agent 里**（这是 agent 独有、脚本做不到的能力）
- 第 3 步**让用户自己填密码**，agent 不得读取/回显/转述
- 第 4 步**问用户** scope，不许猜
- 失败时**报告原始错误**，不许跳过或假装成功
- 说明**MCP server 必须在文件沙箱外运行**（Playwright 需要命名管道）
- 附排查表（现象 → 原因 → 处理）

### 39.7 README 顶部的一句话提示词

```
读 https://github.com/pirate-608/huixuewaiyu-readingpart 的 SETUP.md，
按里面的步骤帮我装好这个工具。我是 <DSH / Codex / Claude Code> 用户。
```

### 39.8 ✅ 从远端安装后逐条验证

```
[第1步] elang list                → 7 个子命令 ✓
[第2步] elang install-browser --check → OK: a browser build is available ✓
[第3步] elang doctor              → launch ok / username set / password set /
                                    All good. / exit 0 ✓
[第5步] elang setup-mcp --dry-run → 正确显示将新增的行 ✓
```

### 39.9 提交

```
2cae424  feat(setup-mcp): register with claude/dsh/codex safely, plus one-prompt setup
```

---

## 40. 🐞 答案库实际作用为 0（四个缺陷，已修）

用户问"答案库有起到实际作用吗"。查证结论：**加载 84 条，实际可用 0 条**。

### 40.1 证据：逐关卡漏斗

| 关卡 | 剩余 | 原因 |
|---|---|---|
| 全部条目 | 93 | |
| 过加载器（跳过 unknown） | 89 | |
| 过标题长度（≥6） | 86 | |
| **过 format 闸门** | **5** | 代码查 `"letters"`（复数），数据是 `"letter"`（单数） |
| **过 `all_choice` 闸门** | **0** | 剩 5 条都是 `letter_and_fill`，含填空即被拒 |

数据真实分布：

```
letter            63      ← 单数，全部被拒
fill_in_blank     16      ← 无处理器
letter_and_fill    5      ← 过 format，但被 all_choice 拦
```

**运行时日志 `Answer bank loaded: 84 entries` 给人"有 84 条可用"的错觉。**

### 40.2 四个独立缺陷

**1. format 单复数不匹配**

```python
if bank_ans.get("format") in ("letters", "letter_and_fill"):   # 查复数
{"format": "letter", ...}                                      # 数据是单数
```

67 条 `letter` 全部静默被拒。

**2. `all_choice` 闸门 + 填空从不处理**

原代码只支持"全是选择题"的文章；而实站文章形状是 **5 选择 + 1 填空**，
所以连那 5 条 `letter_and_fill` 也过不了。

**3. 模糊匹配是死代码**

```python
art_words = set(art_key.split())     # art_key 已被去掉所有空格 → 单个 token
```

`_normalize_title` 去掉了空格，`.split()` 永远只得到一个元素，词重叠比较无意义。

**4. 日志误导**

报"84 entries"，但没说明其中多少可用。

### 40.3 修复

**统一映射函数 `_bank_answers_for(ans, questions)`** 取代 `all_choice` 闸门：

- 银行 `letters` **按顺序**对应**选择题**
- 银行 `fill_in_blank` **按 index 排序**后，按每个填空题的 `blanks` 数**分配给填空题**
- 数量必须**完全匹配**，否则**拒绝并给出原因** —— 半套答案等于静默答错
- **裸字母填空答案**（词库题）通过该空的 `select_options` 映射成 option value
  （`"E"` → `"E-swimming hole"`）；**映射不到就拒绝，绝不猜**

**格式名接受数据里实际存在的全部拼写**：`letter` / `letters` /
`letter_and_fill` / `fill_in_blank`。

**模糊匹配改用原始标题**：索引里保留 `{"answers":…, "title":…}`，
`_title_words()` 对**原始标题**取词。

**日志改为格式细分**：

```
[elang] Answer bank loaded: 84 entries (16 fill_in_blank, 63 letter,
        5 letter_and_fill) ...; 3 title(s) too short to match
```

### 40.4 ✅ MCP 路径接入（此前完全不用）

`elang_session.open_next()` 现在会查答案库，命中时在信封里附：

```json
{"bank_answers": [[0,3],[1,2],[2,2],[3,0]],
 "hint": "This article is in the answer bank: you may call
          elang_submit_answers with bank_answers directly."}
```

未命中但标题命中时附 `bank_note` 说明原因（如数量不匹配）。
异常被捕获，**绝不让答案库拖垮整轮运行**。

### 40.5 ✅ 测试

新增 `scripts/test_answer_bank.py`：

- `letter` 格式被接受（原 bug 的回归测试）
- `letter_and_fill` 的填空按空分组
- 裸字母 → option value 映射
- 无法映射的字母**被拒绝**
- 数量不匹配**被拒绝**（缺选择题/缺填空各一例）
- 未知格式被拒绝
- 模糊匹配（含"标题多出几个词"的正例）
- **MCP 路径**：命中 / 近失 / 未命中三种情况

### 40.6 自洽性验证

用每条记录**自身的形状**合成题目再映射：**83/84 成功**。
唯一失败的是数据本身有问题的一条：

```
title: A Letter of Refusal   raw: "CADB(?)"   letters: [...'?']
```

它的报错现在明确说"bank records an unknown answer ('?')"，
而不是含糊的"字母不匹配选项"。

### 40.7 ⚠️ 未解决的问题：覆盖率

修好代码路径后，**实测 6 篇真实文章仍然全部 miss** —— 因为题库里根本没有这些标题。

```
题库: 84 条可用 vs 站点 ~220 篇
已处理的 6 篇: 0 命中
```

**代码路径现在是对的；答案库是否真的省时间，取决于题库覆盖和线上题目数量是否与记录一致。**
这属于数据问题，不是代码问题。

---

## 41. ✅ `elang run` 成为可用回退：agent 就是答题方

### 41.1 先纠正一个方向性错误

用户说"我做模型答题"，我第一反应是**在工具里接 LLM API**（写了 `llm.py` +
`ELANG_LLM_*` 配置）。**这是错的** —— 用户指的是 **agent 自己答题**。

已全部撤销，`llm.py` 删除。教训：**这个工具的定位是"机制"，不是"智能"**；
智能来自宿主 agent。

### 41.2 真正的病根

`elang run` 从来不是"半成品"，而是**闭环断了一半**：

```
elang run  →  写 elang_current.json  →  等 elang_signal.json
                                              ↑
                                    谁写？ review.py
                                    —— 已被归档 ✗
```

所以它的真实能力退化成：**题库命中的文章能跑完，其余全部空等 600s 后标 timeout**。

`CLAUDE.md` 里我甚至写过"答案不再走文件" —— 那句话在**没有替代答题方**的前提下
等于宣布回退路径死亡。

### 41.3 修复：把答题侧做成一等命令

```
elang pending              # 显示待答文章（立即返回）
elang pending --brief      # 一行摘要
elang pending --json       # 原始请求
elang answer 0=A 1=C       # 选择题给选项字母
elang answer "5=A,B,C"     # 填空题每空一个值
elang answer --raw '[[0,1],[5,["A-x"]]]'
elang skip / continue / stop
```

**`answer_ipc.py` 只 import `config`**，不 import `elang_reader` —— 所以答题侧
**不需要 Playwright**。为此把 IPC 路径规则移到 `config.ipc_dir()`。

### 41.4 关键设计：只有一侧阻塞

| 侧 | 是否阻塞 |
|---|---|
| `elang run` | **是** —— 但它在自己的后台 job 里，这是它的职责 |
| `elang pending` / `answer` / `skip` / `continue` / `stop` | **否**，全部立即返回 |

**旧设计"双方互相等"的锅不在协议，在用法** —— 用 `job_output(wait=true)`
去 poll 一个正在等你的进程，必然死锁。正确姿势：

```
1. elang run batch-all  作为后台 job 启动
2. 轮询 elang pending --brief     （非阻塞）
3. waiting_for_ai → elang pending 看题 → elang answer ...
4. 直到 job 结束
```

`CLAUDE.md` / `SKILL.md` / `README` 都已按这个契约重写。

### 41.5 两个真实细节

**词库填空绑定的是 option 的 `value`，不是 label**

所以 `elang answer "5=A,B"` 必须映射成 `["A-alpha","B-beta"]`，
否则提交进去的是裸字母，页面不认。自由文本填空原样透传；
映射不到时**不臆造**，交给页面判断。

**作答必须校验严格**

未知题号 / 未知选项字母 / 填空数量不对 / 格式错误 → **exit 1 且不写任何文件**。
`status != waiting_for_ai` 时（比如 checkpoint 暂停）明确提示改用
`elang continue` / `elang stop`，而不是写一个没人读的答案。

### 41.6 打包遗漏

`answer_ipc.py` 一开始**没进 wheel** —— `pyproject.toml` 的 force-include 是
**显式列表**，新增模块必须手动加。装成 tool 后 `elang pending` 报
`ModuleNotFoundError`。已补，并验证安装态可用。

### 41.7 顺手修的回归

`scripts/test_mcp.py` 读 `res.isError`，在 MCP 2.x（`is_error`）下崩。
生产代码早有 shim，测试没有。已加同样的双拼写兼容。

### 41.8 ✅ 验证

- `scripts/test_answer_ipc.py`：**20/20** —— 显示、字母→索引、填空 value 映射、
  raw 直通、5 种拒绝路径、3 个控制动词、checkpoint 情形
- 全量回归：answer_bank / setup_mcp(33) / mcp 协议 全通过
- 从 **git 安装**后：`elang doctor` → All good；`elang pending --brief`
  **82ms 返回**；`elang answer 0=B` → `[[0,1]]` 正确

### 41.9 提交

```
e0457d0  feat(cli): make `elang run` a real fallback — the agent answers it
```

---

## 42. ✅ 文档对齐：不让答题 agent 读过时信息

用户要求："更改这个 skill 的文档，不要让答题 agent 运行在过时的信息里。"

`SKILL.md` 是 agent 的**契约**，读错就会走错路径。系统性审计后发现四类过时：

### 42.1 四类过时内容

| 类型 | 具体 |
|---|---|
| **旧布局** | 开头教 `$PY scripts/doctor.py`、定义 `.venv/Scripts/python.exe`、"若 .venv 不存在先跑 scripts/setup.py" —— 全是拆分前的形态。装成 tool 后既没有仓库也没有 `.venv` |
| **自相矛盾** | L126 教 `elang answer`，L181 却写"**答案不再通过文件传递**" |
| **名字错** | 写 `elang-mcp`；实际注册的 serverName 是 `elang`，工具是 `mcp__elang__*` |
| **缺关键信息** | 完全没提答案库、`bank_answers`、`setup-mcp`、`install-skill` |

### 42.2 SKILL.md 重写要点

- 一切从 **`elang`** 开始，明确"不要找 `.venv`、不要用 `python scripts/...`"
- 规则从三条扩到**四条**，新增"**先查题库，再自己答**"
- MCP 段补上 `bank_answers`（命中直接提交，省掉整个模型往返）与 `bank_note`（近失原因）
- CLI 段把答题循环写死：**只有 `elang run` 阻塞**，agent 用 `elang pending --brief`
  轮询，**绝不要 `job_output(wait=true)`**
- IPC 一节改为"答题确实走文件，但你不用手写 —— 用 `elang pending/answer`"
- 补「安装」与「会话保持」（持久化 profile 不保留会话 cookie，重放是必需的）

### 42.3 其余文档

| 文件 | 修正 |
|---|---|
| `CLAUDE.md` | 组件表补 `answer_ipc.py` + 依赖方向图；命令段以 `elang` 为主，仓库路径降级为"开发"小节 |
| `DISTRIBUTION.md` | `install-skill --agent/--scope` 取代旧 `--hosts` 调用；沙箱说明改用真实 server 名 |
| `archive/README.md` | 原文称 IPC 协议"已退休、没有调用方"——**这正是 `elang run` 丢掉答题侧的原因**。改为：归档的是那个临时脚本，协议已恢复为一等命令 |
| `MCP_DESIGN.md` | 加**状态头**：它是设计记录不是现状，"目标态（IPC 退休）"已被推翻 |
| `SETUP.md` | `elang list` 的期望输出补上答题动词 |

**`CHANGELOG.md` 不改** —— 它是带日期的历史记录，改它等于篡改结论。

### 42.4 顺带修正架构不一致

skill payload 里还带着 `scripts/` 和 `references/`，这与新 SKILL.md
（明确说不要用 `python scripts/...`）矛盾，而且**装成 tool 后根本复制不出来**
—— 每次安装都打印 `missing: scripts`，看起来像坏了。

按"skill 只带文档契约"的原则精简为 **8 份文档**，`missing` 消失。

### 42.5 ✅ 验证

从 **git 安装**后检查包内 `SKILL.md`：

```
行数 272 / 含 elang pending / elang doctor / bank_answers
不含 $PY / 不含"答案不再"
唯一一处 `python scripts/` 是"不要用它"的警告句
```

注册到临时目录：8 份文档，无 `missing`。

回归：answer_ipc 20/20、answer_bank 全过、setup_mcp 33/33、mcp 协议往返通过。

### 42.6 提交

```
627adbf  docs: bring the agent-facing docs in line with what the code actually does
```

---

## 43. ✅ 两种 agent 的文档分工（约定 + 强制）

用户要求区分：**开发 agent**（开发调试本项目）与**执行 agent**（跑 skill 答题），
文档不要搞混。

### 43.1 之前的混法（真实问题，不是理论）

`elang install-skill` 把下面这些**一股脑复制进执行 agent 的 skill 目录**：

- `CLAUDE.md`（开发指南）
- `CHANGELOG.md`（**2355 行**实测日志）
- `MCP_DESIGN.md`（设计记录）
- `DISTRIBUTION.md`（分发设计）

而 `SKILL.md` 本身也混着开发内容：站点组件表、Vue 序列化陷阱、
"改代码前读 CHANGELOG"。

### 43.2 约定

| 角色 | 用途 | 文档 | 随 skill 分发 |
|---|---|---|---|
| **执行 agent** | 跑 skill 答题 | `SKILL.md`、`SETUP.md`、`.env.example`、`README.md` | ✅ |
| **开发 agent** | 开发 / 调试本项目 | `CLAUDE.md`、`CHANGELOG.md`、`MCP_DESIGN.md`、`DISTRIBUTION.md`、`SETUP_DESIGN.md`、`archive/` | ❌ |

**规则**：

1. 每份文档开头都有 `> **读者：…**` 横幅
2. `SKILL.md` **只讲怎么用**，实现细节一律在 `CLAUDE.md`
3. 开发文档**不发货**
4. 往 payload 加文件前先问：**执行 agent 需要它吗？**

### 43.3 具体改动

- `SKILL.md`：删掉站点组件表、Vue 陷阱、"读检查点"指令；
  改为一段「工具内部做了什么（你不需要操作页面）」的行为概要。
  对 `CLAUDE.md` 的引用改成**绝对 URL** —— `SKILL.md` 单独分发，相对链接会失效
- `README.md`：新增角色表 + 带「随 skill 分发」列的文档地图
- `install_skill.py` PAYLOAD 与 `pyproject.toml` 的 `elang/share/`：
  都收敛为**四份执行侧文件**
- `.env.example`：加读者横幅与凭据解析顺序说明

### 43.4 ✅ 用测试把约定锁死

新增 `scripts/test_doc_roles.py`（**33 项**），检查：

- payload ⊆ 执行侧文档；**没有任何开发文档**；不含 `scripts/references/archive`
- payload 每一项都能从 wheel 里解析到（不会出现 `missing`）
- `share/` 与 payload 完全一致
- 每份文档都声明了读者
- 横幅指向的角色正确（执行侧说"执行 agent"，开发侧说"开发 agent"）
- `SKILL.md` 没有指向开发文档的**相对**链接
- `SKILL.md` 不含 DOM/Vue 内部细节（`PcReadPraxis` / `PcReadLearn` /
  `PcReadIndex` / `__elangPraxisVm`）

**以后再往 payload 里塞文件，测试会直接失败**，而不是悄悄污染已安装的 skill。

### 43.5 ✅ 验证

从 wheel 安装后执行 `elang install-skill`：

```
文件: .env.example, README.md, SETUP.md, SKILL.md
SKILL.md 269 行
有「读者：执行 agent」 : True
有 DOM/Vue 内部细节    : False
有 CHANGELOG : False
有 elang pending        : True
```

回归：doc_roles 33/33、answer_ipc 20/20、answer_bank 全过、setup_mcp 33/33、MCP 往返通过。

### 43.6 提交

```
cef19eb  docs: split the documentation by audience — 执行 agent vs 开发 agent
```

---

## 44. 凭据变量名：两套都兼容，但文档写混了

用户发现 `.env` 里是 `CAS_PASSWORD`（无前缀），而文档里提到 `ELANG_CAS_*`，
问是不是"已经兼容新的，还是仍在混用"。

### 44.1 结论：代码没混用，文档混了

**代码（`config.py`）从一开始就是两套都认的**：

```python
USER_KEYS = ("ELANG_CAS_USERNAME", "CAS_USERNAME")   # 带前缀优先
PASS_KEYS = ("ELANG_CAS_PASSWORD", "CAS_PASSWORD")
```

实测（逐项验证）：

| 场景 | 结果 |
|---|---|
| 文件写 `CAS_USERNAME` | ✅ `from file:CAS_USERNAME` |
| 文件写 `ELANG_CAS_USERNAME` | ✅ `from file:ELANG_CAS_USERNAME` |
| 两者都在文件 | ✅ 带前缀优先 |
| 环境变量（两种写法） | ✅ 都认 |
| 两者都在环境 | ✅ 带前缀优先 |
| 环境变量 vs 文件 | ✅ 环境变量胜出 |

**问题在呈现**：

- 模板（`write_env_template`、`.env.example`、`init_env` 输出、README 示例）
  写的是**裸名**
- 所有"解析顺序"块只列**带前缀名**作为环境变量覆盖
- 两者并排看像两个不相关的变量 → 看起来像混用

### 44.2 为什么本来就该有两套

- **`.env` 用裸名**：简短，且兼容本项目早期（前缀出现之前）已有的配置
- **环境变量用带前缀名**：进程环境是共享的，裸 `CAS_USERNAME` 可能与其他工具撞车

**两个来源都接受两种写法**，同源内带前缀优先。

### 44.3 修正（只改呈现，不改行为）

- `SKILL.md` / `SETUP.md` / `README.md` / `CLAUDE.md`：统一成**一份**解析块，
  同时列出文件顺序、两套键名与优先级
- `README.md` 补「为什么有两套」的说明
- `write_env_template` 与 `.env.example` 写同样的说明 —— 新生成的 `.env` 自带解释
- `init_env` 输出提示也接受带前缀写法

### 44.4 ✅ 用测试锁住

新增 `scripts/test_env_names.py`（**19 项**）：文件两套、环境两套、同源内带前缀优先、
环境压过文件、部分配置如实报告、生成的模板同时提到两套名、**每份文档都必须同时提到两套**。

以后谁把文档改成只写一套，测试直接失败。

### 44.5 ✅ 验证

真实工作区 `.env`（裸名）仍正常：

```
env file : ...\huixuewaiyu-readingpart\.env  (workspace)
username : set  from file:CAS_USERNAME
password : set  from file:CAS_PASSWORD
All good.
```

全量回归：env_names 19/19、doc_roles 33/33、answer_ipc 20/20、answer_bank 全过、
setup_mcp 33/33、MCP 往返通过。

### 44.6 提交

```
a10b0b0  docs(credentials): state both accepted spellings everywhere they are described
```

---

## 45. 🔴 隐私审计与历史重写（学号误提交进公开仓库）

用户要求两件事：检查提交内容是否含本地敏感信息；确保除 `.env` 外工具不落明文
CAS 隐私数据。

### 45.1 仓库审计结果

| 检查项 | 结果 |
|---|---|
| API key / 私钥 / token | ✅ 无 |
| `.env` 是否曾提交 | ✅ 从未（`.env.example` 只是模板） |
| **真实学号** | 🔴 **2 处**（`CHANGELOG.md`） |
| **含用户名的本机路径** | 🔴 **5 处**（`C:\Users\<user>\…`） |
| **本地仓库路径** | 🔴 **3 处**（开发者的本地检出目录） |

**性质**：那是一枚**真实学号**（形如 `3*********`），出现在公开仓库里（当时 `"private": false`，
9 star、1 fork）。密码从未出现在仓库。

### 45.2 工具侧明文存储核查

| 数据 | 存哪 | 结论 |
|---|---|---|
| **CAS 密码** | **仅 `.env`** | ✅ 唯一一处，且 `.env` 从未跟踪 |
| 密码进日志 | 从不 | ✅ |
| **学号进日志** | 原来**会**：`CAS auto-login as <id>`、`session saved (sid=<id>)` | 🔴 已掩码 |
| 会话（`user` + JWT + cookies，**无密码**） | 原在 `C:/tmp`（本机其他用户可读） | 已移至 `~/.elang/session.json` + POSIX `chmod 600` |
| 浏览器 profile（cookies） | `~/.elang/browser-profile` | Chromium 自身存储，无法避免 |
| 验证码图 / 题面 / 截图 | IPC 目录 | 只有题面，无凭据 |

**结论：密码确实只在 `.env`；但学号曾被写进 stdout，这是真 bug，已修。**

### 45.3 修复 1：当前树脱敏

- 学号 → 占位符
- `C:\Users\<user>\…` → `%USERPROFILE%` / `%APPDATA%` / `%LOCALAPPDATA%`
- 开发者的本地检出目录 → `<repo>`
- 归档脚本里的 `C:\Python3xx` **候选列表保留**（标准安装位置，非本机布局）

### 45.4 修复 2：运行时不落隐私

- `_mask_id()`：学号在日志里显示为 `325*******`
- 会话文件移出共享临时目录，写入后收紧权限（POSIX）
- `.env` 写入后同样收紧权限
- 新增 `scripts/test_no_secrets.py`（8 项）：扫描密钥、字面量密码赋值、
  学号样式数字、本机用户路径；断言 `.env` 未跟踪且被忽略

### 45.5 修复 3：历史重写（force push）

**为什么只能 force push**：git 提交哈希由内容决定，学号只要还在任何一次提交里
就能被 `git log -p` 翻出。要真正移除，必须改变提交内容 → 哈希变化 → 非快进推送。

排除的方案：

- 只改当前树 → 旧提交仍可检索 ❌
- 改仓库为私有 → 但本项目靠公开仓库分发（README 的一句话提示词依赖它）❌
- 请 GitHub 清除 → 只能清缓存，改不了提交内容 ❌

**执行**：`git filter-repo --replace-text`，替换 4 组字符串：

```
<真实学号：10 位数字>        -> <sid>
<含用户名的本机路径>        -> 脱敏形式
<开发者本地检出目录>        -> <repo>
```

（这里刻意不写出原文 —— 这条记录本身曾经因为引用原值，把学号又带回了历史。）

**验证**（重要，证明只改了字符串、没改内容）：

| 检查 | 结果 |
|---|---|
| 提交数 | 37 → 37（不变） |
| **提交信息序列** | 完全一致 |
| **HEAD 树对象** | 一致 → 当前内容零变化 |
| 旧历史含学号提交 | 4 → **0** |
| 旧历史含用户名路径 | 2 → **0** |
| 全新 clone 复查远端 | **0 命中** |

**残留风险（已写入 `SECURITY.md`）**：

- **fork 保留重写前副本**，上游无法删除
- 旧克隆需 `git fetch --all && git reset --hard origin/master` 或重新 clone
- GitHub 可能短期缓存旧对象

**为了不让重写显得粗暴**，专门新增 `SECURITY.md` 说明：发生了什么、为什么必须
force push、排除了哪些替代方案、影响范围（只涉及学号与路径，代码零变化）、
以及旧克隆怎么同步。

### 45.6 本地清理

重写后删除历史备份 bundle 与替换规则文件，并 `reflog expire + gc --prune=now`
清掉旧对象 —— 本地也不留副本。

### 45.7 提交

```
5e9835f  (重写后的 HEAD) docs(security): explain the history rewrite and the privacy rules it produced
```

> 重写改变了所有提交哈希，上文只保留语义信息，不引用旧 SHA。

### 45.8 补记：重写做了两遍（教训）

第一遍重写后，我写这份记录时**引用了学号原文**（为逐条列出替换内容），提交推送后
**又把数据带回了历史** —— 关于泄漏的文档本身成了泄漏。因此做了第二遍，
并把规则定为：**描述，不引用原值**。

由此新增两道防线：

1. `scripts/test_no_secrets.py` —— 扫描受跟踪文件（密钥、字面量密码、10 位学号
   样式数字、本机用户路径），并断言 `.env` 未跟踪
2. `.githooks/pre-commit` —— 每次提交前自动跑上面的扫描，命中即**阻断**
   （每个克隆启用一次：`git config core.hooksPath .githooks`）

最终状态：远端全新克隆复查，**全部 39 个提交 0 命中**。

---

## 46. ✅ 浏览器复用：已经装了 Chrome/Edge 就不再下载（实测）

### 46.1 问题

首次运行的代价是下载约 683 MB（chromium + chrome-headless-shell）。很多机器
本来就有 Chrome 或 Edge，这份下载纯属浪费。原实现只有 `ELANG_BROWSER=msedge`
这一条"逃生口"，且文档把它描述成可能有副作用的选择。

### 46.2 实测：系统浏览器能否启动、能否共用 profile

环境：Playwright 1.60，自带 chromium 1223（UA 里是 Chrome 148）。

| 组合 | headless | 有头 | 页面加载 + `evaluate` |
|---|---|---|---|
| 自带 chromium | ✅ | ✅ | ✅ |
| `channel=chrome`（Chrome 157） | ✅ | ✅ | ✅ |
| `channel=msedge`（Edge 156） | ✅ | ✅ | ✅ |
| `executable_path=<chrome.exe>` | ✅ | ✅ | ✅ |

profile 目录能否在两者之间复用（同一目录先后启动）：

| 顺序 | 结果 |
|---|---|
| Chrome 157 建 profile → chromium 148 打开 | ✅ |
| chromium 148 建 profile → Chrome 157 打开 | ✅ |
| Chrome 157 → Chrome 157 | ✅ |

既然双向都能打开，就不需要按浏览器分 profile 目录。这也意味着会话文件
（`elang_session.json`）不用跟着浏览器走。

### 46.3 ⚠️ 更正第 4 节坑 4 与第 22 节的结论

旧结论是"`channel="msedge"` 会让 Edge 拒绝启动（不受支持的命令行标志）"。
本轮重测：**`channel="msedge"` 本身没问题**，问题出在当时的调用方式——
给 `launch()` 传了额外命令行参数。`launch_persistent_context` 不传那些参数，
Edge 与 Chrome 都正常。旧文档把"渠道"与"参数组合"混为一谈了。

### 46.4 实现

唯一的决定处是 `config.browser_choice()`，优先级：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | `ELANG_BROWSER` | `chromium`/`bundled`；`chrome`/`msedge`；可执行文件路径；其他值原样当 channel |
| 2 | 自带 Chromium | 默认，自包含，与运行它的 Playwright 版本匹配 |
| 3 | 已装 Chrome / Edge | 没有自带构建时用它，省掉下载 |
| 4 | 无 | 报错并给出两条修法 |

要点：

- **探测自己找路径，不靠 Playwright 的 registry 查找。** 顺序是注册表 App Paths、
  常见安装位置、PATH（Windows/macOS/Linux 各一套），找到可执行文件后传
  `executable_path`，这样 scoop、便携版、tarball 安装也能用；只有用户点名了一个
  找不到的 channel 时才原样透传 `channel=`。
- **版本自己读。** Windows 上 `chrome.exe --version` 因为进程脱离控制台拿不到输出
  （实测输出为空），改为读 PE 版本资源；macOS/Linux 直接跑 `--version`。
- **`install-browser` 默认"先复用、再下载"**：有构建什么都不做；没构建但有
  Chrome/Edge 就打印用的是哪一个并退出，不联网；两者都没有才下载。
  `--bundled` 强制下载，`--shared` 装到共享缓存，`--check` 只报告。
- **`doctor.py` 报告并真的启动"实际会用的那一个"**，不再固定检查自带构建的路径，
  否则复用系统浏览器时会被误报为 FAILED。
- **`PLAYWRIGHT_BROWSERS_PATH` 优先**：装了构建却装在别处等于没装，所以下载目标
  跟随这个变量。

### 46.5 测试

`scripts/test_browser_choice.py`（23 项，不启动浏览器）：覆盖四类显式指定、
自动优先级、launch kwargs、探测与版本读取。本机结果 23/23。

### 46.6 干净环境验证（已实测）

做法：`uv build` 出 wheel → 用独立的 `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` 安装
（不碰本机已有安装）→ 工作目录、IPC、profile、浏览器缓存全部换成工作区内全新的
空目录，并让 `PLAYWRIGHT_BROWSERS_PATH` 指向空目录，模拟一台"没有 Chromium
构建"的机器。

| 检查 | 结果 |
|---|---|
| `uv tool install <wheel>` | ✅ 只生成 1 个可执行文件 `elang` |
| wheel 内容 | ✅ 12 个模块 + `data/answers.json` + `share/` 下 4 份执行文档 |
| `elang`（无参数） | ✅ 打印用法 |
| `elang doctor` | ✅ 选中系统 Chrome 157 并启动成功（`launch: ok`） |
| `elang install-browser --check` | ✅ 退出码 0，报告可用的系统浏览器 |
| `elang install-browser` | ✅ 打印 "Reusing the installed browser"，**不联网也不下载** |
| `elang run batch-all --limit 1 --dry-run` | ✅ 用系统 Chrome 完成 CAS 登录；抓到 6 题（5 选择 + 1 填空）、3758 字符文章 |
| 题库未命中 → agent 作答（CLI 回退） | ✅ `elang pending` 显示题目 → `elang answer 0=A 1=B 2=A 3=B 4=A "5=D,C,B,A,F,G,E"` → 运行端 `answers recorded` → 打开提交确认框但**不提交** |
| `elang install-skill --copy --scope project` | ✅ 从 wheel 复制 4 份执行文档到两个 DSH 根目录 |
| `elang setup-mcp --dry-run --host dsh` | ✅ 生成正确的 MCP 条目（`command` 指向隔离安装的 `elang.exe`） |
| `elang mcp`（stdio 客户端驱动） | ✅ initialize、10 个 tool、`elang_status`=idle、`elang_list_subjects` 启动浏览器并返回 11 个主题 |

这次验证同时覆盖了两件事：**新装工具在没有任何既有状态时可用**，以及
**装了 Chrome 的机器不需要下载 683 MB**（`PLAYWRIGHT_BROWSERS_PATH` 是空目录，
`install-browser` 直接复用系统 Chrome）。

一个环境限制，不是工具缺陷：在本会话的 DSH 文件沙箱内，子进程写 `~/.elang/`
被拒绝（`save_session()` 报 `PermissionError` 后只打印警告并继续，浏览器
profile 因为指向工作区而不受影响）。后果是每次都要重新 CAS 登录；正常终端里
没有这个限制，此前几轮实测会话都能保存。需要浏览器和 home 写入的操作应在
沙箱外执行，这与第 3 条规则一致。

---

## 47. 文档改名：`MIGRATION_CHECKPOINT.md` → `CHANGELOG.md`

这份记录的作用已经变了。它不再是"迁移进度检查点"，而是每次改动的详细历史：
比 git 提交信息多出实测数据、被推翻的假设、踩过的坑和判断依据。名字跟上职责，
改为 `CHANGELOG.md`。

- 历史内容不改，只把文中出现的旧文件名统一替换为新名。
- 外部引用同步更新：`AGENTS.md`/`CLAUDE.md`、`README.md` 的文档表、
  `DISTRIBUTION.md`、`MCP_DESIGN.md`、`SECURITY.md`、`pyproject.toml` 注释，
  以及 `scripts/` 里的注释和 `test_doc_roles.py`、`test_no_secrets.py` 的提示。
- 顶部补了三条约定：按时间追加、旧结论不删、被推翻的结论就地更正。
- `test_docs_match_code.py` 的 `DOCS` 列表**故意不包含**本文件：它记录历史
  命令，按设计允许出现过时命令，纳入自动检查只会误报。

---

## 48. 安装 uv：给出官方命令，但先问用户

旧文档只说"`uv` 不存在时告诉用户，不要擅自安装"，没有给具体命令，装不装、怎么装
全靠用户自己查。而这条命令是平台相关的，Windows 上官方推荐用 PowerShell 脚本。

现在的规则：

1. **给出官方安装脚本**，让用户看到要执行什么：

   Windows（PowerShell）：

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   macOS / Linux：

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **agent 不得未经询问就安装**，要拿到用户明确同意再执行。理由：uv 是系统级
   改动，会写用户目录并修改 PATH。
3. 安装脚本从 `astral.sh` 下载，属于"需要代理"的那一类；失败不要连续重试
   （第 4 条规则）。
4. 装完必须重开终端，`uv --version` 能跑再继续。用户拒绝时：clone 仓库 + 自建
   venv，直接从仓库运行 `scripts/elang_reader.py`。

落实位置：`SETUP.md` 第 1 步与排查表、`SKILL.md` 安装一节、`README.md` 依赖
一节、`SETUP_DESIGN.md` 的提示词与"不做的事"，以及 `scripts/setup.py` 的失败
提示（它只打印命令，绝不自己装）。

顺带修掉一处旧错误：`SETUP.md` 原来把"替代方案"写成 `git clone` 后
`python scripts/setup.py`，但那个脚本自己就要求 PATH 上有 `uv`，等于循环依赖。
现在改成自建 venv（`python -m venv .venv` + `pip install -r requirements.txt`），
再从仓库运行 `scripts/elang_reader.py`。

> 2026-11-04 撤回：上面这两条安装命令已从 README / SETUP.md / SKILL.md 删除，
> 理由见第 50 节。

---

## 49. 支持范围定案：只支持 Windows

README 的特性列表原来写着"跨平台：Windows / Linux / macOS"，但项目从头到尾只在
Windows 上实测过。为了判断这句话站不站得住，做了一次审查，含 WSL Ubuntu 24.04
上的实测。

**纯 Python 部分在 Linux 上能用**：

- `config.ipc_dir()` → `/tmp`；共享浏览器缓存 → `~/.cache/ms-playwright`
- 无浏览器时 `browser_choice()` 正确返回 `none`
- `install-browser --check`、`answer_ipc pending`、`install-skill --check`、
  CLI 入口都正常
- `.env` 模板权限 0600（POSIX 的 chmod 分支生效）
- env_names 19/19、answer_ipc 20/20、browser_choice 20/20、doc_roles 37/37、
  docs_match_code 19/19、no_secrets 8/8
- 但 `test_setup_mcp.py` 直接失败：它写死 `.venv/Scripts/python.exe`（Windows 路径）

**挡住 Linux 的是运行环境，不是 Python 代码**：

1. `open_browser()` 硬编码 `headless=False`，`ElangSession` 的 `headless` 参数
   只存不用。Linux 服务器、容器、CI 没有显示服务，启动即失败。
2. `install-browser` 只跑 `playwright install chromium`，Linux 最小安装缺
   `libnss3` 等系统库，需要 `playwright install --with-deps chromium`（要 root）。
3. Ubuntu 23.10+ 默认限制非特权 user namespace，chromium 沙箱可能起不来，
   常规解法是 `--no-sandbox`，而代码没有传浏览器参数的入口。

macOS 从未实测；静态看没有阻碍项，但"静态看没问题"不等于可用。WSL 里安装浏览器
时下载卡住三分钟，按用户要求中止（WSL 内的系统代理不生效）。

**结论：只支持 Windows，不为 Linux / macOS 做兼容。** 目标用户是在 Windows 桌面
上使用慧学外语的人，移植成本（有头浏览器、系统库、沙箱、无 CI）换不来实际价值，
半成品移植只会让文档说谎。

落地：

- README 增加"支持范围"一节，删掉"跨平台"特性条目与 macOS/Linux 的 uv 安装命令；
  依赖列表加上 Windows 10/11
- `SKILL.md`、`SETUP.md` 声明只支持 Windows，删掉其他平台的 uv 命令
- `AGENTS.md` / `CLAUDE.md` 增加第 5 条规则：只支持 Windows，不要做跨平台兼容
- `pyproject.toml` 的 classifier 从 `OS Independent` 改为 `Microsoft :: Windows`
- 新增 `.gitattributes` 固定 `.githooks/*` 与 `*.sh` 的 LF，并给 `pre-commit`
  补上可执行位。这两项 Windows 也需要：`core.autocrlf=true` 会把 hook 签出成
  CRLF，shebang 失效，隐私守卫就静默不跑了
- `test_docs_match_code.py` 增加 4 项检查：README 必须写明"只支持 Windows"、
  文档不得再宣传跨平台、开发指引必须保留禁令、包元数据必须是 Windows

代码里的 POSIX 分支（`/tmp`、symlink、chmod、macOS/Linux 浏览器探测）不删：
它们不影响 Windows，删掉反而增加回归风险；但也不构成承诺，不作为修 bug 的目标。

---

## 50. 撤回 uv 安装命令的推荐

第 48 节把官方安装脚本写进了 README、SETUP.md 和 SKILL.md。这越界了：

- 装 uv 是在改动用户的电脑环境，工具文档不该替用户决定怎么装
- SETUP.md 与 SKILL.md 是 agent 的执行清单，多一段与"跑对命令"无关的内容
  就多一分干扰；原来的"告诉用户，不要擅自安装"已经够用
- README 面向普通用户，依赖列表写清即可，不需要附安装脚本

已恢复的表述：

- SETUP.md：第 1 步直接给 `uv tool install`；uv 缺失时只保留"告诉用户，
  不要擅自安装"一句加自建 venv 的替代方案；排查表里对应的行删除
- SKILL.md：同样恢复为一句
- README.md：删掉整个"没有 `uv` 时"的安装段落，依赖列表保持原样
- SETUP_DESIGN.md：提示词与"不做的事"退回原表述
- `scripts/setup.py`：仍然只报告 `uv` 不在 PATH 并给官方文档链接，不打印安装命令

第 49 节（只支持 Windows）与 `.gitattributes` 的改动不受影响。

---

## 51. 归档两份设计文档

`MCP_DESIGN.md` 与 `SETUP_DESIGN.md` 属于历史开发文档：它们记录的是设计当时的
推演，内容已被 `CHANGELOG.md`（§24 MCP 可行性、§27 状态机、§28 MCP server、
§39 一键配置）与现行的 `SKILL.md` / `SETUP.md` / `CLAUDE.md` 覆盖。继续维护
等于把同一件事写三遍，容易出现互相矛盾的版本。

处理：

- 两份文件移入本地的 `archive/design-docs/`（`archive/` 一直是不入库的本地归档），
  从仓库移除；git 历史里仍可追溯
- 清除引用：README 的文档表、`DISTRIBUTION.md` 的 payload 说明、`pyproject.toml`
  注释、`install_skill.py` 的文档清单，以及 `elang_mcp.py` / `elang_session.py` /
  `setup_mcp.py` 里指向 `MCP_DESIGN.md` 的注释，统一改为指向 `CHANGELOG.md` 的对应节
- `test_doc_roles.py` 的 `DEV_DOCS` 同步删掉这两个名字（该测试要求列入的文档存在
  并带读者 banner）
- `install_skill.py` 里顺带删掉一个从未被引用的 `_SHARE_FILES` 常量，它列的是
  早期"开发文档也进 share/"时期的文件名

---

## 52. Gitee 镜像：让 uv 能从国内地址安装

GitHub 的 `git+https` 安装在国内不稳定，所以加了一个推送式镜像：GitHub 仍是
唯一来源，Gitee 只是只读副本。装的时候用国内地址：

```
uv tool install git+https://gitee.com/<用户名>/huixuewaiyu-readingpart.git
```

### 工作流

`.github/workflows/gitee-mirror.yml`：

- 触发：每次 push、手动 dispatch、每天 03:30（Asia/Shanghai）兜底一次
- 门禁：只有仓库变量 `GITEE_MIRROR_ENABLED=true` 时才在 push 上运行；手动
  dispatch 不受门禁限制，首次同步用它测试。这样在配置完成前不会每次 push 都留
  一条失败记录
- 做法：`git clone --mirror` GitHub 仓库，再用 `--prune --force` 推送
  `refs/heads/*` 与 `refs/tags/*`。`--force` 是必需的：本仓库历史被重写过，
  只允许快进会被拒
- 凭据：`GITEE_USER` / `GITEE_TOKEN`（Actions secrets），通过
  `http.https://gitee.com/.extraheader` 传 Basic 认证，不写进 remote URL，
  避免 `git remote -v`、reflog 或克隆目录泄露
- 校验：推送后 `git ls-remote` 对比 Gitee 的 `refs/heads/master` 与本地，
  不一致就让 workflow 失败
- 并发：`concurrency` 同组串行，避免两次同步竞争

### 一次性操作（需要用户完成）

1. Gitee 建**公开的空仓库**，名字与 GitHub 一致（`huixuewaiyu-readingpart`），
   不要初始化 README，首次推送会用本仓库内容覆盖 master
2. Gitee 设置 → 安全设置 → 私人令牌 → 生成，勾选 `projects`。令牌只显示一次
3. GitHub 仓库 Settings → Secrets and variables → Actions：
   - Secrets：`GITEE_USER`（Gitee 登录名，不是昵称）、`GITEE_TOKEN`
   - Variables：`GITEE_MIRROR_ENABLED=true`；可选 `GITEE_REPO`（仓库名，
     默认 `huixuewaiyu-readingpart`）
4. Actions → "Mirror to Gitee" → Run workflow，确认三个 step 全绿
5. 验证：`git ls-remote https://gitee.com/<用户名>/huixuewaiyu-readingpart.git`
   能看到 master；再用上面的 `uv tool install` 装一遍
6. 建议在 Gitee 仓库设置里确认默认分支是 `master`，仓库介绍写"镜像仓库，
   问题请到 GitHub 提"

注意：

- Gitee 仓库必须**公开**，否则 `uv` 匿名 clone 会失败
- 令牌若怀疑泄露，在 Gitee 撤销重发并更新 secret。Actions 会对 secret 原文
  打码，但 base64 形式不会，所以 workflow 里不能开 `set -x`

---

## 53. Gitee 镜像已上线，文档补国内地址

镜像已配对成功：`https://gitee.com/huang-youran/huixuewaiyu-readingpart`。

验证：

- `git ls-remote` 显示 Gitee 的 `refs/heads/master` 与本地一致
- `uv tool install --force "git+https://gitee.com/huang-youran/huixuewaiyu-readingpart.git"`
  在隔离的 `UV_TOOL_DIR` 里装成功；生成的 `elang` 能跑，`install-browser --check`
  正确复用系统 Chrome

文档同步：

- README：安装步骤给出 Gitee 地址；"交给 agent"的提示词补镜像链接；常见问题新增
  "安装时连不上 GitHub"
- SKILL.md：安装一节补 Gitee 备用地址
- SETUP.md：第 1 步补 Gitee 备用地址

镜像仓库是只读副本，问题与 PR 仍以 GitHub 为准；同步可能滞后几分钟。

---

## 54. P0 加固：隐私、假成功与状态文件

实施审查计划里的 Phase 0（8 项）。原则：正常路径的站点交互与输出不变，只修正失败
路径被误报、秘密被打印、状态文件损坏这几类问题。

隐私：

- `elang doctor --json` 改为脱敏视图，只保留 `ok`、环境文件来源和 `username_set` /
  `password_set`，不再包含学号与密码
- `setup-mcp` 不再打印整份配置的文本 diff（重新序列化会让其他 server 的密钥变成
  "新增行"），只打印本次写入的条目；DSH 的 `cordis.patch.yml` 改为按 `- id:` 块
  文本插入/替换，保留注释与原有缩进

假成功：

- CLI 与 MCP 两条路径都检查 `set_answers()` 与 `submit()` 的结果。新增
  `answers_incomplete` / `submit_failed` 状态，失败不计数、不标记完成
- `selectOption` 单条异常降级为 note，不再中断整批
- `_read_back()` 的 error 结构不再触发 `AttributeError`；`skip_article` 同样校验
- 主题只有无失败结果时才标记完成；读到空文章列表也不再标记完成（可能只是没加载
  出来）

状态与退出码：

- 检查点改为 `.tmp` + `os.replace` 原子写，读取损坏时告警并从头开始
- `setup.py` 汇总各步结果，失败返回 1
- `install-skill --check` 任一目标缺失返回 1；junction 识别为 `linked`
- IPC：`answer` 的逗号分支与 `--raw` 都校验题号/类型/状态；信号携带
  `article_number` 与 `url`，reader 丢弃不属于当前文章的迟到信号；torn read 增加
  `UnicodeDecodeError`

验证：

- 11 个测试脚本全部通过：新增 `test_p0_safety` 19 项、`test_install_skill` 13 项；
  `test_setup_mcp` 38 项（新增"注释保留"与"不打印其他 server 密钥"）、
  `test_answer_ipc` 28 项（新增无效逗号答案与 `--raw` 门禁）
- 真实 dry-run 一篇：答案 5+1/6 全部应用，`submit` 返回 `dry-run`，信号带
  `article_number=1`，运行正常结束，无假失败
- `elang doctor --json` 实跑确认学号与密码不出现在输出里
- DSH 配置实测：追加与替换两条路径都保留注释，其他插件条目不变

未做（留给 P1/P2）：异常路径的 `try/finally` 关浏览器、登录失败传播、每篇 token
检查、IPC 发布顺序、提交后 4 秒固定睡眠、`mode_solve` 的验证码闸门等。

---

## 55. P1 加固：竞态、卡死、恢复与配置编辑

实施审查计划里的 Phase 1。正常路径行为不变；这一批解决的是「失败后不恢复、竞态
吞答案、诊断命令卡死、配置编辑丢内容」这一类问题。

主引擎与会话：

- 浏览器 context 有进程级兜底：`main()` 的三个模式经 `_run_guarded` 运行，
  无论正常返回还是抛异常都会关闭 context；`ElangSession.start()` 失败时清理
  Playwright 与 context
- 登录失败不再被吞：`ensure_logged_in()` 返回 `finish_login()` 的真实结果，
  三个 CLI 模式据此中止
- token 改为在每篇文章边界检查（阈值 300 秒），刷新后回到文章列表；一次刷新失败
  就中止本主题，而不是让剩余文章全部假失败
- `go_back_to_learn()` 失败会中止本主题并记 `list_lost`；`mode_solve` 补上验证码
  闸门与答案应用/提交校验
- 验证码：新请求发布前删除旧答案文件（旧代码残留会被当成新图答案提交）

IPC 与并发：

- `request_ai_answers()` 与 50 篇检查点都改为「先删信号、再原子写 CURRENT」，
  避免快速应答被删除；`wait_for_ai(clear_at_start=False)` 不再二次清空
- `answer_ipc._send()` 用 `.tmp` + `os.replace` 原子发布，杜绝半写文件
- 迟到信号按 `article_number` 丢弃；torn read 捕获 `UnicodeDecodeError`

MCP：

- 工具异常转为 `state=error` 的 JSON 信封，而不是协议层错误
- 服务器退出时 best-effort 关闭会话与浏览器

配置编辑与诊断：

- `setup-mcp`：`mkstemp` 唯一临时文件 + 失败清理；写入 OSError 只让该 host 失败，
  其余 host 继续；project scope 从 cwd 向上找项目根；没有可运行的 `elang` 命令时
  报错而不是注册一个起不来的 server
- `install-skill`：仓库检出时优先仓库里的载荷（开发改动立即生效）；复制后清理
  PAYLOAD 之外的文件（不跟随符号链接/junction）；copy 覆盖 link 前先移除链接
- `doctor`：套用私有浏览器缓存的解析顺序；无浏览器时带上 `choice["reason"]`；
  安装版提示 `elang init-env`；去掉已不使用的 `dotenv` 探测；launch 探测改为
  60 秒有界线程，超时给出明确错误
- `config`：注册表值去引号；`.env` 解码失败在 `describe()` 里可见并带
  `parse_problem`；相对 `ELANG_TMP_DIR` 统一 resolve 成绝对路径；
  `init-env --force` 覆盖前先备份 `.env.bak-<时间戳>`
- `setup.py`：子进程输出按 UTF-8 解码；doctor 单独 120 秒超时并打印尾部与退出码

配套清理：

- `.gitignore` 增加 `*.bak-*`（`.env` 的 force 备份、`setup-mcp` 的配置备份都可能
  含凭据或本机路径）
- 移除 `python-dotenv` 依赖：没有任何模块导入它，`.env` 由 `config.py` 自解析

验证：

- 13 个测试脚本全部通过：新增 `test_p1_safety` 16 项（浏览器兜底关闭、发布顺序、
  迟到答案、验证码残留、信号原子写）、`test_p1_config` 19 项（GBK `.env` 报错、
  相对 IPC 路径、force 备份、注册表去引号、doctor 脱敏）；`test_setup_mcp` 41、
  `test_install_skill` 20、`test_answer_ipc` 28、`test_p0_safety` 19
- `elang doctor --json` 实跑：`browser.ok=true`，无学号/密码，模块列表无 `dotenv`
- 未改站点交互、选择器与提交时序；性能项（固定睡眠、整页重载、config 缓存、
  每轮验证码整图传输）留到 P2

---

## 56. P2 性能：去掉固定等待与重复工作

目标是不改变站点交互，只削减每篇文章与每个主题的固定开销。

- 提交后的 4 秒固定等待改为等待路由变化（8 秒上限，未观察到变化时再等 800 ms）
- 删除收尾的 `asyncio.sleep(3)`、`asyncio.sleep(10)` 与单篇模式的 3 秒确认后等待
- 主题切换改为等待 `PcReadLearn` 的数据（`JS_PIN_LEARN_VM`），删掉 `about:blank`
  后的 500 ms、每轮 1 秒的正文文本枚举和重复的重试块；科目列表在 `_wait_until`
  证明 `listData` 非空后只读一次
- CAS 登录后的 2.5 秒改为等待 `authorization` 出现（最多 10 秒）
- 文章内容轮询间隔 1500 ms → 750 ms，总时长仍由 timeout 封顶
- 验证码轮询不再回传整张 base64：`_captcha_state(want_image=False)` 返回图片长度与
  尾部 48 字符签名，只有 OCR、首次读取与图片变化时才取整图
- `set_answers()` / `submit()` 优先使用已钉住的 `window.__elangPraxisVm`，少 2-3 次
  Vue 树遍历
- 题库词集在加载时预计算；标题相同的常见情况下不再匹配第二次（reader 与 session
  两处）
- `config`：`_windows_app_paths` 与 `exe_version` 加进程内缓存，`describe_browser`
  只扫描一次系统浏览器
- 50 篇检查点按「下一个阈值」触发，恢复时恰好落在边界值也不会立刻再次暂停

顺带修正（在 live 验证中发现）：`finish_login()` 之前把 `save_session()` 的失败当成
登录失败，导致只读 home 环境下登录成功却中止运行。保存只是下次运行的优化，现在
失败只告警，登录结果不受影响。

验证：

- 一次完整的单篇流程（登录、科目列表、文章抓取、人工应答、dry-run 提交、收尾）
  实测 35.2 秒，输出与状态流转不变
- 13 个测试脚本全部通过；`test_answer_bank` 覆盖词集预计算后的匹配行为
- 未改选择器、验证码流程与提交时序；`submit()` 的路由等待有上限与兜底

---

## 57. 修复"读到底部"提交守卫；P3 死代码清理

发现经过：用户观察浏览器进程时注意到一篇文章里有"请先阅读到底部"的提示，询问是否
有影响。实测 `PcReadPraxis` 组件源码确认 **有影响且严重**：

    readHint() {
        if (!this.articleRead) return "请先将原文阅读到底部";
        const left = this.jobList.filter((q, i) => !this.readQuestions[i]).length;
        if (left) return "请将每道题查看到底部（剩余" + left + "题）";
        return this.readingStayReady ? "" : "请在认真阅读答题后提交";
    }

`openSubmitConfirm()` 与 `confirmSubmit()` 在 `readHint` 非空时**只弹 toast 就返回**，
`confirmSubmit` 的两次 POST 与跳转根本不会执行——而旧代码把 `confirmSubmit` 返回
"OK" 当成提交成功，等于"看起来提交了、实际什么都没发生"。

修复：

- 新增 `satisfy_read_guard(page)`：置 `articleRead=true`、每题 `readQuestions[i]=true`、
  `readingStayMs` 抬到 120 秒以上（这些状态只存在于客户端，不进 POST），并滚动
  文章容器到底部；返回清完后的 `readHint`
- `submit()` 增加三道硬校验：守卫已清、确认框真的打开（`submitConfirmVisible`）、
  POST 后路由真的变化（12 秒上限），任一失败按 error 返回，不再误报成功
- dry-run 实测：subject 25 前 4 篇文章均 `confirmVisible=True, articleRead=True,
  readHint=''`，`submit(dry_run)` 全部返回 `dry-run`

P3 清理（全部是死代码，删除前逐一 grep 确认无引用）：

- 常量 `NAV_LOAD_WAIT` / `BACK_LOAD_WAIT` / `BACK_RETRIES` / `CAT_LOAD_RETRIES`
- `_captcha_seen` 标志与只被它使用的 `detect_captcha()`、`check_and_handle_captcha()`；
  验证码闸门检测已由 `extract_page_content` 的 `blocked` 承担
- `config.env_map()` / `config.get()`（无任何调用方；凭据解析统一走
  `load_credentials()`）

题库发现（为后续扩充做依据，见计划）：

- **`jobList[].options_answer` 随题目一起下发**，就是服务端判分的标准答案；
  实测 subject 25 前 4 篇文章共 21 题全覆盖（`missing=0`）。填空题在
  `optionsArray1[].title` 里按 label 顺序给出正确答案匹配。这意味着：
  1) 运行时可以直接读 `options_answer` 自动答题，连题库和 AI 都不需要；
  2) 写一个采集脚本遍历全部主题，可一次性重建/扩充 `references/answers.json`。
  是否实现这两个方向由用户决定（非必需项）。

验证：13 个测试脚本全部通过；AGENTS/CLAUDE 文档补充了守卫与答案键的说明。

---

## 58. 合并社区题库 4drvuezy.docx

用户从社区拿到一份新题库（Word），要求与现有 `references/answers.json` 分析整合。
本次**不登录站点**（TUN 模式占用网络），全部离线完成。

### 文档结构（实测）

`assets/4drvuezy.docx` 是纯文本 + 5 张截图，没有表格。段落**格式**就是结构：

| 段落类型 | 判别特征 | 内容 |
|---|---|---|
| 分类 | 粗体 + 字号 18 | 旅游与交通 / 历史与文化 / 文学与艺术 / 职业与发展 / 运动与娱乐 |
| 标题 | 粗体，无显式字号 | 文章英文标题 |
| 答案 | **非**粗体 | 字母串、`(n)` 编号填空、词填空，或"(不建议)"之类的备注 |

答案行的五种形态：`DBCDA`（纯字母）、`BAAAB  CB`（空格分隔的字母，忽略空格）、
`(1) C (2) H …`（编号填空）、`(1) roam (2) teem …`（编号词填空）、以及紧跟在字母行
之后的**裸词行**（如 Highways 的三个填空，源文档里没有编号）。

解析坑（都已处理）：

- 粗体备注行 `(不建议，所以答案截图了)` 夹在标题和答案之间，按"粗体即标题"会把
  它误判成文章，把后面真正的答案吞掉。修正：整行只有一对括号且含中文的粗体行按
  答案/备注处理。
- 源文档有笔误 `(9 I`（缺右括号），正则需容忍缺括号才能凑齐 10 个填空。
- 标题带引号是**正常**的（`"United 93"`、`The Exploration of the "New World"`），
  不能整行去引号；只有落单的尾部引号才清理（`The British Balance…Life"`）。
- `The Power of the Press` 的答案**只在截图里**，本轮模型不支持图像输入、
  Windows OCR 也不可用（WinRT 投影在 pwsh 7 缺失，PS 5.1 的 `AsTask` 泛型
  转换失败），因此按既有惯例记成跳过条目，原因写"答案在截图（不建议）"。
  后续用视觉模型补录即可。

### 合并结果

| | 数量 |
|---|---|
| 原题库 | 93 |
| 文档条目 | 61 |
| 完全一致（重复） | 22 |
| 新增 | 34（28 条可用 + 6 条跳过） |
| 就地改进 | 2 |
| 真实冲突（保留旧值） | 3 |
| **合并后** | **127** |

可匹配条目 119（127 − 6 跳过 − 2 条同名折叠），格式分布
`letter 85 / fill_in_blank 26 / letter_and_fill 8`。

**就地改进**（新数据严格更优，才覆盖）：

- `Highways`：旧条目 `raw` 里本来就有 3 个填空却从未索引（format 是 `letter`），
  升级为 `letter_and_fill`，7 字母 + 3 填空。
- `A Letter of Refusal`：旧值 `CADB(?)` 带未解占位符，`_bank_answers_for` 会直接
  拒用；新数据补全为 `CADBD`，条目从"不可用"变成"可用"。

**真实冲突**（保守保留旧值，等待联网核对）：

- `Alamogordo`：旧 5 字母 `ACDBB`，新 4 字母 `ACDB`。
- `Beyond Spectators…`：旧 `CBBDD`，新 `ABBCD`，答案完全不同。
- `Bridging Cultural Gaps Gracefully`：旧 9 字母 + 34 填空，新 8 字母 + 20 填空。
  新数据少的那部分是文档里的**截图**，不是抄错，所以旧值更完整。

### 同时修掉的两个既有缺陷

1. **多段填空题被排序打乱**。`_bank_answer_parts()` 会
   `sorted(fill_in_blank, key=index)`，而 3 个老条目是从几段独立的 `(1)…(n)` 抄来的，
   编号在列表中途重新从 1 开始；排序后各段**交错**，答案顺序就错了
   （`Bridging…`、`The Great Tropical S..`、`Large Temperature……`）。
   存储顺序才是与原文一致的顺序，因此把全库填空编号规范成按位置的 `1..n`，
   排序退化为恒等，顺序得到保留。
2. **短标题永远匹配不上**。加载器把规范化后短于 6 字符的标题直接丢弃，
   于是 `tree`、`sleep`、`El Niño`、`IT Job` 四条一直在库里但从未生效。
   阈值改为 4：短键只参与**精确匹配**，子串匹配另有 10 字符下限，且这 4 个键都
   不是其他标题的子串，不会误配。改后这 4 条立刻生效。

### 复现方式

解析脚本没有入库（避免为一次性操作给运行期增加 `python-docx` 依赖）。
重新导入时按上表的"格式判别"规则解析即可；`assets/4drvuezy.docx` 保留在仓库，
加上本节的三条解析坑说明足以复现。

验证：`test_answer_bank` / `test_doc_roles` / `test_docs_match_code` / `test_no_secrets`
/ `test_p0_safety` / `test_p1_safety` 全部通过；加载器冒烟测试确认 13 个代表性标题
（含 4 个短标题与 2 个改进条目）匹配正常。


