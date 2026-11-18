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
  state.currentMsgId = id;
  if (msg.unread) { msg.unread = false; renderAll(); }

  $("chatEmpty").hidden = true;
  $("chatBody").hidden = false;

  renderChatHead(msg);
  renderThread();
  renderQuickReplies();
  $("chatInput").value = "";
  $("emojiPanel").hidden = true;
  $("convDetail").classList.remove("open");
  updateConvPreview("");
  renderAll();

  // 后端真数据模式下，异步拉取该会话的历史 thread（含我方回复），拉到后刷新
  loadThread(id);
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
      from: t.from === "me" ? "me" : "them",
      text: t.text,
      time: t.time,
      sendStatus: t.sendStatus || (t.from === "me" ? "synced" : undefined),
      channel: t.channel || undefined,
    }));
    if (mapped.length) {
      state.threads[msgId] = mapped;
      // 仅当还在看这条消息时刷新（避免刷新别的会话）
      if (state.currentMsgId === msgId) renderThread();
    }
  } catch (e) { /* 忽略，保留本地 */ }
}

function closeChat() {
  state.currentMsgId = null;
  $("chatBody").hidden = true;
  $("chatEmpty").hidden = false;
  renderAll();
}

function renderChatHead(msg) {
  if (!msg) return;
  const plan = planOf(msg);
  $("chatAvatar").innerHTML =
    `<span>${getAvatarText(msg.sender)}</span><i class="av-dot ${msg.platform}"></i>`;
  $("chatName").textContent = msg.sender;
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

/* ---------- 会话气泡 ---------- */
function renderThread() {
  const msg = state.messages.find(m => m.id === state.currentMsgId);
  if (!msg) return;
  const thread = getThread(msg.id);
  const plan = planOf(msg);

  $("chatThread").innerHTML = thread.map((t, idx) => {
    if (t.from === "me") {
      const ch = t.channel || plan.primary;
      const chDef = CHANNELS[ch] || { name: ch || "未知通道", short: ch || "?" };   // 未知通道兜底，避免渲染中断
      const failed = t.sendStatus === "failed";
      const stText = t.sendStatus === "sending" ? "发送中…"
        : t.sendStatus === "sent" ? "已发送，等待平台回执"
        : t.sendStatus === "synced" ? `已同步到${PLATFORMS[msg.platform].name}`
        : "";
      const target = msg.chat ? `回给 ${msg.sender} · ${msg.chat}` : `回给 ${msg.sender}`;
      return `
        <div class="bubble-row me">
          <div class="bubble me-bubble ${t.sendStatus === "sending" ? "sending" : ""} ${failed ? "failed" : ""}">
            <div class="bubble-target">→ ${target}</div>
            <div class="bubble-text">${t.text}</div>
            ${failed ? `<div class="bubble-fail">发送失败 · ${t.failReason}</div>` : ""}
            <div class="bubble-status">
              ${stText ? stText + " · " : ""}${t.time}
              <span class="ch-tag ${ch}" title="经${chDef.name}发送">${chDef.short}</span>
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
        <div class="bubble them-bubble">
          <div class="bubble-text">${t.text}</div>
          <div class="bubble-status">${t.time}</div>
        </div>
      </div>`;
  }).join("");

  // 失败气泡上的重试入口
  $("chatThread").querySelectorAll("[data-retry]").forEach(btn => {
    btn.onclick = () => retrySend(msg.id, Number(btn.dataset.retry), btn.dataset.switch === "1");
  });

  const box = $("chatThread");
  box.scrollTop = box.scrollHeight;
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
      bubble.failReason = data.reason || "文件发送失败";
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
