/* ===== format-adapter.js — 消息格式适配器 =====
   职责：内部统一格式 ↔ 各平台发送格式 的双向适配
   这是赛题"消息格式统一转换与适配"的核心模块，无 UI 依赖，可单独测试
   ============================================================ */

/* 回复场景：构建内部统一格式（发给后端的报文） */
function buildInternalFormat(msg, replyText) {
  return JSON.stringify({
    action: "send",
    targetPlatform: msg.platform,
    relatedMsgId: msg.id,
    sender: "统一消息中心",
    type: "text",
    content: replyText,
  }, null, 2);
}

/* 内部统一格式 → 各平台真实发送格式（对齐各平台机器人 API） */
function convertToPlatformFormat(platform, replyText) {
  switch (platform) {
    case "dingtalk":   // 钉钉机器人 markdown
      return JSON.stringify({
        msgtype: "markdown",
        markdown: { title: "统一消息中心回复", text: `### 统一回复\n\n${replyText}` },
      }, null, 2);
    case "wechat":     // 企业微信机器人 text
      return JSON.stringify({
        msgtype: "text",
        text: { content: `[统一消息中心回复] ${replyText}` },
      }, null, 2);
    default:
      return replyText;
  }
}
