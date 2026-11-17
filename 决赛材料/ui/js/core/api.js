/* ===== api.js — 后端通信层（前端对接后端的唯一入口）=====
   1. WebSocket：接收后端实时推送（新消息 / 状态回流）
   2. sendReply：发送回复（当前用定时器模拟，TODO 换成真实接口）
   3. 演示模式：后端连不上时自动启用，保证答辩演示不翻车
   ============================================================ */

let ws = null;
let demoTimer = null;
let demoIdx = 0;

function updateWsStatus(mode, text) {
  const box = $("wsStatus");
  // 用 classList 增删，保留布局类（ws-inline 等），不要整体覆盖 className
  box.classList.remove("demo", "connected");
  box.classList.add(mode);
  $("wsText").textContent = text;
}

/* ---------- WebSocket 连接 ---------- */
function connectWebSocket() {
  try {
    ws = new WebSocket(WS_URL);
  } catch { enterDemoMode(); return; }

  const timeout = setTimeout(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) enterDemoMode();
  }, 3000);

  ws.onopen = () => {
    clearTimeout(timeout);
    if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
    updateWsStatus("connected", "已连接后端 · 实时刷新");
    toast("WebSocket 已连接，开始接收实时消息");
    // 连上后端后，拉取真实数据替换 mock（登录后再拉，避免未登录就替换）
    if (state.loggedIn) loadBackendData();
  };
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      // 推送约定：{ type: "new_message", data: {统一格式消息} }
      //           { type: "status_update", data: { id, status } }
      if (data.type === "new_message") pushMessage(data.data);
      if (data.type === "status_update") updateStatus(data.data.id, data.data.status);
    } catch { /* 忽略无法解析的消息 */ }
  };
  ws.onclose = () => { updateWsStatus("demo", "演示模式 · 模拟数据"); enterDemoMode(); };
  ws.onerror = () => ws.close();
}

/* ---------- 演示模式：每 15 秒模拟收到一条新消息 ---------- */
function enterDemoMode() {
  if (demoTimer) return;
  updateWsStatus("demo", "演示模式 · 模拟数据");
  demoTimer = setInterval(() => {
    // 停留在登录页时不推消息，登录后再开始模拟来消息
    if (!state.loggedIn) return;
    if (demoIdx >= INCOMING_DEMO_MESSAGES.length) return;
    pushMessage(INCOMING_DEMO_MESSAGES[demoIdx]);
    demoIdx++;
  }, 15000);
}

/* ---------- 发送时解析后端真实消息 ID ----------
   页面显示保持原样（照片形式），不动任何样式和数据；
   只在发送前按 platform+sender(+content) 匹配后端真实消息，避免 ID 错位。 */
let beCache = null, beCacheAt = 0;
async function resolveBackendId(msg) {
  try {
    if (!beCache || Date.now() - beCacheAt > 30000) {
      const headers = window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {};
      const r = await fetch(`${API_BASE}/messages`, { headers });
      if (!r.ok) return msg.id;
      beCache = (await r.json()).messages || [];
      beCacheAt = Date.now();
    }
    // 先精确匹配 platform+sender+content，再退到 platform+sender，最后退到同平台第一条
    let hit = beCache.find(m => m.platform === msg.platform && m.sender === msg.sender && m.content === msg.content)
           || beCache.find(m => m.platform === msg.platform && m.sender === msg.sender)
           || beCache.find(m => m.platform === msg.platform);
    return hit ? hit.id : msg.id;
  } catch { return msg.id; }
}

/* ---------- 手动同步平台消息（演示「平台→统一入口」接收闭环）----------
   正式环境由钉钉事件订阅回调 / RPA 采集触发；本地 localhost 无法被钉钉公网
   回调触达，故提供此入口，把钉钉群里的消息手动同步进页面。走完整归一化 +
   AI 分类 + WebSocket 实时推送链路。 */
