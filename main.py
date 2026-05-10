"""
四Agent飞书消息路由服务 — 严格@mention版本
只有被@的机器人才回复
"""

import os
import json
import re
import logging
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from agents import SYSTEM_PROMPTS, ANALYSIS_AGENTS
from llm import call_llm
from memory import (
    save_conversation,
    save_agent_memory,
    get_all_recent_analysis as get_db_recent_analysis,
)
from feishu_bot import send_message_to_chat, send_text_message

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("feishu-agents")

# ============ FastAPI 应用 ============
app = FastAPI(
    title="四Agent飞书消息路由服务",
    description="产品战略官 | 用户体验官 | 数据研究员 | 逻辑校验官",
    version="3.0.0"
)

# ============ Agent列表 ============
AGENT_NAMES = ["产品战略官", "用户体验官", "数据研究员", "逻辑校验官"]

# 英文到中文的映射
AGENT_NAME_MAP = {
    "strategy": "产品战略官",
    "ux": "用户体验官",
    "data": "数据研究员",
    "logic": "逻辑校验官",
}

# ============ 消息历史缓存 ============
MESSAGE_HISTORY = []
MAX_HISTORY = 100

def save_to_history(agent_name, question, answer):
    MESSAGE_HISTORY.append({
        "agent": agent_name,
        "question": question,
        "answer": answer,
        "time": datetime.now().isoformat()
    })
    if len(MESSAGE_HISTORY) > MAX_HISTORY:
        MESSAGE_HISTORY.pop(0)

# ============ @mention检测 ============

def check_mentioned(agent_name, text):
    """
    检查消息中是否@了指定机器人
    支持飞书<at>标签格式和纯文本格式
    """
    if not text:
        return False

    # 1. 检查飞书<at>标签格式: <at id="ou_xxx">@产品战略官</at>
    at_pattern = f'<at[^>]*>@{re.escape(agent_name)}</at>'
    if re.search(at_pattern, text):
        return True

    # 2. 检查纯文本格式: @产品战略官
    text_pattern = f'@{re.escape(agent_name)}'
    if text_pattern in text:
        return True

    return False

def extract_mentioned_agents(text):
    """
    从消息中提取所有被@的机器人
    返回被@的机器人列表
    """
    if not text:
        return []

    mentioned = []

    # 1. 提取<at>标签中的@mention
    at_matches = re.findall(r'<at[^>]*>@([^<]+)</at>', text)
    mentioned.extend(at_matches)

    # 2. 提取纯文本@mention
    text_matches = re.findall(r'@([^\s@]+)', text)
    mentioned.extend(text_matches)

    # 过滤出有效的Agent名称
    valid_mentions = [name for name in mentioned if name in AGENT_NAMES]

    return valid_mentions

# ============ 核心处理逻辑 ============

async def handle_agent_request(agent_name, question):
    system_prompt = SYSTEM_PROMPTS.get(agent_name, SYSTEM_PROMPTS["产品战略官"])

    if agent_name == "逻辑校验官" and ("审查以上" in question or "审查" in question):
        recent = get_db_recent_analysis(limit=5)
        context = f"近期分析记录：\n{recent}\n\n用户要求：{question}"
    else:
        context = question

    try:
        response, tokens_used, model_used = await call_llm(system_prompt, context, agent_name=agent_name)
        return response, tokens_used, model_used
    except Exception as e:
        logger.error(f"[{agent_name}] LLM调用失败: {e}")
        return f"❌ 服务暂时异常，请稍后重试。\n错误: {str(e)[:200]}", 0, "error"

# ============ API 端点 ============

@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "四Agent飞书消息路由服务",
        "agents": AGENT_NAMES,
        "history_count": len(MESSAGE_HISTORY)
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "history_count": len(MESSAGE_HISTORY)}

