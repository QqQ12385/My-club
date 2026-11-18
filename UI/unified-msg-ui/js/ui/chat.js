/* ===== chat.js — 会话面板（微信式右会话区）=====
   职责：工作台概览 + 会话上下文气泡 + 回复输入 + 表情面板 + 格式转换提示
   ============================================================ */

/* ---------- 工作台概览（会话面板空置时展示） ---------- */
function renderOverview() {
  // 今日概览
  const todayMsgs = state.messages.filter(m => m.day === "today");
  $("ovToday").textContent = todayMsgs.length;
  $("ovUnread").textContent = state.messages.filter(m => m.unread).length;
  $("ovReplied").textContent = state.messages.filter(m => m.status === "replied" || m.status === "synced").length;
  const todoOpen = state.todos.filter(t => !t.done);
  $("ovTodo").textContent = todoOpen.length;

  // 待办预览（最多 3 条）
  $("ovTodoList").innerHTML = todoOpen.length
    ? todoOpen.slice(0, 3).map(t => `
        <div class="ov-todo" data-id="${t.id}">
          <span class="t">${t.title}</span>
          <span class="d">${t.deadline}</span>
        </div>`).join("")
    : `<div class="ov-empty">✅ 暂无待办</div>`;
  document.querySelectorAll(".ov-todo").forEach(el => {
    el.onclick = () => switchTab("todos");
  });

  // 闭环说明（用实时数字）
  const pendingCount = state.messages.filter(m =>
    m.status === "received" || m.status === "processing" || m.status === "failed").length;
  $("ovFlowNote").textContent =
    `当前 ${state.messages.length} 条消息已进入统一入口，其中待处理 ${pendingCount} 条`;

  // RPA 采集任务
  $("ovRpa").innerHTML = MOCK_RPA.map(r => `
    <div class="ov-rpa-row">
      <span class="plat"><i class="pdot"></i>${PLATFORMS[r.platform].name}</span>
      <span class="meta">上次采集 ${r.lastRun} · 每 2 分钟轮询</span>
      <span class="rate">成功率 ${r.successRate}</span>
      <button class="ov-sync-btn" data-platform="${r.platform}">手动同步</button>
    </div>`).join("");
  document.querySelectorAll(".ov-sync-btn").forEach(btn => {
    btn.onclick = () => manualSync(btn.dataset.platform);
  });
}

function initOverviewEvents() {
  $("ovTodoMore").onclick = () => switchTab("todos");
}

/* ---------- 手动同步平台消息 ----------
   演示「平台 → 统一入口」接收闭环：把钉钉/微信群里新到的消息
   手动同步进页面，走完整归一化 + AI 分类 + 实时推送。正式环境由
   平台事件订阅回调（钉钉）或 RPA 采集（微信）自动触发。 */
function manualSync(platform) {
  const pname = PLATFORMS[platform].name;
  // 用一个轻量弹窗收集发送人与内容（不新增 HTML，用 prompt 类交互）
  const sender = prompt(`同步「${pname}」消息\n请输入消息发送人：`, "钉钉群-小陈");
  if (sender === null) return;
  const content = prompt(`同步「${pname}」消息\n请输入消息内容（复制群里的原文）：`);
  if (content === null || !content.trim()) { toast("已取消同步"); return; }
  const chat = prompt(`同步「${pname}」消息\n请输入群/会话名：`, "研发协作群");
  if (chat === null) return;

  toast(`正在同步${pname}消息...`);
  syncPlatformMessage(platform, sender.trim(), chat.trim(), content.trim()).then(res => {
    if (res.ok) {
      toast(res.duplicated ? "消息已存在，跳过（去重生效）" : `已同步${pname}消息：${sender}（消息经 AI 分类，实时推送已发出）`);
    } else {
      toast(res.reason || "同步失败");
    }
  });
}

/* ---------- 常用表情（演示集，够用即可） ---------- */
const EMOJIS = [
  "😀","😄","😁","😅","😂","🙂","😉","😊","😍","😘","😜","🤔",
  "😌","😥","😢","😭","😤","😠","😷","🤒","👍","👎","👌","✌️",
  "🙏","💪","🎉","🎊","❤️","💔","🌹","⭐","🔥","✅","❌","❗",
  "❓","💬","📎","📁","📊","🕐","☕","🍕","🚀","📌","📝","💯",
];

