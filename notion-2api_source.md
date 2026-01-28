# 📁 notion-2api 源码导出

> 导出时间：2026-01-28 21:44:42
> 项目路径：`C:\dev\notion-2api`

---

## 📂 项目结构

```
notion-2api/
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base_provider.py
│   │   └── notion_provider.py
│   └── utils/
│       └── sse_utils.py
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── main.py
├── nginx.conf
├── project_to_md_gui.py
├── README.md
├── requirements.txt
└── 项目完整结构代码.txt
```

---

## 📄 源码文件

### `.env.example`

```
# ====================================================================
# notion-2api 配置文件模板 (最终版)
# ====================================================================
#
# 请将此文件重命名为 ".env" 并填入您的凭证。
#

# --- 核心安全配置 (可选) ---
API_MASTER_KEY=your_secret_key_here

# --- 部署配置 (可选) ---
NGINX_PORT=8088

# --- Notion 凭证 (以下均为必须或强烈建议设置) ---
# 1) 粘贴 token_v2 的值 或 完整 Cookie
NOTION_COOKIE="在此处粘贴 token_v2 值 或 完整 Cookie"

# 2) 您的 Space ID
NOTION_SPACE_ID="在此处粘贴您的 Space ID"

# 3) 您的用户 ID (浏览器开发者工具中 x-notion-active-user-header 的值)
NOTION_USER_ID="在此处粘贴您的 Notion 用户 ID"

# 4) 您的 Notion 用户名 (显示在左上角的名称)
NOTION_USER_NAME="利仔"

# 5) 您的 Notion 登录邮箱
NOTION_USER_EMAIL="q13645947407@gmail.com"

# 可选：想绑定的页面 blockId。留空则不绑定特定页面上下文。
NOTION_BLOCK_ID=""

# 可选：浏览器中看到的客户端版本
NOTION_CLIENT_VERSION="23.13.20251011.2037"
```

### `app\core\__init__.py`

```python

```

### `app\core\config.py`

```python
# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"
    )

    APP_NAME: str = "notion-2api"
    APP_VERSION: str = "4.0.0" # 最终稳定版
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

    # 【最终修正】更新所有已知的模型列表
    DEFAULT_MODEL: str = "claude-sonnet-4.5"
    
    KNOWN_MODELS: List[str] = [
        "claude-sonnet-4.5",
        "gpt-5",
        "claude-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）",
        "gemini-2.5-pro（未修复，不可用）",
        "gpt-4.1"
    ]
    
    # 【最终修正】根据您提供的信息，填充所有模型的真实后台名称
    MODEL_MAP: dict = {
        "claude-sonnet-4.5": "anthropic-sonnet-alt",
        "gpt-5": "openai-turbo",
        "claude-opus-4.1": "anthropic-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）": "vertex-gemini-2.5-flash",
        "gemini-2.5-pro（未修复，不可用）": "vertex-gemini-2.5-pro",
        "gpt-4.1": "openai-gpt-4.1"
    }

settings = Settings()
```

### `app\providers\__init__.py`

```python

```

### `app\providers\base_provider.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Union
from fastapi.responses import StreamingResponse, JSONResponse

class BaseProvider(ABC):
    @abstractmethod
    async def chat_completion(
        self,
        request_data: Dict[str, Any]
    ) -> Union[StreamingResponse, JSONResponse]:
        pass

    @abstractmethod
    async def get_models(self) -> JSONResponse:
        pass
```

### `app\providers\notion_provider.py`

```python
# app/providers/notion_provider.py
import json
import time
import logging
import uuid
import re
import cloudscraper
from typing import Dict, Any, AsyncGenerator, List, Optional, Tuple
from datetime import datetime

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.providers.base_provider import BaseProvider
from app.utils.sse_utils import create_sse_data, create_chat_completion_chunk, DONE_CHUNK

# 设置日志记录器
logger = logging.getLogger(__name__)

