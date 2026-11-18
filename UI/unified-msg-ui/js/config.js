/* ===== config.js — 全局配置与接口约定 =====
   ★ 本文件是前后端接口约定的唯一入口，修改前先同步 README
------------------------------------------------------------ */

// 平台配置
const PLATFORMS = {
  all:      { name: "全部" },
  wechat:   { name: "微信", short: "微" },
  dingtalk: { name: "钉钉", short: "钉" },
  user:     { name: "站内好友", short: "友" },
};

// 消息状态名称（业务闭环：已接收 → 已回复 → 已同步到平台）
const STATUS_TEXT = {
  received:   "已接收",
  processing: "处理中",
  sending:    "发送中",
  replied:    "已回复",
  synced:     "已同步到平台",
  failed:     "发送失败",
};

// 状态筛选维度
const STATUS_FILTERS = [
  { key: "all",     name: "全部" },
  { key: "unread",  name: "未读" },
  { key: "pending", name: "待处理" },
  { key: "done",    name: "已回复" },
];

// 快捷回复模板
const QUICK_REPLIES = [
  "收到，马上处理",
  "好的，我看下回复你",
  "已安排，稍后同步结果",
  "这个需要我再确认一下",
  "没问题，按原计划推进",
];

/* ★ 双通道接入约定 ★
   每个平台一条主通道 + 一条备用通道：
     api = 官方开放平台接口（实时、有回执，受权限/资质限制）
     rpa = 界面自动化采集（无接口也能接，轮询、稳定性较弱）
   发送与接收走同一套通道；主通道失败可切备用通道重发 */
const CHANNELS = {
  api: { name: "API 通道", short: "API" },
  rpa: { name: "RPA 通道", short: "RPA" },
};

const CHANNEL_PLAN = {
  wechat:   { primary: "rpa", backup: "api" },  // 个人号无开放接口，RPA 为主
  dingtalk: { primary: "api", backup: "rpa" },
};

/* 演示用：故障演练时给出的失败原因（真实环境由后端/连接器回报） */
const FAIL_REASON = {
  api: "平台接口返回 429，调用频率超限",
  rpa: "RPA 页面元素定位超时，未找到输入框",
};

/* ★ 后端对接地址（成员 A 填写）★
   WebSocket：接收实时消息推送
   API_BASE ：发送回复等 REST 接口前缀 */
const WS_URL   = "ws://localhost:8080/ws";
const API_BASE = "http://localhost:8080/api";
