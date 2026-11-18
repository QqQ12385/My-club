/* ===== views.js — 全屏视图层：个人资料 / 应用连接 / 联系人清单 =====
   职责：设置类页面与联系人页的渲染与交互（不碰消息列表与会话面板）
   数据：state.profile（用户信息）、state.apps（接入状态）、CHANNEL_PLAN（通道）
   ============================================================ */

const VIEW_META = {
  profile:  { title: "个人资料", sub: "账号信息 · 消息偏好 · 我的接入平台" },
  apps:     { title: "应用连接", sub: "平台接入 · 主备通道 · 连通性检测" },
  contacts: { title: "联系人清单", sub: "朋友清单 · 按平台聚合 · 点击查看消息并发送" },
};

/* ---------- 打开 / 关闭 ---------- */
function openView(name) {
  if (!VIEW_META[name]) return;
  state.view = name;

  $("viewTitle").textContent = VIEW_META[name].title;
  $("viewSub").textContent = VIEW_META[name].sub;
  $("viewProfile").hidden = name !== "profile";
  $("viewApps").hidden = name !== "apps";
  $("viewContacts").hidden = name !== "contacts";

  $("viewLayer").hidden = false;
  document.body.classList.add("view-open");

  if (name === "profile") renderProfile();
  if (name === "apps") renderApps();
  if (name === "contacts") renderContacts();
  $("viewLayer").querySelector(".view-scroll").scrollTop = 0;
}

function closeView() {
  state.view = null;
  $("viewLayer").hidden = true;
  document.body.classList.remove("view-open");
  renderAll();
}

