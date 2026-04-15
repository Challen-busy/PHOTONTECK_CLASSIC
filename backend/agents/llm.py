"""
LLM接口层 — 唯一和AI模型打交道的文件

整个项目只在这里配置模型和API Key
换模型 = 改这两行
"""

import json
import os

import httpx

# ===== 全局唯一配置（从环境变量读）=====
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "z-ai/glm-5.1")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
# ========================

if not API_KEY:
    import warnings
    warnings.warn("OPENROUTER_API_KEY 未设置，LLM 调用会失败。export OPENROUTER_API_KEY=xxx 再启动。")


async def call_llm(
    messages: list[dict],
    system: str = "",
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
    **kwargs,  # 忽略其他参数（如旧代码传的model=xxx）
) -> dict:
    """
    调用LLM，返回统一格式

    整个系统所有Agent都调这一个函数，用同一个模型
    """
    # 构建OpenRouter请求（OpenAI兼容格式）
    oai_messages = []
    if system:
        oai_messages.append({"role": "system", "content": system})

    for msg in messages:
        if msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, list):
                # tool_result格式转换
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        parts.append(f"[Tool Result for {item.get('tool_use_id', '?')}]: {item.get('content', '')}")
                    elif isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    else:
                        parts.append(str(item))
                oai_messages.append({"role": "user", "content": "\n".join(parts)})
            else:
                oai_messages.append({"role": "user", "content": content})
        elif msg["role"] == "assistant":
            content = msg["content"]
            if hasattr(content, '__iter__') and not isinstance(content, str):
                text_parts = []
                tool_calls = []
                for block in content:
                    if hasattr(block, 'type'):
                        if block.type == "text":
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id, "type": "function",
                                "function": {"name": block.name, "arguments": json.dumps(block.input)},
                            })
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"], "type": "function",
                                "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                            })
                assistant_msg = {"role": "assistant", "content": " ".join(text_parts) or None}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                oai_messages.append(assistant_msg)
            else:
                oai_messages.append({"role": "assistant", "content": str(content)})

    # 构建tools（OpenAI格式）
    oai_tools = None
    if tools:
        oai_tools = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        } for t in tools]

    body = {"model": MODEL, "messages": oai_messages, "max_tokens": max_tokens}
    if oai_tools:
        body["tools"] = oai_tools

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(BASE_URL, headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }, json=body)
        data = resp.json()

    if "error" in data:
        return {"text": f"LLM错误: {data['error'].get('message', str(data['error']))}", "tool_calls": [], "tokens": 0, "stop_reason": "error", "raw": data}

    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})

    text = msg.get("content", "") or ""
    tool_calls = []
    for tc in msg.get("tool_calls", []):
        func = tc.get("function", {})
        try:
            parsed_args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            parsed_args = {}
        tool_calls.append({"id": tc.get("id", ""), "name": func.get("name", ""), "input": parsed_args})

    return {
        "text": text,
        "tool_calls": tool_calls,
        "tokens": data.get("usage", {}).get("total_tokens", 0),
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "raw": data,
    }


def build_tool_result_message(tool_call_id: str, result: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_call_id, "content": result}
