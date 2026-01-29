import json
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import cloudscraper
from app.core.config import settings

logger = logging.getLogger(__name__)


class NotionAIProvider:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.base_url = "https://www.notion.so"
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Notion-Client-Version": "23.13.0.1",
            "x-notion-active-user-header": settings.NOTION_USER_ID,
            "x-notion-space-id": settings.NOTION_SPACE_ID,
        }
        self.cookies = {"token_v2": settings.NOTION_COOKIE}
        self._warmup_session()

    def _warmup_session(self):
        """预热会话，建立 Cloudflare 信任"""
        try:
            logger.info("正在进行会话预热 (Session Warm-up)...")
            response = self.scraper.get(
                self.base_url,
                headers=self.headers,
                cookies=self.cookies,
                timeout=10,
            )
            response.raise_for_status()
            logger.info("会话预热成功。")
        except Exception as e:
            logger.error(f"会话预热失败: {e}")

    async def _create_thread(self, thread_type: str = "workflow") -> str:
        """创建新的对话线程"""
        thread_id = str(uuid.uuid4())
        logger.info(f"正在创建新的对话线程 (type: {thread_type})...")

        payload = {
            "requestId": str(uuid.uuid4()),
            "transactions": [
                {
                    "id": str(uuid.uuid4()),
                    "spaceId": settings.NOTION_SPACE_ID,
                    "operations": [
                        {
                            "pointer": {
                                "table": "thread",
                                "id": thread_id,
                                "spaceId": settings.NOTION_SPACE_ID,
                            },
                            "command": "set",
                            "path": [],
                            "args": {
                                "type": thread_type,
                                "id": thread_id,
                                "space_id": settings.NOTION_SPACE_ID,
                                "parent_id": settings.NOTION_SPACE_ID,
                                "parent_table": "space",
                                "alive": True,
                            },
                        }
                    ],
                }
            ],
        }

        try:
            response = self.scraper.post(
                f"{self.base_url}/api/v3/saveTransactionsFanout",
                headers=self.headers,
                cookies=self.cookies,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            logger.info(f"对话线程创建成功, Thread ID: {thread_id}")
            return thread_id
        except Exception as e:
            logger.error(f"创建对话线程失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"HTTP 状态码: {e.response.status_code}")
                logger.error(f"响应内容: {e.response.text[:500]}")
            raise Exception("无法创建新的对话线程。")

    async def stream_chat(
        self,
        messages: list,
        model: str = "apple-danish",
        stream: bool = True,
        thread_type: str = "workflow",
    ) -> AsyncGenerator[str, None]:
        """流式聊天接口"""
        async for chunk in self.stream_generator(messages, model, thread_type):
            yield chunk

    async def stream_generator(
        self,
        messages: list,
        model: str,
        thread_type: str = "workflow",
    ) -> AsyncGenerator[str, None]:
        """生成流式响应"""
        try:
            # 构建 transcript
            transcript = self._build_transcript(messages, model, thread_type)

            payload = {
                "traceId": str(uuid.uuid4()),
                "spaceId": settings.NOTION_SPACE_ID,
                "transcript": transcript,
                "createThread": True,  # 让 Notion 自动创建线程
                "isPartialTranscript": True,
                "asPatchResponse": True,
                "generateTitle": True,
                "saveAllThreadOperations": True,
                "threadType": thread_type,
            }

            url = f"{self.base_url}/api/v3/runInferenceTranscript"
            logger.info(f"请求 Notion AI URL: {url}")
            logger.info(f"请求体: {json.dumps(payload, indent=2, ensure_ascii=False)}")

            response = self.scraper.post(
                url,
                headers=self.headers,
                cookies=self.cookies,
                json=payload,
                stream=True,
                timeout=120,
            )
            response.raise_for_status()

            full_content = ""
            buffer = ""
            last_text_content = ""

            for chunk in response.iter_content(chunk_size=None):
                if not chunk:
                    continue

                # 解码 bytes 为 str
                chunk_str = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                buffer += chunk_str

                # 尝试解析 buffer 中的完整 JSON 对象
                while buffer:
                    # 找到第一个 { 的位置
                    start = buffer.find("{")
                    if start == -1:
                        buffer = ""
                        break

                    # 尝试找到匹配的 }
                    depth = 0
                    end = -1
                    for i in range(start, len(buffer)):
                        if buffer[i] == "{":
                            depth += 1
                        elif buffer[i] == "}":
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break

                    if end == -1:
                        # 没有找到完整的 JSON，等待更多数据
                        buffer = buffer[start:]
                        break

                    json_str = buffer[start:end]
                    buffer = buffer[end:]

                    try:
                        data = json.loads(json_str)
                        
                        # 处理 agent-inference 类型的消息（流式累积更新）
                        if data.get("type") == "agent-inference":
                            value_list = data.get("value", [])
                            for item in value_list:
                                if item.get("type") == "text":
                                    raw_content = item.get("content", "")
                                    
                                    # 处理开头未闭合的 <lang> 标签，防止输出乱码
                                    if raw_content.lstrip().startswith("<lang") and "/>" not in raw_content and ">" not in raw_content:
                                        clean_content = ""
                                    else:
                                        # 过滤掉 <lang> 标签
                                        clean_content = re.sub(r'<lang[^>]*/>', '', raw_content)
                                        clean_content = re.sub(r'<lang[^>]*>', '', clean_content) # 过滤残留
                                        
                                    if clean_content:
                                        # 计算增量
                                        if len(clean_content) > len(last_text_content):
                                            delta = clean_content[len(last_text_content):]
                                            last_text_content = clean_content
                                            yield self._format_sse_chunk(delta)

                        # 格式1: 处理 record-map 类型的数据（兜底，通常包含最终完整响应）
                        elif data.get("type") == "record-map" and "recordMap" in data:
                            record_map = data["recordMap"]
                            if "thread_message" in record_map:
                                for msg_id, msg_data in record_map["thread_message"].items():
                                    value_data = msg_data.get("value", {}).get("value", {})
                                    step = value_data.get("step", {})
                                    if not step:
                                        continue
                                    
                                    content = ""
                                    step_type = step.get("type")
                                    
                                    if step_type == "agent-inference":
                                        agent_values = step.get("value", [])
                                        if isinstance(agent_values, list):
                                            for item in agent_values:
                                                if isinstance(item, dict) and item.get("type") == "text":
                                                    content = item.get("content", "")
                                                    break
                                    
                                    if content and isinstance(content, str):
                                        # 如果之前流式已经发送了部分，这里只发送剩余的
                                        if len(content) > len(last_text_content):
                                            delta = content[len(last_text_content):]
                                            last_text_content = content
                                            yield self._format_sse_chunk(delta)
                                        # 标记已获取完整内容
                                        full_content = content
                                        break
                        
                        # 格式2: 处理 patch 类型的消息（旧版协议）
                        elif data.get("type") == "patch" and "v" in data:
                             for op in data.get("v", []):
                                if op.get("o") == "x" and "/value/" in op.get("p", ""):
                                    # Patch 通常是增量的，直接发送
                                    val = op.get("v", "")
                                    if val:
                                        yield self._format_sse_chunk(val)


                    except json.JSONDecodeError:
                        continue

            if full_content:
                logger.info(f"成功提取响应内容，长度: {len(full_content)} 字符")
            else:
                logger.warning("警告: Notion 返回的数据流中未提取到任何有效文本。请检查您的 .env 配置是否全部正确且凭证有效。")

            # 发送结束标记
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"处理 Notion AI 流时发生意外错误: {e}")
            import traceback
            traceback.print_exc()
            yield self._format_sse_error(str(e))

    def _build_transcript(self, messages: list, model: str, thread_type: str) -> list:
        """构建 Notion AI 的 transcript 格式"""
        now = datetime.now(timezone.utc).astimezone()
        timestamp = now.isoformat()

        transcript = [
            {
                "id": str(uuid.uuid4()),
                "type": "config",
                "value": {
                    "type": thread_type,
                    "model": model,
                    "useWebSearch": True,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "type": "context",
                "value": {
                    "timezone": "Asia/Shanghai",
                    "spaceId": settings.NOTION_SPACE_ID,
                    "userId": settings.NOTION_USER_ID,
                    "userEmail": settings.NOTION_USER_EMAIL if hasattr(settings, 'NOTION_USER_EMAIL') else "",
                    "currentDatetime": timestamp,
                    "userName": settings.NOTION_USER_NAME if hasattr(settings, 'NOTION_USER_NAME') else "User",
                    "surface": "workflows",
                },
            },
        ]

        # 添加用户消息
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                transcript.append(
                    {
                        "id": str(uuid.uuid4()),
                        "type": "user",
                        "value": [[content]],
                        "userId": settings.NOTION_USER_ID,
                        "createdAt": timestamp,
                    }
                )
            elif role == "assistant":
                transcript.append(
                    {
                        "id": str(uuid.uuid4()),
                        "type": "agent-inference",
                        "value": [{"type": "text", "content": content}],
                    }
                )

        return transcript

    def _format_sse_chunk(self, content: str) -> str:
        """格式化为 OpenAI SSE 格式"""
        data = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion.chunk",
            "created": int(datetime.now().timestamp()),
            "model": "notion-ai",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _format_sse_error(self, error: str) -> str:
        """格式化错误为 SSE"""
        data = {
            "error": {
                "message": error,
                "type": "server_error",
            }
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def chat_completion(self, request_data: dict):
        """处理聊天完成请求（main.py 调用的接口）"""
        from fastapi.responses import StreamingResponse
        
        messages = request_data.get("messages", [])
        model = request_data.get("model", settings.DEFAULT_MODEL)
        stream = request_data.get("stream", True)
        
        # 模型映射
        notion_model = settings.MODEL_MAP.get(model, "apple-danish")
        logger.info(f"收到聊天请求，模型: {model} -> {notion_model}")
        
        # 返回流式响应
        return StreamingResponse(
            self.stream_chat(messages, notion_model, stream),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    async def get_models(self):
        """获取可用模型列表（main.py 调用的接口）"""
        models = []
        for model_name in settings.KNOWN_MODELS:
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": "notion-ai",
            })
        
        return {
            "object": "list",
            "data": models
        }
