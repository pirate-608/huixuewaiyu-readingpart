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
  **有图且 `jobList` 为空**
- 错误答案会让服务端刷新图片；若图片未变，重试同一猜测无意义
- **绝不要主动调 `refreshCaptcha()`**——会在正常页面上制造一个验证码

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
- **同一页面两处读到不同的题目状态**：因为把 Vue 实例传进了 `evaluate`。
  必须读钉住的全局变量。
- **题目数量与题库记录不一致**：题量会变，题库只是参考；以页面为准。

---

## 9. 未验证 / 需谨慎

- 多选（`type_id 4`）与自由文本（`3/6`）的答案键编码**未实测**，引擎不解析它们，
  一律回退题库/AI。
- 写操作接口的**响应体结构**只从前端代码推断（`code === 100` 视为成功），
  没有逐个抓包确认。
- 站点改版后本文可能过期。判据：`/en/job/gets` 返回的 `jobList` 里还有没有
  `options_answer`；没有就说明第 7 节失效，退回题库/AI。
- 更新时间见 `CHANGELOG.md` 中"API 推断文档"相关条目；本文随代码一起维护，
  修改接口相关逻辑时请同步更新对应小节。