class NotionAIProvider(BaseProvider):
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.api_endpoints = {
            "runInference": "https://www.notion.so/api/v3/runInferenceTranscript",
            "saveTransactions": "https://www.notion.so/api/v3/saveTransactionsFanout"
        }
        
        if not all([settings.NOTION_COOKIE, settings.NOTION_SPACE_ID, settings.NOTION_USER_ID]):
            raise ValueError("配置错误: NOTION_COOKIE, NOTION_SPACE_ID 和 NOTION_USER_ID 必须在 .env 文件中全部设置。")

        self._warmup_session()

    def _warmup_session(self):
        try:
            logger.info("正在进行会话预热 (Session Warm-up)...")
            headers = self._prepare_headers()
            headers.pop("Accept", None)
            response = self.scraper.get("https://www.notion.so/", headers=headers, timeout=30)
            response.raise_for_status()
            logger.info("会话预热成功。")
        except Exception as e:
            logger.error(f"会话预热失败: {e}", exc_info=True)
            
    async def _create_thread(self, thread_type: str) -> str:
        thread_id = str(uuid.uuid4())
        payload = {
            "requestId": str(uuid.uuid4()),
            "transactions": [{
                "id": str(uuid.uuid4()),
                "spaceId": settings.NOTION_SPACE_ID,
                "operations": [{
                    "pointer": {"table": "thread", "id": thread_id, "spaceId": settings.NOTION_SPACE_ID},
                    "path": [],
                    "command": "set",
                    "args": {
                        "id": thread_id, "version": 1, "parent_id": settings.NOTION_SPACE_ID,
                        "parent_table": "space", "space_id": settings.NOTION_SPACE_ID,
                        "created_time": int(time.time() * 1000),
                        "created_by_id": settings.NOTION_USER_ID, "created_by_table": "notion_user",
                        "messages": [], "data": {}, "alive": True, "type": thread_type
                    }
                }]
            }]
        }
        try:
            logger.info(f"正在创建新的对话线程 (type: {thread_type})...")
            response = await run_in_threadpool(
                lambda: self.scraper.post(
                    self.api_endpoints["saveTransactions"],
                    headers=self._prepare_headers(),
                    json=payload,
                    timeout=20
                )
            )
            response.raise_for_status()
            logger.info(f"对话线程创建成功, Thread ID: {thread_id}")
            return thread_id
        except Exception as e:
            logger.error(f"创建对话线程失败: {e}", exc_info=True)
            raise Exception("无法创建新的对话线程。")

    async def chat_completion(self, request_data: Dict[str, Any]):
        stream = request_data.get("stream", True)

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            request_id = f"chatcmpl-{uuid.uuid4()}"
            incremental_fragments: List[str] = []
            final_message: Optional[str] = None
            
            try:
                model_name = request_data.get("model", settings.DEFAULT_MODEL)
                mapped_model = settings.MODEL_MAP.get(model_name, "anthropic-sonnet-alt")
                
                thread_type = "markdown-chat" if mapped_model.startswith("vertex-") else "workflow"
                
                thread_id = await self._create_thread(thread_type)
                payload = self._prepare_payload(request_data, thread_id, mapped_model, thread_type)
                headers = self._prepare_headers()

                role_chunk = create_chat_completion_chunk(request_id, model_name, role="assistant")
                yield create_sse_data(role_chunk)

                def sync_stream_iterator():
                    try:
                        logger.info(f"请求 Notion AI URL: {self.api_endpoints['runInference']}")
                        logger.info(f"请求体: {json.dumps(payload, indent=2, ensure_ascii=False)}")
                        
                        response = self.scraper.post(
                            self.api_endpoints['runInference'], headers=headers, json=payload, stream=True,
                            timeout=settings.API_REQUEST_TIMEOUT
                        )
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if line:
                                yield line
                    except Exception as e:
                        yield e

                sync_gen = sync_stream_iterator()
              
                while True:
                    line = await run_in_threadpool(lambda: next(sync_gen, None))
                    if line is None:
                        break
                    if isinstance(line, Exception):
                        raise line

                    parsed_results = self._parse_ndjson_line_to_texts(line)
                    for text_type, content in parsed_results:
                        if text_type == 'final':
                            final_message = content
                        elif text_type == 'incremental':
                            incremental_fragments.append(content)
              
                full_response = ""
                if final_message:
                    full_response = final_message
                    logger.info(f"成功从 record-map 或 Gemini patch/event 中提取到最终消息。")
                else:
                    full_response = "".join(incremental_fragments)
                    logger.info(f"使用拼接所有增量片段的方式获得最终消息。")

                if full_response:
                    cleaned_response = self._clean_content(full_response)
                    logger.info(f"清洗后的最终响应: {cleaned_response}")
                    chunk = create_chat_completion_chunk(request_id, model_name, content=cleaned_response)
                    yield create_sse_data(chunk)
                else:
                    logger.warning("警告: Notion 返回的数据流中未提取到任何有效文本。请检查您的 .env 配置是否全部正确且凭证有效。")

                final_chunk = create_chat_completion_chunk(request_id, model_name, finish_reason="stop")
                yield create_sse_data(final_chunk)
                yield DONE_CHUNK

            except Exception as e:
                error_message = f"处理 Notion AI 流时发生意外错误: {str(e)}"
                logger.error(error_message, exc_info=True)
                error_chunk = {"error": {"message": error_message, "type": "internal_server_error"}}
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK

        if stream:
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            raise HTTPException(status_code=400, detail="此端点当前仅支持流式响应 (stream=true)。")

    def _prepare_headers(self) -> Dict[str, str]:
        cookie_source = (settings.NOTION_COOKIE or "").strip()
        cookie_header = cookie_source if "=" in cookie_source else f"token_v2={cookie_source}"

        return {
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "Cookie": cookie_header,
            "x-notion-space-id": settings.NOTION_SPACE_ID,
            "x-notion-active-user-header": settings.NOTION_USER_ID,
            "x-notion-client-version": settings.NOTION_CLIENT_VERSION,
            "notion-audit-log-platform": "web",
            "Origin": "https://www.notion.so",
            "Referer": "https://www.notion.so/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }

    def _normalize_block_id(self, block_id: str) -> str:
        if not block_id: return block_id
        b = block_id.replace("-", "").strip()
        if len(b) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", b):
            return f"{b[0:8]}-{b[8:12]}-{b[12:16]}-{b[16:20]}-{b[20:]}"
        return block_id

    def _prepare_payload(self, request_data: Dict[str, Any], thread_id: str, mapped_model: str, thread_type: str) -> Dict[str, Any]:
        req_block_id = request_data.get("notion_block_id") or settings.NOTION_BLOCK_ID
        normalized_block_id = self._normalize_block_id(req_block_id) if req_block_id else None

        context_value: Dict[str, Any] = {
            "timezone": "Asia/Shanghai",
            "spaceId": settings.NOTION_SPACE_ID,
            "userId": settings.NOTION_USER_ID,
            "userEmail": settings.NOTION_USER_EMAIL,
            "currentDatetime": datetime.now().astimezone().isoformat(),
        }
        if normalized_block_id:
            context_value["blockId"] = normalized_block_id

        config_value: Dict[str, Any]
        
        if mapped_model.startswith("vertex-"):
            logger.info(f"检测到 Gemini 模型 ({mapped_model})，应用特定的 config 和 context。")
            context_value.update({
                "userName": f" {settings.NOTION_USER_NAME}",
                "spaceName": f"{settings.NOTION_USER_NAME}的 Notion",
                "spaceViewId": "2008eefa-d0dc-80d5-9e67-000623befd8f",
                "surface": "ai_module"
            })
            config_value = {
                "type": thread_type,
                "model": mapped_model,
                "useWebSearch": True,
                "enableAgentAutomations": False, "enableAgentIntegrations": False,
                "enableBackgroundAgents": False, "enableCodegenIntegration": False,
                "enableCustomAgents": False, "enableExperimentalIntegrations": False,
                "enableLinkedDatabases": False, "enableAgentViewVersionHistoryTool": False,
                "searchScopes": [{"type": "everything"}], "enableDatabaseAgents": False,
                "enableAgentComments": False, "enableAgentForms": False,
                "enableAgentMakesFormulas": False, "enableUserSessionContext": False,
                "modelFromUser": True, "isCustomAgent": False
            }
        else:
            context_value.update({
                "userName": settings.NOTION_USER_NAME,
                "surface": "workflows"
            })
            config_value = {
                "type": thread_type,
                "model": mapped_model,
                "useWebSearch": True,
            }

        transcript = [
            {"id": str(uuid.uuid4()), "type": "config", "value": config_value},
            {"id": str(uuid.uuid4()), "type": "context", "value": context_value}
        ]
      
        for msg in request_data.get("messages", []):
            if msg.get("role") == "user":
                transcript.append({
                    "id": str(uuid.uuid4()),
                    "type": "user",
                    "value": [[msg.get("content")]],
                    "userId": settings.NOTION_USER_ID,
                    "createdAt": datetime.now().astimezone().isoformat()
                })
            elif msg.get("role") == "assistant":
                transcript.append({"id": str(uuid.uuid4()), "type": "agent-inference", "value": [{"type": "text", "content": msg.get("content")}]})

        payload = {
            "traceId": str(uuid.uuid4()),
            "spaceId": settings.NOTION_SPACE_ID,
            "transcript": transcript,
            "threadId": thread_id,
            "createThread": False,
            "isPartialTranscript": True,
            "asPatchResponse": True,
            "generateTitle": True,
            "saveAllThreadOperations": True,
            "threadType": thread_type
        }

        if mapped_model.startswith("vertex-"):
            logger.info("为 Gemini 请求添加 debugOverrides。")
            payload["debugOverrides"] = {
                "emitAgentSearchExtractedResults": True,
                "cachedInferences": {},
                "annotationInferences": {},
                "emitInferences": False
            }
        
        return payload

    def _clean_content(self, content: str) -> str:
        if not content:
            return ""
            
        content = re.sub(r'<lang primary="[^"]*"\s*/>\n*', '', content)
        content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<thought>[\s\S]*?</thought>\s*', '', content, flags=re.IGNORECASE)
        
        content = re.sub(r'^.*?Chinese whatmodel I am.*?Theyspecifically.*?requested.*?me.*?to.*?reply.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?This.*?is.*?a.*?straightforward.*?question.*?about.*?my.*?identity.*?asan.*?AI.*?assistant\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?Idon\'t.*?need.*?to.*?use.*?any.*?tools.*?for.*?this.*?-\s*it\'s.*?asimple.*?informational.*?response.*?aboutwhat.*?I.*?am\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?Sincethe.*?user.*?asked.*?in.*?Chinese.*?and.*?specifically.*?requested.*?a.*?Chinese.*?response.*?I.*?should.*?respond.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?What model are you.*?in Chinese and specifically requesting.*?me.*?to.*?reply.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?This.*?is.*?a.*?question.*?about.*?my.*?identity.*?not requiring.*?any.*?tool.*?use.*?I.*?should.*?respond.*?directly.*?to.*?the.*?user.*?in.*?Chinese.*?as.*?requested\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?I.*?should.*?identify.*?myself.*?as.*?Notion.*?AI.*?as.*?mentioned.*?in.*?the.*?system.*?prompt.*?\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?I.*?should.*?not.*?make.*?specific.*?claims.*?about.*?the.*?underlying.*?model.*?architecture.*?since.*?that.*?information.*?is.*?not.*?provided.*?in.*?my.*?context\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        
        return content.strip()

    def _parse_ndjson_line_to_texts(self, line: bytes) -> List[Tuple[str, str]]:
        results: List[Tuple[str, str]] = []
        try:
            s = line.decode("utf-8", errors="ignore").strip()
            if not s: return results
            
            data = json.loads(s)
            logger.debug(f"原始响应数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 格式1: Gemini 返回的 markdown-chat 事件
            if data.get("type") == "markdown-chat":
                content = data.get("value", "")
                if content:
                    logger.info("从 'markdown-chat' 直接事件中提取到内容。")
                    results.append(('final', content))

            # 格式2: Claude 和 GPT 返回的补丁流，以及 Gemini 的 patch 格式
            elif data.get("type") == "patch" and "v" in data:
                for operation in data.get("v", []):
                    if not isinstance(operation, dict): continue
                    
                    op_type = operation.get("o")
                    path = operation.get("p", "")
                    value = operation.get("v")
                    
                    # 【修改】Gemini 的完整内容 patch 格式
                    if op_type == "a" and path.endswith("/s/-") and isinstance(value, dict) and value.get("type") == "markdown-chat":
                        content = value.get("value", "")
                        if content:
                            logger.info("从 'patch' (Gemini-style) 中提取到完整内容。")
                            results.append(('final', content))
                    
                    # 【修改】Gemini 的增量内容 patch 格式
                    elif op_type == "x" and "/s/" in path and path.endswith("/value") and isinstance(value, str):
                        content = value
                        if content:
                            logger.info(f"从 'patch' (Gemini增量) 中提取到内容: {content}")
                            results.append(('incremental', content))
                    
                    # 【修改】Claude 和 GPT 的增量内容 patch 格式
                    elif op_type == "x" and "/value/" in path and isinstance(value, str):
                        content = value
                        if content:
                            logger.info(f"从 'patch' (Claude/GPT增量) 中提取到内容: {content}")
                            results.append(('incremental', content))
                    
                    # 【修改】Claude 和 GPT 的完整内容 patch 格式
                    elif op_type == "a" and path.endswith("/value/-") and isinstance(value, dict) and value.get("type") == "text":
                        content = value.get("content", "")
                        if content:
                            logger.info("从 'patch' (Claude/GPT-style) 中提取到完整内容。")
                            results.append(('final', content))

            # 格式3: 处理record-map类型的数据
            elif data.get("type") == "record-map" and "recordMap" in data:
                record_map = data["recordMap"]
                if "thread_message" in record_map:
                    for msg_id, msg_data in record_map["thread_message"].items():
                        value_data = msg_data.get("value", {}).get("value", {})
                        step = value_data.get("step", {})
                        if not step: continue

                        content = ""
                        step_type = step.get("type")

                        if step_type == "markdown-chat":
                            content = step.get("value", "")
                        elif step_type == "agent-inference":
                            agent_values = step.get("value", [])
                            if isinstance(agent_values, list):
                                for item in agent_values:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        content = item.get("content", "")
                                        break
                        
                        if content and isinstance(content, str):
                            logger.info(f"从 record-map (type: {step_type}) 提取到最终内容。")
                            results.append(('final', content))
                            break 
    
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"解析NDJSON行失败: {e} - Line: {line.decode('utf-8', errors='ignore')}")
        
        return results

    async def get_models(self) -> JSONResponse:
        model_data = {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "created": int(time.time()), "owned_by": "lzA6"}
                for name in settings.KNOWN_MODELS
            ]
        }
        return JSONResponse(content=model_data)