async function syncPlatformMessage(platform, sender, chat, content) {
  try {
    const resp = await fetch(`${API_BASE}/collector/sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ platform, sender, chat, content }),
    });
    const data = await resp.json();
    if (!data.ok) return { ok: false, reason: data.reason || "同步失败" };
    return { ok: true, duplicated: !!data.duplicated, id: data.id };
  } catch (e) {
    return { ok: false, reason: "无法连接后端服务，请先运行 后端\\启动.bat" };
  }
}

/* ---------- 拉取后端真实数据（登录后整体替换 mock）----------
   从 /api/messages、/api/apps、/api/me 拉真数据，替换 state 里的 mock：
   - messages/todos 以后端数据库为准（9 条种子消息）
   - apps 以后端连接状态为准
   - profile 以后端 /me 返回的角色为准
   之后发送 reply 直接用真实消息 id，不再做 ID 映射。
   失败（后端未启动）时静默回退 mock，保证离线也能演示。 */
async function loadBackendData() {
  const headers = window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {};
  try {
    const [msgsResp, appsResp, meResp] = await Promise.all([
      fetch(`${API_BASE}/messages`, { headers }),
      fetch(`${API_BASE}/apps`, { headers }),
      fetch(`${API_BASE}/me`, { headers }),
    ]);
    if (!msgsResp.ok) return false;

    const msgsData = await msgsResp.json();
    const appsData = appsResp.ok ? await appsResp.json() : null;
    const meData = meResp.ok ? await meResp.json() : null;

    // 1) 消息：后端真数据 → state.messages（字段与前端 mock 完全一致）
    const msgs = (msgsData.messages || []).map(m => ({
      id: m.id, platform: m.platform, sender: m.sender, chat: m.chat || m.platform,
      time: m.time, day: m.day, type: m.type, content: m.content, status: m.status,
      unread: !!m.unread, pinned: !!m.pinned, muted: !!m.muted,
      convId: m.convId || "",            // 钉钉会话ID（联系人主动发消息真实回发用）
    }));
    state.messages = msgs;
    state.msgSeq = msgs.length + 100;

    // 2.5) 好友清单（手动添加的联系人）
    try {
      const frResp = await fetch(`${API_BASE}/contacts/list`, { headers });
      if (frResp.ok) state.friends = await frResp.json();
    } catch (e) { /* 好友接口失败不阻塞主流程 */ }

    // 2) 待办：从后端消息里提取 type=todo 且未完成的消息（后端无独立 todo 表）
    state.todos = msgs.filter(m => m.type === "todo").map(m => ({
      id: "t" + m.id, msgId: m.id, platform: m.platform,
      title: (m.content.replace("【待办】", "").split("，")[0] || m.content).split("。")[0],
      detail: `来自 ${m.sender}`, deadline: "尽快处理", done: m.status === "synced" || m.status === "replied",
    }));

    // 3) 应用连接：后端连接状态
    if (appsData && Array.isArray(appsData)) {
      state.apps = appsData.map(a => ({
        key: a.key, connected: !!a.connected, account: a.account || "",
        org: a.org || "", lastSync: a.last_sync || "", successRate: a.success_rate || "",
        since: a.since || "", note: a.note || "",
      }));
    }

    // 4) 个人资料：后端角色
    if (meData && meData.name) applyProfile(meData);

    // 5) 会话上下文：按需懒加载（openChat 时 getThread 会请求，这里先清空缓存）
    state.threads = {};
    state.trace = {};

    renderAll();
    return true;
  } catch (e) {
    // 后端不可达：保留 mock，演示模式继续
    return false;
  }
}

/* ---------- 数据写入（WebSocket 推送 / 演示共用）---------- */
function pushMessage(data) {
  state.msgSeq++;
  const msg = {
    id: data.id || "m" + state.msgSeq,
    platform: data.platform || "dingtalk",
    sender: data.sender || "未知",
    time: data.time || nowTime(),
    day: data.day || "today",
    type: data.type || "text",
    content: data.content || "",
    status: data.status || "received",
    unread: true,
    pinned: !!data.pinned,
    muted: !!data.muted,
  };
  state.messages.unshift(msg);

  // 含【待办】标记的文本自动生成待办项
  if (msg.type === "todo" && msg.content.includes("【待办】")) {
    const title = msg.content.replace("【待办】", "").split("，")[0].split("。")[0];
    state.todos.unshift({
      id: "t" + state.msgSeq, msgId: msg.id, platform: msg.platform,
      title: title || msg.content, detail: `来自 ${msg.sender}`,
      deadline: "尽快处理", done: false,
    });
  }
  addTrace(msg.id, "已接收", `来自 ${PLATFORMS[msg.platform].name}（${msg.sender}）`);
  renderAll();
  toast(`收到${PLATFORMS[msg.platform].name}新消息：${msg.sender}`);
}

function updateStatus(id, status) {
  const msg = state.messages.find(m => m.id === id);
  if (!msg) return;
  msg.status = status;
  addTrace(id, STATUS_TEXT[status] || status, "由后端推送回流");
  renderAll();
}

/* ---------- 通道选择 ---------- */
function planOf(msg) {
  return CHANNEL_PLAN[msg.platform] || { primary: "api", backup: "rpa" };
}

/* ---------- 发送回复 ----------
   已对接后端：POST ${API_BASE}/messages/:id/reply
   后端负责：选通道 → 格式转换 → 调平台接口/RPA 发送 → 失败切备用 → 回报通道与状态
   成功 { ok:true, channel, status } / 失败 { ok:false, channel, reason } */
async function sendReply(msg, text, bubble, opts) {
  const o = opts || {};
  const plan = planOf(msg);
  const channel = o.channel || bubble.channel || plan.primary;

  bubble.channel = channel;
  bubble.sendStatus = "sending";
  bubble.failReason = "";
  msg.status = "sending";
  renderThread();
  renderChatHead(msg);
  renderAll();

  // 故障演练标记随请求发给后端（后端在主通道注入失败）
  const fault = !!state.faultPending;
  state.faultPending = false;
  if (typeof renderFaultBtn === "function") renderFaultBtn();

  try {
    // 关键：页面用演示 ID，发往后端前换成真实 ID（按 platform+sender 匹配）
    const realId = await resolveBackendId(msg);
    const resp = await fetch(`${API_BASE}/messages/${encodeURIComponent(realId)}/reply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ text, channel, fault }),
    });
    const data = await resp.json();

    if (data.ok) {
      bubble.channel = data.channel || channel;
      bubble.sendStatus = "sent";
      msg.status = data.status || "replied";
      addTrace(msg.id, o.isRetry ? "重试成功 · 已回复" : "已回复",
        CHANNELS[bubble.channel].name + " 发送成功：" + text);
      renderAll();
      if (o.onReplied) o.onReplied();

      // synced 由后端 WS status_update 推送回流；2.5s 兜底本地补一次
      setTimeout(() => {
        if (msg.status !== "synced") {
          bubble.sendStatus = "synced";
          msg.status = "synced";
          addTrace(msg.id, "已同步到平台",
            "状态已回流至 " + PLATFORMS[msg.platform].name + "（" + CHANNELS[bubble.channel].name + " 回执）");
          renderAll();
          if (o.onSynced) o.onSynced();
        }
      }, 2500);
    } else {
      bubble.channel = data.channel || channel;
      bubble.sendStatus = "failed";
      bubble.failReason = data.reason || "发送失败";
      msg.status = "failed";
      addTrace(msg.id, "发送失败", CHANNELS[bubble.channel].name + "：" + bubble.failReason);
      renderAll();
      toast("发送失败（" + CHANNELS[bubble.channel].name + "），可重试或切换备用通道");
      if (o.onFailed) o.onFailed(bubble);
    }
  } catch (e) {
    // 后端不可达：失败气泡引导启动后端
    bubble.sendStatus = "failed";
    bubble.failReason = "无法连接后端服务，请先运行 后端\\启动.bat";
    msg.status = "failed";
    addTrace(msg.id, "发送失败", bubble.failReason);
    renderAll();
    if (o.onFailed) o.onFailed(bubble);
  }
}
