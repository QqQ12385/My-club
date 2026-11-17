/* ===== login.js — 登录页 =====
   职责：登录校验、记住登录状态、扫码登录演示、退出登录
   说明：演示环境用前端硬校验（DEMO_ACCOUNT），真实环境换成 POST `${API_BASE}/auth/login`，
        后端返回 token 后存起来，WebSocket 建连时带上
   ============================================================ */

const DEMO_ACCOUNT = {
  pass: "demo123",
  aliases: ["gary", "gary@xingchen-tech.com", "xc-1024"],
};
const REMEMBER_KEY = "umc.remember";
const REMEMBER_USER_KEY = "umc.lastUser";
let lastUserCache = "";   // 内存缓存：localStorage 不可用时仍能带回上次账号

/* ---------- 本地记住登录（file:// 下 localStorage 可能被限制，统一 try 包裹）---------- */
function readRemember() {
  try { return localStorage.getItem(REMEMBER_KEY) === "1"; } catch { return false; }
}
function saveRemember(on) {
  try {
    if (on) localStorage.setItem(REMEMBER_KEY, "1");
    else localStorage.removeItem(REMEMBER_KEY);
  } catch { /* 忽略无痕模式等限制 */ }
}
function saveLastUser(u) {
  lastUserCache = u || "";              // 内存兜底：无痕模式 / file:// 受限时也能带回账号
  try { localStorage.setItem(REMEMBER_USER_KEY, u); } catch { /* 同上 */ }
}
function readLastUser() {
  if (lastUserCache) return lastUserCache;
  try { return localStorage.getItem(REMEMBER_USER_KEY) || ""; } catch { return ""; }
}

/* ---------- 显示 / 隐藏 ---------- */
function showLogin() {
  $("loginLayer").hidden = false;
  document.body.classList.add("login-open");
  setLoginError("");
  $("loginPass").value = "";

  const last = readLastUser();
  if (last && !$("loginUser").value) $("loginUser").value = last;

  setTimeout(() => {
    ($("loginUser").value ? $("loginPass") : $("loginUser")).focus();
  }, 80);
}

function hideLogin() {
  $("loginLayer").hidden = true;
  document.body.classList.remove("login-open");
}

function setLoginError(text) {
  const box = $("loginError");
  box.hidden = !text;
  box.textContent = text || "";
  $("lgFieldUser").classList.toggle("error", !!text);
  $("lgFieldPass").classList.toggle("error", !!text);
}

/* ---------- 登录成功 / 退出 ---------- */
function finishLogin() {
  state.loggedIn = true;
  saveRemember($("loginRemember").checked);
  // 扫码登录时账号框可能为空，退回到资料里的企业邮箱
  saveLastUser($("loginUser").value.trim() || state.profile.email);
  hideLogin();
  renderAll();

  // 已记住登录时，记录一下本次登录到资料页的最近操作
  state.profile.lastLogin = { time: "刚刚", device: "Windows · Chrome", ip: "10.20.31.86" };
}

/* 把后端返回的 user 同步到 state.profile（含真实角色），并刷新顶栏 */
function applyProfile(user) {
  if (!user) return;
  state.profile = { ...state.profile, ...user };
  state.profile.initial = (user.cnName || user.name || "用").charAt(0);
  if (typeof renderTopbarUser === "function") renderTopbarUser();
}

function doLoginSuccess(msg) {
  setLoginError("");
  finishLogin();
  toast(msg || `欢迎回来，${state.profile.cnName}`);
  // 登录后拉取后端真实数据替换 mock（WS 若已连上 onopen 可能早于登录触发，这里补一次）
  if (typeof loadBackendData === "function") loadBackendData();
}

function logout() {
  state.loggedIn = false;
  saveRemember(false);
  $("loginRemember").checked = false;
  $("loginUser").value = readLastUser();
  showLogin();
  toast("已退出登录");
}

/* ---------- 账号密码登录 ---------- */
async function attemptLogin() {
  const user = $("loginUser").value.trim().toLowerCase();
  const pass = $("loginPass").value.trim();

  if (!user) { setLoginError("请输入账号"); $("loginUser").focus(); return; }
  if (!pass) { setLoginError("请输入密码"); $("loginPass").focus(); return; }

  setLoginError("");
  const btn = $("loginBtn");
  btn.disabled = true;
  btn.textContent = "登录中…";

  // 已对接后端：POST ${API_BASE}/auth/login → { token, user }
  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account: user, password: pass }),
    });
    if (resp.status === 401) {
      setLoginError("账号或密码不正确，可使用下方演示账号体验");
      $("loginPass").select();
      return;
    }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    window.AUTH_TOKEN = data.token;              // 后续 REST 请求带 token
    applyProfile(data.user);                     // 用后端资料（含真实角色）覆盖并刷新顶栏
    doLoginSuccess();
  } catch (e) {
    // 后端不可达：退回本地演示校验，保证答辩不翻车
    const ok = DEMO_ACCOUNT.aliases.includes(user) && pass === DEMO_ACCOUNT.pass;
    if (ok) doLoginSuccess("（离线演示模式）欢迎回来");
    else { setLoginError("无法连接后端服务，且账号校验失败"); $("loginPass").select(); }
  } finally {
    btn.disabled = false;
    btn.textContent = "登 录";
  }
}

