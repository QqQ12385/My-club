/* ===== mock-data.js — 模拟数据 =====
   ★ 给队友（成员A 后端）的约定：
   所有平台消息在后端先转成这种"内部统一格式"再推给前端：
   {
     id, platform: "wechat"|"dingtalk", sender, time,
     day: "today"|"yesterday"|"earlier",
     type: "text"|"todo",
     content,
     status: "received"|"processing"|"replied"|"synced"|"failed",
     unread: true|false,
     pinned: true|false,     // 置顶（可选，缺省 false）
     muted: true|false       // 免打扰（可选，缺省 false；免打扰不计入未读提醒）
   }
   ============================================================ */

// ---- 初始模拟消息 ----
const MOCK_MESSAGES = [
  {
    id: "m001", platform: "dingtalk", sender: "张经理", chat: "项目冲刺群", day: "today",
    time: "09:02", type: "todo", unread: true, status: "received",
    content: "【待办】下午 3 点项目评审会，请提前准备演示材料并确认会议室。",
  },
  {
    id: "m002", platform: "dingtalk", sender: "产品组-李工", chat: "产品协作群", day: "today",
    time: "09:15", type: "text", unread: true, status: "received",
    content: "需求文档 v2.3 已经上传，麻烦今天下班前帮忙确认一下第 4 节的流程图是否正确。",
  },
  {
    id: "m003", platform: "wechat", sender: "客户-王总", chat: "王总（客户对接）", day: "today",
    time: "09:27", type: "text", unread: true, status: "received", pinned: true,
    content: "上次说的合同条款我们内部讨论过了，有两处要修改，方便今天通话聊一下吗？",
  },
  {
    id: "m004", platform: "dingtalk", sender: "系统通知", chat: "全员通知群", day: "today",
    time: "08:50", type: "todo", unread: true, status: "processing", muted: true,
    content: "【待办】本月报销单截止本周五，请提交差旅票据。",
  },
  {
    id: "m005", platform: "dingtalk", sender: "技术群-小陈", chat: "研发协作群", day: "today",
    time: "08:41", type: "text", unread: false, status: "synced",
    content: "测试环境已经部署好了，账号密码发你邮箱了，帮忙验证一下登录。",
  },
  {
    id: "m006", platform: "wechat", sender: "市场部-周姐", chat: "周姐（市场对接）", day: "yesterday",
    time: "17:20", type: "text", unread: false, status: "replied",
    content: "下周展会的物料清单发你，帮忙核对接待人名单。",
  },
  {
    id: "m007", platform: "dingtalk", sender: "财务-小赵", chat: "财务对接群", day: "yesterday",
    time: "15:06", type: "text", unread: false, status: "synced",
    content: "上季度的差旅明细已经核对完，没有问题，可以提交了。",
  },
  {
    id: "m008", platform: "dingtalk", sender: "技术群-小陈", chat: "研发协作群", day: "yesterday",
    time: "10:32", type: "text", unread: false, status: "synced",
    content: "接口联调文档更新了，新增了消息回调和状态推送两个字段说明。",
  },
  {
    id: "m009", platform: "wechat", sender: "行政-小林", chat: "小林（行政对接）", day: "earlier",
    time: "周二 14:08", type: "text", unread: false, status: "synced",
    content: "工位调整通知：本周六搬至 B 区 3 楼。",
  },
];

// ---- 会话上下文（按消息 id 组织；后端可提供历史接口替换）----
// from: "them" = 对方发来，"me" = 统一入口发出
// me 消息的 sendStatus: "sent" | "synced"（体现状态回流）
const MOCK_THREADS = {
  m005: [
    { from: "them", text: "测试环境已经部署好了，账号密码发你邮箱了，帮忙验证一下登录。", time: "08:41" },
    { from: "me",   text: "收到，我现在去验证，结果稍后同步给你。", time: "08:45", sendStatus: "synced" },
    { from: "them", text: "好的，麻烦了。", time: "08:47" },
  ],
  m006: [
    { from: "them", text: "下周展会的物料清单发你，帮忙核对接待人名单。", time: "17:20" },
    { from: "me",   text: "已核对，名单没问题，有两家公司的对接人电话我更新在表格里了。", time: "17:36", sendStatus: "sent" },
  ],
  m003: [
    { from: "them", text: "上次说的合同条款我们内部讨论过了，有两处要修改，方便今天通话聊一下吗？", time: "09:27" },
  ],
};