```

### `app\utils\sse_utils.py`

```python
# app/utils/sse_utils.py
import json
import time
from typing import Dict, Any, Optional

DONE_CHUNK = b"data: [DONE]\n\n"

def create_sse_data(data: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode('utf-8')

def create_chat_completion_chunk(
    request_id: str,
    model: str,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
    role: Optional[str] = None
) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content

    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason
            }
        ]
    }
```

### `docker-compose.yml`

```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:latest
    container_name: notion-2api-nginx
    restart: always
    ports:
      - "${NGINX_PORT:-8088}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - app
    networks:
      - notion-net

  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: notion-2api-app
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - notion-net

networks:
  notion-net:
    driver: bridge
```

### `Dockerfile`

```dockerfile
# ====================================================================
# Dockerfile for inception-2api (v4.0 - Cloudscraper Edition)
# ====================================================================

FROM python:3.10-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建并切换到非 root 用户
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口并启动
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### `main.py`

```python
# main.py
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.providers.notion_provider import NotionAIProvider

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

provider = NotionAIProvider()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"应用启动中... {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("服务已配置为 Notion AI 代理模式。")
    logger.info(f"服务将在 http://localhost:{settings.NGINX_PORT} 上可用")
    yield
    logger.info("应用关闭。")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan
)

async def verify_api_key(authorization: Optional[str] = Header(None)):
    if settings.API_MASTER_KEY and settings.API_MASTER_KEY != "1":
        if not authorization or "bearer" not in authorization.lower():
            raise HTTPException(status_code=401, detail="需要 Bearer Token 认证。")
        token = authorization.split(" ")[-1]
        if token != settings.API_MASTER_KEY:
            raise HTTPException(status_code=403, detail="无效的 API Key。")

@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request) -> StreamingResponse:
    try:
        request_data = await request.json()
        return await provider.chat_completion(request_data)
    except Exception as e:
        logger.error(f"处理聊天请求时发生顶层错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

@app.get("/v1/models", dependencies=[Depends(verify_api_key)], response_class=JSONResponse)
async def list_models():
    return await provider.get_models()

@app.get("/", summary="根路径")
def root():
    return {"message": f"欢迎来到 {settings.APP_NAME} v{settings.APP_VERSION}. 服务运行正常。"}
```

### `nginx.conf`

```ini
worker_processes auto;

events {
    worker_connections 1024;
}

http {
    upstream notion_backend {
        server app:8000;
    }

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://notion_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # 【核心修正】增加代理超时时间，以应对Cloudflare挑战
            proxy_connect_timeout 600s;
            proxy_send_timeout 600s;
            proxy_read_timeout 600s;
            send_timeout 600s;
            
            # 流式传输优化
            proxy_buffering off;
            proxy_cache off;
            proxy_set_header Connection '';
            proxy_http_version 1.1;
            chunked_transfer_encoding off;
        }
    }
}
```

### `project_to_md_gui.py`

```python
#!/usr/bin/env python3
"""
项目源码 → Markdown 导出器 (PySide6 + Material Design)
选择文件夹，一键生成 Markdown，自动复制到剪贴板
"""

import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

# Material Design 主题
try:
    from qt_material import apply_stylesheet
    HAS_MATERIAL = True
except ImportError:
    HAS_MATERIAL = False
    print("提示: 未安装 qt-material，运行 pip install qt-material 安装")


# ==================== 配置 ====================

INCLUDE_EXTENSIONS = {
    '.py', '.java', '.kt', '.kts', '.scala', '.go', '.rs', '.rb', '.php',
    '.cs', '.fs', '.swift', '.dart', '.lua', '.pl', '.pm', '.r',
    '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx',
    '.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs',
    '.vue', '.svelte', '.astro',
    '.html', '.css', '.scss', '.sass', '.less', '.styl',
    '.pug', '.ejs', '.hbs', '.j2', '.jinja2',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.env',
    '.xml', '.cfg', '.conf', '.properties',
    '.dockerfile', '.tf', '.hcl', '.nix',
    '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
    '.gradle', '.cmake',
    '.sql', '.graphql', '.gql', '.proto',
    '.md', '.txt', '.rst',
}

INCLUDE_FILENAMES = {
    'Makefile', 'Dockerfile', 'Jenkinsfile', 'Vagrantfile',
    '.gitignore', '.dockerignore', '.env.example',
    'requirements.txt', 'setup.py', 'pyproject.toml',
    'package.json', 'tsconfig.json', 'vite.config.js',
    'Cargo.toml', 'go.mod', 'go.sum',
}

EXCLUDE_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
    '.idea', '.vscode', '.vs', 'dist', 'build', 'out', 'target',
    '.next', '.nuxt', '.cache', '.parcel-cache',
    'egg-info', '.eggs', '.tox', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'coverage', '.coverage', 'htmlcov', 'bin', 'obj',
}

MAX_FILE_SIZE = 100 * 1024  # 100KB


# ==================== 核心逻辑 ====================

def get_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    name = Path(filename).name.lower()
    
    name_map = {'dockerfile': 'dockerfile', 'makefile': 'makefile', 'jenkinsfile': 'groovy', 'vagrantfile': 'ruby'}
    if name in name_map:
        return name_map[name]
    
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript', '.jsx': 'jsx', '.tsx': 'tsx',
        '.vue': 'vue', '.svelte': 'svelte', '.astro': 'astro',
        '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin', '.scala': 'scala',
        '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
        '.cs': 'csharp', '.fs': 'fsharp', '.swift': 'swift', '.dart': 'dart',
        '.lua': 'lua', '.pl': 'perl', '.pm': 'perl', '.r': 'r',
        '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.hxx': 'cpp',
        '.css': 'css', '.scss': 'scss', '.sass': 'sass', '.less': 'less', '.styl': 'stylus',
        '.html': 'html', '.pug': 'pug', '.ejs': 'ejs', '.hbs': 'handlebars',
        '.j2': 'jinja2', '.jinja2': 'jinja2', '.xml': 'xml',
        '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
        '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini', '.properties': 'properties',
        '.env': 'bash', '.sh': 'bash', '.bash': 'bash', '.zsh': 'zsh',
        '.ps1': 'powershell', '.bat': 'batch', '.cmd': 'batch',
        '.sql': 'sql', '.graphql': 'graphql', '.gql': 'graphql', '.proto': 'protobuf',
        '.tf': 'hcl', '.hcl': 'hcl', '.nix': 'nix',
        '.gradle': 'gradle', '.cmake': 'cmake',
        '.md': 'markdown', '.rst': 'rst', '.txt': 'text', '.dockerfile': 'dockerfile',
    }
    return ext_map.get(ext, '')


def should_include(path: Path) -> bool:
    return path.name in INCLUDE_FILENAMES or path.suffix.lower() in INCLUDE_EXTENSIONS


def generate_tree(root: Path, prefix: str = '') -> list[str]:
    lines = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except PermissionError:
        return lines
    
    visible = [i for i in items if (i.is_dir() and i.name not in EXCLUDE_DIRS) or (i.is_file() and should_include(i))]
    
    for i, item in enumerate(visible):
        is_last = i == len(visible) - 1
        conn = '└── ' if is_last else '├── '
        if item.is_dir():
            lines.append(f'{prefix}{conn}{item.name}/')
            lines.extend(generate_tree(item, prefix + ('    ' if is_last else '│   ')))
        else:
            lines.append(f'{prefix}{conn}{item.name}')
    return lines


def collect_files(root: Path, progress_cb=None) -> list[tuple[Path, str]]:
    files = []
    all_files = list(root.rglob('*'))
    total = len(all_files)
    
    for idx, item in enumerate(sorted(all_files)):
        if progress_cb:
            progress_cb(idx + 1, total)
        if item.is_dir():
            continue
        if any(ex in item.parts for ex in EXCLUDE_DIRS):
            continue
        if not should_include(item):
            continue
        try:
            if item.stat().st_size > MAX_FILE_SIZE:
                continue
            content = item.read_text(encoding='utf-8')
            files.append((item.relative_to(root), content))
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
    return files


def generate_markdown(project_path: Path, progress_cb=None) -> str:
    name = project_path.name
    lines = [
        f'# 📁 {name} 源码导出', '',
        f'> 导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'> 项目路径：`{project_path}`',
        '', '---', '', '## 📂 项目结构', '', '```', f'{name}/',
    ]
    lines.extend(generate_tree(project_path))
    lines.extend(['```', '', '---', '', '## 📄 源码文件', ''])
    
    files = collect_files(project_path, progress_cb)
    for rel_path, content in files:
        lang = get_language(str(rel_path))
        lines.extend([f'### `{rel_path}`', '', f'```{lang}', content.rstrip(), '```', ''])
    
    lines.extend(['---', '', '## 📊 统计', '', f'- 文件数量：{len(files)}'])
    total_lines = sum(c.count('\n') + 1 for _, c in files)
    total_chars = sum(len(c) for _, c in files)
    lines.append(f'- 总行数：{total_lines:,}')
    lines.append(f'- 总字符数：{total_chars:,}')
    return '\n'.join(lines)


