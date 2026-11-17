/* ===== render.js — 界面渲染层 =====
   职责：筛选标签 / 会话列表（紧凑行，时间分组）/ 待办 / 统计 / 状态流转弹窗
   ============================================================ */

const DAY_NAME = { today: "今天", yesterday: "昨天", earlier: "更早" };

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------- 筛选标签 ----------
function renderChips() {
  const platList = [{ key: "all", name: "全部" }, ...Object.keys(PLATFORMS)
    .filter(k => k !== "all")
    .map(k => ({ key: k, name: PLATFORMS[k].name }))];

  $("platformChips").innerHTML = platList.map(p => {
    const offline = p.key !== "all" && !isPlatformConnected(p.key);
    return `
      <div class="chip ${state.filter === p.key ? "active" : ""} ${offline ? "offline" : ""}"
           data-pk="${p.key}"
           title="${offline ? "该平台未连接：历史消息可查看，发送会失败" : ""}">
        ${p.name}<span class="n">${countFor({ platform: p.key, status: state.statusFilter })}</span>
      </div>`;
  }).join("");

  $("statusChips").innerHTML = STATUS_FILTERS.map(f => `
    <div class="chip ${state.statusFilter === f.key ? "active" : ""}" data-sk="${f.key}">
      ${f.name}<span class="n">${countFor({ platform: state.filter, status: f.key })}</span>
    </div>`).join("");

  document.querySelectorAll("[data-pk]").forEach(el => {
    el.onclick = () => { state.filter = el.dataset.pk; renderAll(); };
  });
  document.querySelectorAll("[data-sk]").forEach(el => {
    el.onclick = () => { state.statusFilter = el.dataset.sk; renderAll(); };
  });
}

// ---------- 筛选面包屑 ----------
function renderFilterBar() {
  const bar = $("filterBar");
  const parts = [];
  if (state.filter !== "all") parts.push(PLATFORMS[state.filter].name);
  if (state.statusFilter !== "all") {
    parts.push(STATUS_FILTERS.find(f => f.key === state.statusFilter).name);
  }
  if (state.keyword) parts.push(`关键词「${state.keyword}」`);

  if (parts.length === 0) { bar.classList.remove("show"); return; }

  const total = state.messages.length;
  const shown = state.messages.filter(matchMessage).length;

  bar.classList.add("show");
  bar.innerHTML = `
    <span>${parts.join(' <span class="fb-and">且</span> ')} · ${shown}/${total} 条</span>
    <button class="fb-clear" id="clearFilter">清除</button>`;
  $("clearFilter").onclick = () => {
    state.filter = "all"; state.statusFilter = "all"; state.keyword = "";
    $("searchInput").value = "";
    renderAll();
  };
}

// ---------- 会话列表（微信式紧凑行：置顶 → 今天/昨天/更早）----------
const ICON = {
  pin: `<svg viewBox="0 0 24 24" class="flag-ic"><path d="M9 3h6l-1 5 4 4v2H6v-2l4-4-1-5z" fill="currentColor"/><line x1="12" y1="14.5" x2="12" y2="21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  mute: `<svg viewBox="0 0 24 24" class="flag-ic"><path d="M12 4a5 5 0 0 1 5 5v4l2 2H5l2-2V9a5 5 0 0 1 5-5z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M10 18a2 2 0 0 0 4 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><line x1="4" y1="4" x2="20" y2="20" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
};

function convRowHtml(m) {
  const flags = `${isPinned(m) ? `<i class="conv-flag pin" title="已置顶">${ICON.pin}</i>` : ""}` +
                `${isMuted(m) ? `<i class="conv-flag mute" title="免打扰">${ICON.mute}</i>` : ""}`;
  return `
    <div class="conv-item ${m.unread ? "unread" : ""} ${m.muted ? "muted" : ""} ${m.id === state.currentMsgId ? "active" : ""}"
         data-id="${m.id}">
      <div class="avatar"><span>${getAvatarText(m.sender)}</span><i class="av-dot ${m.platform}"></i></div>
      <div class="conv-main">
        <div class="conv-top">
          <span class="conv-name">${m.sender}</span>
          ${flags}
          <span class="status-badge ${m.status}">${STATUS_TEXT[m.status]}</span>
          <span class="conv-time">${m.time}</span>
        </div>
        <div class="conv-preview">${m.content}</div>
      </div>
    </div>`;
}