function openChat(id) {
  const msg = state.messages.find(m => m.id === id);
  if (!msg) return;
  openContact(contactKeyOf(msg));
}

/* 按联系人打开会话：同一人（平台+发送人）的所有消息合并成一个连续会话。
   锚点取最新一条消息（回复走它，conv_id 也是最新的）。 */
function openContact(key) {
  const msgs = messagesOfContact(key);
  if (!msgs.length) return;
  const anchor = msgs[0];          // 最新一条
  state.currentContactKey = key;
  state.currentMsgId = anchor.id;
  msgs.forEach(m => { if (m.unread) m.unread = false; });

  $("chatEmpty").hidden = true;
  $("chatBody").hidden = false;

  renderChatHead(anchor);
  renderThread();
  renderQuickReplies();
  $("chatInput").value = "";
  $("emojiPanel").hidden = true;
  $("convDetail").classList.remove("open");
  updateConvPreview("");
  renderAll();

  // 异步拉取该联系人每条消息的历史 thread（含我方回复），全部拉到后合并刷新
  msgs.forEach(m => loadThread(m.id));
}

/* 从后端拉取会话上下文（懒加载）。后端未启动或失败时静默保留本地缓存。 */
async function loadThread(msgId) {
  try {
    const headers = window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {};
    const r = await fetch(`${API_BASE}/messages/${encodeURIComponent(msgId)}/thread`, { headers });
    if (!r.ok) return;
    const rows = await r.json();
    if (!Array.isArray(rows)) return;
    const mapped = rows.map(t => ({
      id: t.id,
      from: t.from === "me" ? "me" : "them",
      text: t.text,
      time: t.time,
      sendStatus: t.sendStatus || (t.from === "me" ? "synced" : undefined),
      channel: t.channel || undefined,
    }));
    if (mapped.length) {
      state.threads[msgId] = mapped;
      // 该消息属于当前打开的联系人会话时刷新（合并视图）
      const cur = state.currentContactKey && messagesOfContact(state.currentContactKey) || [];
      if (cur.some(m => m.id === msgId)) renderThread();
    }
  } catch (e) { /* 忽略，保留本地 */ }
}

function closeChat() {
  state.currentMsgId = null;
  state.currentContactKey = null;
  $("chatBody").hidden = true;
  $("chatEmpty").hidden = false;
  renderAll();
}

function renderChatHead(msg) {
  if (!msg) return;
  const plan = planOf(msg);
  const dName = msg._displayName || msg.sender;   // 站内会话显示对方姓名
  $("chatAvatar").innerHTML =
    `<span>${getAvatarText(dName)}</span><i class="av-dot ${msg.platform}"></i>`;
  $("chatName").textContent = dName;
  // 群/会话名 + 平台 + 主通道：明确「这条回给谁、发到哪」
  const chatName = msg.chat ? `「${msg.chat}」` : "";
  $("chatSub").textContent =
    `${chatName ? chatName + " · " : ""}${PLATFORMS[msg.platform].name} · 主通道 ${CHANNELS[plan.primary].name}`;
  $("chatStatusBadge").className = `status-badge ${msg.status}`;
  $("chatStatusBadge").textContent = STATUS_TEXT[msg.status];
  // 发送提示整体重建（含 convPlatform，避免 innerHTML 重写后引用丢失）
  $("convToggle").innerHTML =
    `发送时将自动转换为 <b id="convPlatform">${PLATFORMS[msg.platform].name}</b> 格式${msg.chat ? `，发至「${msg.chat}」` : ""} <i>详情</i>`;

  // 置顶 / 免打扰按钮状态
  $("chatPin").classList.toggle("on", isPinned(msg));
  $("chatPin").title = isPinned(msg) ? "取消置顶" : "置顶该会话";
  $("chatMute").classList.toggle("on", isMuted(msg));
  $("chatMute").title = isMuted(msg) ? "取消免打扰" : "开启免打扰";
}

/* ---------- 文件气泡渲染：图片直接显示缩略图（微信式），点击看大图；其他文件可下载 ---------- */
const IMG_NAME_RE = /\.(png|jpe?g|gif|webp|bmp|svg)\s*$/i;

function isImageBubble(t) {
  return !!t.fileId && IMG_NAME_RE.test((t.text || "").replace(/^\[文件\]\s*/, ""));
}