/* ---------- 个人资料 ---------- */
function renderProfile() {
  const p = state.profile;
  const conn = connectedAppCount();
  const replied = state.messages.filter(m => m.status === "replied" || m.status === "synced").length;
  const unread = state.messages.filter(isAlertUnread).length;

  const editing = !!state.profileEditing;

  /* 基本信息：只读态 / 编辑态（工号、部门由企业目录同步，不开放编辑） */
  const row = (label, value) => `<div class="pf-row"><span>${label}</span><b>${value}</b></div>`;
  const input = (label, field, value, extra) =>
    `<div class="pf-row"><span>${label}</span><input class="pf-input" data-f="${field}" value="${value}" ${extra || ""}></div>`;

  const basicRows = editing
    ? input("姓名", "cnName", p.cnName, 'maxlength="12"') +
      input("英文名", "name", p.name, 'maxlength="20"') +
      input("企业邮箱", "email", p.email) +
      input("手机", "phone", p.phone, 'maxlength="20"') +
      input("所在地", "city", p.city, 'maxlength="12"') +
      row("工号 / 部门", `${p.staffNo} · ${p.dept}`) +
      row("时区 / 入职", `${p.tz} · ${p.joinedAt}`)
    : row("姓名", `${p.cnName}（${p.name}）`) +
      row("工号", p.staffNo) +
      row("部门", p.dept) +
      row("企业邮箱", p.email) +
      row("手机", p.phone) +
      row("所在地 / 时区", `${p.city} · ${p.tz}`) +
      row("入职时间", p.joinedAt);

  const appsHtml = state.apps.map(a => `
    <div class="pf-app-row">
      <i class="pf-app-dot ${a.key}"></i>
      <span class="pf-app-name">${PLATFORMS[a.key].name}</span>
      <span class="pf-app-acc">${a.account}</span>
      <span class="pf-app-state ${a.connected ? "on" : "off"}">${a.connected ? "已连接" : "未连接"}</span>
    </div>`).join("");

  const actionsHtml = p.actions.map(x => `
    <div class="pf-log">
      <span class="pf-log-time">${x.time}</span>
      <span class="pf-log-text">${x.text}</span>
    </div>`).join("");

  $("viewProfile").innerHTML = `
    <!-- 头部：身份卡 -->
    <div class="v-card pf-hero">
      <div class="pf-avatar">${p.initial}</div>
      <div class="pf-hero-main">
        <div class="pf-hero-top">
          <b>${p.cnName}</b>
          <span class="pf-tag">${p.name}</span>
          <span class="pf-tag solid">${p.role}</span>
        </div>
        <div class="pf-hero-sub">${p.dept} · ${p.org}</div>
        <div class="pf-hero-meta">工号 ${p.staffNo} · ${p.city} · ${p.tz}</div>
      </div>
      <div class="pf-hero-right">
        <div class="pf-kv"><b>${conn}<span>/${state.apps.length}</span></b><i>已接入平台</i></div>
        <div class="pf-kv"><b>${unread}</b><i>未读消息</i></div>
        <div class="pf-kv"><b>${replied}</b><i>已回复</i></div>
      </div>
    </div>

    <div class="pf-grid">
      <!-- 基本信息（可编辑） -->
      <div class="v-card">
        <div class="v-card-title">
          基本信息
          ${editing
            ? `<span class="pf-edit-actions">
                 <button class="v-link" data-edit="cancel">取消</button>
                 <button class="v-link strong" data-edit="save">保存修改</button>
               </span>`
            : `<button class="v-link" data-edit="start">修改</button>`}
        </div>
        <div class="pf-rows">${basicRows}</div>
        ${editing ? `<p class="pf-edit-hint">工号、部门、入职时间由企业目录同步，不可在此修改。</p>` : ""}
      </div>

      <!-- 消息偏好（可切换） -->
      <div class="v-card">
        <div class="v-card-title">消息偏好</div>

        <div class="pref-row">
          <div class="pref-main"><b>新消息桌面通知</b><span>收到新消息时在浏览器弹出提醒</span></div>
          <button class="switch ${p.prefs.notify ? "on" : ""}" data-pref="notify" role="switch"></button>
        </div>

        <div class="pref-row">
          <div class="pref-main"><b>免打扰时段</b><span>时段内不弹通知，未读仍正常计数</span></div>
          <button class="switch ${p.prefs.dnd ? "on" : ""}" data-pref="dnd" role="switch"></button>
        </div>
        <div class="pref-sub">当前时段：${p.prefs.dndRange}（可在后端设置中调整）</div>

        <div class="pref-row column">
          <div class="pref-main"><b>默认发送通道</b><span>回复时优先走哪条通道，失败自动切备用</span></div>
          <div class="seg" data-seg="route">
            <button data-route="api" class="${p.prefs.route === "api" ? "on" : ""}">API 优先</button>
            <button data-route="rpa" class="${p.prefs.route === "rpa" ? "on" : ""}">RPA 优先</button>
          </div>
        </div>
      </div>

      <!-- 账号与安全 -->
      <div class="v-card">
        <div class="v-card-title">账号与安全</div>
        <div class="pf-rows">
          <div class="pf-row"><span>登录方式</span><b>${p.loginType}</b></div>
          <div class="pf-row"><span>二次验证</span><b>${p.twoFactor ? "已开启" : "未开启"}</b></div>
          <div class="pf-row"><span>最近登录</span><b>${p.lastLogin.time}</b></div>
          <div class="pf-row"><span>登录设备</span><b>${p.lastLogin.device}</b></div>
          <div class="pf-row"><span>登录 IP</span><b>${p.lastLogin.ip}</b></div>
        </div>
        <button class="v-btn" id="pfLogout">退出登录</button>
      </div>

      <!-- 我的接入平台 -->
      <div class="v-card">
        <div class="v-card-title">
          我的接入平台
          <button class="v-link" data-goto="apps">管理连接 ›</button>
        </div>
        <div class="pf-apps">${appsHtml}</div>
        <p class="v-note">每个平台一条主通道 + 一条备用通道，主通道失败自动降级。</p>
      </div>
    </div>

    <!-- 最近操作 -->
    <div class="v-card">
      <div class="v-card-title">最近操作</div>
      <div class="pf-logs">${actionsHtml}</div>
    </div>`;

  // 成员管理（仅管理员）：列出全部账号，可切换角色
  if (p.role === "系统管理员") {
    loadMembersPanel();
  }
}