# ==================== 后台线程 ====================

class ExportWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str, int)  # success, message, char_count
    
    def __init__(self, project_path: Path, save_path: str = None):
        super().__init__()
        self.project_path = project_path
        self.save_path = save_path
        self.markdown = ""
    
    def run(self):
        try:
            self.markdown = generate_markdown(
                self.project_path,
                lambda cur, tot: self.progress.emit(cur, tot)
            )
            if self.save_path:
                Path(self.save_path).write_text(self.markdown, encoding='utf-8')
                self.finished.emit(True, f"已保存到：\n{self.save_path}", len(self.markdown))
            else:
                self.finished.emit(True, "", len(self.markdown))
        except Exception as e:
            self.finished.emit(False, str(e), 0)


# ==================== GUI ====================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📦 项目源码导出器")
        self.setFixedSize(520, 380)
        self.worker = None
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        title = QLabel("项目源码 → Markdown 导出器")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        desc = QLabel("选择项目文件夹，生成包含所有源码的 Markdown 文件")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: gray;")
        layout.addWidget(desc)
        
        layout.addSpacing(10)
        
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择项目文件夹...")
        path_layout.addWidget(self.path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_folder)
        browse_btn.setFixedWidth(80)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("请选择项目文件夹")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)
        
        layout.addSpacing(10)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.clipboard_btn = QPushButton("📋 生成并复制到剪贴板")
        self.clipboard_btn.clicked.connect(self.export_to_clipboard)
        self.clipboard_btn.setFixedHeight(36)
        btn_layout.addWidget(self.clipboard_btn)
        
        self.save_btn = QPushButton("💾 生成并保存文件")
        self.save_btn.clicked.connect(self.export_to_file)
        self.save_btn.setFixedHeight(36)
        btn_layout.addWidget(self.save_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择项目文件夹")
        if folder:
            self.path_input.setText(folder)
            self.status_label.setText(f"已选择：{Path(folder).name}")
    
    def export_to_clipboard(self):
        self._start_export(to_clipboard=True)
    
    def export_to_file(self):
        self._start_export(to_clipboard=False)
    
    def _start_export(self, to_clipboard=True):
        path = self.path_input.text()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择项目文件夹")
            return
        
        project_path = Path(path)
        if not project_path.exists() or not project_path.is_dir():
            QMessageBox.critical(self, "错误", "选择的路径不存在或不是文件夹")
            return
        
        save_path = None
        if not to_clipboard:
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存文件", f"{project_path.name}_source.md",
                "Markdown (*.md);;所有文件 (*.*)"
            )
            if not save_path:
                return
        
        self.clipboard_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在扫描文件...")
        self.progress_bar.setValue(0)
        
        self.worker = ExportWorker(project_path, save_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(lambda ok, msg, cnt: self._on_finished(ok, msg, cnt, to_clipboard))
        self.worker.start()
    
    def _on_progress(self, current, total):
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))
    
    def _on_finished(self, success, message, char_count, to_clipboard):
        self.clipboard_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        
        if success:
            if to_clipboard and self.worker:
                QApplication.clipboard().setText(self.worker.markdown)
                QMessageBox.information(
                    self, "完成",
                    f"已复制到剪贴板！\n\n字符数：{char_count:,}\n\n现在可以粘贴到 Notion 页面或聊天窗口。"
                )
            elif message:
                QMessageBox.information(self, "完成", message)
            self.status_label.setText("完成！")
        else:
            QMessageBox.critical(self, "错误", f"导出失败：{message}")
            self.status_label.setText("导出失败")


def main():
    app = QApplication(sys.argv)
    if HAS_MATERIAL:
        apply_stylesheet(app, theme='dark_teal.xml')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