function bubbleFileHtml(t) {
  if (!t.fileId) return t.text;
  const dl = `${API_BASE}/files/${t.fileId}?download=1`;
  const name = (t.text || "").replace(/^\[文件\]\s*/, "");
  if (isImageBubble(t)) {
    return `<img class="bubble-img" src="${API_BASE}/files/${t.fileId}" alt="${name}"
              data-fid="${t.fileId}" data-name="${name}" title="点击查看大图">
            <a class="bubble-file" href="${dl}">${t.text}</a>`;
  }
  return `<a class="bubble-file" href="${dl}">${t.text}</a>`;
}

/* 微信式图片预览：点击缩略图弹出大图，可下载 */
function openFilePreview(fid, name) {
  let ov = $("filePreviewLayer");
  if (!ov) {
    ov = document.createElement("div");
    ov.id = "filePreviewLayer";
    ov.className = "file-preview-layer";
    ov.innerHTML = `
      <div class="fp-box">
        <div class="fp-head">
          <span class="fp-name"></span>
          <button class="fp-dl">下载</button>
          <button class="fp-close" title="关闭">×</button>
        </div>
        <div class="fp-body"><img class="fp-img" alt=""></div>
      </div>`;
    document.body.appendChild(ov);
    ov.addEventListener("click", (e) => {
      if (e.target === ov || e.target.classList.contains("fp-close")) closeFilePreview();
    });
  }
  ov.querySelector(".fp-name").textContent = name || "图片预览";
  ov.querySelector(".fp-img").src = `${API_BASE}/files/${fid}`;
  ov.querySelector(".fp-dl").onclick = () => { window.location.href = `${API_BASE}/files/${fid}?download=1`; };
  ov.classList.add("show");
}

function closeFilePreview() {
  const ov = $("filePreviewLayer");
  if (ov) ov.classList.remove("show");
}

/* ---------- 会话气泡（联系人合并视图：同一人的全部消息连续展示）---------- */
function renderThread() {
  const msg = state.messages.find(m => m.id === state.currentMsgId);
  if (!msg) return;
  const thread = getContactThread(state.currentContactKey);
  const plan = planOf(msg);

  $("chatThread").innerHTML = thread.map((t, idx) => {
    // 每个气泡带删除入口（后端落库的记录可真删，本地未落库的仅前端移除）
    const delBtn = `<button class="bubble-del" data-del="${idx}" title="删除这条记录">删除</button>`;
    if (t.from === "me") {
      const ch = t.channel || plan.primary;
      const chDef = CHANNELS[ch] || { name: ch || "未知通道", short: ch || "?" };   // 未知通道兜底，避免渲染中断
      const failed = t.sendStatus === "failed";
      const stText = t.sendStatus === "sending" ? "发送中…"
        : t.sendStatus === "sent" ? "已发送，等待平台回执"
        : t.sendStatus === "synced" ? `已同步到${PLATFORMS[msg.platform].name}`
        : "";
      const target = msg.chat ? `回给 ${msg.sender} · ${msg.chat}` : `回给 ${msg.sender}`;
      // 微信式语义：只能撤回「自己发的」消息（别人发的只有删除）
      const recallBtn = (t._mid && (t.sendStatus === "synced" || t.sendStatus === "sent"))
        ? `<button class="bubble-del" data-recall="${idx}" title="撤回这条消息（保留记录，标记为已撤回）">撤回</button>` : "";
      return `
        <div class="bubble-row me">
          <div class="bubble me-bubble ${t.sendStatus === "sending" ? "sending" : ""} ${failed ? "failed" : ""}">
            <div class="bubble-target">→ ${target}</div>
            <div class="bubble-text">${t.fileId ? bubbleFileHtml(t) : t.text}</div>
            ${failed ? `<div class="bubble-fail">发送失败 · ${t.failReason}</div>` : ""}
            <div class="bubble-status">
              ${stText ? stText + " · " : ""}${t.time}
              <span class="ch-tag ${ch}" title="经${chDef.name}发送">${chDef.short}</span>
              ${recallBtn}
              ${delBtn}
            </div>
            ${failed ? `
              <div class="bubble-actions">
                <button data-retry="${idx}" data-switch="0">重试</button>
                <button class="primary" data-retry="${idx}" data-switch="1">切换备用通道重试</button>
              </div>` : ""}
          </div>
        </div>`;
    }
    return `
      <div class="bubble-row them">
        <div class="avatar small"><span>${getAvatarText(msg.sender)}</span></div>
        <div class="bubble them-bubble ${t.recalled ? "recalled" : ""}">
          <div class="bubble-text">${t.fileId ? bubbleFileHtml(t) : t.text}</div>
          <div class="bubble-status">${t.time} ${delBtn}</div>
        </div>
      </div>`;
  }).join("");

  // 失败气泡上的重试入口（定位到气泡归属的消息 thread）
  $("chatThread").querySelectorAll("[data-retry]").forEach(btn => {
    btn.onclick = () => {
      const t = thread[Number(btn.dataset.retry)];
      if (t) retrySend(t._mid, t._idx, btn.dataset.switch === "1");
    };
  });
  // 删除单条会话记录
  $("chatThread").querySelectorAll("[data-del]").forEach(btn => {
    btn.onclick = () => deleteThreadItem(thread[Number(btn.dataset.del)]);
  });
  // 撤回单条消息（标记为已撤回，保留痕迹）
  $("chatThread").querySelectorAll("[data-recall]").forEach(btn => {
    btn.onclick = () => recallThreadItem(thread[Number(btn.dataset.recall)]);
  });

  // 图片缩略图：点击弹出大图预览
  $("chatThread").querySelectorAll(".bubble-img").forEach(img => {
    img.onclick = () => openFilePreview(img.dataset.fid, img.dataset.name);
  });

  const box = $("chatThread");
  box.scrollTop = box.scrollHeight;
}