/* ---------- 注册 ---------- */
async function attemptRegister() {
  const name = $("loginName").value.trim();
  const user = $("loginUser").value.trim().toLowerCase();
  const pass = $("loginPass").value.trim();

  if (!name) { setLoginError("请输入姓名"); $("loginName").focus(); return; }
  if (!user) { setLoginError("请输入账号（字母数字组合）"); $("loginUser").focus(); return; }
  if (pass.length < 6) { setLoginError("密码至少 6 位"); $("loginPass").focus(); return; }

  setLoginError("");
  const btn = $("loginBtn");
  btn.disabled = true;
  btn.textContent = "注册中…";

  try {
    const resp = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account: user, password: pass, name }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setLoginError(data.detail || "注册失败，请重试");
      return;
    }
    window.AUTH_TOKEN = data.token;
    applyProfile(data.user);
    doLoginSuccess("注册成功，欢迎加入");
  } catch (e) {
    setLoginError("无法连接后端服务，请确认后端已启动");
  } finally {
    btn.disabled = false;
    btn.textContent = "登 录";
  }
}

/* ---------- 登录/注册模式切换 ---------- */
let loginMode = "login";   // login | register
function switchLoginMode(mode) {
  loginMode = mode;
  const isReg = mode === "register";
  $("loginTitle").textContent = isReg ? "注册账号" : "登录";
  $("loginSub").textContent = isReg ? "创建你的统一消息中心账号" : "使用企业账号登录统一消息中心";
  $("lgFieldName").hidden = !isReg;
  $("loginUser").placeholder = isReg ? "设置账号（字母数字组合）" : "工号 / 企业邮箱";
  $("loginBtn").textContent = isReg ? "注 册" : "登 录";
  $("loginSwitchHint").textContent = isReg ? "已有账号？" : "还没有账号？";
  $("loginSwitch").textContent = isReg ? "返回登录" : "注册账号";
  $("loginRemember").closest(".lg-row").style.display = isReg ? "none" : "";
  $("loginQr").style.display = isReg ? "none" : "";
  setLoginError("");
}

/* ---------- 钉钉扫码登录（OAuth 授权登录）----------
   流程：前端 GET /auth/dingtalk/url 拿授权 URL → window.open 打开钉钉授权页
   → 用户扫码授权 → 钉钉回跳后端 callback → 后端换用户信息、签 token
   → 后端落地页 postMessage 回传 token+user → 前端收下完成登录。 */
async function dingtalkQrLogin() {
  setLoginError("");
  try {
    const resp = await fetch(`${API_BASE}/auth/dingtalk/url`);
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      setLoginError(data.detail || "钉钉扫码登录未配置（需在开放平台开通扫码登录并配置回调）");
      return;
    }
    const data = await resp.json();
    // 打开授权窗口（新窗口，扫码后钉钉回跳，postMessage 回传）
    const win = window.open(data.url, "dingtalk-login", "width=460,height=620");
    if (!win) { setLoginError("浏览器拦截了弹窗，请允许弹出窗口后重试"); return; }
    setLoginError("已打开钉钉授权页，请用钉钉 App 扫码…");

    // 监听回传（后端 callback 页 window.opener.postMessage）
    const handler = (e) => {
      if (!e.data || e.data.type !== "dingtalk-login") return;
      window.removeEventListener("message", handler);
      const { token, user } = e.data;
      window.AUTH_TOKEN = token;
      applyProfile(user);
      doLoginSuccess(`钉钉扫码登录成功，欢迎 ${user.cnName || user.name}`);
    };
    window.addEventListener("message", handler);
    // 兜底：30 秒后若未回传，提示可重试
    setTimeout(() => {
      window.removeEventListener("message", handler);
      setLoginError("");
    }, 30000);
  } catch (e) {
    setLoginError("无法连接后端服务，无法发起钉钉扫码登录");
  }
}

/* ---------- 事件绑定 ---------- */
function initLogin() {
  $("loginBtn").onclick = () => loginMode === "register" ? attemptRegister() : attemptLogin();

  [$("loginUser"), $("loginPass"), $("loginName")].forEach(el => {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); loginMode === "register" ? attemptRegister() : attemptLogin(); }
    });
  });

  $("loginSwitch").onclick = () => switchLoginMode(loginMode === "register" ? "login" : "register");

  $("loginDemo").onclick = () => {
    if (loginMode === "register") switchLoginMode("login");
    $("loginUser").value = "gary";
    $("loginPass").value = DEMO_ACCOUNT.pass;
    attemptLogin();
  };

  $("loginQr").onclick = () => {
    dingtalkQrLogin();
  };

  $("loginForget").onclick = () => {
    setLoginError("请联系信息化中心重置密码（分机 8021）");
  };

  // 勾选「记住登录」时立即写入，避免用户没点登录就关闭页面
  $("loginRemember").onchange = (e) => saveRemember(e.target.checked);

  // 已记住登录：跳过登录页
  if (readRemember()) {
    state.loggedIn = true;
    hideLogin();
    $("loginRemember").checked = true;
  } else {
    showLogin();
  }
}
