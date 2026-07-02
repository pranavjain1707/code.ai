import json
import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional
import httpx
from app.config.settings import settings
from app.services.redis_cache import cache_service

logger = logging.getLogger(__name__)

# Fallback local models if the local docker runner is offline
FALLBACK_LOCAL_MODELS = [
    {"id": "llama3", "name": "Llama 3 (Local)"},
    {"id": "mistral", "name": "Mistral (Local)"},
    {"id": "gemma2", "name": "Gemma 2 (Local)"},
    {"id": "phi3", "name": "Phi 3 (Local)"}
]

class LocalModelService:
    def __init__(self):
        self.base_url = settings.DOCKER_MODEL_RUNNER_URL.rstrip('/')
        self.headers = {
            "Content-Type": "application/json"
        }

    def count_tokens(self, text: str) -> int:
        """Estimate token count for a text chunk (approx 4 chars per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Local models run free, so cost is always 0.0."""
        return 0.0

    async def get_models(self) -> List[Dict[str, Any]]:
        """Get models available from the local Docker Model Runner with caching."""
        cache_key = "local_models_list"
        cached_models = cache_service.get(cache_key)
        
        if cached_models:
            try:
                return json.loads(cached_models)
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/models")
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("data", []):
                        model_id = model.get("id")
                        # Format a user-friendly name, e.g., "Llama 3 (Local)"
                        name = model_id.split("/")[-1].replace("-", " ").replace(":", " ").title()
                        models.append({
                            "id": model_id,
                            "name": f"{name} (Local)",
                            "pricing": {"prompt": "0.0", "completion": "0.0"}
                        })
                    if models:
                        # Cache local models list for 10 minutes
                        cache_service.set(cache_key, json.dumps(models), expire_seconds=600)
                        return models
        except Exception as e:
            logger.warning(f"Failed to fetch models from local runner: {e}")
            
        return FALLBACK_LOCAL_MODELS

    async def _send_request_with_retry(
        self, 
        payload: Dict[str, Any], 
        stream: bool = False
    ) -> httpx.Response:
        """Execute request to local model runner with retry backoff."""
        retries = 3
        backoff = 1.0
        
        for attempt in range(retries):
            try:
                if stream:
                    client = httpx.AsyncClient(timeout=30.0)
                    req = client.build_request("POST", f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
                    response = await client.send(req, stream=True)
                    if response.status_code == 429:
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        await client.aclose()
                        continue
                    return response
                else:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
                        if response.status_code == 429:
                            await asyncio.sleep(backoff)
                            backoff *= 2.0
                            continue
                        return response
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                logger.warning(f"Network/Timeout on attempt {attempt+1}: {e}")
                if attempt == retries - 1:
                    raise e
                await asyncio.sleep(backoff)
                backoff *= 2.0
        raise Exception(f"Failed to contact local model runner at {self.base_url} after multiple retries.")

    async def send_message(self, model: str, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Send a standard blocking chat completion request to the local runner."""
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        payload = {
            "model": model,
            "messages": formatted_messages
        }

        try:
            response = await self._send_request_with_retry(payload, stream=False)
            if response.status_code != 200:
                logger.error(f"Local runner Error {response.status_code}: {response.text}")
                raise Exception(f"Local runner returned status code {response.status_code}: {response.text}")
            
            data = response.json()
            choices = data.get("choices", [])
            choice_msg = choices[0].get("message", {}) if choices else {}
            content = choice_msg.get("content", "")
            reasoning = choice_msg.get("reasoning_details") or choice_msg.get("reasoning") or choice_msg.get("reasoning_content")
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", self.count_tokens(str(formatted_messages)))
            completion_tokens = usage.get("completion_tokens", self.count_tokens(content))
            
            return {
                "content": content,
                "reasoning": reasoning,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "estimated_cost": 0.0
            }
        except Exception as e:
            logger.error(f"Error in send_message: {e}")
            raise e

    async def stream_response(self, model: str, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Stream chat completions from the local runner via Server-Sent Events (SSE)."""
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        payload = {
            "model": model,
            "messages": formatted_messages,
            "stream": True
        }

        response = None
        try:
            response = await self._send_request_with_retry(payload, stream=True)
            if response.status_code != 200:
                err_content = await response.aread()
                err_text = err_content.decode('utf-8')
                logger.error(f"Local runner Streaming Error {response.status_code}: {err_text}")
                error_msg = f"Local Runner Error {response.status_code}"
                try:
                    err_json = json.loads(err_text)
                    if "error" in err_json and "message" in err_json["error"]:
                        error_msg = err_json["error"]["message"]
                except Exception:
                    pass
                yield f"data: {json.dumps({'error': error_msg})}\n\n"
                return

            accumulated_content = []
            accumulated_reasoning = []
            
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        p_tokens = self.count_tokens(str(formatted_messages))
                        c_tokens = self.count_tokens("".join(accumulated_content))
                        usage_summary = {
                            "done": True,
                            "reasoning": "".join(accumulated_reasoning),
                            "prompt_tokens": p_tokens,
                            "completion_tokens": c_tokens,
                            "total_tokens": p_tokens + c_tokens,
                            "estimated_cost": 0.0
                        }
                        yield f"data: {json.dumps(usage_summary)}\n\n"
                        break
                    
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            
                            # Handle reasoning chunks if present
                            reasoning_chunk = delta.get("reasoning") or delta.get("reasoning_details") or delta.get("reasoning_content")
                            if reasoning_chunk:
                                accumulated_reasoning.append(reasoning_chunk)
                                yield f"data: {json.dumps({'reasoning': reasoning_chunk})}\n\n"
                            
                            # Handle content chunks
                            content_chunk = delta.get("content", "")
                            if content_chunk:
                                accumulated_content.append(content_chunk)
                                yield f"data: {json.dumps({'content': content_chunk})}\n\n"
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in stream_response: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if response:
                await response.aclose()

# Singleton local model service instance
local_model_service = LocalModelService()
