# 统一消息中心 — 前端交付说明

> 赛题 1/A「多平台连接器与统一消息管理」· 成员 B（前端/演示）交付物
> 技术栈：原生 HTML + CSS + JavaScript，**双击 `index.html` 即可运行**，无需安装 Node / 构建工具。

---

## 一、怎么跑起来

1. 解压后双击 `unified-msg-ui/index.html`（Chrome / Edge 均可）。
2. 进登录页 → 点登录卡底部 **「一键演示登录」**，或输入账号 `gary` / 密码 `demo123`。
3. 进入后默认处于**演示模式**（侧栏统计卡下方有「演示模式 · 模拟数据」标签），每 15 秒自动来一条新消息，可直接演示完整闭环。

> 后端接好后只需改 `js/config.js` 里的两个地址，界面右上角标签会从「演示模式」变成「已连接后端」，其余代码不用动。

---

## 二、已完成的功能

### 1. 登录与账号

| 功能 | 说明 |
|------|------|
| 账号密码登录 | 演示账号 `gary` / `demo123`（也接受 `gary@xingchen-tech.com`、工号 `XC-1024`） |
| 一键演示登录 | 答辩时免输入，直接进入 |
| 企业微信扫码登录 | 演示版：点击后 2 秒模拟扫码成功 |
| 记住登录状态 | 勾选后下次打开跳过登录页；**默认不勾**，方便每次演示登录流程 |
| 退出登录 | 个人资料页 → 退出登录，回到登录页并带回上次账号 |
| 登录校验 | 空账号 / 空密码 / 密码错误分别提示，输入框标红；密码错误不放行 |

### 2. 统一入口（主界面）

三栏布局：左侧筛选与统计 → 中间会话列表 → 右侧会话面板。

- **消息列表**：微信 / 钉钉集中展示，按「置顶 → 今天 / 昨天 / 更早」分组，行内显示头像、发送人、状态徽章、时间、内容预览
- **双维筛选**：平台 + 状态是**「且」**关系；标签数字随对方条件交叉变化，筛选生效时 Tab 数字变筛选后条数并出现面包屑（`钉钉 且 已回复 · 2 / 9 条 · 清除`）
- **全局搜索**：按发送人 / 内容实时过滤
- **会话面板**：微信式气泡对话，带历史上下文；发送后气泡显示实际通道（API / RPA）
- **回复能力**：快捷回复模板、48 个表情、Enter 发送 / Shift+Enter 换行、格式转换提示（可展开看两栏 JSON）
- **消息管理**：置顶、免打扰（免打扰未读不计入未读提醒，侧栏有单独说明）、全部标为已读
- **待办页**：待办类消息自动入列，打钩完成后状态回流原平台
- **工作台概览**：未选会话时展示今日概览、待办预览、业务闭环四步、RPA 采集任务状态

### 3. 业务闭环（赛题核心）

```
平台消息 → 连接器归一化 → 统一入口展示 → 回复（格式转换）→ 通道发送 → 状态回流
```

状态机：`received`（已接收）→ `processing`（处理中）→ `sending`（发送中）→ `replied`（已回复）→ `synced`（已同步到平台），失败为 `failed`（发送失败）。

每一次流转都写入状态流转记录，会话头部的时间线按钮可查看完整时间线（接收来源、经哪条通道发送、回执时间）。

### 4. 双通道（API + RPA）

每个平台一条主通道 + 一条备用通道，在「应用连接」页可实时切换：

| 平台 | 默认主通道 | 备用 | 理由 |
|------|-----------|------|------|
| 微信 | RPA | API | 个人号无开放接口，只能界面自动化 |
| 钉钉 | API | RPA | 企业内部应用 + 机器人回调成熟 |

- 发送走主通道，失败可**重试**或**切换备用通道重发**，气泡上的通道标签会跟着变
- 会话工具栏有**故障演练**按钮（⚠️）：开启后下一次发送必定失败（给出真实失败原因），用于现场演示失败重试
- 平台被断开时，该平台的历史消息仍可查看，但发送会直接失败并引导去重新连接

### 5. 应用连接管理