/* ---------- 删除单条会话记录（气泡级）----------
   后端落库的记录（有 id）真删；本地未落库的只从界面移除。 */
async function deleteThreadItem(t) {
  if (!t) return;
  if (!confirm("删除这条聊天记录？")) return;
  const arr = state.threads[t._mid];
  if (arr) arr.splice(t._idx, 1);
  if (t.id) {
    try {
      await fetch(`${API_BASE}/thread/${t.id}`, {
        method: "DELETE",
        headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
      });
    } catch (e) { /* 后端不可达时仅前端移除 */ }
  }
  renderThread();
  renderAll();
  toast("已删除该条记录");
}

/* ---------- 撤回单条消息（气泡级）----------
   调后端 /recall，把消息标记为「已撤回」（记录保留，微信/钉钉同款体验）。 */
async function recallThreadItem(t) {
  if (!t || !t._mid) return;
  if (!confirm("撤回这条消息？记录会保留并标记为「已撤回」。")) return;
  try {
    const resp = await fetch(`${API_BASE}/messages/${encodeURIComponent(t._mid)}/recall`, {
      method: "POST",
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    });
    const data = await resp.json();
    if (!data.ok) { toast("撤回失败：" + ((data.detail && data.detail[0] && data.detail[0].msg) || "未知错误")); return; }
    // 自己撤回：文案与钉钉侧撤回（applyRecall 的 WS 推送）区分
    const msg = state.messages.find(m => m.id === t._mid);
    if (msg) { msg.type = "recall"; msg.content = "（已撤回一条消息）"; }
    const arr = state.threads[t._mid];
    if (arr) arr.forEach(x => { x.recalled = true; });
    renderAll();
    renderThread();
    toast("已撤回");
  } catch (e) {
    toast("撤回失败：后端不可达");
  }
}

/* 应用撤回状态（WS 推送 / 本地撤回共用）：消息标记为 recall 类型 */
function applyRecall(mid) {
  const msg = state.messages.find(m => m.id === mid);
  if (!msg) return;
  msg.type = "recall";
  msg.content = "（对方在钉钉撤回了一条消息）";
  const arr = state.threads[mid];
  if (arr) arr.forEach(t => { t.recalled = true; });
  renderAll();
  if (state.currentContactKey && getContactThread(state.currentContactKey).some(t => t._mid === mid)) {
    renderThread();
  }
}