function renderMessages() {
  const list = state.messages.filter(matchMessage);
  const box = $("messageList");

  if (list.length === 0) {
    box.innerHTML = `
      <div class="empty-tip">
        <span class="empty-icon">📭</span>
        当前筛选下没有消息
      </div>`;
    return;
  }

  // 置顶区独立成组置顶展示，但计入所属天分组（今天/昨天/更早）的条数，
  // 保证分组标题数与「今日概览 · 今日新消息」等统计口径一致
  const pinned = list.filter(isPinned);
  const groups = { today: [], yesterday: [], earlier: [] };
  list.forEach(m => { (groups[m.day || "today"]).push(m); });

  let html = "";
  if (pinned.length) {
    html += `<div class="group-title">置顶 · ${pinned.length} 条</div>`;
    html += pinned.map(convRowHtml).join("");
  }
  for (const key of ["today", "yesterday", "earlier"]) {
    const nonPinned = groups[key].filter(m => !isPinned(m));
    if (groups[key].length === 0) continue;
    html += `<div class="group-title">${DAY_NAME[key]} · ${groups[key].length} 条</div>`;
    html += nonPinned.map(convRowHtml).join("");
  }
  box.innerHTML = html;

  // 行点击进会话；右键查看状态流转（置顶/免打扰在会话头部操作）
  box.querySelectorAll(".conv-item").forEach(item => {
    const id = item.dataset.id;
    item.onclick = () => openChat(id);
    item.oncontextmenu = (e) => { e.preventDefault(); openTrace(id); };
  });
}

// ---------- 待办 ----------
function renderTodos() {
  if (state.todos.length === 0) {
    $("todoList").innerHTML = `
      <div class="empty-tip">
        <span class="empty-icon">✅</span>
        没有待办事项，消息都已处理完
      </div>`;
    return;
  }
  const sorted = [...state.todos].sort((a, b) => a.done - b.done);
  $("todoList").innerHTML = sorted.map(t => `
    <div class="todo-item" data-msg="${t.msgId}">
      <div class="todo-check ${t.done ? "done" : ""}" data-id="${t.id}">✓</div>
      <div class="todo-main">
        <div class="todo-title ${t.done ? "done" : ""}">${t.title}</div>
        <div class="todo-meta">${PLATFORMS[t.platform].name} · ${t.detail}</div>
      </div>
      <span class="todo-deadline">${t.deadline}</span>
    </div>`).join("");

  // 点待办文字/内容 → 跳到对应消息的聊天对话框
  document.querySelectorAll(".todo-item").forEach(el => {
    el.onclick = (e) => {
      if (e.target.closest(".todo-check")) return;   // 勾选框另有处理
      const msgId = el.dataset.msg;
      const msg = state.messages.find(m => m.id === msgId);
      if (!msg) { toast("未找到对应消息"); return; }
      switchTab("messages");       // 切回消息列表
      openChat(msgId);             // 打开对应会话
      toast(`已打开「${msg.sender}」的会话`);
    };
  });

  document.querySelectorAll(".todo-check").forEach(el => {
    el.onclick = (e) => {
      e.stopPropagation();
      const t = state.todos.find(x => x.id === el.dataset.id);
      if (!t) return;
      t.done = !t.done;
      const msg = state.messages.find(m => m.id === t.msgId);
      if (msg && t.done && (msg.status === "received" || msg.status === "processing")) {
        msg.status = "synced";
        addTrace(msg.id, "已同步到平台", `待办「${t.title}」已完成，处理状态回流原平台`);
      }
      renderAll();
      toast(t.done ? "待办已完成，状态同步回原平台" : "已恢复为待办");
    };
  });
}