/* 成员管理面板：管理员查看所有账号并调整角色 */
async function loadMembersPanel() {
  const host = $("viewProfile");
  // 避免重复插入
  if (host.querySelector("#membersCard")) host.querySelector("#membersCard").remove();
  const card = document.createElement("div");
  card.className = "v-card";
  card.id = "membersCard";
  card.innerHTML = `<div class="v-card-title">成员管理</div><div class="pf-rows" id="memberRows">加载中…</div>`;
  host.appendChild(card);
  try {
    const resp = await fetch(`${API_BASE}/users`, {
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    });
    if (!resp.ok) throw new Error();
    const users = await resp.json();
    $("memberRows").innerHTML = users.map(u => `
      <div class="pf-row member-row">
        <span>${u.name} <small>（${u.account}）</small></span>
        <b>
          ${u.role === "admin" ? "系统管理员" : "普通用户"}
          <button class="v-link member-role-btn" data-account="${u.account}" data-to="${u.role === "admin" ? "user" : "admin"}">
            设为${u.role === "admin" ? "普通用户" : "管理员"}
          </button>
        </b>
      </div>`).join("");
  } catch (e) {
    $("memberRows").innerHTML = `<div class="pf-row"><span>成员列表加载失败（需要管理员登录）</span></div>`;
  }
}

/* 保存基本信息编辑
   TODO(后端对接): 换成 PATCH `${API_BASE}/me`，提交 {cnName, name, email, phone, city} */
function saveProfileEdit() {
  const p = state.profile;
  const next = {};
  $("viewProfile").querySelectorAll(".pf-input").forEach(inp => {
    next[inp.dataset.f] = inp.value.trim();
  });

  if (!next.cnName) { toast("姓名不能为空"); return; }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(next.email)) { toast("企业邮箱格式不正确"); return; }

  Object.assign(p, next);
  p.initial = p.cnName.charAt(0);
  p.actions.unshift({ time: "刚刚", text: "更新了个人基本信息" });

  state.profileEditing = false;
  renderProfile();
  renderAll();          // 顶栏头像与姓名同步
  toast("个人资料已保存");
}

/* ---------- 应用连接 ---------- */
function renderApps() {
  const conn = connectedAppCount();
  const todayIn = state.messages.filter(m => m.day === "today").length;
  const pending = state.messages.filter(m =>
    m.status === "received" || m.status === "processing" || m.status === "failed").length;

  // 防御：只渲染前端已知的平台（后端库若残留已下线平台不至于整页崩掉）
  const knownApps = state.apps.filter(a => PLATFORMS[a.key]);
  const cards = knownApps.map(a => {
    const plan = CHANNEL_PLAN[a.key] || { primary: "api", backup: "rpa" };
    return `
      <div class="app-card ${a.connected ? "" : "off"}">
        <div class="ac-head">
          <span class="ac-logo">${PLATFORMS[a.key].short}</span>
          <div class="ac-name">
            <b>${PLATFORMS[a.key].name}</b>
            <span>${a.org}</span>
          </div>
          <span class="ac-state ${a.connected ? "on" : "off"}"><i></i>${a.connected ? "已连接" : "未连接"}</span>
        </div>

        <div class="ac-rows">
          <div class="ac-row"><span>接入账号</span><b>${a.account}</b></div>
          <div class="ac-row">
            <span>主通道 / 备用</span>
            <b>
              <span class="ch-pill">${CHANNELS[plan.primary].short}</span>
              <span class="ch-pill ghost">${CHANNELS[plan.backup].short}</span>
            </b>
          </div>
          <div class="ac-row"><span>上次同步</span><b>${a.connected ? a.lastSync : "—"}</b></div>
          <div class="ac-row"><span>近 7 日成功率</span><b>${a.connected ? a.successRate : "—"}</b></div>
        </div>

        <div class="ac-note">${a.note}</div>

        <div class="ac-actions">
          <button data-app="${a.key}" data-act="test">测试连接</button>
          <button data-app="${a.key}" data-act="swap">切换主备</button>
          <button data-app="${a.key}" data-act="toggle" class="${a.connected ? "danger" : "primary"}">
            ${a.connected ? "断开连接" : "连接"}
          </button>
        </div>
      </div>`;
  }).join("");

  $("viewApps").innerHTML = `
    <!-- 汇总 -->
    <div class="apps-summary">
      <div class="as-item">
        <b>${conn}<span>/${state.apps.length}</span></b>
        <i>已连接平台</i>
      </div>
      <div class="as-item">
        <b>${todayIn}</b>
        <i>今日汇入消息</i>
      </div>
      <div class="as-item">
        <b>${pending}</b>
        <i>待处理</i>
      </div>
      <div class="as-item">
        <b>${state.apps.length}<span>/${state.apps.length}</span></b>
        <i>主备通道就绪</i>
      </div>
    </div>

    <div class="apps-grid">${cards}</div>

    <div class="apps-bottom">
      <!-- 添加应用 -->
      <div class="v-card add-app" id="addAppCard">
        <div class="v-card-title">添加应用</div>
        <p class="add-app-text">
          支持接入微信、钉钉，以及任何有网页端或客户端界面的平台。
          新平台只需实现一个连接器（接收 / 发送 / 健康检查三个方法），即可复用统一入口。
        </p>
        <div class="add-app-chips">
          <span>微信</span><span>钉钉</span><span class="ghost">更多平台 · 可扩展</span>
        </div>
        <button class="v-btn" id="addAppBtn">+ 添加新平台</button>
      </div>

      <!-- 通道机制说明 -->
      <div class="v-card">
        <div class="v-card-title">双通道机制</div>
        <div class="ch-explain">
          <div class="ch-line">
            <span class="ch-pill">API</span>
            <div>
              <b>开放平台接口</b>
              <span>实时、可回执，用于钉钉等有开放能力的平台</span>
            </div>
          </div>
          <div class="ch-line">
            <span class="ch-pill ghost">RPA</span>
            <div>
              <b>界面自动化采集</b>
              <span>无接口平台（如微信个人号）的兜底方案，定时轮询、低频操作</span>
            </div>
          </div>
        </div>
        <p class="v-note">
          主通道失败（限流、权限不足、页面异常）时自动切备用通道重发，
          发送结果与通道信息一并回流到会话气泡。
        </p>
      </div>
    </div>`;
}