/* ---------- 删除整个会话（当前联系人的全部消息）---------- */
async function deleteContactConversation() {
  const key = state.currentContactKey;
  if (!key) return;
  const anchor = state.messages.find(m => m.id === state.currentMsgId);
  if (!anchor) return;
  if (!confirm(`删除与「${anchor.sender}」的全部聊天记录？此操作不可恢复。`)) return;
  try {
    const resp = await fetch(`${API_BASE}/messages/delete-contact`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ platform: anchor.platform, sender: anchor.sender }),
    });
    const data = await resp.json();
    if (!data.ok) { toast("删除失败：" + (data.detail || "未知错误")); return; }
  } catch (e) { /* 后端不可达也继续清前端 */ }
  // 前端同步移除
  const mids = messagesOfContact(key).map(m => m.id);
  state.messages = state.messages.filter(m => contactKeyOf(m) !== key);
  mids.forEach(id => { delete state.threads[id]; delete state.trace[id]; });
  closeChat();
  if (typeof loadBackendData === "function") loadBackendData();
  toast(`已删除与「${anchor.sender}」的会话`);
}

/* ---------- 清空全部聊天记录 ---------- */
async function clearAllMessages() {
  if (!confirm("清空全部聊天记录？所有会话将被删除，此操作不可恢复。")) return;
  try {
    const resp = await fetch(`${API_BASE}/messages/clear`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
    });
    const data = await resp.json();
    if (!data.ok) { toast("清空失败"); return; }
    toast(`已清空 ${data.deleted} 条聊天记录`);
  } catch (e) { /* 后端不可达也继续清前端 */ }
  state.messages = [];
  state.todos = [];
  state.threads = {};
  state.trace = {};
  closeChat();
  renderAll();
}

/* ---------- 重试发送 ----------
   same = 同一通道重发；switch = 切到备用通道重发（主备切换） */
function retrySend(msgId, index, useBackup) {
  const msg = state.messages.find(m => m.id === msgId);
  const bubble = getThread(msgId)[index];
  if (!msg || !bubble || bubble.from !== "me") return;

  const plan = planOf(msg);
  const channel = useBackup
    ? (bubble.channel === plan.primary ? plan.backup : plan.primary)
    : (bubble.channel || plan.primary);

  addTrace(msg.id, "重试发送",
    useBackup ? `主通道失败，切换至${CHANNELS[channel].name}重发` : `在${CHANNELS[channel].name}上重试`);
  toast(useBackup ? `已切换到${CHANNELS[channel].name}重发…` : `重新通过${CHANNELS[channel].name}发送…`);
  sendReply(msg, bubble.text, bubble, { channel, isRetry: true });
}

/* ---------- 快捷回复 ---------- */
function renderQuickReplies() {
  $("chatQuick").innerHTML = QUICK_REPLIES.map(t =>
    `<span class="quick-chip" data-text="${t}">${t}</span>`).join("");
  document.querySelectorAll(".quick-chip").forEach(chip => {
    chip.onclick = () => {
      const input = $("chatInput");
      input.value = input.value ? input.value + " " + chip.dataset.text : chip.dataset.text;
      updateConvPreview(input.value.trim());
      input.focus();
    };
  });
}

/* ---------- 表情面板 ---------- */
function renderEmojiPanel() {
  $("emojiPanel").innerHTML = EMOJIS.map(e =>
    `<span class="emoji-item" data-emoji="${e}">${e}</span>`).join("");
  document.querySelectorAll(".emoji-item").forEach(el => {
    el.onclick = () => {
      const input = $("chatInput");
      input.value += el.dataset.emoji;
      updateConvPreview(input.value.trim());
      input.focus();
    };
  });
}

function toggleEmojiPanel() {
  const panel = $("emojiPanel");
  if (panel.hidden) renderEmojiPanel();
  panel.hidden = !panel.hidden;
}

/* ---------- 工具栏其他按钮 ---------- */
function handleTool(name) {
  if (name === "file") {           // 真实文件发送（钉钉走机器人媒体上传 API）
    $("fileInput").value = "";
    $("fileInput").click();
    return;
  }
  if (name === "voice") {          // 语音输入：浏览器语音识别转文字（Web Speech API）
    toggleVoiceInput();
    return;
  }
  const tips = {
    screenshot: "演示环境：截图能力依赖各平台客户端，统一入口保留该扩展位",
  };
  toast(tips[name] || "该能力在演示环境中未启用");
}

/* ---------- 语音输入（Web Speech API：语音 → 文字填入输入框）----------
   点击语音按钮开始识别，再次点击/结束自动停；识别结果写入输入框后照常发送。
   浏览器不支持（如部分非 Chrome）时 toast 提示降级。 */
