"""
LLM API 调用封装 — 支持多模型混合配置 + 记忆注入

每个Agent根据其角色有独立的记忆系统：
- 产品战略官: 长期战略记忆（产品定位、竞品动态、战略决策）
- 用户体验官: 用户画像记忆（用户旅程、情感地图、原声库）
- 数据研究员: 数据结论记忆（数据结论、缺口记录、方法论）
- 逻辑校验官: 短期对话记忆（仅当前对话上下文）

每个Agent可独立配置模型，实现"对的模型做对的事"。
支持任意兼容OpenAI格式的API提供商。
"""

import os
import logging
import httpx

from agents import AGENT_MODEL_MAP
from memory import get_agent_memory_context

logger = logging.getLogger("feishu-agents.llm")


async def call_llm(system_prompt: str, user_message: str, agent_name: str = "default") -> tuple:
    """
    调用 LLM API 生成回复，支持按Agent选择不同模型 + 记忆注入
    
    参数:
        system_prompt: Agent的System Prompt
        user_message: 用户消息
        agent_name: Agent名称，用于选择对应模型和记忆
    
    返回:
        (reply_text, tokens_used, model_used)
    
    记忆系统:
        产品战略官: 注入长期战略记忆（产品定位、竞品动态等）
        用户体验官: 注入用户画像记忆（旅程、情感、原声等）
        数据研究员: 注入数据结论记忆（历史结论、数据缺口等）
        逻辑校验官: 注入近期对话记录（供审查使用）
    """
    
    # 获取通用配置
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise ValueError("LLM_API_KEY 环境变量未设置")
    
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "120"))
    
    # 获取该Agent的模型配置
    model = AGENT_MODEL_MAP.get(agent_name, "deepseek-chat")
    
    # 支持为特定Agent配置独立的API Key和Base URL
    agent_api_key = os.environ.get(f"LLM_API_KEY_{agent_name}", "") or api_key
    agent_base_url = os.environ.get(f"LLM_BASE_URL_{agent_name}", "") or base_url
    agent_base_url = agent_base_url.rstrip("/")
    
    # 按Agent调整temperature
    effective_temperature = temperature
    if agent_name == "逻辑校验官":
        effective_temperature = 0.2   # 极致严谨
    elif agent_name == "产品战略官":
        effective_temperature = 0.85  # 创意发散
    elif agent_name == "数据研究员":
        effective_temperature = 0.4   # 数据严谨
    elif agent_name == "用户体验官":
        effective_temperature = 0.75  # 共情温度
    
    # ============ 记忆注入 ============
    # 获取Agent的记忆上下文
    memory_context = get_agent_memory_context(agent_name, user_message)
    
    # 构建消息序列
    messages = [{"role": "system", "content": system_prompt}]
    
    # 有长期记忆的Agent，在system后注入记忆
    if agent_name in ["产品战略官", "用户体验官", "数据研究员"] and memory_context and len(memory_context) > 30:
        messages.append({
            "role": "system", 
            "content": f"【你的历史记忆（每次回复前先回顾）】\n{memory_context}\n\n以上是你的历史记忆，请基于这些记忆进行分析，保持思考的连续性。"
        })
    
    # 逻辑校验官注入近期对话
    if agent_name == "逻辑校验官":
        from memory import get_all_recent_analysis
        recent = get_all_recent_analysis(limit=5)
        if recent and len(recent) > 30:
            messages.append({
                "role": "system",
                "content": f"【近期对话记录（供你审查）】\n{recent}\n\n请审查以上各Agent的分析。"
            })
    
    messages.append({"role": "user", "content": user_message})
    
    # 构建请求
    url = f"{agent_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {agent_api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": effective_temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    
    # 发送请求
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info(
                f"[{agent_name}] 调用LLM: model={model}, "
                f"temp={effective_temperature}, "
                f"mem_len={len(memory_context) if memory_context else 0}, "
                f"msg_len={len(user_message)}"
            )
            resp = await client.post(url, headers=headers, json=payload)
            
            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(f"[{agent_name}] LLM API错误: status={resp.status_code}, body={error_text}")
                raise RuntimeError(f"LLM API返回错误: {resp.status_code} - {error_text}")
            
            result = resp.json()
            
            # 提取回复内容
            choices = result.get("choices", [])
            if not choices:
                raise RuntimeError("LLM API返回空choices")
            
            content = choices[0].get("message", {}).get("content", "")
            usage = result.get("usage", {})
            
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = prompt_tokens + completion_tokens
            
            logger.info(
                f"[{agent_name}] LLM响应完成: "
                f"model={model}, "
                f"prompt={prompt_tokens}t, "
                f"completion={completion_tokens}t, "
                f"total={total_tokens}t"
            )
            
            return content.strip(), total_tokens, model
            
    except httpx.TimeoutException:
        logger.error(f"[{agent_name}] LLM API请求超时")
        raise RuntimeError("LLM API请求超时，请稍后重试")
    except httpx.ConnectError as e:
        logger.error(f"[{agent_name}] LLM API连接失败: {e}")
        raise RuntimeError(f"无法连接到LLM API，请检查网络或BASE_URL配置")
    except Exception as e:
        logger.error(f"[{agent_name}] LLM调用异常: {e}")
        raise RuntimeError(f"LLM调用失败: {str(e)[:200]}")