- 三张平台卡片：接入账号、组织、主 / 备通道、上次同步、近 7 日成功率
- 操作：**测试连接**（返回模拟延迟）、**切换主备**、**连接 / 断开**（连接有 0.8 秒握手过程）
- 断开后全局联动：顶栏计数 `3/3 → 2/3` 变红、侧栏「接入平台」变「2/3 1 个未连接」、左侧平台标签变虚线灰
- 「添加应用」说明新平台只需实现「接收 / 发送 / 健康检查」三个方法即可复用统一入口

### 6. 个人资料

- 身份卡：头像、中英文名、角色、部门、工号 / 城市 / 时区，右侧三个实时数字（已接入平台 / 未读 / 已回复）
- **基本信息可编辑**：「修改」→ 改姓名、英文名、企业邮箱、手机、所在地 → 保存（邮箱格式校验，保存后顶栏头像与姓名同步，最近操作留痕）
- 消息偏好：桌面通知、免打扰时段、默认发送通道（API 优先 / RPA 优先）
- 账号与安全：登录方式、二次验证、最近登录时间 / 设备 / IP
- 我的接入平台：三个平台状态，可跳转连接管理页
- 最近操作：操作日志时间线

---

## 三、文件结构

```
unified-msg-ui/
├── index.html                  页面结构（登录层 / 顶栏 / 三栏主区 / 视图层 / 弹窗）
├── README.md                   本文件
├── css/
│   ├── base.css                设计变量、配色规则、头像、分布条
│   ├── layout.css              顶栏、侧栏、列表区骨架 + 共享组件（chip / 统计卡 / 顶部胶囊）
│   ├── components.css          会话行、状态徽章、待办、弹窗、toast
│   ├── chat.css                会话面板（气泡、输入区、工具栏、格式转换详情）
│   ├── views.css               全屏视图层（个人资料 / 应用连接）
│   └── login.css               登录页
└── js/
    ├── config.js               ★ 全局配置与接口约定（平台、状态、通道、地址）
    ├── data/
    │   └── mock-data.js        模拟数据（消息 / 会话上下文 / 待办 / 用户 / 应用 / RPA）
    ├── core/
    │   ├── format-adapter.js   格式转换（内部统一格式 ↔ 各平台格式）
    │   ├── store.js            全局状态与纯数据操作（不做 DOM）
    │   └── api.js              ★ 后端通信层（WebSocket + 发送回复 + 演示模式）
    ├── ui/
    │   ├── render.js           列表 / 筛选 / 待办 / 统计 / 状态流转弹窗
    │   ├── chat.js             会话面板（气泡、发送、表情、重试）
    │   ├── views.js            个人资料页 + 应用连接页
    │   └── login.js            登录页逻辑
    └── app.js                  入口：事件绑定 + 启动
```

**分层约定**（改动时请保持）：

- `config.js` 是配置唯一入口；`core/` 不碰 DOM；`ui/` 只管渲染与交互；`app.js` 只做装配
- 脚本加载顺序写在 `index.html` 底部，不可调换：`config → mock-data → core(format-adapter → store → api) → ui(render → chat → views → login) → app`
- 凡是容器自带 `display: flex/grid` 又需要 `hidden` 控制的，CSS 必须补 `[hidden] { display: none; }`，否则 `hidden` 会失效（本项目已踩过三次坑）

---

## 四、给后端（成员 A）的对接清单

### 0. 先改这两行

`js/config.js` 末尾：

```js
const WS_URL   = "ws://localhost:8080/ws";     // ★ WebSocket 地址
const API_BASE = "http://localhost:8080/api";  // ★ REST 前缀
```

### 1. 认证

| 方法 | 路径 | 请求 | 返回 |
|------|------|------|------|
| POST | `/auth/login` | `{ account, password }` | `{ token, user: <Profile> }` |
| POST | `/auth/logout` | — | `{ ok: true }` |
| GET | `/me` | — | `<Profile>` |
| PATCH | `/me` | `{ cnName, name, email, phone, city }` | `<Profile>` |