let voiceRec = null;       // SpeechRecognition 实例
let voiceActive = false;   // 是否正在监听

function toggleVoiceInput() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    toast("当前浏览器不支持语音识别，请使用 Chrome/Edge 打开，或改用文字输入");
    return;
  }
  if (voiceActive) { stopVoiceInput(); return; }

  try {
    voiceRec = new SR();
    voiceRec.lang = "zh-CN";
    voiceRec.interimResults = false;
    voiceRec.maxAlternatives = 1;

    voiceRec.onstart = () => {
      voiceActive = true;
      const btn = document.querySelector('[data-tool="voice"]');
      if (btn) btn.classList.add("listening");
      toast("🎤 正在聆听，请说话…（再次点击结束）");
    };
    voiceRec.onresult = (e) => {
      let text = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) text += e.results[i][0].transcript;
      }
      if (text) {
        const input = $("chatInput");
        // 已有内容时补空格，避免粘连
        input.value = (input.value ? input.value + " " : "") + text;
        updateConvPreview(input.value.trim());
        toast("已识别：" + text);
      }
    };
    voiceRec.onerror = (e) => {
      stopVoiceInput();
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        toast("麦克风权限被拒绝，请在浏览器地址栏允许麦克风权限");
      } else if (e.error !== "no-speech") {
        toast("语音识别失败：" + (e.error || "未知错误"));
      }
    };
    voiceRec.onend = () => {
      if (voiceActive) {   // 非手动停止时刷新按钮态
        stopVoiceInput();
      }
    };
    voiceRec.start();
  } catch (e) {
    toast("无法启动语音识别：" + (e.message || "请检查麦克风"));
    stopVoiceInput();
  }
}

function stopVoiceInput() {
  voiceActive = false;
  if (voiceRec) {
    try { voiceRec.stop(); } catch { /* 忽略 */ }
    voiceRec = null;
  }
  const btn = document.querySelector('[data-tool="voice"]');
  if (btn) btn.classList.remove("listening");
}

/* ---------- 文件发送（真实接口）----------
   POST ${API_BASE}/messages/:id/send-file（multipart）
   钉钉：媒体上传 API + 机器人 sampleFile 真实发到群；
   微信：RPA 通道（个人号无 API）。状态流转与文本回复一致。 */
async function handleFileSend(file) {
  const msg = state.messages.find(m => m.id === state.currentMsgId);
  if (!msg) return;
  if (file.size > 20 * 1024 * 1024) { toast("文件超过 20MB（钉钉机器人上传上限）"); return; }

  const bubble = {
    from: "me", text: `📎 [文件] ${file.name}`, time: nowTime(),
    sendStatus: "sending", channel: planOf(msg).primary,
  };
  appendThread(msg.id, bubble);
  toast(`正在上传「${file.name}」并发送到${PLATFORMS[msg.platform].name}...`);

  try {
    const realId = await resolveBackendId(msg);
    const fd = new FormData();
    fd.append("file", file, file.name);
    const resp = await fetch(`${API_BASE}/messages/${encodeURIComponent(realId)}/send-file`, {
      method: "POST",
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
      body: fd,
    });
    const data = await resp.json();
    if (data.ok) {
      bubble.channel = data.channel || bubble.channel;
      bubble.sendStatus = "sent";
      msg.status = "replied";
      addTrace(msg.id, "已回复", `文件发送成功：${file.name}`);
      loadThread(msg.id);   // 重新拉取 thread 拿到 fileId，气泡变为可点击下载
      renderAll();
      toast(`文件「${file.name}」已发送给 ${msg.sender}${msg.chat ? "（" + msg.chat + "）" : ""}`);
      // synced 由 WS 回流；2.5s 兜底
      setTimeout(() => {
        if (msg.status !== "synced") {
          bubble.sendStatus = "synced"; msg.status = "synced";
          addTrace(msg.id, "已同步到平台", `文件已回流至 ${PLATFORMS[msg.platform].name}`);
          renderAll();
        }
      }, 2500);
    } else {
      bubble.sendStatus = "failed";
      const d = data.detail;
      bubble.failReason = data.reason
        || (typeof d === "string" ? d : (d && (d.msg || d[0] && (d[0].msg || d[0].msgvalue))) )
        || `发送失败（HTTP ${resp.status}）`;
      msg.status = "failed";
      addTrace(msg.id, "发送失败", `文件发送失败：${bubble.failReason}`);
      renderAll();
      toast("文件发送失败：" + bubble.failReason);
    }
  } catch (e) {
    bubble.sendStatus = "failed";
    bubble.failReason = "后端不可达，请确认启动.bat 已运行";
    msg.status = "failed";
    renderAll();
    toast("文件发送失败：后端不可达");
  }
}