/* ---------- 联系人聚合（消息自动聚合 + 手动添加的好友合并）---------- */
function buildContactList() {
  const map = new Map();
  state.messages.forEach(m => {
    const key = `${m.platform}|${m.sender}`;
    if (!map.has(key)) {
      map.set(key, {
        key, platform: m.platform, sender: m.sender,
        chat: m.chat || "", lastTime: m.time, lastText: m.content,
        unread: 0, count: 0, msgIds: [], convId: m.convId || "", friend: false,
      });
    }
    const c = map.get(key);
    c.count += 1;
    c.msgIds.push(m.id);
    if (m.convId && !c.convId) c.convId = m.convId;
    if (isAlertUnread(m)) c.unread += 1;
  });
  // 手动添加的好友：消息里没有也出现在清单里（带 id，可删除）
  (state.friends || []).forEach(f => {
    const key = `${f.platform}|${f.name}`;
    if (!map.has(key)) {
      map.set(key, { key, platform: f.platform, sender: f.name,
        chat: f.chat || "", lastTime: "—", lastText: "（暂无消息）",
        unread: 0, count: 0, msgIds: [], convId: "", friend: true, friendId: f.id });
    } else {
      map.get(key).friend = true;
      map.get(key).friendId = f.id;
    }
  });
  return [...map.values()].sort((a, b) => b.count - a.count);
}