前端待改位置：`js/ui/login.js` 的 `attemptLogin()`（已标 `TODO(后端对接)`）、`js/ui/views.js` 的 `saveProfileEdit()`。
拿到 token 后：REST 请求加 `Authorization: Bearer <token>`，WebSocket 建连改为 `ws://host/ws?token=<token>`（改 `js/core/api.js` 的 `connectWebSocket()`）。

### 2. 应用连接

| 方法 | 路径 | 请求 | 返回 |
|------|------|------|------|
| GET | `/apps` | — | `[<AppConnection>]` |
| POST | `/apps/:key/connect` | — | `<AppConnection>` |
| POST | `/apps/:key/disconnect` | — | `<AppConnection>` |
| POST | `/apps/:key/test` | — | `{ ok, latencyMs, reason? }` |
| PATCH | `/apps/:key/channel` | `{ primary: "api" \| "rpa" }` | `{ primary, backup }` |

`:key` 取值 `wechat | dingtalk`。

### 3. 消息与回复

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/messages?platform=&status=&keyword=` | 拉取消息，返回 `{ messages: [...], total }` |
| GET | `/messages/:id/thread` | 会话上下文 `[{ from, text, time, sendStatus, channel }]` |
| POST | `/messages/:id/reply` | 发送回复，请求体为**内部统一格式**（见下） |

`POST /messages/:id/reply` 成功返回：

```json
{ "ok": true, "channel": "api", "status": "replied", "messageId": "m003" }
```

失败返回（前端据此渲染失败气泡与重试入口）：

```json
{ "ok": false, "channel": "rpa", "reason": "RPA 页面元素定位超时，未找到输入框" }
```

前端待改位置：`js/core/api.js` 的 `sendReply()`（已标 `TODO(后端对接)`，目前用 `setTimeout` 模拟）。

### 4. WebSocket 推送

后端 → 前端，`type` 目前前端监听两种：

```json
{ "type": "new_message",   "data": <Message> }
{ "type": "status_update", "data": { "id": "m003", "status": "synced" } }
```

> 如需推送通道状态变化（如自动降级），新增 `{"type":"channel_update","data":{...}}`，前端需要在 `api.js` 的 `ws.onmessage` 里加一个分支。

### 5. 数据结构定义

**Message（统一消息格式）**

```json
{
  "id": "m001",
  "platform": "wechat | dingtalk",
  "sender": "张经理",
  "time": "09:02",
  "day": "today | yesterday | earlier",
  "type": "text | todo",
  "content": "消息内容",
  "status": "received | processing | sending | replied | synced | failed",
  "unread": true,
  "pinned": false,
  "muted": false
}
```

- `type: "todo"` 且内容含 `【待办】` 时，前端会自动生成一条待办
- `muted: true` 的会话，未读不计入未读提醒

**Profile**

```json
{
  "id": "U1024", "name": "Gary", "cnName": "高远", "initial": "高",
  "role": "系统管理员", "dept": "信息化中心 · 协同办公组", "org": "星辰科技",
  "staffNo": "XC-1024", "email": "gary@xingchen-tech.com", "phone": "138****6620",
  "city": "深圳", "tz": "GMT+8 北京时间", "joinedAt": "2024-03-12",
  "loginType": "企业微信扫码", "twoFactor": true,
  "lastLogin": { "time": "今天 08:42", "device": "Windows · Chrome 141", "ip": "10.20.31.86" },
  "prefs": { "notify": true, "dnd": true, "dndRange": "22:00 - 08:00", "route": "api" },
  "actions": [{ "time": "今天 15:59", "text": "在统一消息中心回复「技术群-小陈」" }]
}
```

**AppConnection**

```json
{
  "key": "dingtalk",
  "connected": true,
  "account": "高远（XC-1024）",
  "org": "星辰科技",
  "lastSync": "15:59",
  "successRate": "100%",
  "since": "2024-05-20",
  "note": "企业内部应用 · 机器人回调"
}
```

> 主 / 备通道不在此结构里，统一由 `js/config.js` 的 `CHANNEL_PLAN` 管理，避免两处数据源打架。

### 6. 后端需要真正实现的三件事（按依赖顺序）

1. **归一化层**：收到钉钉 / RPA 采集的原始消息 → 转成上面的 `Message` 结构 → 去重（同平台 `msg_id`；RPA 无 ID 时用「发送人 + 时间 + 内容哈希」）→ 落库 → WebSocket 推送
2. **发送路由**：收到 `POST /messages/:id/reply` → 按 `CHANNEL_PLAN` 选主通道 → 转成平台格式（参考 `js/core/format-adapter.js`）→ 调平台接口 / RPA 动作 → 失败则切备用通道重发 → 把 `channel` 与最终 `status` 回报前端
3. **状态回流**：平台回执（已读 / 已发送）→ 更新 `status` → 通过 WebSocket `status_update` 推给前端

---

## 五、演示动线（答辩用，约 3 分钟）

1. **登录**：打开页面 → 输错密码一次（展示校验）→ 一键演示登录
2. **统一入口**：9 条消息来自两个平台，按天分组；左侧点「钉钉」+「已回复」→ Tab 变 2、出现筛选面包屑
3. **回复闭环**：点「技术群-小陈」（有历史对话）→ 看上下文气泡 → 输入回复 → 气泡先「发送中…」→ 显示 `API` 通道 → 「已同步到钉钉」
4. **格式转换**：点工具栏右侧「详情」→ 展示内部统一格式与平台格式两栏 JSON
5. **双通道与失败重试**：点 ⚠️ 故障演练 → 发送 → 失败气泡给出原因 → 「切换备用通道重试」→ 通道标签从 `API` 变 `RPA`，状态回到「已同步到平台」
6. **连接管理**：顶栏「应用连接」→ 断开钉钉 → 回主界面看顶栏 `1/2`、侧栏「1 个未连接」、钉钉标签变虚线灰 → 给钉钉会话发消息失败 → 回来重新连接
7. **个人资料**：点顶栏头像 → 展示资料 → 「修改」改手机号 → 保存 → 顶栏同步 → 退出登录回到登录页

---

## 六、当前限制（答辩时如实说明，不要硬撑）

| 项 | 现状 |
|----|------|
| 数据持久化 | 无。除「记住登录」外，刷新后消息 / 待办 / 连接状态回到初始 |
| 发送 | 前端用定时器模拟，未真正调用平台接口（接口已留位） |
| RPA | 前端只做通道状态展示与切换；真实采集需在后端连接器实现，且要控制频率、只读优先、可随时停用 |
| 文件 / 截图 / 语音 | 工具图标保留为扩展位，点击提示依赖平台客户端能力 |
| 消息去重 | 前端未做，由后端归一化层负责（键：`platform + msg_id`） |
| 多端同步 | 未实现，单浏览器会话内状态自洽 |

---

## 七、交付验收清单

- [x] 双击 `index.html` 可直接打开，无控制台报错
- [x] 登录页：错误密码被拦、正确密码进入、扫码与一键演示可用、退出回到登录页
- [x] 三平台消息集中展示，置顶 / 已读 / 免打扰 / 搜索 / 双维筛选均正常
- [x] 回复闭环：发送中 → 已回复 → 已同步到平台，流转时间线可回溯
- [x] 失败重试：故障演练 → 失败气泡 → 原通道重试 / 切备用通道重试
- [x] 应用连接：连接 / 断开 / 测试 / 切换主备，且与顶栏、侧栏、筛选标签联动
- [x] 个人资料：展示 + 修改保存 + 顶栏同步
- [x] 断网（无后端）时自动进入演示模式，不白屏、不卡死

---

## 八、给队友的提醒

- 改代码前先看 `js/config.js` 顶部注释，那是前后端约定的唯一入口
- 新增一个平台时：`config.js` 加 `PLATFORMS` 与 `CHANNEL_PLAN` 条目 → `mock-data.js` 加一条 `MOCK_APPS` → 后端实现一个 Connector，前端无需改渲染代码
- 提交前建议跑一遍回归（若有 jsdom 环境）：登录 / 筛选联动 / 回复闭环 / 断连发送失败 四条路径最关键