// ---- 初始模拟待办 ----
const MOCK_TODOS = [
  { id: "t001", msgId: "m001", platform: "dingtalk", title: "准备项目评审会演示材料", detail: "下午 3 点会议，需确认会议室", deadline: "今天 15:00", done: false },
  { id: "t002", msgId: "m002", platform: "dingtalk", title: "确认需求文档 v2.3 第 4 节流程图", detail: "来自 产品组-李工", deadline: "今天 18:00", done: false },
  { id: "t003", msgId: "m004", platform: "dingtalk", title: "提交本月差旅报销单", detail: "系统提醒", deadline: "本周五", done: false },
];

// ---- 演示模式下定时"新到"的模拟消息 ----
const INCOMING_DEMO_MESSAGES = [
  { platform: "dingtalk", sender: "人事-刘姐", type: "text", day: "today", content: "明天上午 10 点新员工培训，记得签到。" },
  { platform: "dingtalk", sender: "运维-老赵", type: "todo", day: "today", content: "【待办】线上服务今晚 22:00 例行升级，请关注监控告警。" },
  { platform: "wechat", sender: "客户-王总", type: "text", day: "today", content: "那我们下午 4 点电话沟通修改细节。" },
];

// ---- RPA 采集任务状态（工作台概览用，演示数据）----
// 对接后端后由真实采集任务回报替换
const MOCK_RPA = [
  { platform: "wechat",  lastRun: "15:56", successRate: "98.7%", status: "ok" },
  { platform: "dingtalk", lastRun: "15:59", successRate: "100%", status: "ok" },
];

/* ---- 当前登录用户（个人资料页）----
   TODO(后端对接): 换成 GET `${API_BASE}/me`，字段保持一致即可直接渲染 */
const MOCK_PROFILE = {
  id: "U1024",
  name: "Gary",
  cnName: "高远",
  initial: "高",
  role: "系统管理员",
  dept: "信息化中心 · 协同办公组",
  org: "星辰科技",
  staffNo: "XC-1024",
  email: "gary@xingchen-tech.com",
  phone: "138****6620",
  city: "深圳",
  tz: "GMT+8 北京时间",
  joinedAt: "2024-03-12",
  loginType: "企业微信扫码",
  twoFactor: true,
  lastLogin: { time: "今天 08:42", device: "Windows · Chrome 141", ip: "10.20.31.86" },
  // 消息偏好（页面内可切换，演示用）
  prefs: {
    notify: true,        // 新消息桌面通知
    dnd: true,           // 免打扰时段
    dndRange: "22:00 - 08:00",
    route: "api",        // 默认发送通道：api 优先 | rpa 优先
  },
  // 最近操作（演示数据，真实环境由后端操作日志提供）
  actions: [
    { time: "今天 15:59", text: "在统一消息中心回复「技术群-小陈」" },
    { time: "今天 15:52", text: "将「客户-王总」会话置顶" },
    { time: "今天 09:10", text: "登录统一消息中心（企业微信扫码）" },
    { time: "昨天 18:04", text: "修改钉钉连接器主通道为 API" },
  ],
};

/* ---- 应用接入配置（应用连接页）----
   连接状态与通道配置分开：
     connected 等字段 → 本文件（连接事实，后端 /api/apps 返回）
     主备通道        → config.js CHANNEL_PLAN（发送路由规则）
   TODO(后端对接): GET `${API_BASE}/apps` 返回同结构数组 */
const MOCK_APPS = [
  {
    key: "wechat", connected: true, account: "Gary（个人号）",
    org: "未绑定组织", lastSync: "15:56", successRate: "98.7%", since: "2024-04-11",
    note: "无个人号开放接口 · 走 RPA 采集",
  },
  {
    key: "dingtalk", connected: true, account: "高远（XC-1024）",
    org: "星辰科技", lastSync: "15:59", successRate: "100%", since: "2024-05-20",
    note: "企业内部应用 · 机器人回调",
  },
];