/* ---------- 联系人清单（朋友清单，全屏视图）---------- */
function renderContacts() {
  const list = buildContactList();

  const connCount = new Set(list.map(c => c.platform)).size;
  const totalUnread = list.reduce((s, c) => s + c.unread, 0);

  const card = (c) => {
    const p = PLATFORMS[c.platform];
    return `
      <div class="app-card contact-card">
        <div class="ac-head">
          <span class="ac-logo">${getAvatarText(c.sender)}</span>
          <div class="ac-name">
            <b>${c.sender}${c.friend ? ' <em class="friend-badge">好友</em>' : ""}</b>
            <span>${c.chat || p.name}</span>
          </div>
          <span class="ac-state on"><i></i>${p.name}</span>
        </div>
        <div class="contact-last">
          <span class="contact-last-text">${c.lastText}</span>
          <span class="contact-last-time">${c.lastTime}</span>
        </div>
        <div class="ac-actions" style="border:none;padding-top:6px;">
          <button class="primary" data-send-contact="${c.sender}"
                  data-platform="${c.platform}" data-chat="${c.chat}" data-conv="${c.convId}">发消息</button>
          ${c.msgIds.length ? `<button data-open-msg="${c.msgIds[0]}">查看消息</button>` : ""}
          ${c.friendId ? `<button class="danger" data-del-friend="${c.friendId}" data-name="${c.sender}">删除好友</button>` : ""}
          ${c.unread ? `<span class="contact-unread">${c.unread} 未读</span>` : `<span class="contact-unread zero">已读</span>`}
          <span class="contact-unread zero">${c.count} 条</span>
        </div>
      </div>`;
  };

  $("viewContacts").innerHTML = `
    <div class="apps-summary">
      <div class="as-item"><b>${list.length}</b><i>联系人 / 会话对象</i></div>
      <div class="as-item"><b>${connCount}<span>/${state.apps.length}</span></b><i>涉及平台</i></div>
      <div class="as-item"><b>${totalUnread}</b><i>未读</i></div>
      <div class="as-item"><b>${state.messages.length}</b><i>累计消息</i></div>
    </div>
    <div class="apps-grid">
      ${list.length ? list.map(card).join("") : `<div class="v-card"><div class="v-card-title">暂无联系人</div><p class="v-note">收到平台消息后会自动聚合成联系人卡片。</p></div>`}
    </div>
    <p class="v-note" style="margin-top:14px;">
      联系人由各平台消息自动聚合（发送人 + 会话），体现连接器的统一数据模型：
      无论钉钉、微信，联系人与消息都是同一种内部格式。「发消息」可主动向该联系人发起消息，
      「查看消息」进入历史会话回复。
    </p>`;
}

/* ---------- 主动发消息：打开一个与该联系人的「发起新消息」输入浮层 ----------
   点「发消息」→ 弹出一个轻量输入框 → 走 POST /api/contacts/send 真实发送。
   钉钉有 conv_id 时机器人真实 @该人 发到群；微信走 RPA。 */
let contactSendTarget = null;   // { sender, platform, chat, convId }

function openContactSend(target) {
  contactSendTarget = target;
  $("contactSendName").textContent = target.sender;
  $("contactSendPlatform").textContent = PLATFORMS[target.platform].name + (target.chat ? " · " + target.chat : "");
  $("contactSendInput").value = "";
  const layer = $("contactSendLayer");
  layer.hidden = false;
  layer.classList.add("show");   // CSS 用 .show 控制显示（与 traceModal 一致）
  setTimeout(() => $("contactSendInput").focus(), 80);
}

function closeContactSend() {
  contactSendTarget = null;
  const layer = $("contactSendLayer");
  layer.classList.remove("show");
  layer.hidden = true;
}

async function submitContactSend() {
  const text = $("contactSendInput").value.trim();
  if (!text) { toast("请输入要发送的内容"); return; }
  if (!contactSendTarget) return;
  const t = contactSendTarget;

  const btn = $("contactSendBtn");
  btn.disabled = true;
  btn.textContent = "发送中…";
  try {
    const resp = await fetch(`${API_BASE}/contacts/send`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ platform: t.platform, sender: t.sender,
                             chat: t.chat, conv_id: t.convId, text }),
    });
    const data = await resp.json();
    if (data.ok) {
      closeContactSend();
      toast(`已发送给 ${t.sender}（${PLATFORMS[t.platform].name}）`);
      // 刷新消息列表以显示新落库的「我发出的」消息
      if (typeof loadBackendData === "function") loadBackendData();
    } else {
      toast("发送失败：" + (data.reason || "未知错误"));
    }
  } catch (e) {
    toast("后端不可达，请确认启动.bat 已运行");
  } finally {
    btn.disabled = false;
    btn.textContent = "发 送";
  }
}

/* ---------- 添加好友弹窗 ---------- */
function openFriendAdd() {
  $("friendNameInput").value = "";
  $("friendChatInput").value = "";
  $("friendPlatformSelect").value = "dingtalk";
  toggleFriendPlatformUI("dingtalk");
  const layer = $("friendAddLayer");
  layer.hidden = false;
  layer.classList.add("show");
  setTimeout(() => $("friendNameInput").focus(), 80);
}

