# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from pathlib import Path
import json
import os

# JSON 配置文件路径
CONFIG_FILE = Path.home() / ".notion-ai-proxy" / "config.json"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"
    )

    APP_NAME: str = "notion-2api"
    APP_VERSION: str = "4.0.0"
    DESCRIPTION: str = "一个将 Notion AI 转换为兼容 OpenAI 格式 API 的高性能代理。"

    API_MASTER_KEY: Optional[str] = None

    # --- Notion 凭证 ---
    NOTION_COOKIE: Optional[str] = None
    NOTION_SPACE_ID: Optional[str] = None
    NOTION_USER_ID: Optional[str] = None
    NOTION_USER_NAME: Optional[str] = None
    NOTION_USER_EMAIL: Optional[str] = None
    NOTION_BLOCK_ID: Optional[str] = None
    NOTION_CLIENT_VERSION: Optional[str] = "23.13.20251011.2037"

    API_REQUEST_TIMEOUT: int = 180
    NGINX_PORT: int = 8088

    DEFAULT_MODEL: str = "claude-opus-4.5"
    
    KNOWN_MODELS: List[str] = [
        "claude-opus-4.5",
        "claude-sonnet-4.5",
        "gpt-5",
        "claude-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）",
        "gemini-2.5-pro（未修复，不可用）",
        "gpt-4.1"
    ]
    
    MODEL_MAP: dict = {
        "claude-opus-4.5": "apple-danish",
        "claude-sonnet-4.5": "anthropic-sonnet-alt",
        "gpt-5": "openai-turbo",
        "claude-opus-4.1": "anthropic-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）": "vertex-gemini-2.5-flash",
        "gemini-2.5-pro（未修复，不可用）": "vertex-gemini-2.5-pro",
        "gpt-4.1": "openai-gpt-4.1"
    }
    
    def reload_from_json(self):
        """从 JSON 配置文件重新加载凭证"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 更新凭证字段
                if "token_v2" in config:
                    self.NOTION_COOKIE = config["token_v2"]
                if "space_id" in config:
                    self.NOTION_SPACE_ID = config["space_id"]
                if "user_id" in config:
                    self.NOTION_USER_ID = config["user_id"]
                if "port" in config:
                    self.NGINX_PORT = int(config["port"])
                
                print(f"✅ 已从 JSON 配置文件重新加载配置: {CONFIG_FILE}")
            except Exception as e:
                print(f"⚠️ 加载 JSON 配置失败: {e}")

# 创建全局 settings 实例
settings = Settings()

# 启动时尝试从 JSON 加载（优先级高于 .env）
settings.reload_from_json()