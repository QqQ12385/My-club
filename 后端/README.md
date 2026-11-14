# 统一消息管理后端 — 成员 A 交付说明

> 赛题 1/A「多平台连接器与统一消息管理」· 成员 A（后端/集成）
> 技术栈：Python FastAPI + SQLite + httpx + DeepSeek API
> 接口契约与成员 B 前端 README 第四节**完全一致**，前端只需改 `js/config.js` 两个地址（已经是 8080，默认不用改）。

## 一、30 秒跑起来

```
双击 启动.bat
```
（首次会自动建虚拟环境装依赖；之后直接启动，监听 `http://localhost:8080`）

> ⚠️ **后端必须由你自己在系统终端里启动**（双击 `启动.bat`）。
> 不要在 AI 助手（WorkBuddy/CodeBuddy 等）的沙箱里让 AI 帮你起后端——沙箱有网络隔离和代理，
> AI 起的 uvicorn 进程会随对话轮次结束被回收，或端口被沙箱代理拦截（表现为 `/api/health` 返回 502），
> 最终还是要回到你自己双击 `启动.bat` 这一步。这是本机开发环境的固定动作，请养成习惯。

**推荐访问方式**：浏览器打开 `http://localhost:8080/`（后端已内置 UI 静态托管）。
> 不要双击 `index.html`（file:// 打开会因跨域拦截 fetch，导致「界面显示已同步但平台收不到」）。

自检：浏览器打开 `http://localhost:8080/api/health`，返回 `{"ok":true,...}` 即成功。
登录后右上角显示 **「已连接后端 · 实时刷新」**。

## 二、文件结构

```
后端/
├── 启动.bat                  一键启动
├── requirements.txt
├── .env.example              配置模板（复制为 .env 填写）
└── app/
    ├── main.py               全部 REST 接口 + WebSocket + 种子数据 + 注册/角色认证
    ├── normalize.py          归一化层（各平台消息 → 统一 Message → 去重 → 落库）
    ├── send_router.py        发送路由（主通道失败自动降级备用通道）
    ├── format_adapter.py     格式转换（内部统一格式 ↔ 平台格式，与前端同规则）
    ├── ai.py                 DeepSeek：智能分类 / 回复建议 / 每日摘要
    ├── config.py             读 .env
    ├── db.py                 SQLite（消息/会话/流转记录/应用/资料/用户表）
    ├── ws.py                 WebSocket 广播
    └── connectors/__init__.py  钉钉Webhook / 微信RPA 两连接器
```

## 三、两种模式（重点）

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| **真实模式** | `.env` 填了对应凭据 | 钉钉调真实接口发送，RPA 调 Power Automate 流，DeepSeek 真实推理 |
| **模拟模式** | 不填凭据（默认） | 连接器返回成功但标注 `simulated`，闭环完整可演示；DeepSeek 降级为规则分类 |

**三种功能对凭据的要求：**
1. **AI 功能（要 API Key）**：`DEEPSEEK_API_KEY` 填入 → `/api/ai/*` 三个接口变成真实大模型输出；
2. **平台 API 通道（要平台凭据）**：钉钉 Webhook；
3. **RPA 通道（不需要任何 API）**：默认模拟；接真 Power Automate 时把 `RPA_MODE=power_automate`、`RPA_FLOW_URL` 指向流触发地址。

## 四、接口清单（与前端契约对应）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/login | `{account,password}` → `{token,user}`（查 users 表，含角色） |
| POST | /api/auth/register | `{account,password,name}` → 注册为**普通用户**并返回 token |
| POST | /api/auth/logout | 退出 |
| GET / PATCH | /api/me | 个人资料读/改（带 token 返回对应用户真实角色） |
| GET | /api/apps | 应用连接列表 |
| POST | /api/apps/{key}/connect · disconnect · test | 连接/断开/测试 |
| PATCH | /api/apps/{key}/channel | 切主备通道 |
| GET | /api/messages?platform=&status=&keyword= | 消息列表（筛选） |
| GET | /api/messages/{id}/thread | 会话上下文 |
| POST | /api/messages/{id}/reply | 回复（选通道→转格式→发送→降级→状态回流） |
| POST | /api/collector/incoming | **归一化入口**（平台回调/RPA 采集流都打到这，含去重） |
| POST | /api/ai/classify · GET /api/ai/suggest/{id} · GET /api/ai/summary | AI 三件套 |
| WS | /ws | 推送 `new_message` / `status_update` / `channel_update` |

## 五、业务闭环实现（对应 README 4.6 的三件事）

1. **归一化推送**：`POST /api/collector/incoming` → 统一 Message → 去重（平台 msg_key 或 sender+time+content 哈希）→ SQLite → WS `new_message`
2. **发送路由**：`POST /api/messages/{id}/reply` → 按 CHANNEL_PLAN 选主通道 → format_adapter 转平台格式 → 连接器发送 → 失败自动切备用 → 回报 `{ok, channel, status/reason}`
3. **状态回流**：发送成功后 1.1 秒推送 `status_update: synced`，全部流转写入 traces 时间线

## 六、手动操作清单（需要你自己做的）

| # | 事项 | 步骤 |
|---|------|------|
| 1 | 日常启动 | 双击 `启动.bat`，看到 `Uvicorn running on ...8080` 即可 |
| 2 | 启用 DeepSeek | `.env.example` 复制为 `.env`，填 `DEEPSEEK_API_KEY`，重启 |
| 3 | 钉钉真实对接 | 钉钉群 → 智能群助手 → 自定义机器人 → 拿 Webhook（+加签密钥）填 `.env` |
| 4 | RPA 真对接（可选） | Power Automate Desktop 建流：定位微信窗口→粘贴→发送，触发方式选「HTTP 收到请求」，地址填 `RPA_FLOW_URL` |
| 5 | 初始化测试数据 | 删掉 `app/unified_msg.db` 再重启，自动重建 9 条种子消息 |
| 6 | 演示前检查 | 打开 `/api/health` 确认各连接器模式；跑一遍 B 的演示动线 |

## 七、已通过的端到端自测

**2026-11-13（前端切真实后端数据）**：前端登录后自动拉 `/api/messages`+`/api/apps`+`/api/me`
替换 mock（loadBackendData），会话 thread 懒加载（loadThread），页面显示后端数据库真数据。
种子消息 `unread` 逻辑修正（received→未读），重置数据库后为 9 条：未读 6 / 待办 1 / 已回复 3。
数据库备份在 `app/unified_msg.db.bak`。

**2026-11-12（真实凭据）**：钉钉真实发送 errcode=0 ✓ / 钉钉回复闭环→synced ✓ /
DeepSeek 真实分类(engine=deepseek) ✓

**2026-11-14（移除飞书）**：飞书个人组织无法调开放平台 API（21001 需企业认证），
故彻底移除飞书连接器与相关配置，系统保留钉钉（Webhook）+ 微信（RPA）两平台，
仍满足赛题「对接至少两个平台」要求；接收闭环走 RPA 采集 + 手动同步兜底。

**2026-11-09（模拟模式）**：

登录 ✓ / 消息列表 ✓ / 回复闭环→synced ✓ / 故障注入→失败回报 ✓ / 微信 RPA 通道发送 ✓ /
RPA 采集+去重 ✓ / AI 分类·建议·摘要 ✓ / 断开平台→发送被拦→重连 ✓
