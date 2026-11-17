"""config.py — 读取 .env 配置"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
    DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

    # 钉钉企业内部应用（Stream 模式，可收可发）
    DINGTALK_APP_KEY = os.getenv("DINGTALK_APP_KEY", "")
    DINGTALK_APP_SECRET = os.getenv("DINGTALK_APP_SECRET", "")

    # 钉钉扫码登录（OAuth 授权登录）：corpId 在开放平台「首页-组织信息」查看
    DINGTALK_CORP_ID = os.getenv("DINGTALK_CORP_ID", "")
    DINGTALK_LOGIN_REDIRECT = os.getenv("DINGTALK_LOGIN_REDIRECT",
                                        "http://localhost:8080/api/auth/dingtalk/callback")

    RPA_MODE = os.getenv("RPA_MODE", "simulated")
    RPA_FLOW_URL = os.getenv("RPA_FLOW_URL", "")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8080"))
    DEMO_ACCOUNT = os.getenv("DEMO_ACCOUNT", "gary")
    DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo123")


settings = Settings()