/* ---------- AI 自动回复 ----------
   开启后新消息进来由 AI 生成回复并经发送路由自动发到对应平台（后端真实执行） */
async function toggleAutoreply() {
  try {
    // 先查当前状态再取反（按钮点击时调用）
    const cur = await fetch(`${API_BASE}/ai/autoreply`, {
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    }).then(r => r.json());
    const resp = await fetch(`${API_BASE}/ai/autoreply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ enabled: !cur.enabled }),
    }).then(r => r.json());
    state.autoreplyOn = !!resp.enabled;
    renderAutoReplyBtn();
    toast(state.autoreplyOn
      ? "AI 自动回复已开启：新消息将由 AI 自动回复"
      : "AI 自动回复已关闭");
  } catch (e) {
    toast("后端不可达，无法切换自动回复");
  }
}

async function refreshAutoreplyState() {
  try {
    const cur = await fetch(`${API_BASE}/ai/autoreply`, {
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    }).then(r => r.json());
    state.autoreplyOn = !!cur.enabled;
    renderAutoReplyBtn();
  } catch (e) { /* 后端未启动时静默 */ }
}

function renderAutoReplyBtn() {
  const btn = $("autoReplyBtn");
  if (!btn) return;
  btn.classList.toggle("on", !!state.autoreplyOn);
  btn.title = state.autoreplyOn
    ? "AI 自动回复已开启（点击关闭）"
    : "AI 自动回复：开启后新消息由 AI 自动生成并发送回复";
}

/* ---------- 联系人角标 ---------- */
function refreshContactCount() {
  const el = $("contactCount");
  if (!el) return;
  const seen = new Set();
  state.messages.forEach(m => seen.add(`${m.platform}|${m.sender}`));
  el.textContent = seen.size;
}

/* ---------- 格式转换预览（折叠） ---------- */
function updateConvPreview(text) {
  const msg = state.messages.find(m => m.id === state.currentMsgId);
  if (!msg) return;
  const sample = text || "（回复内容）";
  $("convInternal").textContent = buildInternalFormat(msg, sample);
  $("convPlatformFmt").textContent = convertToPlatformFormat(msg.platform, sample);
}

/* ---------- 故障演练（演示用）----------
   开启后，下一次发送会在主通道失败，用来现场演示「失败 → 重试 / 切备用通道」 */
function toggleFault() {
  state.faultPending = !state.faultPending;
  renderFaultBtn();
  toast(state.faultPending
    ? "故障演练已开启：下一次发送将模拟主通道失败"
    : "已关闭故障演练，下次发送正常");
}

function renderFaultBtn() {
  const btn = $("faultBtn");
  if (!btn) return;
  btn.classList.toggle("on", !!state.faultPending);
  btn.title = state.faultPending
    ? "故障演练已开启：下一次发送将失败（点击取消）"
    : "故障演练：让下一次发送模拟通道失败，用于演示失败重试";
}

/* ---------- 发送 ---------- */
function sendFromChat() {
  const msg = state.messages.find(m => m.id === state.currentMsgId);
  if (!msg) return;
  const text = $("chatInput").value.trim();
  if (!text) { toast("请先填写回复内容"); return; }

  // 立即把气泡加入会话（发送中），通道取该平台主通道
  const bubble = {
    from: "me", text, time: nowTime(),
    sendStatus: "sending", channel: planOf(msg).primary,
  };
  appendThread(msg.id, bubble);

  $("chatInput").value = "";
  updateConvPreview("");
  toast(`正在转换为${PLATFORMS[msg.platform].name}格式并发送...`);

  sendReply(msg, text, bubble, {
    onReplied: () => renderFaultBtn(),
    onSynced: () => {
      renderFaultBtn();
      toast(`已发送给 ${msg.sender}${msg.chat ? "（" + msg.chat + "）" : ""}，状态已同步`);
    },
    onFailed: () => renderFaultBtn(),
  });
}