/* 选「站内好友」时切换为从注册用户目录选人；其他平台为手动填写 */
function toggleFriendPlatformUI(platform) {
  const isUser = platform === "user";
  $("friendUserPick").hidden = !isUser;
  $("friendManualName").hidden = isUser;
  $("friendManualChat").hidden = isUser;
  if (isUser && !$("friendUserSelect").dataset.loaded) {
    fetch(`${API_BASE}/users/directory`, {
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    }).then(r => r.json()).then(users => {
      if (!Array.isArray(users)) throw new Error("接口不存在（请重启后端）");
      $("friendUserSelect").innerHTML = users.length
        ? users.map(u => `<option value="${u.account}">${u.name}（${u.account}${u.role === "admin" ? " · 管理员" : ""}）</option>`).join("")
        : `<option value="">暂无其他注册用户</option>`;
      $("friendUserSelect").dataset.loaded = "1";
    }).catch(() => {
      $("friendUserSelect").innerHTML = `<option value="">目录加载失败，请重启后端后刷新</option>`;
      delete $("friendUserSelect").dataset.loaded;
    });
  }
}

function closeFriendAdd() {
  const layer = $("friendAddLayer");
  layer.classList.remove("show");
  layer.hidden = true;
}

async function submitFriendAdd() {
  const platform = $("friendPlatformSelect").value;
  let name = $("friendNameInput").value.trim();
  let chat = $("friendChatInput").value.trim();
  if (platform === "user") {
    const acc = $("friendUserSelect").value;
    if (!acc) { toast("请选择要添加的注册用户"); return; }
    chat = acc;
    const m = $("friendUserSelect").selectedOptions[0]?.textContent.match(/^(.+?)（/);
    name = m ? m[1] : acc;
  }
  if (!name) { toast("请输入好友名称"); return; }
  const btn = $("friendAddBtn2");
  btn.disabled = true;
  btn.textContent = "添加中…";
  try {
    const resp = await fetch(`${API_BASE}/contacts/add`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
      },
      body: JSON.stringify({ name, platform, chat }),
    });
    const data = await resp.json();
    if (data.ok) {
      closeFriendAdd();
      toast(`已添加好友：${name}${platform === "user" ? "（站内，可互发消息）" : ""}`);
      if (typeof loadBackendData === "function") await loadBackendData();
      renderContactTabPanel();
      if (state.view === "contacts") renderContacts();
    } else {
      toast("添加失败：" + (data.detail || "未知错误"));
    }
  } catch (e) {
    toast("后端不可达，请确认启动.bat 已运行");
  } finally {
    btn.disabled = false;
    btn.textContent = "添 加";
  }
}

/* ---------- 消息页「联系人」tab 面板（紧凑列表，微信式）---------- */
function renderContactTabPanel() {
  const el = $("contactTabList");
  if (!el) return;
  const list = buildContactList();

  // tab 角标
  const cnt = $("tabContactCount");
  if (cnt) cnt.textContent = list.length;

  const row = (c) => {
    const p = PLATFORMS[c.platform];
    return `
      <div class="contact-row">
        <span class="cr-avatar">${getAvatarText(c.sender)}</span>
        <div class="cr-main">
          <div class="cr-line1">
            <b>${c.sender}</b>
            ${c.friend ? '<em class="friend-badge">好友</em>' : ""}
            <span class="cr-chat">${c.chat || p.name}</span>
            <span class="cr-time">${c.lastTime}</span>
          </div>
          <div class="cr-line2">
            <span class="cr-last">${c.lastText}</span>
            ${c.unread ? `<span class="cr-unread">${c.unread}</span>` : ""}
          </div>
          <div class="cr-actions">
            <button class="primary" data-send-contact="${c.sender}"
                    data-platform="${c.platform}" data-chat="${c.chat}" data-conv="${c.convId}">发消息</button>
            ${c.msgIds.length ? `<button data-open-msg="${c.msgIds[0]}">查看消息</button>` : ""}
            ${c.friendId ? `<button class="danger" data-del-friend="${c.friendId}" data-name="${c.sender}">删除</button>` : ""}
          </div>
        </div>
      </div>`;
  };

  el.innerHTML = list.length
    ? list.map(row).join("")
    : `<div class="ov-empty">暂无联系人 · 收到平台消息或手动添加好友后显示</div>`;
}

