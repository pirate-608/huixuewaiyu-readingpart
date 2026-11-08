# 慧学外语站点 API 与内部结构推断

> **读者：执行 agent / 排查故障的人。** 本文是 `elang` 驱动站点时的"地图"：
> 哪一步调了哪个接口、页面里有哪些状态会挡住流程、报错该往哪里看。
> 内容来自**实测抓包**与**前端 bundle 静态读取**，未经验证的会明确标注。

用途只有两个：

1. **出错时定位**：日志里某一行停住了，照着第 8 节查它是哪一步、为什么停。
2. **改代码前确认**：不要凭 DOM 猜测，先看这里的状态字段与接口契约。

本文**不包含**任何账号、令牌或 Cookie，路径中也不含个人标识。

---

## 1. 基本事实

| 项 | 值 |
|---|---|
| 站点 | `https://elang.zju.edu.cn`（前端是 Vue 2 SPA，hash 路由） |
| 登录 | 统一身份认证 `zjuam.zju.edu.cn`，CAS 回跳后前端再换 token |
| API 前缀 | `/en`（例：`https://elang.zju.edu.cn/en/job/gets`） |
| 鉴权 | 请求头带前端 token；token 寿命约 2 小时，存 `localStorage.authorization` |
| 请求特征 | 每个请求额外带 `checkParams` / `checkSign`（前端算的签名，无法手工重放） |

**签名这一点很关键**：接口不能绕过前端直接 curl。这也正是本项目用 Playwright
驱动真实页面的原因——必须让页面自己发请求。

---

## 2. 前端路由与组件

| 路由 | 组件 | 主要数据 |
|---|---|---|
| `#/pc/read/index` | `PcReadIndex` | `$data.listData`（主题列表） |
| `#/pc/read/learn?subject_id=<id>` | `PcReadLearn` | `$data.resourceList`（文章列表） |
| `#/pc/read/praxis?log_id=&resources_id=` | `PcReadPraxis` | `$data.jobList`（题目） |

组件实例被钉在页面全局变量上，供所有读取复用：

- `window.__elangIndexVm` / `window.__elangLearnVm` / `window.__elangPraxisVm`

**为什么必须钉住**：Vue 实例是巨大的循环对象，`page.evaluate` 传不进去（传进去
就是空值，所有字段读成 0）。所有读取都必须在浏览器内部完成。

---

## 3. 接口一览（实测）