// ---------- 侧栏统计（始终为全局数字）----------
function renderStats() {
  // 未读统一口径：所有页面/筛选/chips 一律按原始未读计数，
  // 免打扰的未读只在下方文字单独说明，不再从数字里扣掉（避免两处数字不一致）
  const unreadMsgs = state.messages.filter(m => m.unread);
  const unread = unreadMsgs.length;
  const mutedUnread = state.messages.filter(m => m.unread && m.muted).length;
  const todo = state.todos.filter(t => !t.done).length;
  const replied = state.messages.filter(m => m.status === "replied" || m.status === "synced").length;

  $("statUnread").textContent = unread;
  $("statTodo").textContent = todo;
  $("statReplied").textContent = replied;

  const byPlat = { wechat: 0, dingtalk: 0 };
  unreadMsgs.forEach(m => { byPlat[m.platform] = (byPlat[m.platform] || 0) + 1; });
  const total = unread || 1;
  $("distBar").innerHTML = Object.keys(byPlat).map(k =>
    byPlat[k] ? `<i class="dist-${k}" style="width:${(byPlat[k] / total) * 100}%"></i>` : ""
  ).join("");
  $("statUnreadSub").textContent =
    `微信 ${byPlat.wechat} · 钉钉 ${byPlat.dingtalk}`;

  // 免打扰未读作为补充说明（数字已含它，仅提示有静音会话）
  const note = $("statMuteNote");
  note.hidden = !mutedUnread;
  note.textContent = mutedUnread ? `其中 ${mutedUnread} 条为免打扰会话` : "";

  $("tabMsgCount").textContent = state.messages.filter(matchMessage).length;
  $("tabTodoCount").textContent = todo;

  // 接入平台：随「应用连接」页的连接/断开实时变化
  const conn = connectedAppCount();
  const totalApps = state.apps.length;
  const allOnline = conn === totalApps;
  $("statApps").innerHTML = `${conn}/${totalApps} ` +
    `<span class="pill-ok ${allOnline ? "" : "off"}"><i></i>${allOnline ? "全部在线" : `${totalApps - conn} 个未连接`}</span>`;
  $("appConnCount").textContent = `${conn}/${totalApps}`;
  $("appConnCount").classList.toggle("warn", !allOnline);

  const filtering = state.filter !== "all" || state.statusFilter !== "all" || state.keyword;
  $("statCard").classList.toggle("muted", !!filtering);
}

// ---------- 顶栏个人资料标签 ----------
function renderTopbarUser() {
  const p = state.profile;
  $("pcAvatar").textContent = p.initial;
  $("pcName").textContent = p.cnName;
  $("pcRole").textContent = p.role;
}

function renderAll() {
  renderChips();
  renderFilterBar();
  renderMessages();
  renderTodos();
  renderStats();
  renderOverview();
  renderFaultBtn();
  renderAutoReplyBtn();
  if (typeof refreshContactCount === "function") refreshContactCount();
  if (typeof renderContactTabPanel === "function") renderContactTabPanel();  // 消息页联系人 tab
  renderTopbarUser();
  if (state.currentMsgId) { renderThread(); renderChatHead(state.messages.find(m => m.id === state.currentMsgId)); }
  // 视图层打开时同步刷新（后台来新消息 / 断开平台后数字要跟着变）
  if (state.view === "profile") renderProfile();
  if (state.view === "apps") renderApps();
}

// ---------- 状态流转弹窗 ----------
function openTrace(id) {
  const msg = state.messages.find(m => m.id === id);
  if (!msg) return;
  if (!state.trace[id]) {
    state.trace[id] = [{ step: "已接收", detail: `来自 ${PLATFORMS[msg.platform].name}（${msg.sender}）`, time: msg.time }];
  }
  $("traceList").innerHTML = state.trace[id].map((t, i, arr) => `
    <div class="trace-item">
      <div class="trace-dot-col">
        <div class="trace-dot"></div>
        ${i < arr.length - 1 ? `<div class="trace-line"></div>` : ""}
      </div>
      <div class="trace-content">
        <div class="trace-step">${t.step}</div>
        <div class="trace-detail">${t.detail} · ${t.time}</div>
      </div>
    </div>`).join("");
  $("traceModal").classList.add("show");
}