/* ---------- 删除好友 ---------- */
async function deleteFriend(id, name) {
  if (!confirm(`删除好友「${name}」？（仅删除好友记录，消息保留）`)) return;
  try {
    const resp = await fetch(`${API_BASE}/contacts/${id}`, {
      method: "DELETE",
      headers: window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {},
    });
    const data = await resp.json();
    if (data.ok) {
      state.friends = (state.friends || []).filter(f => f.id !== id);
      toast(`已删除好友：${name}`);
      renderContactTabPanel();
      if (state.view === "contacts") renderContacts();
    } else {
      toast("删除失败");
    }
  } catch (e) {
    toast("后端不可达，请确认启动.bat 已运行");
  }
}

/* ---------- 事件（容器级委托，渲染重建后依然有效）---------- */function initViewEvents() {
  $("viewBack").onclick = closeView;

  // 添加好友弹窗（消息页联系人 tab 与全屏视图共用）
  const fab = $("friendAddBtn");
  if (fab) fab.onclick = openFriendAdd;
  $("closeFriendAdd").onclick = closeFriendAdd;
  $("friendAddBtn2").onclick = submitFriendAdd;
  $("friendPlatformSelect").onchange = (e) => toggleFriendPlatformUI(e.target.value);
  $("friendNameInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); submitFriendAdd(); }
  });
  $("friendAddLayer").addEventListener("click", (e) => {
    if (e.target === $("friendAddLayer")) closeFriendAdd();
  });

/* 站内好友：优先打开与 123 一样的完整聊天页（有历史消息时）。
   站内会话 key 是 user|对方姓名；同时兼容「联系人显示名」与「账号」两种情况。 */
