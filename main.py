"""
四Agent飞书消息路由服务 — 完整版
支持：产品战略官、用户体验官、数据研究员、逻辑校验官
"""

import os
import json
import logging
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx

from agents import SYSTEM_PROMPTS, ANALYSIS_AGENTS
from llm import call_llm
from memory import (
    save_conversation, 
    save_agent_memory,
    get_all_recent_analysis as get_db_recent_analysis,
)

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
    version="1.0.0"
)

# ============ Webhook 配置（从英文环境变量读取） ============
AGENT_WEBHOOKS = {
    "产品战略官": os.environ.get("WEBHOOK_ZHANGLUE", os.environ.get("WEBHOOK_1", "")),
    "用户体验官": os.environ.get("WEBHOOK_TIYAN", os.environ.get("WEBHOOK_2", "")),
    "数据研究员": os.environ.get("WEBHOOK_SHUJU", os.environ.get("WEBHOOK_3", "")),
    "逻辑校验官": os.environ.get("WEBHOOK_LUOJI", os.environ.get("WEBHOOK_4", "")),
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

# ============ 飞书消息发送 ============

async def send_feishu_card(webhook_url, agent_name, content):
    if not webhook_url:
        logger.error(f"[{agent_name}] Webhook 未配置")
        return False
    
    color_map = {"产品战略官": "red", "用户体验官": "green", "数据研究员": "yellow", "逻辑校验官": "grey"}
    color = color_map.get(agent_name, "blue")
    
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🤖 {agent_name}"},
                "template": color
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content[:8000]}},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
            ]
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=card)
            return resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"[{agent_name}] 发送失败: {e}")
        return False

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
        "agents": list(AGENT_WEBHOOKS.keys()),
        "history_count": len(MESSAGE_HISTORY)
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "history_count": len(MESSAGE_HISTORY)}

@app.post("/webhook/{agent_name}")
async def feishu_webhook(agent_name: str, request: Request, background_tasks: BackgroundTasks):
    if agent_name not in AGENT_WEBHOOKS:
        raise HTTPException(status_code=404, detail=f"未知Agent: {agent_name}")
    
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    logger.info(f"[{agent_name}] 收到请求: {json.dumps(body, ensure_ascii=False)[:500]}")
    
    # ============ 处理飞书URL验证（challenge） ============
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"[{agent_name}] URL验证 challenge={challenge}")
        return JSONResponse({"challenge": challenge})
    
    # ============ 处理消息事件 ============
    event = body.get("event", {})
    message = event.get("message", {})
    
    content_str = message.get("content", "{}")
    try:
        content_json = json.loads(content_str) if isinstance(content_str, str) else content_str
        text = content_json.get("text", "")
    except Exception:
        text = str(content_str)
    
    for name in AGENT_WEBHOOKS.keys():
        text = text.replace(f"@{name}", "").strip()
    
    if not text:
        text = "你好，请提出问题。"
    
    logger.info(f"[{agent_name}] 提问: {text[:200]}")
    
    # 异步处理
    async def process_and_reply():
        try:
            reply, tokens_used, model_used = await handle_agent_request(agent_name, text)
            save_to_history(agent_name, text, reply)
            
            try:
                conv_id = save_conversation(agent_name, text, reply, model_used, tokens_used)
                if conv_id > 0:
                    save_agent_memory(conv_id, agent_name, text, reply)
            except Exception as mem_err:
                logger.error(f"[{agent_name}] 记忆保存失败: {mem_err}")
            
            webhook_url = AGENT_WEBHOOKS[agent_name]
            await send_feishu_card(webhook_url, agent_name, reply)
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
    
    if agent_name not in AGENT_WEBHOOKS:
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