```

### `README.md`

```markdown
# 🚀 notion-2api: 将 Notion AI 转换为私有 OpenAI API

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Stars](https://img.shields.io/github/stars/lzA6/notion-2api?style=social)
![Issues](https://img.shields.io/github/issues/lzA6/notion-2api)
![Forks](https://img.shields.io/github/forks/lzA6/notion-2api)

> "我们并非在创造工具，而是在延伸自我。每一次代码的敲击，都是对世界的一次温柔的重塑。" —— lzA6 (AI 构想)

欢迎来到 `notion-2api` 的世界！这是一个能将你强大的 Notion AI 体验，无缝转换为兼容 OpenAI 格式的 API 服务的神奇项目。这意味着，你可以将 Notion AI 作为后端，驱动任何支持 OpenAI API 的应用程序、脚本或服务。

**English Readme Coming Soon!**

---

## 📋 目录

- [✨ 项目亮点](#-项目亮点)
- [📂 项目结构](#-项目结构)
- [🤔 工作原理](#-工作原理)
- [🛠️ 技术栈](#️-技术栈)
- [📖 使用教程](#-使用教程)
- [🔗 一键部署](#-一键部署-规划中)
- [🧠 源码解析](#-源码解析)
- [📊 项目评估](#-项目评估)
- [🗺️ 未来规划](#️-未来规划)
- [🤖 AI 开发者指南](#-ai-开发者指南)
- [💖 贡献指南](#-贡献指南)

---

## ✨ 项目亮点

- **无缝转换**: 将 Notion AI 的非官方接口完美伪装成标准的 OpenAI `v1/chat/completions` 接口
- **多模型支持**: 支持 Notion AI 后端的所有可用模型（以 Notion 实际提供为准）
- **流式响应**: 完全支持 `stream=true`，提供流畅的打字机体验
- **Docker 化部署**: 一行命令轻松启动，告别繁琐环境配置
- **高性能**: 基于 FastAPI 和 Uvicorn，提供稳定高效的异步处理能力
- **智能反爬**: 内置 `cloudscraper`，绕过 Cloudflare 防护，提高请求成功率
- **灵活配置**: 通过简单的 `.env` 文件管理所有凭证和配置

---

## 📂 项目结构

```
notion-2api/
├── .env                    # 环境配置文件（生产环境）
├── .env.example            # 环境配置模板
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── main.py                 # FastAPI 应用主入口
├── nginx.conf              # Nginx 反向代理配置
├── requirements.txt        # Python 依赖列表
└── app/
    ├── core/
    │   ├── __init__.py
    │   └── config.py       # Pydantic 配置模型
    ├── providers/
    │   ├── __init__.py
    │   ├── base_provider.py # 抽象基类
    │   └── notion_provider.py # Notion API 交互核心
    └── utils/
        └── sse_utils.py    # Server-Sent Events 工具
```

---

## 🤔 工作原理

`notion-2api` 充当了 OpenAI API 和 Notion AI 之间的翻译官，将两种不同的协议进行无缝转换。

### 架构流程图

```mermaid
graph TD
    A[客户端应用] --> B[Nginx 反向代理]
    B --> C[FastAPI 应用]
    C --> D[认证中间件]
    D --> E[Notion Provider]
    E --> F[Cloudscraper]
    F --> G[Notion AI API]
    G --> H[NDJSON 流解析]
    H --> I[SSE 格式转换]
    I --> C
    C --> B
    B --> A
```

### 数据流详解

1. **请求接收**: 客户端发送标准的 OpenAI API 格式请求
2. **协议转换**: FastAPI 将请求转换为 Notion AI 能理解的格式
3. **会话管理**: 创建 Notion 对话线程并维持会话状态
4. **流式处理**: 实时解析 Notion 返回的 NDJSON 数据流
5. **格式转换**: 将解析后的数据转换为 OpenAI 兼容的 SSE 格式
6. **响应返回**: 通过流式响应将数据实时返回给客户端

---

## 🛠️ 技术栈

| 技术组件 | 版本/类型 | 用途说明 |
|---------|-----------|----------|
| **FastAPI** | 0.104+ | 现代化异步 Web 框架，提供高性能 API 服务 |
| **Uvicorn** | 0.24+ | ASGI 服务器，用于运行 FastAPI 应用 |
| **Cloudscraper** | 最新版 | 绕过 Cloudflare 防护，确保稳定连接 |
| **Pydantic** | 2.0+ | 数据验证和设置管理 |
| **Docker** | 最新版 | 容器化部署和环境隔离 |
| **Nginx** | 最新版 | 反向代理和负载均衡 |
| **Python** | 3.8+ | 主要编程语言 |

---

## 📖 使用教程

### 环境准备

1. **安装 Docker**: 访问 [Docker 官网](https://www.docker.com/get-started) 下载并安装
2. **安装 Git**: 用于克隆代码仓库

### 获取 Notion 凭证

这是最关键的一步，请仔细按照以下步骤操作：

#### 获取 token_v2

1. 登录 [Notion](https://www.notion.so/)
2. 打开浏览器开发者工具 (F12)
3. 切换到 **Application** 标签页
4. 展开 **Cookies** → **https://www.notion.so**
5. 找到 `token_v2` 项，复制其 **Value**

#### 获取 Space ID 和 User ID

1. 在开发者工具中切换到 **Network** 标签页
2. 在 Notion 中进行任意操作（如点击页面）
3. 找到 `getRecordValues` 或类似请求
4. 查看请求头中的：
   - `x-notion-active-user-header` → **User ID**
   - `x-notion-space-id` → **Space ID**

### 配置环境变量

1. **克隆项目**:
   ```bash
   git clone https://github.com/lzA6/notion-2api.git
   cd notion-2api
   ```

2. **创建配置文件**:
   ```bash
   cp .env.example .env
   ```

3. **编辑 `.env` 文件**:
   ```env
   # 安全配置（可选）
   API_MASTER_KEY=your_secret_key_here
   
   # 部署配置
   NGINX_PORT=8088
   
   # Notion 凭证（必需）
   NOTION_COOKIE="你的token_v2值"
   NOTION_SPACE_ID="你的Space ID"
   NOTION_USER_ID="你的User ID"
   NOTION_USER_NAME="你的名字"
   NOTION_USER_EMAIL="your_email@example.com"
   ```

### 启动服务

```bash
docker-compose up -d --build
```

### 测试 API

```bash
curl http://localhost:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_secret_key_here" \
  -d '{
    "model": "claude-sonnet-4.5",
    "messages": [{"role": "user", "content": "你好，请介绍一下你自己"}],
    "stream": true
  }'
```

如果一切正常，你将看到来自 Notion AI 的流式响应！

---

## 🧠 源码解析

### 核心模块架构

```mermaid
graph TB
    A[main.py] --> B[Config Manager]
    A --> C[Auth Middleware]
    A --> D[Route Handlers]
    D --> E[Notion Provider]
    E --> F[Session Management]
    E --> G[Stream Parser]
    E --> H[Response Formatter]
    G --> I[NDJSON Parser]
    H --> J[SSE Generator]
```

### `main.py` - 应用入口

负责初始化 FastAPI 应用、配置中间件和路由：

```python
@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    auth: bool = Depends(verify_api_key)
):
    """处理聊天补全请求，支持流式和非流式响应"""
```

### `app/core/config.py` - 配置管理

使用 Pydantic 进行类型安全的配置管理：

```python
class Settings(BaseSettings):
    """应用配置模型，自动从环境变量加载"""
    API_MASTER_KEY: str = "1"
    NGINX_PORT: int = 8088
    NOTION_COOKIE: str
    NOTION_SPACE_ID: str
    NOTION_USER_ID: str
```

### `app/providers/notion_provider.py` - 核心逻辑

实现与 Notion AI 的交互：

- **会话预热**: 初始化时访问 Notion 以获取有效 Cookie
- **线程管理**: 为每个对话创建独立的 Notion 线程
- **流式解析**: 实时解析 Notion 的 NDJSON 响应流
- **数据清洗**: 清理响应中的冗余信息和格式标记

### `app/utils/sse_utils.py` - 流式响应

将数据转换为 Server-Sent Events 格式：

```python
def create_sse_data(data: dict) -> str:
    """将数据转换为 SSE 格式"""
    return f"data: {json.dumps(data)}\n\n"
```

---

## 📊 项目评估

### ✅ 已完成功能

- [x] 核心代理功能 - OpenAI API 到 Notion AI 的协议转换
- [x] 完整的流式响应支持
- [x] Docker 容器化部署
- [x] Cloudflare 防护绕过
- [x] 多模型支持（Claude、GPT、Gemini）
- [x] API 密钥认证
- [x] 环境配置管理

### 🌟 核心优势

1. **生态兼容性**: 无缝接入现有 OpenAI 生态工具
2. **成本效益**: 利用现有 Notion 订阅，无需额外付费
3. **隐私保护**: 私有化部署，数据完全自主控制
4. **技术价值**: 学习现代 Web 开发和 API 设计的优秀范例

### ⚠️ 限制与挑战

1. **API 稳定性**: 依赖 Notion 非官方接口，存在变更风险
2. **凭证维护**: `token_v2` 会过期，需要定期更新
3. **防护对抗**: Cloudflare 策略更新可能导致连接失败
4. **功能局限**: 目前主要支持聊天补全功能

---

## 🗺️ 未来规划

### 🎯 短期目标

- [ ] 支持非流式响应 (`stream=false`)
- [ ] 增强错误处理和用户反馈
- [ ] 改进 token 自动刷新机制
- [ ] 动态模型列表获取
- [ ] 更详细的运行日志

### 💡 长期愿景

- [ ] 多账户负载均衡
- [ ] Function Calling 支持
- [ ] Web 管理界面
- [ ] 插件化架构
- [ ] 使用量统计和限制

---

## 🤖 AI 开发者指南

### 项目理解要点

1. **架构模式**: 这是一个典型的协议转换代理服务
2. **核心技术**: 异步编程、流式处理、反爬虫技术
3. **关键挑战**: 非官方 API 的稳定性和兼容性维护
4. **扩展方向**: 更多 AI 服务的协议转换支持

### 代码贡献建议

- 优先修复稳定性相关问题
- 改进错误处理和用户反馈
- 添加单元测试和集成测试
- 优化文档和示例代码

---

## 💖 贡献指南

我们欢迎各种形式的贡献：

- 🐛 **问题反馈**: 提交 [Issue](https://github.com/lzA6/notion-2api/issues)
- 🔧 **代码贡献**: 创建 [Pull Request](https://github.com/lzA6/notion-2api/pulls)
- 💡 **想法分享**: 参与 [Discussions](https://github.com/lzA6/notion-2api/discussions)
- ⭐ **项目支持**: 给项目点赞和分享

每一个贡献，无论大小，都是对开源世界的宝贵礼物。

---

**让我们一起，用代码创造更多可能性！** 🚀
```

### `requirements.txt`

```text
# requirements.txt
fastapi
uvicorn[standard]
httpx
pydantic-settings
python-dotenv
cloudscraper
```

### `项目完整结构代码.txt`

```text
项目 'notion-2api' 的结构树:
📂 notion-2api/
    📄 .env
    📄 .env.example
    📄 Dockerfile
    📄 docker-compose.yml
    📄 main.py
    📄 nginx.conf
    📄 requirements.txt
    📂 app/
        📂 core/
            📄 __init__.py
            📄 config.py
        📂 providers/
            📄 __init__.py
            📄 base_provider.py
            📄 notion_provider.py
        📂 utils/
            📄 sse_utils.py
================================================================================

--- 文件路径: .env ---

# [自动填充] notion-2api 生产环境配置

# --- 安全配置 ---
API_MASTER_KEY=1

# --- 端口配置 ---
NGINX_PORT=8088

# --- Notion 凭证 (以下均为必须或强烈建议设置) ---

# 1. 您的 token_v2 (已从最新日志中提取并更新)
NOTION_COOKIE="v03%3AeyJhbGciOiJkaXIiLCJraWQiOiJwcm9kdWN0aW9uOnRva2VuLXYzOjIwMjQtMTEtMDciLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIn0..mIRgS9AYZx8rn6OUJ7F9pA.QFex5O4ZzVCLG1JCNOgbbqmYf9IyntouodTfm2wn7LbmY0Zs-akV51n3dwtaC2K3ctm9Jj91PVRsl-6k9phiTUaIO_3FtSYmEYZrmCYEXa1iWJAwdROmySSRcMeSwsswgakVanb-sal9B8IH-YACTq9SLfooARLw65pwljahMdG-jJKi5X2PwfUrENeeRGDTQF0I6SLxp0-VxzOuWn-MDPej-S40hbDQY9kDyDZ9tyaYptOsu3KEP1M6HiwD0kqqQETUdYFPbYqK8ItPdKDyrFr8zIo21zfMAwLMeSvvTda-cBm0OVnBuGvqlLA92dVYON55mts-r_U2Xmjt9g9pAwL_GG8-HW9Qo-IyiaO9oB4.D17Jn2Mp6Y62_lbuZ0Ggz0ugnej-Ue7coltqqYHI-KE"

# 2. 您的 Space ID (保持不变)
NOTION_SPACE_ID="f108eefa-d0dc-8181-8382-0003e15d764e"

# 3. 您的用户 ID (从日志中提取)
NOTION_USER_ID="200d872b-594c-8153-b674-00028d202a8b"

# 4. 您的 Notion 用户名 (请确认是否准确)
NOTION_USER_NAME="利仔"

# 5. 您的 Notion 登录邮箱 (请替换为您的真实邮箱)
NOTION_USER_EMAIL="q13645947407@gmail.com"

# 6. 可选：页面 Block ID (保持留空以提高兼容性)
NOTION_BLOCK_ID=""

# 7. 可选：客户端版本 (保持默认即可)
NOTION_CLIENT_VERSION="23.13.20251011.2037"

--- 文件路径: .env.example ---

# ====================================================================
# notion-2api 配置文件模板 (最终版)
# ====================================================================
#
# 请将此文件重命名为 ".env" 并填入您的凭证。
#

# --- 核心安全配置 (可选) ---
API_MASTER_KEY=your_secret_key_here

# --- 部署配置 (可选) ---
NGINX_PORT=8088

# --- Notion 凭证 (以下均为必须或强烈建议设置) ---
# 1) 粘贴 token_v2 的值 或 完整 Cookie
NOTION_COOKIE="在此处粘贴 token_v2 值 或 完整 Cookie"

# 2) 您的 Space ID
NOTION_SPACE_ID="在此处粘贴您的 Space ID"

# 3) 您的用户 ID (浏览器开发者工具中 x-notion-active-user-header 的值)
NOTION_USER_ID="在此处粘贴您的 Notion 用户 ID"

# 4) 您的 Notion 用户名 (显示在左上角的名称)
NOTION_USER_NAME="利仔"

# 5) 您的 Notion 登录邮箱
NOTION_USER_EMAIL="q13645947407@gmail.com"

# 可选：想绑定的页面 blockId。留空则不绑定特定页面上下文。
NOTION_BLOCK_ID=""

# 可选：浏览器中看到的客户端版本
NOTION_CLIENT_VERSION="23.13.20251011.2037"

--- 文件路径: Dockerfile ---

# ====================================================================
# Dockerfile for inception-2api (v4.0 - Cloudscraper Edition)
# ====================================================================

FROM python:3.10-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建并切换到非 root 用户
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口并启动
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]


--- 文件路径: docker-compose.yml ---

# docker-compose.yml
services:
  nginx:
    image: nginx:latest
    container_name: notion-2api-nginx
    restart: always
    ports:
      - "${NGINX_PORT:-8088}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - app
    networks:
      - notion-net

  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: notion-2api-app
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - notion-net

networks:
  notion-net:
    driver: bridge


--- 文件路径: main.py ---

# main.py
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.providers.notion_provider import NotionAIProvider

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

provider = NotionAIProvider()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"应用启动中... {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("服务已配置为 Notion AI 代理模式。")
    logger.info(f"服务将在 http://localhost:{settings.NGINX_PORT} 上可用")
    yield
    logger.info("应用关闭。")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan
)

async def verify_api_key(authorization: Optional[str] = Header(None)):
    if settings.API_MASTER_KEY and settings.API_MASTER_KEY != "1":
        if not authorization or "bearer" not in authorization.lower():
            raise HTTPException(status_code=401, detail="需要 Bearer Token 认证。")
        token = authorization.split(" ")[-1]
        if token != settings.API_MASTER_KEY:
            raise HTTPException(status_code=403, detail="无效的 API Key。")

@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request) -> StreamingResponse:
    try:
        request_data = await request.json()
        return await provider.chat_completion(request_data)
    except Exception as e:
        logger.error(f"处理聊天请求时发生顶层错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

@app.get("/v1/models", dependencies=[Depends(verify_api_key)], response_class=JSONResponse)
async def list_models():
    return await provider.get_models()

@app.get("/", summary="根路径")
def root():
    return {"message": f"欢迎来到 {settings.APP_NAME} v{settings.APP_VERSION}. 服务运行正常。"}


--- 文件路径: nginx.conf ---

worker_processes auto;

events {
    worker_connections 1024;
}

http {
    upstream notion_backend {
        server app:8000;
    }

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://notion_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # 【核心修正】增加代理超时时间，以应对Cloudflare挑战
            proxy_connect_timeout 600s;
            proxy_send_timeout 600s;
            proxy_read_timeout 600s;
            send_timeout 600s;
            
            # 流式传输优化
            proxy_buffering off;
            proxy_cache off;
            proxy_set_header Connection '';
            proxy_http_version 1.1;
            chunked_transfer_encoding off;
        }
    }
}


--- 文件路径: requirements.txt ---

# requirements.txt
fastapi
uvicorn[standard]
httpx
pydantic-settings
python-dotenv
cloudscraper


--- 文件路径: app\core\__init__.py ---



--- 文件路径: app\core\config.py ---

# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"
    )

    APP_NAME: str = "notion-2api"
    APP_VERSION: str = "4.0.0" # 最终稳定版
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

    # 【最终修正】更新所有已知的模型列表
    DEFAULT_MODEL: str = "claude-sonnet-4.5"
    
    KNOWN_MODELS: List[str] = [
        "claude-sonnet-4.5",
        "gpt-5",
        "claude-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）",
        "gemini-2.5-pro（未修复，不可用）",
        "gpt-4.1"
    ]
    
    # 【最终修正】根据您提供的信息，填充所有模型的真实后台名称
    MODEL_MAP: dict = {
        "claude-sonnet-4.5": "anthropic-sonnet-alt",
        "gpt-5": "openai-turbo",
        "claude-opus-4.1": "anthropic-opus-4.1",
        "gemini-2.5-flash（未修复，不可用）": "vertex-gemini-2.5-flash",
        "gemini-2.5-pro（未修复，不可用）": "vertex-gemini-2.5-pro",
        "gpt-4.1": "openai-gpt-4.1"
    }

settings = Settings()

--- 文件路径: app\providers\__init__.py ---



--- 文件路径: app\providers\base_provider.py ---

from abc import ABC, abstractmethod
from typing import Dict, Any, Union
from fastapi.responses import StreamingResponse, JSONResponse

class BaseProvider(ABC):
    @abstractmethod
    async def chat_completion(
        self,
        request_data: Dict[str, Any]
    ) -> Union[StreamingResponse, JSONResponse]:
        pass

    @abstractmethod
    async def get_models(self) -> JSONResponse:
        pass


--- 文件路径: app\providers\notion_provider.py ---

# app/providers/notion_provider.py
import json
import time
import logging
import uuid
import re
import cloudscraper
from typing import Dict, Any, AsyncGenerator, List, Optional, Tuple
from datetime import datetime

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.providers.base_provider import BaseProvider
from app.utils.sse_utils import create_sse_data, create_chat_completion_chunk, DONE_CHUNK

# 设置日志记录器
logger = logging.getLogger(__name__)

class NotionAIProvider(BaseProvider):
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.api_endpoints = {
            "runInference": "https://www.notion.so/api/v3/runInferenceTranscript",
            "saveTransactions": "https://www.notion.so/api/v3/saveTransactionsFanout"
        }
        
        if not all([settings.NOTION_COOKIE, settings.NOTION_SPACE_ID, settings.NOTION_USER_ID]):
            raise ValueError("配置错误: NOTION_COOKIE, NOTION_SPACE_ID 和 NOTION_USER_ID 必须在 .env 文件中全部设置。")

        self._warmup_session()

    def _warmup_session(self):
        try:
            logger.info("正在进行会话预热 (Session Warm-up)...")
            headers = self._prepare_headers()
            headers.pop("Accept", None)
            response = self.scraper.get("https://www.notion.so/", headers=headers, timeout=30)
            response.raise_for_status()
            logger.info("会话预热成功。")
        except Exception as e:
            logger.error(f"会话预热失败: {e}", exc_info=True)
            
    async def _create_thread(self, thread_type: str) -> str:
        thread_id = str(uuid.uuid4())
        payload = {
            "requestId": str(uuid.uuid4()),
            "transactions": [{
                "id": str(uuid.uuid4()),
                "spaceId": settings.NOTION_SPACE_ID,
                "operations": [{
                    "pointer": {"table": "thread", "id": thread_id, "spaceId": settings.NOTION_SPACE_ID},
                    "path": [],
                    "command": "set",
                    "args": {
                        "id": thread_id, "version": 1, "parent_id": settings.NOTION_SPACE_ID,
                        "parent_table": "space", "space_id": settings.NOTION_SPACE_ID,
                        "created_time": int(time.time() * 1000),
                        "created_by_id": settings.NOTION_USER_ID, "created_by_table": "notion_user",
                        "messages": [], "data": {}, "alive": True, "type": thread_type
                    }
                }]
            }]
        }
        try:
            logger.info(f"正在创建新的对话线程 (type: {thread_type})...")
            response = await run_in_threadpool(
                lambda: self.scraper.post(
                    self.api_endpoints["saveTransactions"],
                    headers=self._prepare_headers(),
                    json=payload,
                    timeout=20
                )
            )
            response.raise_for_status()
            logger.info(f"对话线程创建成功, Thread ID: {thread_id}")
            return thread_id
        except Exception as e:
            logger.error(f"创建对话线程失败: {e}", exc_info=True)
            raise Exception("无法创建新的对话线程。")

    async def chat_completion(self, request_data: Dict[str, Any]):
        stream = request_data.get("stream", True)

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            request_id = f"chatcmpl-{uuid.uuid4()}"
            incremental_fragments: List[str] = []
            final_message: Optional[str] = None
            
            try:
                model_name = request_data.get("model", settings.DEFAULT_MODEL)
                mapped_model = settings.MODEL_MAP.get(model_name, "anthropic-sonnet-alt")
                
                thread_type = "markdown-chat" if mapped_model.startswith("vertex-") else "workflow"
                
                thread_id = await self._create_thread(thread_type)
                payload = self._prepare_payload(request_data, thread_id, mapped_model, thread_type)
                headers = self._prepare_headers()

                role_chunk = create_chat_completion_chunk(request_id, model_name, role="assistant")
                yield create_sse_data(role_chunk)

                def sync_stream_iterator():
                    try:
                        logger.info(f"请求 Notion AI URL: {self.api_endpoints['runInference']}")
                        logger.info(f"请求体: {json.dumps(payload, indent=2, ensure_ascii=False)}")
                        
                        response = self.scraper.post(
                            self.api_endpoints['runInference'], headers=headers, json=payload, stream=True,
                            timeout=settings.API_REQUEST_TIMEOUT
                        )
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if line:
                                yield line
                    except Exception as e:
                        yield e

                sync_gen = sync_stream_iterator()
              
                while True:
                    line = await run_in_threadpool(lambda: next(sync_gen, None))
                    if line is None:
                        break
                    if isinstance(line, Exception):
                        raise line

                    parsed_results = self._parse_ndjson_line_to_texts(line)
                    for text_type, content in parsed_results:
                        if text_type == 'final':
                            final_message = content
                        elif text_type == 'incremental':
                            incremental_fragments.append(content)
              
                full_response = ""
                if final_message:
                    full_response = final_message
                    logger.info(f"成功从 record-map 或 Gemini patch/event 中提取到最终消息。")
                else:
                    full_response = "".join(incremental_fragments)
                    logger.info(f"使用拼接所有增量片段的方式获得最终消息。")

                if full_response:
                    cleaned_response = self._clean_content(full_response)
                    logger.info(f"清洗后的最终响应: {cleaned_response}")
                    chunk = create_chat_completion_chunk(request_id, model_name, content=cleaned_response)
                    yield create_sse_data(chunk)
                else:
                    logger.warning("警告: Notion 返回的数据流中未提取到任何有效文本。请检查您的 .env 配置是否全部正确且凭证有效。")

                final_chunk = create_chat_completion_chunk(request_id, model_name, finish_reason="stop")
                yield create_sse_data(final_chunk)
                yield DONE_CHUNK

            except Exception as e:
                error_message = f"处理 Notion AI 流时发生意外错误: {str(e)}"
                logger.error(error_message, exc_info=True)
                error_chunk = {"error": {"message": error_message, "type": "internal_server_error"}}
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK

        if stream:
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            raise HTTPException(status_code=400, detail="此端点当前仅支持流式响应 (stream=true)。")

    def _prepare_headers(self) -> Dict[str, str]:
        cookie_source = (settings.NOTION_COOKIE or "").strip()
        cookie_header = cookie_source if "=" in cookie_source else f"token_v2={cookie_source}"

        return {
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "Cookie": cookie_header,
            "x-notion-space-id": settings.NOTION_SPACE_ID,
            "x-notion-active-user-header": settings.NOTION_USER_ID,
            "x-notion-client-version": settings.NOTION_CLIENT_VERSION,
            "notion-audit-log-platform": "web",
            "Origin": "https://www.notion.so",
            "Referer": "https://www.notion.so/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }

    def _normalize_block_id(self, block_id: str) -> str:
        if not block_id: return block_id
        b = block_id.replace("-", "").strip()
        if len(b) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", b):
            return f"{b[0:8]}-{b[8:12]}-{b[12:16]}-{b[16:20]}-{b[20:]}"
        return block_id

    def _prepare_payload(self, request_data: Dict[str, Any], thread_id: str, mapped_model: str, thread_type: str) -> Dict[str, Any]:
        req_block_id = request_data.get("notion_block_id") or settings.NOTION_BLOCK_ID
        normalized_block_id = self._normalize_block_id(req_block_id) if req_block_id else None

        context_value: Dict[str, Any] = {
            "timezone": "Asia/Shanghai",
            "spaceId": settings.NOTION_SPACE_ID,
            "userId": settings.NOTION_USER_ID,
            "userEmail": settings.NOTION_USER_EMAIL,
            "currentDatetime": datetime.now().astimezone().isoformat(),
        }
        if normalized_block_id:
            context_value["blockId"] = normalized_block_id

        config_value: Dict[str, Any]
        
        if mapped_model.startswith("vertex-"):
            logger.info(f"检测到 Gemini 模型 ({mapped_model})，应用特定的 config 和 context。")
            context_value.update({
                "userName": f" {settings.NOTION_USER_NAME}",
                "spaceName": f"{settings.NOTION_USER_NAME}的 Notion",
                "spaceViewId": "2008eefa-d0dc-80d5-9e67-000623befd8f",
                "surface": "ai_module"
            })
            config_value = {
                "type": thread_type,
                "model": mapped_model,
                "useWebSearch": True,
                "enableAgentAutomations": False, "enableAgentIntegrations": False,
                "enableBackgroundAgents": False, "enableCodegenIntegration": False,
                "enableCustomAgents": False, "enableExperimentalIntegrations": False,
                "enableLinkedDatabases": False, "enableAgentViewVersionHistoryTool": False,
                "searchScopes": [{"type": "everything"}], "enableDatabaseAgents": False,
                "enableAgentComments": False, "enableAgentForms": False,
                "enableAgentMakesFormulas": False, "enableUserSessionContext": False,
                "modelFromUser": True, "isCustomAgent": False
            }
        else:
            context_value.update({
                "userName": settings.NOTION_USER_NAME,
                "surface": "workflows"
            })
            config_value = {
                "type": thread_type,
                "model": mapped_model,
                "useWebSearch": True,
            }

        transcript = [
            {"id": str(uuid.uuid4()), "type": "config", "value": config_value},
            {"id": str(uuid.uuid4()), "type": "context", "value": context_value}
        ]
      
        for msg in request_data.get("messages", []):
            if msg.get("role") == "user":
                transcript.append({
                    "id": str(uuid.uuid4()),
                    "type": "user",
                    "value": [[msg.get("content")]],
                    "userId": settings.NOTION_USER_ID,
                    "createdAt": datetime.now().astimezone().isoformat()
                })
            elif msg.get("role") == "assistant":
                transcript.append({"id": str(uuid.uuid4()), "type": "agent-inference", "value": [{"type": "text", "content": msg.get("content")}]})

        payload = {
            "traceId": str(uuid.uuid4()),
            "spaceId": settings.NOTION_SPACE_ID,
            "transcript": transcript,
            "threadId": thread_id,
            "createThread": False,
            "isPartialTranscript": True,
            "asPatchResponse": True,
            "generateTitle": True,
            "saveAllThreadOperations": True,
            "threadType": thread_type
        }

        if mapped_model.startswith("vertex-"):
            logger.info("为 Gemini 请求添加 debugOverrides。")
            payload["debugOverrides"] = {
                "emitAgentSearchExtractedResults": True,
                "cachedInferences": {},
                "annotationInferences": {},
                "emitInferences": False
            }
        
        return payload

    def _clean_content(self, content: str) -> str:
        if not content:
            return ""
            
        content = re.sub(r'<lang primary="[^"]*"\s*/>\n*', '', content)
        content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<thought>[\s\S]*?</thought>\s*', '', content, flags=re.IGNORECASE)
        
        content = re.sub(r'^.*?Chinese whatmodel I am.*?Theyspecifically.*?requested.*?me.*?to.*?reply.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?This.*?is.*?a.*?straightforward.*?question.*?about.*?my.*?identity.*?asan.*?AI.*?assistant\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?Idon\'t.*?need.*?to.*?use.*?any.*?tools.*?for.*?this.*?-\s*it\'s.*?asimple.*?informational.*?response.*?aboutwhat.*?I.*?am\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?Sincethe.*?user.*?asked.*?in.*?Chinese.*?and.*?specifically.*?requested.*?a.*?Chinese.*?response.*?I.*?should.*?respond.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?What model are you.*?in Chinese and specifically requesting.*?me.*?to.*?reply.*?in.*?Chinese\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?This.*?is.*?a.*?question.*?about.*?my.*?identity.*?not requiring.*?any.*?tool.*?use.*?I.*?should.*?respond.*?directly.*?to.*?the.*?user.*?in.*?Chinese.*?as.*?requested\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?I.*?should.*?identify.*?myself.*?as.*?Notion.*?AI.*?as.*?mentioned.*?in.*?the.*?system.*?prompt.*?\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'^.*?I.*?should.*?not.*?make.*?specific.*?claims.*?about.*?the.*?underlying.*?model.*?architecture.*?since.*?that.*?information.*?is.*?not.*?provided.*?in.*?my.*?context\.\s*', '', content, flags=re.IGNORECASE | re.DOTALL)
        
        return content.strip()

    def _parse_ndjson_line_to_texts(self, line: bytes) -> List[Tuple[str, str]]:
        results: List[Tuple[str, str]] = []
        try:
            s = line.decode("utf-8", errors="ignore").strip()
            if not s: return results
            
            data = json.loads(s)
            logger.debug(f"原始响应数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 格式1: Gemini 返回的 markdown-chat 事件
            if data.get("type") == "markdown-chat":
                content = data.get("value", "")
                if content:
                    logger.info("从 'markdown-chat' 直接事件中提取到内容。")
                    results.append(('final', content))

            # 格式2: Claude 和 GPT 返回的补丁流，以及 Gemini 的 patch 格式
            elif data.get("type") == "patch" and "v" in data:
                for operation in data.get("v", []):
                    if not isinstance(operation, dict): continue
                    
                    op_type = operation.get("o")
                    path = operation.get("p", "")
                    value = operation.get("v")
                    
                    # 【修改】Gemini 的完整内容 patch 格式
                    if op_type == "a" and path.endswith("/s/-") and isinstance(value, dict) and value.get("type") == "markdown-chat":
                        content = value.get("value", "")
                        if content:
                            logger.info("从 'patch' (Gemini-style) 中提取到完整内容。")
                            results.append(('final', content))
                    
                    # 【修改】Gemini 的增量内容 patch 格式
                    elif op_type == "x" and "/s/" in path and path.endswith("/value") and isinstance(value, str):
                        content = value
                        if content:
                            logger.info(f"从 'patch' (Gemini增量) 中提取到内容: {content}")
                            results.append(('incremental', content))
                    
                    # 【修改】Claude 和 GPT 的增量内容 patch 格式
                    elif op_type == "x" and "/value/" in path and isinstance(value, str):
                        content = value
                        if content:
                            logger.info(f"从 'patch' (Claude/GPT增量) 中提取到内容: {content}")
                            results.append(('incremental', content))
                    
                    # 【修改】Claude 和 GPT 的完整内容 patch 格式
                    elif op_type == "a" and path.endswith("/value/-") and isinstance(value, dict) and value.get("type") == "text":
                        content = value.get("content", "")
                        if content:
                            logger.info("从 'patch' (Claude/GPT-style) 中提取到完整内容。")
                            results.append(('final', content))

            # 格式3: 处理record-map类型的数据
            elif data.get("type") == "record-map" and "recordMap" in data:
                record_map = data["recordMap"]
                if "thread_message" in record_map:
                    for msg_id, msg_data in record_map["thread_message"].items():
                        value_data = msg_data.get("value", {}).get("value", {})
                        step = value_data.get("step", {})
                        if not step: continue

                        content = ""
                        step_type = step.get("type")

                        if step_type == "markdown-chat":
                            content = step.get("value", "")
                        elif step_type == "agent-inference":
                            agent_values = step.get("value", [])
                            if isinstance(agent_values, list):
                                for item in agent_values:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        content = item.get("content", "")
                                        break
                        
                        if content and isinstance(content, str):
                            logger.info(f"从 record-map (type: {step_type}) 提取到最终内容。")
                            results.append(('final', content))
                            break 
    
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"解析NDJSON行失败: {e} - Line: {line.decode('utf-8', errors='ignore')}")
        
        return results

    async def get_models(self) -> JSONResponse:
        model_data = {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "created": int(time.time()), "owned_by": "lzA6"}
                for name in settings.KNOWN_MODELS
            ]
        }
        return JSONResponse(content=model_data)


--- 文件路径: app\utils\sse_utils.py ---

# app/utils/sse_utils.py
import json
import time
from typing import Dict, Any, Optional

DONE_CHUNK = b"data: [DONE]\n\n"

def create_sse_data(data: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode('utf-8')

def create_chat_completion_chunk(
    request_id: str,
    model: str,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
    role: Optional[str] = None
) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content

    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason
            }
        ]
    }
```

---

## 📊 统计

- 文件数量：15
- 总行数：2,164
- 总字符数：75,285