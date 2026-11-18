/* ===== store.js — 全局状态与数据操作 =====
   职责：集中管理 state，提供纯数据操作方法
   约定：本模块不做任何 DOM 操作；UI 渲染统一由 ui/render.js 负责
   ============================================================ */

// ---------- 全局状态 ----------
const state = {
  messages: [...MOCK_MESSAGES],
  todos: [...MOCK_TODOS],
  threads: JSON.parse(JSON.stringify(MOCK_THREADS)), // 会话上下文（深拷贝，避免污染种子数据）
  filter: "all",           // 平台筛选 all | wechat | dingtalk
  statusFilter: "all",     // 状态筛选 all | unread | pending | done
  keyword: "",
  currentMsgId: null,      // 当前打开会话的锚点消息 id（最新一条）
  currentContactKey: null, // 当前打开的联系人（platform|sender），同一人合并一个会话
  trace: {},               // 状态流转记录：msgId -> [{step, detail, time}]
  msgSeq: 100,
  faultPending: false,     // 故障演练：下一次发送注入一次主通道故障（演示用）
  friends: [],             // 好友清单（手动添加的联系人，来自后端 contacts 表）

  profile: MOCK_PROFILE,   // 当前登录用户
  profileEditing: false,   // 个人资料：基本信息是否处于编辑态
  apps: JSON.parse(JSON.stringify(MOCK_APPS)),  // 应用接入状态（连接事实）
  view: null,              // 当前打开的视图层页面：null | "profile" | "apps"
  loggedIn: false,         // 是否已登录（登录页 js/ui/login.js 维护）
};

// ---------- 应用接入（连接管理）----------
function getApp(key) {
  return state.apps.find(a => a.key === key);
}

/* 平台是否已连接：未连接的平台仍可查看历史消息，但不能发送 */
function isPlatformConnected(key) {
  const app = getApp(key);
  return app ? !!app.connected : true;
}

function connectedAppCount() {
  return state.apps.filter(a => a.connected).length;
}

function setAppConnected(key, connected) {
  const app = getApp(key);
  if (!app) return null;
  app.connected = connected;
  if (connected) app.lastSync = nowTime();
  return app;
}

/* 主备通道互换：改的是 config.js 的 CHANNEL_PLAN（发送路由的唯一来源） */
function swapPrimaryChannel(key) {
  const plan = CHANNEL_PLAN[key];
  if (!plan) return null;
  const next = { primary: plan.backup, backup: plan.primary };
  CHANNEL_PLAN[key] = next;
  return next;
}

// ---------- 消息管理：置顶 / 免打扰 ----------
function isPinned(m) { return !!m.pinned; }
function isMuted(m) { return !!m.muted; }

/* 计入未读提醒的消息：免打扰会话的未读不算提醒（与常见 IM 一致） */
function isAlertUnread(m) { return !!m.unread && !m.muted; }

function togglePin(msgId) {
  const m = state.messages.find(x => x.id === msgId);
  if (!m) return null;
  m.pinned = !m.pinned;
  return m;
}

function toggleMute(msgId) {
  const m = state.messages.find(x => x.id === msgId);
  if (!m) return null;
  m.muted = !m.muted;
  return m;
}

// ---------- 工具 ----------
function $(id) { return document.getElementById(id); }

function nowTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function getAvatarText(sender) {
  const name = sender.includes("-") ? sender.split("-").pop() : sender;
  return name.charAt(0);
}

// ---------- 状态流转记录 ----------
function addTrace(msgId, step, detail) {
  if (!state.trace[msgId]) state.trace[msgId] = [];
  state.trace[msgId].push({ step, detail, time: nowTime() });
}

// ---------- 筛选判断（平台 + 状态 + 关键字，三者是「且」）----------
function isStatusOk(m, s) {
  if (s === "unread") return m.unread;
  if (s === "pending") return m.status === "received" || m.status === "processing" || m.status === "failed";
  if (s === "done") return m.status === "replied" || m.status === "synced";
  return true;
}

function isKeywordOk(m) {
  if (!state.keyword) return true;
  const kw = state.keyword.toLowerCase();
  return m.content.toLowerCase().includes(kw) || m.sender.toLowerCase().includes(kw);
}

function matchMessage(m) {
  if (state.filter !== "all" && m.platform !== state.filter) return false;
  if (!isStatusOk(m, state.statusFilter)) return false;
  return isKeywordOk(m);
}

/* 交叉计数：给平台标签算数时套用当前状态筛选，反之亦然（数字才有意义） */
function countFor(target) {
  return state.messages.filter(m => {
    if (target.platform && target.platform !== "all" && m.platform !== target.platform) return false;
    if (target.status && target.status !== "all" && !isStatusOk(m, target.status)) return false;
    return isKeywordOk(m);
  }).length;
}

// ---------- 会话上下文 ----------
function getThread(msgId) {
  if (!state.threads[msgId]) {
    const msg = state.messages.find(m => m.id === msgId);
    if (!msg) return [];
    // 没有历史记录时，以原消息作为第一条
    state.threads[msgId] = [{ from: "them", text: msg.content, time: msg.time }];
  }
  return state.threads[msgId];
}

function appendThread(msgId, entry) {
  getThread(msgId).push(entry);
}

// ---------- 联系人会话合并（同一人只显示一个会话）----------
/* 联系人唯一键：平台 + 发送人（同一个人在同一个平台只有一个会话） */
function contactKeyOf(m) {
  // 站内会话按 conv_id（user:对方账号）聚合：管理员能看到收发双方的消息副本，
  // 若按 sender 聚合会拆成"1"和"高远"两个幽灵联系人
  if (m.platform === "user" && m.convId) return m.convId;
  return `${m.platform}|${m.sender}`;
}

/* 站内会话统一显示名：取组内"对方姓名"（sender ≠ 我的姓名的那条消息），写入 _displayName。
   管理员视角下同一会话既有我发出的（sender=对方名）也有对方收到的副本（sender=我名），
   统一后列表/聊天头部都显示对方姓名。 */
function refreshContactDisplayNames() {
  const myName = (state.profile && (state.profile.name || state.profile.cnName)) || "";
  const groups = new Map();
  state.messages.forEach(m => {
    if (m.platform !== "user") return;
    const k = m.convId || `user:${m.sender}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(m);
  });
  groups.forEach(arr => {
    const other = arr.find(m => m.sender !== myName);
    const name = other ? other.sender : arr[0].sender;
    arr.forEach(m => { m._displayName = name; });
  });
}

/* 取某联系人的全部消息（按 state.messages 顺序 = 新→旧） */
function messagesOfContact(key) {
  return state.messages.filter(m => contactKeyOf(m) === key);
}

/* 合并后的会话气泡：该联系人每条消息的 thread 按时间先后拼接。
   每个气泡带 _mid（归属消息）与 _idx（在该消息 thread 中的下标），供重试/删除定位。 */
function getContactThread(key) {
  const msgs = messagesOfContact(key).slice().reverse();  // 旧→新
  const merged = [];
  msgs.forEach(m => {
    getThread(m.id).forEach((t, idx) => {
      merged.push({ ...t, _mid: m.id, _idx: idx });
    });
  });
  return merged;
}