### 3.1 浏览链路（抓包确认，均为 200）

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/en/login/auth` | CAS 回跳后换取登录态 |
| GET | `/en/user/getUserRowByToken` | 当前用户信息（`sid` 等） |
| GET | `/en/subject/gets` | 阅读主题列表 → `PcReadIndex.listData` |
| GET | `/en/resources/gets` | 某主题下的文章列表 → `PcReadLearn.resourceList` |
| POST | `/en/resources/saveUserStudyResource` | **`toPraxis`**：服务端签发 `log_id` |
| GET | `/en/job/gets` | 题目列表 → `PcReadPraxis.jobList`（含答案键，见第 7 节） |
| GET | `/en/jobAnswer/getHistoryList` | 历史作答记录 |
| POST | `/en/yzm/saveAccessLog` | 记录访问（打开文章时自动发） |
| GET | `/en/user_task/submit` | 任务状态心跳 |
| GET | `/en/user/getUserStudy` | 学习统计（首页挂件） |
| GET | `/en/plan/get` | 学习计划（首页挂件） |
| POST | `/en/user_sign/save` / `getDateList` | 签到（首页挂件） |
| GET | `/en/resources/getNewUserResource` 等 | 首页推荐位 |

### 3.2 写操作（从前端 bundle 静态确认，未抓包）

前端把接口封装成极短函数名，对应关系如下（bundle 内实际代码）：

| 函数 | 方法 | 路径 | 作用 |
|---|---|---|---|
| `sa` | POST | `/en/jobAnswer/save` | **提交答案**（`data = {params: JSON.stringify(buildSubmitData())}`） |
| `ia` | POST | `/en/resources/updateUserStudy` | **标记该文章已学完**（`data = {id: logId}`） |
| `ua` | POST | `/en/yzm/createCaptcha` | 刷新验证码图 |
| `ha` | POST | `/en/yzm/checkCaptcha` | 校验验证码 |
| `da` | POST | `/en/yzm/saveAccessLog` | 访问日志 |

> 另有一套 `/captcha/get`、`/captcha/check`，属于其它模块的验证码，阅读练习不走它。

**提交是两次 POST**：先 `jobAnswer/save` 存答案，再 `resources/updateUserStudy`
标记完成，两次都返回 `code === 100` 才算成功，随后前端跳到详情页。

---

## 4. 提交载荷（`buildSubmitData`）

提交内容由页面自己组装，引擎不手工拼。字段语义：

| `type_id` | 题型 | 每题的 `answer` | 正确性判定 |
|---|---|---|---|
| 1 | 单选 | 选中项 `label`（`"B"`） | `options_answer === label` |
| 4 | 多选 | 选中项 `label` 用逗号拼接（`"A,C"`） | `options_answer === 拼接串` |
| 2 | 文本填空 | 每空一条记录，`answer` 为该空输入值 | `isFillRight(输入, optionsArray[n].title)` |
| 5 / 7 / 8 | 选词填空 | 每空一条记录，`answer` 为 `insertWordAnswers[id][n]` | 取 `answer.split("-")[0]` 与 `optionsArray1[n].title` 比较 |
| 3 / 6 | 自由文本 | `user_answer` | 恒为 0（不计对错） |

每条记录的字段：`{user_id, job_id, type_id, lable|answer, is_right, resource_id}`。

注意两点：

- 单选/多选字段名是 `lable`（**拼写如此**），不是 `label`。
- `jobList` 为空时，前端会提交一条 `{job_id: 0, type_id: 999, is_right: 1}` 的占位记录。

---

## 5. 提交前的三道关卡

按顺序，任一不满足就不会真的 POST：

### 5.1 读到底部守卫（`readHint`，最容易踩）

```js
readHint() {
    if (!this.articleRead)                return "请先将原文阅读到底部";
    const left = 未查看的题数;
    if (left)                             return "请将每道题查看到底部（剩余N题）";
    return this.readingStayReady ? "" : "请在认真阅读答题后提交";
}
readingStayReady() { return this.readingStayMs > 120000 }   // 停留 2 分钟
```

`readHint` 非空时，`openSubmitConfirm()` 与 `confirmSubmit()` **只弹一个 toast
就 return**，两次 POST 根本不会发生。

引擎的处理：`satisfy_read_guard()` 把 `articleRead`、每题 `readQuestions[i]`、
`readingStayMs` 置到位并滚动到底部。**这些都是纯客户端状态，不进 POST 载荷**，
服务端看不到。

### 5.2 确认框真的打开

`submitConfirmVisible` 必须变为 `true`。若仍为 `false`，说明守卫没清干净。

### 5.3 提交后路由真的变化

`confirmSubmit` 成功后跳 `PcPracticeDetailRead`。引擎等 hash 变化（12 秒上限），
**没变化就判失败**——否则会出现"看起来提交了、其实没提交"。

---

## 6. 验证码

- 图在 `PcReadPraxis.$data.imageBase64`（data URI），不是 DOM `<img>`
- 页面**没有 `<input>`**：校验走 `$data.verifyCode` + `checkCaptchaCode()`
- 题目只有通过验证码后 `jobList` 才会有内容，所以"闸门"的判据是
  **有图且 `jobList` 为空**（且 DOM 里没有题目块）
- 错误答案会让服务端刷新图片；若图片未变，重试同一猜测无意义
- **绝不要主动调 `refreshCaptcha()`**——会在正常页面上制造一个验证码

### 实测（2026-11）：闸门与提交的真实行为

用一个一次性 profile 主动触发验证码跑通了整条链路，观察到：

| 阶段 | 实测结果 |
|---|---|
| 触发 | `refreshCaptcha()` 后 `imageBase64` 从 0 → 约 7.5 KB，但 `jobs` 仍为 6，**不构成闸门** |
| 闸门判据 | 把 `jobList` 清空后 `gated=True`，说明判据确实是"有图 + 无题" |
| 交接 | `elang_captcha_request.json`（约 400 B）与 `elang_captcha_image.png`（约 5.9 KB）都正常写出 |
| 提交 | 写错的码会被读到并发送；服务端返回**图片变大**（7570→7786 B）、`jobs` 仍为 0，即被拒绝 |
| 重试 | 引擎识别到"图换了"→ 重新写请求、允许再试一次；图没换则停止重试 |
| 超时 | 等满上限后干净返回 `False`，答案文件被删除 |

**补测（同一篇 `BBC Experience`，装了 ddddocr）**：正确码确实清闸——

```
blocked=True → OCR attempt 1/3: '9153' → jobs 0->3 → [OK] CAPTCHA solved by OCR
```

四次独立运行分别解出 `4174`/`0993`/`0126`/`9153`，均一次命中。样本小，
只能说这几张图都读对了，不能据此给识别率。

### 答案键在 `type_id 2` 上的位置（与 5/7/8 不同）

`type_id 2`（文本填空）**没有 `options_answer`**。它的标准答案在
`optionsArray[n].title`，逐空一个——因为 `confirmSubmit` 就是用
`isFillRight(输入, optionsArray[n].title)` 判分的，而 `isFillRight` 是归一化后的
纯比较。`&` 表示多个可接受写法（`transportation&transport`），提交第一个即可。

这也是曾经"某篇文章答案键未覆盖"的原因：缺了这条规则时整篇会降级到题库/AI。

**结论**：整条链路**已完整验证**——错的码会被正确判失败并换图（不会死循环），
对的码能清闸并加载题目，之后答案键、读守卫、提交确认全部走通。
**仍未量化**的是 ddddocr 在更噪声图片上的识别率（当前 4 次样本全部一次命中，
样本太小不足以给结论）。

### 触发时机（未验证）

用户观察是"一天做了十篇左右开始要验证码"。这个阈值**没有实测**，
不要当成确定规则写进逻辑；引擎的做法是被动响应——每篇进入时探测闸门，
不预测何时触发。频繁输错会招来更多验证码，所以失败时应当交接而不是硬试。

---

## 7. 页面自带的答案键（当前主作答来源）

`jobList[i].options_answer` 就是服务端判分用的标准值，随题目一起下发。

| `type_id` | 编码 | 例 |
|---|---|---|
| 1 | 裸选项字母 | `"B"` |
| 5 / 7 / 8 | JSON 数组 `[{title,label,score}]`，`label` 是空号、`title` 是该空的值 | `[{"title":"D","label":1},…]` |

`optionsArray1` 是同一份数据的镜像（`[{label,title}]`），可作为交叉校验或兜底。

引擎的作答来源优先级：

| 优先级 | 来源 | 命中条件 |
|---|---|---|
| 1 | 页面答案键 | 每道题都解析出 key |
| 2 | 本地题库 `references/answers.json` | 标题匹配且题目形态吻合 |
| 3 | agent / AI 作答 | 前两级都没击中 |

**部分命中一律整篇降级**，不混用"一半来自 key、一半来自猜测"的答案。

---

## 8. 出错时看哪里

### 8.1 本地文件（`<ipc>` = `$ELANG_TMP_DIR`，否则 `C:/tmp`）

| 文件 | 含义 |
|---|---|
| `elang_current.json` | 当前待答文章（题目、正文、`article_number`） |
| `elang_signal.json` | 作答方写回：`answers_ready` / `skip` / `continue` / `stop` |
| `elang_checkpoint.json` | 断点：已完成主题与累计篇数 |
| `elang_captcha_request.json` / `elang_captcha_image.png` / `elang_captcha.json` | 验证码交接 |
| `elang_screenshots/` | 失败时的页面截图 |

会话文件在 `~/.elang/elang_session.json`（Cookie + localStorage 快照）。

### 8.2 日志关键字 → 排查方向

| 日志 | 含义 | 排查 |
|---|---|---|
| `[KEY] the page shipped all N answer(s)` | 答案键命中，正常 | — |
| `[KEY] not used: …` | 答案键缺失或编码不识别 | 看后半句原因；会回退题库/AI |
| `[BANK] matched …` | 题库命中 | — |
| `[BANK] matched … but …` | 题库命中但题目数量/形态不符 | 题库过期，照常作答即可 |
| `[ANSWER NEEDED]` | 前两级都没命中，等人作答 | 用 `elang pending` / `elang answer` |
| `captcha probe: … gated=True` | 验证码拦住了题目 | 等 OCR 或人工给码 |
| `submit dialog did not open (readHint=…)` | 守卫未清除 | 检查 `articleRead` / `readQuestions` / `readingStayMs` |
| `submit did not navigate after confirmSubmit` | POST 被拒或网络失败 | 看是否 `code !== 100`；答案可能被判错 |
| `captcha state read failed` | Vue 实例未钉住 | 页面未渲染完或路由不对 |
| `[elang] ignoring a signal for article N` | 收到其它文章的迟到答案 | 正常保护，等当前文章 |
| `no questions and no captcha image (empty jobList)` | 题目没加载 | 可能是验证码未过，或文章本身无题 |

### 8.3 常见误判

- **"提交成功"但网站没记录**：旧版本把 `confirmSubmit` 返回 `"OK"` 当成功，
  实际守卫拦住了。现在会校验确认框与路由，失败会明确报错。
- **`code: 100` 等于答对了**：**不等**。它只表示接口接受了这次提交。
  答对没答对要看 8.4 的详情页。
- **同一页面两处读到不同的题目状态**：因为把 Vue 实例传进了 `evaluate`。
  必须读钉住的全局变量。
- **题目数量与题库记录不一致**：题量会变，题库只是参考；以页面为准。

### 8.4 判分核对：详情页（验证答案正确性的标准手段）

提交成功后路由会跳到：

```
#/pc/read/detail?resource_id=<resources_id>
```

组件是 `PcPracticeDetail`，直接给出判分结果，**这是判断"答案对不对"的唯一可靠证据**。
两次写接口返回 `code: 100` 只说明服务端收下了，不代表得分。

页面文本里能直接读到：

```
当前位置：首页>今日任务>答题结果
16/16
共16题，答对16题
正确率：100.00%
题1
正确答案：(1) H  (2) C  (3) J  (4) B  (5) G  (6) E
题2
正确答案：(1) A  (2) B  (3) B  (4) C  (5) A  (6) B
题3
正确答案：(1) a few exhibits  (2) multiscreen video diary
          (3) interactive room  (4) sports
