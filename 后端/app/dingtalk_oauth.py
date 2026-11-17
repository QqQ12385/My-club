"""dingtalk_oauth.py — 钉钉扫码登录（OAuth 授权登录）

钉钉「扫码登录」是第三方网站让钉钉用户用钉钉 App 扫码登录的能力，
与「企业内部应用」是两个独立能力，需在开放平台分别开通。

流程（授权码模式）：
  1. 前端跳到 https://login.dingtalk.com/oauth2/auth?redirect_uri=...&response_type=code
     &client_id=<AppKey>&scope=openid&prompt=consent
  2. 用户扫码授权后，钉钉 302 回跳 redirect_uri 并带上 code
  3. 后端用 code 换 access_token（getUserAccessToken），再拿 userInfo（unionId/openId/nick）
  4. 按 unionId 映射/自动注册本地账号，签发本系统 token

说明：corpId 用于「企业内部应用免登」；「扫码登录」用的是 AppKey + AppSecret +
      redirect_uri（client_id 即 AppKey）。scope=openid 拿到 unionId（跨应用唯一用户标识）。
"""
from __future__ import annotations

import json
import secrets
import urllib.parse

import httpx

from .config import settings

_AUTH_URL = "https://login.dingtalk.com/oauth2/auth"
_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
_USERINFO_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


def is_configured() -> bool:
    return bool(settings.DINGTALK_APP_KEY and settings.DINGTALK_APP_SECRET)


def build_authorize_url(state: str) -> str:
    """生成钉钉扫码登录授权 URL（前端跳转用）。"""
    params = {
        "redirect_uri": settings.DINGTALK_LOGIN_REDIRECT,
        "response_type": "code",
        "client_id": settings.DINGTALK_APP_KEY,
        "scope": "openid",           # 拿 unionId / openId / nick
        "state": state,
        "prompt": "consent",
    }
    return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_user(code: str) -> dict | None:
    """用授权码换用户信息。返回 {unionId, openId, nick, avatarUrl} 或 None。"""
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            # 1) code → accessToken
            tr = await c.post(_TOKEN_URL, json={
                "clientId": settings.DINGTALK_APP_KEY,
                "clientSecret": settings.DINGTALK_APP_SECRET,
                "code": code,
                "grantType": "authorization_code",
            })
            td = tr.json()
            access_token = td.get("accessToken")
            if tr.status_code != 200 or not access_token:
                return None
            # 2) accessToken → 用户信息（需要 x-acs 头）
            ur = await c.get(_USERINFO_URL, headers={
                "x-acs-dingtalk-access-token": access_token,
            })
            ud = ur.json()
            if ur.status_code != 200:
                return None
            return {
                "unionId": ud.get("unionId", ""),
                "openId": ud.get("openId", ""),
                "nick": ud.get("nick", ""),
                "avatarUrl": ud.get("avatarUrl", ""),
            }
    except Exception:
        return None


def make_state() -> str:
    return secrets.token_urlsafe(16)
