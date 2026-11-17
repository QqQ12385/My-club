/* ===== app.js — 应用入口 =====
   职责：事件绑定 + 初始化启动
   模块加载顺序见 index.html 底部（config → mock-data → core → ui → app）
   ============================================================ */

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
}

function init() {
  // 选项卡切换
  document.querySelectorAll(".tab").forEach(t => {
    t.onclick = () => switchTab(t.dataset.tab);
  });

  // 搜索
  $("searchInput").oninput = (e) => {
    state.keyword = e.target.value.trim();
    renderAll();
  };

  // 全部标为已读
  $("markAllRead").onclick = () => {
    const n = state.messages.filter(m => m.unread).length;
    state.messages.forEach(m => m.unread = false);
    renderAll();
    toast(n ? `已将 ${n} 条消息标为已读` : "当前没有未读消息");
  };

  // 帮助气泡（侧栏底部）
  $("helpBtn").onclick = (e) => {
    e.stopPropagation();
    $("helpPop").classList.toggle("show");
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#helpPop") && !e.target.closest("#helpBtn")) {
      $("helpPop").classList.remove("show");
    }
  });

  // 会话面板
  $("chatClose").onclick = closeChat;
  $("chatSend").onclick = sendFromChat;
  $("chatTrace").onclick = () => {
    if (state.currentMsgId) openTrace(state.currentMsgId);
  };

  // 会话头部：置顶 / 免打扰
  $("chatPin").onclick = () => {
    const m = togglePin(state.currentMsgId);
    if (!m) return;
    renderAll();
    toast(m.pinned ? "已置顶，会话固定在列表顶部" : "已取消置顶");
  };
  $("chatMute").onclick = () => {
    const m = toggleMute(state.currentMsgId);
    if (!m) return;
    renderAll();
    toast(m.muted
      ? "已开启免打扰，该会话未读不再计入未读提醒"
      : "已关闭免打扰，未读恢复正常提醒");
  };

  // 故障演练（演示发送失败与重试）
  $("faultBtn").onclick = toggleFault;
  $("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFromChat(); }
  });
  $("chatInput").oninput = (e) => updateConvPreview(e.target.value.trim());
  $("convToggle").onclick = () => {
    updateConvPreview($("chatInput").value.trim());
    $("convDetail").classList.toggle("open");
  };

  // 工具栏：表情面板 + 其他能力提示
  $("emojiBtn").onclick = (e) => { e.stopPropagation(); toggleEmojiPanel(); };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#emojiPanel") && !e.target.closest("#emojiBtn")) {
      $("emojiPanel").hidden = true;
    }
  });
  document.querySelectorAll(".tool-btn[data-tool]").forEach(btn => {
    btn.onclick = () => handleTool(btn.dataset.tool);
  });
  // 文件选择 → 真实发送（钉钉媒体上传 API）
  $("fileInput").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) handleFileSend(f);
  });

  // 状态流转弹窗
  $("closeTraceModal").onclick = () => $("traceModal").classList.remove("show");
  document.querySelectorAll(".modal-mask").forEach(m => {
    m.onclick = (e) => { if (e.target === m) m.classList.remove("show"); };
  });

  // 工作台概览（会话面板空置时）
  initOverviewEvents();

  // 侧栏收起 / 展开（窄屏时用 .side-open 控制显隐，宽屏用 .side-collapsed）
  $("sidebarCollapse").onclick = () => {
    const layout = document.querySelector(".layout");
    layout.classList.add("side-collapsed");
    layout.classList.remove("side-open");
    $("sidebarExpand").hidden = false;
  };
  $("sidebarExpand").onclick = () => {
    const layout = document.querySelector(".layout");
    layout.classList.remove("side-collapsed");
    layout.classList.add("side-open");
    $("sidebarExpand").hidden = true;
  };

  // 统计卡行点击 → 跳到对应筛选/选项卡
  document.querySelectorAll("[data-stat-jump]").forEach(el => {
    el.onclick = () => {
      const t = el.dataset.statJump;
      if (t === "unread") {
        state.statusFilter = "unread"; state.filter = "all"; switchTab("messages");
        toast("已筛选：全部平台的未读消息");
      } else if (t === "replied") {
        state.statusFilter = "done"; state.filter = "all"; switchTab("messages");
        toast("已筛选：已回复的消息");
      } else if (t === "todo") {
        switchTab("todos"); toast("已切换到待办列表");
      }
      renderAll();
    };
  });

  // 顶栏入口：联系人 / 个人资料 / 应用连接 / 导出记录
  const contactsBtn = $("contactsBtn");
  if (contactsBtn) contactsBtn.onclick = () => openView("contacts");
  $("profileBtn").onclick = () => openView("profile");
  $("appsBtn").onclick = () => openView("apps");
  const arBtn = $("autoReplyBtn");
  if (arBtn) arBtn.onclick = toggleAutoreply;
  const exportBtn = $("exportBtn");
  if (exportBtn) exportBtn.onclick = () => {
    window.open("/api/messages/export", "_blank");
    toast("已导出消息记录 CSV（UTF-8，Excel 可直接打开）");
  };
  initViewEvents();

  // Esc 关闭视图层
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.view) closeView();
  });

  // 初始流转记录
  state.messages.forEach(m => {
    state.trace[m.id] = [{ step: "已接收", detail: `来自 ${PLATFORMS[m.platform].name}（${m.sender}）`, time: m.time }];
    if (m.status !== "received") {
      state.trace[m.id].push({ step: STATUS_TEXT[m.status], detail: "（历史状态，本次接入前发生）", time: "-" });
    }
  });

  renderAll();
  refreshContactCount();
  refreshAutoreplyState();   // 拉取 AI 自动回复开关状态
  initLogin();       // 登录页：未记住登录时挡住主界面
  connectWebSocket();
}

init();