```

组件数据（同样钉住后读取即可）：

| 字段 | 含义 |
|---|---|
| `jobList` | 逐题结果，含每题**正确答案**文本 |
| `flatAnswers` | 扁平化的逐空答案数组（上例 16 个空） |
| `resourcesId` | 文章 id |
| `loading` | 结果是否已加载 |

**用途**：

- 验证答案键/题库是否真的正确（不是只验证"提交被接受"）
- 文章被判错时，直接对照"正确答案"定位是哪一空理解错了
- 想批量核对题库时，逐篇提交后读这个页面即可，不需要猜

实测（2026-11）：`BBC Experience` 用页面下发的答案键作答（含一道 `type_id 2`），
提交后详情页显示 **共 16 题答对 16 题、正确率 100%**，
由此确认 `type_id 2` 的答案确实在 `optionsArray[n].title`（第 6 节）。

---

### 8.5 浏览器控制台脚本（人工应急）

`tools/browser/elang-console.js` 用于人已经在题目页、不想走 IPC 往返的场景。
粘进 DevTools 控制台后使用：

| 调用 | 作用 |
|---|---|
| `elang.status()` | 本题型、答案键可用性、读守卫状态 |
| `elang.extract()` | 只列出答案，不改页面 |
| `elang.answer()` | 应用答案并清除读守卫 |
| `elang.submit()` | 应用后打开确认框（不提交） |
| `elang.submit(true)` | 真正提交 |

它与引擎共用同一套解码规则（`options_answer` / `optionsArray[n].title` /
`optionsArray1` 镜像），本题多选走 `selectOption` 的切换语义，与
`set_answers()` 一致。有题目拿不到答案键时它会拒绝提交并列出是哪几题。

## 9. 未验证 / 需谨慎

- 多选（`type_id 4`）的答案键编码已实测：`options_answer` 是选中项 `label` 用逗号
  拼接的字符串（`"A,C"`），与 `buildSubmitData` 拼出的判分串一致。引擎解析它，
  并用应用自己的 `selectOption()` 逐项勾选。
- 自由文本（`type_id 3/6`）在阅读题中**未出现过**（38 篇 / 204 题的采样里 0 例），
  引擎不解析，如遇到会回退题库/AI。
- `type_id 2` 的答案键来自 `optionsArray[n].title`，已通过一次真实提交验证
  （详情页 16/16，正确率 100%，见 8.4）。但样本只有一篇，`&` 分隔多写法
  （`transportation&transport`）取首项这条**未在真实判分里验证过**。
- 写操作接口的**响应体结构**只确认到 `code: 100` 这一层；`data` 字段的具体含义
  没有逐一考证（实测其值为 `"1"`，是否代表得分未知）。
- 站点改版后本文可能过期。判据：`/en/job/gets` 返回的 `jobList` 里还有没有
  `options_answer`；没有就说明第 7 节失效，退回题库/AI。另可按 8.4 提交一篇，
  用详情页正确率反向确认本文是否仍然成立。
- 本文随代码一起维护：修改接口相关逻辑时请同步更新对应小节。