@app.post("/webhook/{agent_name}")
async def feishu_webhook(agent_name: str, request: Request, background_tasks: BackgroundTasks):
    # 英文路径转中文
    if agent_name in AGENT_NAME_MAP:
        agent_name = AGENT_NAME_MAP[agent_name]

    if agent_name not in AGENT_NAMES:
        raise HTTPException(status_code=404, detail=f"未知Agent: {agent_name}")

    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"[WEBHOOK] agent={agent_name}, raw={json.dumps(body, ensure_ascii=False)[:500]}")

    # ============ 处理飞书URL验证（challenge） ============
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"[WEBHOOK] URL验证 challenge={challenge}")
        return JSONResponse({"challenge": challenge})

    # ============ 处理消息事件 ============
    event = body.get("event", {})
    message = event.get("message", {})

    # 提取群聊ID
    chat_id = message.get("chat_id", "") or event.get("chat", {}).get("chat_id", "")

    # 提取消息文本
    content_str = message.get("content", "{}")
    try:
        content_json = json.loads(content_str) if isinstance(content_str, str) else content_str
        text = content_json.get("text", "")
    except Exception:
        text = str(content_str)

    logger.info(f"[WEBHOOK] chat_id={chat_id}, text={text[:300]}")

    # ============ 严格的@mention检查 ============
    # 从飞书mentions字段提取被@的实体（这才是准确的）
    mentions = message.get("mentions", [])
    logger.info(f"[WEBHOOK] mentions字段: {json.dumps(mentions, ensure_ascii=False)[:500]}")

    # 从mentions中提取被@的机器人名称
    mentioned_agents = []
    for mention in mentions:
        mention_name = mention.get("name", "")
        if mention_name in AGENT_NAMES:
            mentioned_agents.append(mention_name)

    # 如果从mentions没提取到，再从文本内容尝试（fallback）
    if not mentioned_agents:
        mentioned_agents = extract_mentioned_agents(text)

    logger.info(f"[WEBHOOK] 被@的机器人: {mentioned_agents}")

    # 检查当前机器人是否被@
    is_mentioned = agent_name in mentioned_agents

    # 如果没有@任何机器人，不回复
    if not mentioned_agents:
        logger.info(f"[WEBHOOK] 消息未@任何机器人，忽略")
        return JSONResponse({"code": 0, "msg": "ok"})

    # 如果@了其他机器人但不是当前机器人，不回复
    if not is_mentioned:
        logger.info(f"[WEBHOOK] 消息@了其他机器人({mentioned_agents})，不是当前机器人({agent_name})，忽略")
        return JSONResponse({"code": 0, "msg": "ok"})

    # 5. 清理@mention，提取实际问题
    clean_text = text
    for name in AGENT_NAMES:
        clean_text = clean_text.replace(f"@{name}", "")
        clean_text = re.sub(f'<at[^>]*>@{re.escape(name)}</at>', '', clean_text)
    clean_text = clean_text.strip()

    if not clean_text:
        clean_text = "你好，请提出问题。"

    logger.info(f"[WEBHOOK] 当前机器人({agent_name})被@，处理问题: {clean_text[:200]}")

    # ============ 异步处理 ============
    async def process_and_reply(cid=chat_id):
        logger.info(f"[TASK] 开始处理: agent={agent_name}, chat_id={cid}")
        try:
            reply, tokens_used, model_used = await handle_agent_request(agent_name, clean_text)
            save_to_history(agent_name, clean_text, reply)

            try:
                conv_id = save_conversation(agent_name, clean_text, reply, model_used, tokens_used)
                if conv_id > 0:
                    save_agent_memory(conv_id, agent_name, clean_text, reply)
            except Exception as mem_err:
                logger.error(f"[{agent_name}] 记忆保存失败: {mem_err}")

            # 使用Bot API发送消息到群聊
            if cid:
                success = await send_message_to_chat(agent_name, cid, reply)
                if success:
                    logger.info(f"[{agent_name}] 消息发送成功")
                else:
                    logger.error(f"[{agent_name}] 消息发送失败")
            else:
                logger.error(f"[{agent_name}] 缺少chat_id，无法发送回复")

            logger.info(f"[{agent_name}] 处理完成, model={model_used}")
        except Exception as e:
            logger.error(f"[{agent_name}] 处理失败: {e}")

    background_tasks.add_task(process_and_reply)

    return JSONResponse({
        "challenge": body.get("challenge", ""),
        "code": 0,
        "msg": "ok"
    })

@app.post("/api/ask")
async def api_ask(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": 400, "msg": "无效请求体"})

    agent_name = body.get("agent", "产品战略官")
    question = body.get("question", "")

    if agent_name not in AGENT_NAMES:
        return JSONResponse({"code": 404, "msg": f"未知Agent: {agent_name}"})
    if not question:
        return JSONResponse({"code": 400, "msg": "问题不能为空"})

    reply, tokens_used, model_used = await handle_agent_request(agent_name, question)
    save_to_history(agent_name, question, reply)

    try:
        conv_id = save_conversation(agent_name, question, reply, model_used, tokens_used)
        save_agent_memory(conv_id, agent_name, question, reply)
    except Exception:
        pass

    return JSONResponse({
        "code": 0,
        "data": {"agent": agent_name, "question": question, "answer": reply, "model": model_used}
    })

# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