function openUserChat(name, conv) {
  // 先用 conv_id（user:账号）反查对方姓名，再退回显示名直接匹配
  const msg = state.messages.find(m =>
    m.platform === "user" && (
      (conv && m.convId === conv) ||
      m.sender === name ||
      (m.convId && m.convId === `user:${name}`)
    ));
  if (!msg) return false;
  // 清除可能残留的筛选，确保消息列表能看到这条会话
  state.filter = "all";
  state.statusFilter = "all";
  state.keyword = "";
  const kw = $("searchInput"); if (kw) kw.value = "";
  switchTab("messages");
  openContact(contactKeyOf(msg));
  const input = $("chatInput");
  if (input) input.focus();
  return true;
}

  // 消息页联系人 tab：发消息 / 查看消息 / 删除好友（与全屏视图同样的事件委托）
  const ctl = $("contactTabList");
  if (ctl) ctl.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del-friend]");
    if (del) { deleteFriend(del.dataset.delFriend, del.dataset.name); return; }
    const send = e.target.closest("[data-send-contact]");
    if (send) {
      if (send.dataset.platform === "user" && openUserChat(send.dataset.sendContact, send.dataset.conv)) return;
      openContactSend({
        sender: send.dataset.sendContact,
        platform: send.dataset.platform,
        chat: send.dataset.chat,
        convId: send.dataset.conv,
      });
      return;
    }
    const go = e.target.closest("[data-open-msg]");
    if (!go) return;
    switchTab("messages");
    openChat(go.dataset.openMsg);
    const input = $("chatInput");
    if (input) input.focus();
  });

  // 主动发消息浮层：关闭 / 发送 / Enter 发送
  $("closeContactSend").onclick = closeContactSend;
  $("contactSendBtn").onclick = submitContactSend;
  $("contactSendInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitContactSend();
    }
  });
  // 点击遮罩空白处关闭
  $("contactSendLayer").addEventListener("click", (e) => {
    if (e.target === $("contactSendLayer")) closeContactSend();
  });

  // 联系人清单：查看消息 → 打开会话；发消息 → 弹出主动发送输入框
  $("viewContacts").addEventListener("click", (e) => {
    const del = e.target.closest("[data-del-friend]");
    if (del) { deleteFriend(del.dataset.delFriend, del.dataset.name); return; }
    const send = e.target.closest("[data-send-contact]");
    if (send) {
      if (send.dataset.platform === "user" && openUserChat(send.dataset.sendContact, send.dataset.conv)) return;
      openContactSend({
        sender: send.dataset.sendContact,
        platform: send.dataset.platform,
        chat: send.dataset.chat,
        convId: send.dataset.conv,
      });
      return;
    }
    const go = e.target.closest("[data-open-msg]");
    if (!go) return;
    const mid = go.dataset.openMsg;
    closeView();
    openChat(mid);
    const input = $("chatInput");
    if (input) input.focus();
  });

  // 个人资料：偏好开关 / 通道偏好 / 跳转连接页 / 退出
  $("viewProfile").addEventListener("click", async (e) => {
    const sw = e.target.closest("[data-pref]");
    if (sw) {
      const key = sw.dataset.pref;
      state.profile.prefs[key] = !state.profile.prefs[key];
      renderProfile();
      toast(key === "notify"
        ? (state.profile.prefs.notify ? "已开启新消息通知" : "已关闭新消息通知")
        : (state.profile.prefs.dnd ? "已开启免打扰时段" : "已关闭免打扰时段"));
      return;
    }

    const segBtn = e.target.closest("[data-route]");
    if (segBtn) {
      state.profile.prefs.route = segBtn.dataset.route;
      renderProfile();
      toast(`默认发送通道已设为 ${CHANNELS[segBtn.dataset.route].name}`);
      return;
    }

    const goto = e.target.closest("[data-goto]");
    if (goto) { openView(goto.dataset.goto); return; }

    // 基本信息：修改 / 保存 / 取消
    const editBtn = e.target.closest("[data-edit]");
    if (editBtn) {
      const act = editBtn.dataset.edit;
      if (act === "start") { state.profileEditing = true; renderProfile(); }
      if (act === "cancel") { state.profileEditing = false; renderProfile(); }
      if (act === "save") saveProfileEdit();
      return;
    }

    if (e.target.closest("#pfLogout")) {
      closeView();
      logout();
      return;
    }

    // 成员管理：切换角色
    const roleBtn = e.target.closest(".member-role-btn");
    if (roleBtn) {
      const acc = roleBtn.dataset.account, to = roleBtn.dataset.to;
      if (!confirm(`将该成员角色改为「${to === "admin" ? "系统管理员" : "普通用户"}」？`)) return;
      try {
        const resp = await fetch(`${API_BASE}/users/${encodeURIComponent(acc)}/role`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            ...(window.AUTH_TOKEN ? { "Authorization": "Bearer " + AUTH_TOKEN } : {}),
          },
          body: JSON.stringify({ role: to }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) { toast("设置失败：" + (data.detail || "未知错误")); return; }
        toast(`已将 ${acc} 设为${to === "admin" ? "系统管理员" : "普通用户"}`);
        loadMembersPanel();
      } catch (err) { toast("设置失败：后端不可达"); }
      return;
    }
  });

  // 应用连接：测试 / 切换主备 / 连接与断开 / 添加应用
  $("viewApps").addEventListener("click", (e) => {
    if (e.target.closest("#addAppBtn") || e.target.closest("#addAppCard")) {
      toast("新平台接入：实现接收 / 发送 / 健康检查三个方法即可复用统一入口");
      return;
    }

    const btn = e.target.closest("[data-act]");
    if (!btn) return;

    const key = btn.dataset.app;
    const app = getApp(key);
    if (!app) return;
    const name = PLATFORMS[key].name;

    if (btn.dataset.act === "test") {
      if (!app.connected) { toast(`${name}未连接，请先连接后再测试`); return; }
      const ms = 90 + Math.floor(Math.random() * 120);
      toast(`${name}连通性正常 · 往返延迟 ${ms}ms`);
      return;
    }

    if (btn.dataset.act === "swap") {
      const next = swapPrimaryChannel(key);
      renderApps();
      renderAll();
      toast(`${name}主通道已切换为 ${CHANNELS[next.primary].name}（备用 ${CHANNELS[next.backup].short}）`);
      return;
    }

    if (btn.dataset.act === "toggle") {
      if (app.connected) {
        setAppConnected(key, false);
        renderApps();
        renderAll();
        toast(`${name}已断开：历史消息仍可查看，发送将失败`);
        return;
      }
      // 连接过程给一个短延时，贴近真实握手
      btn.disabled = true;
      btn.textContent = "连接中…";
      setTimeout(() => {
        setAppConnected(key, true);
        renderApps();
        renderAll();
        toast(`${name}连接成功，开始接收消息`);
      }, 800);
    }
  });
}
