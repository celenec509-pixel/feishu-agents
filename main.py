"""
四Agent飞书消息路由服务
支持：产品战略官、用户体验官、数据研究员、逻辑校验官
"""

import os
import json
import time
import hmac
import hashlib
import base64
import logging
from typing import Dict, Optional
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
    get_agent_memory_context,
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

# ============ 配置 ============
# 飞书机器人 Webhook 地址（从英文环境变量读取，避免中文Key问题）
AGENT_WEBHOOKS = {
    "产品战略官": os.environ.get("WEBHOOK_ZHANGLUE", os.environ.get("WEBHOOK_1", "")),
    "用户体验官": os.environ.get("WEBHOOK_TIYAN", os.environ.get("WEBHOOK_2", "")),
    "数据研究员": os.environ.get("WEBHOOK_SHUJU", os.environ.get("WEBHOOK_3", "")),
    "逻辑校验官": os.environ.get("WEBHOOK_LUOJI", os.environ.get("WEBHOOK_4", "")),
}

# Outgoing 验证密钥（可选）
OUTGOOK_SECRETS = {
    "产品战略官": os.environ.get("SECRET_产品战略官", ""),
    "用户体验官": os.environ.get("SECRET_用户体验官", ""),
    "数据研究员": os.environ.get("SECRET_数据研究员", ""),
    "逻辑校验官": os.environ.get("SECRET_逻辑校验官", ""),
}

# 消息历史缓存（用于逻辑校验官获取近期对话）
MESSAGE_HISTORY = []
MAX_HISTORY = 100

# ============ 工具函数 ============

def verify_sign(secret: str, timestamp: str, signature: str) -> bool:
    """验证飞书 outgoing 签名"""
    if not secret:
        return True  # 未配置密钥时不验证
    try:
        key = f"{timestamp}\n{secret}".encode('utf-8')
        expected = base64.b64encode(
            hmac.new(key, b'', digestmod=hashlib.sha256).digest()
        ).decode('utf-8')
        # 实际验证逻辑：用请求体做hmac
        return True  # 简化版本，生产环境建议完整实现
    except Exception:
        return True


def save_to_history(agent_name: str, question: str, answer: str):
    """保存消息到历史记录"""
    MESSAGE_HISTORY.append({
        "agent": agent_name,
        "question": question,
        "answer": answer,
        "time": datetime.now().isoformat()
    })
    if len(MESSAGE_HISTORY) > MAX_HISTORY:
        MESSAGE_HISTORY.pop(0)


def get_recent_analysis(limit: int = 10) -> str:
    """获取近期分析记录（供逻辑校验官使用）"""
    recent = MESSAGE_HISTORY[-limit:]
    if not recent:
        return "暂无近期分析记录。"
    
    lines = []
    for i, msg in enumerate(recent, 1):
        if msg["agent"] in ANALYSIS_AGENTS:
            lines.append(
                f"【{i}】{msg['agent']}\n"
                f"问题：{msg['question']}\n"
                f"回答：{msg['answer'][:500]}...\n"
            )
    return "\n".join(lines) if lines else "暂无分析记录。"


async def send_feishu_card(webhook_url: str, agent_name: str, content: str):
    """发送飞书卡片消息"""
    if not webhook_url:
        logger.error(f"[{agent_name}] Webhook 地址未配置")
        return False
    
    # 选择颜色
    color_map = {
        "产品战略官": "red",
        "用户体验官": "green",
        "数据研究员": "yellow",
        "逻辑校验官": "grey",
    }
    color = color_map.get(agent_name, "blue")
    
    # 构建卡片消息
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🤖 {agent_name}"
                },
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content[:8000]  # 飞书卡片长度限制
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=card)
            result = resp.json()
            if result.get("code") == 0:
                logger.info(f"[{agent_name}] 消息发送成功")
                return True
            else:
                logger.error(f"[{agent_name}] 发送失败: {result}")
                return False
    except Exception as e:
        logger.error(f"[{agent_name}] 发送异常: {e}")
        return False


async def send_text_reply(webhook_url: str, content: str):
    """发送纯文本消息（用于快速回复）"""
    if not webhook_url:
        return False
    
    payload = {
        "msg_type": "text",
        "content": {"text": content[:4000]}
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=payload)
            return resp.json().get("code") == 0
    except Exception as e:
        logger.error(f"发送文本消息失败: {e}")
        return False


# ============ 核心路由逻辑 ============

async def handle_agent_request(agent_name: str, question: str) -> tuple:
    """
    处理Agent请求，调用LLM生成回复
    返回: (reply_text, tokens_used, model_used)
    """
    system_prompt = SYSTEM_PROMPTS.get(agent_name, SYSTEM_PROMPTS["产品战略官"])
    
    # 逻辑校验官特殊处理：获取近期分析记录
    if agent_name == "逻辑校验官":
        if "审查以上" in question or "审查" in question:
            recent = get_db_recent_analysis(limit=5)
            context = f"近期分析记录：\n{recent}\n\n用户要求：{question}"
        else:
            context = question
    else:
        context = question
    
    # 调用 LLM（带记忆注入）
    try:
        response, tokens_used, model_used = await call_llm(
            system_prompt, context, agent_name=agent_name
        )
        return response, tokens_used, model_used
    except Exception as e:
        logger.error(f"[{agent_name}] LLM调用失败: {e}")
        error_msg = f"❌ 服务暂时异常，请稍后重试。\n错误: {str(e)[:200]}"
        return error_msg, 0, "error"


# ============ API 端点 ============

@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "running",
        "service": "四Agent飞书消息路由服务",
        "agents": list(AGENT_WEBHOOKS.keys()),
        "history_count": len(MESSAGE_HISTORY)
    }


@app.get("/health")
async def health():
    """健康检查端点"""
    # 检查配置
    missing_webhooks = [k for k, v in AGENT_WEBHOOKS.items() if not v]
    return {
        "status": "healthy" if not missing_webhooks else "degraded",
        "missing_webhooks": missing_webhooks,
        "history_count": len(MESSAGE_HISTORY)
    }


@app.post("/webhook/{agent_name}")
async def feishu_webhook(
    agent_name: str,
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    接收飞书事件订阅回调
    
    支持飞书事件订阅的两种请求：
    1. URL验证（challenge）- 飞书首次配置时验证URL
    2. 消息事件 - 用户@机器人时触发
    
    每个机器人配置不同的URL:
    - /webhook/产品战略官
    - /webhook/用户体验官
    - /webhook/数据研究员
    - /webhook/逻辑校验官
    """
    # 验证agent_name
    if agent_name not in AGENT_WEBHOOKS:
        raise HTTPException(status_code=404, detail=f"未知Agent: {agent_name}")
    
    # 解析请求体
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    logger.info(f"[{agent_name}] 收到请求: {json.dumps(body, ensure_ascii=False)[:500]}")
    
    # ============ 关键：处理飞书URL验证（challenge） ============
    # 飞书首次配置事件订阅URL时，会发送验证请求
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"[{agent_name}] 处理URL验证, challenge={challenge}")
        return JSONResponse({
            "challenge": challenge  # 必须返回challenge值
        })
    
    # ============ 处理消息事件 ============
    # 飞书事件订阅的消息格式
    header = body.get("header", {})
    event_type = header.get("event_type", "")
    
    # 提取消息内容（飞书事件订阅格式）
    event = body.get("event", {})
    message = event.get("message", {})
    
    # 获取消息文本
    content_str = message.get("content", "{}")
    try:
        content_json = json.loads(content_str) if isinstance(content_str, str) else content_str
        text = content_json.get("text", "")
    except Exception:
        text = content_str
    
    # 去除@机器人的部分
    for name in AGENT_WEBHOOKS.keys():
        text = text.replace(f"@{name}", "").strip()
    
    if not text:
        text = "你好，请提出问题。"
    
    # 提取用户ID
    user = event.get("sender", {}).get("sender_id", {}).get("user_id", "unknown")
    
    logger.info(f"[{agent_name}] 用户 {user} 提问: {text[:200]}")
    
    # 异步处理（避免超时）
    async def process_and_reply():
        try:
            # 1. 调用LLM生成回复（带记忆注入）
            reply, tokens_used, model_used = await handle_agent_request(agent_name, text)
            
            # 2. 保存到内存历史（快速查询）
            save_to_history(agent_name, text, reply)
            
            # 3. 保存到持久化数据库（含记忆提取）
            try:
                conv_id = save_conversation(agent_name, text, reply, model_used, tokens_used)
                if conv_id > 0:
                    save_agent_memory(conv_id, agent_name, text, reply)
                    logger.info(f"[{agent_name}] 对话+记忆已保存 (conv_id={conv_id})")
            except Exception as mem_err:
                logger.error(f"[{agent_name}] 记忆保存失败: {mem_err}")
            
            # 4. 发送到飞书
            webhook_url = AGENT_WEBHOOKS[agent_name]
            await send_feishu_card(webhook_url, agent_name, reply)
            
            logger.info(f"[{agent_name}] 处理完成，回复长度: {len(reply)}, model={model_used}")
        except Exception as e:
            logger.error(f"[{agent_name}] 处理失败: {e}")
            # 发送错误提示
            await send_text_reply(
                AGENT_WEBHOOKS[agent_name],
                f"❌ 处理出错: {str(e)[:200]}"
            )
    
    # 在后台处理，立即返回200（飞书要求3秒内响应）
    background_tasks.add_task(process_and_reply)
    
    return JSONResponse({
        "challenge": body.get("challenge", ""),  # 如果有challenge也要返回
        "code": 0,
        "msg": "ok"
    })


@app.post("/webhook/unified")
async def unified_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    统一接收端点（所有机器人共用同一个URL）
    通过消息内容中的 @机器人名称 来路由
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    # 提取消息
    event = body.get("event", {})
    message = event.get("message", {})
    
    content_str = message.get("content", "{}")
    try:
        content_json = json.loads(content_str) if isinstance(content_str, str) else content_str
        text = content_json.get("text", "")
    except Exception:
        text = str(content_str)
    
    # 确定目标Agent（根据@的机器人）
    target_agent = None
    for name in AGENT_WEBHOOKS.keys():
        if f"@{name}" in text:
            target_agent = name
            break
    
    if not target_agent:
        return JSONResponse({
            "code": 0,
            "msg": "ok",
            "data": {"message": "请@具体的Agent（产品战略官/用户体验官/数据研究员/逻辑校验官）"}
        })
    
    # 转发到对应Agent处理
    return await feishu_webhook(target_agent, request, background_tasks)


@app.post("/api/ask")
async def api_ask(request: Request):
    """
    直接调用API提问（不通过飞书，用于测试）
    
    请求体:
    {
        "agent": "产品战略官",
        "question": "曲面雕刻功能应该作为核心卖点还是辅助功能？"
    }
    """
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
    
    # 同步处理（带记忆保存）
    reply, tokens_used, model_used = await handle_agent_request(agent_name, question)
    save_to_history(agent_name, question, reply)
    
    # 保存到持久化数据库
    try:
        conv_id = save_conversation(agent_name, question, reply, model_used, tokens_used)
        if conv_id > 0:
            save_agent_memory(conv_id, agent_name, question, reply)
    except Exception as mem_err:
        logger.error(f"[{agent_name}] API记忆保存失败: {mem_err}")
    
    return JSONResponse({
        "code": 0,
        "msg": "ok",
        "data": {
            "agent": agent_name,
            "question": question,
            "answer": reply,
            "model": model_used,
            "tokens": tokens_used
        }
    })


@app.post("/api/cross-analysis")
async def api_cross_analysis(request: Request):
    """
    三Agent并行分析 + 逻辑校验
    
    请求体:
    {
        "question": "CBB模块化扩展是否值得在Gen2阶段投入？",
        "auto_review": true
    }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": 400, "msg": "无效请求体"})
    
    question = body.get("question", "")
    auto_review = body.get("auto_review", True)
    
    if not question:
        return JSONResponse({"code": 400, "msg": "问题不能为空"})
    
    results = {}
    
    # 并行调用三个分析Agent（带记忆保存）
    for name in ANALYSIS_AGENTS:
        try:
            reply, tokens_used, model_used = await handle_agent_request(name, question)
            results[name] = reply
            save_to_history(name, question, reply)
            
            # 保存到持久化数据库
            try:
                conv_id = save_conversation(name, question, reply, model_used, tokens_used)
                if conv_id > 0:
                    save_agent_memory(conv_id, name, question, reply)
            except Exception as mem_err:
                logger.error(f"[{name}] 交叉分析记忆保存失败: {mem_err}")
            
            # 发送到飞书
            webhook_url = AGENT_WEBHOOKS[name]
            if webhook_url:
                await send_feishu_card(webhook_url, name, reply)
        except Exception as e:
            results[name] = f"处理出错: {e}"
    
    # 自动触发逻辑校验
    review_result = None
    if auto_review:
        try:
            context = f"请审查以下三个Agent对问题的分析：\n\n问题：{question}\n\n"
            for name, reply in results.items():
                context += f"【{name}】\n{reply[:1000]}\n\n"
            
            review, r_tokens, r_model = await handle_agent_request("逻辑校验官", context)
            review_result = review
            save_to_history("逻辑校验官", f"审查: {question}", review)
            
            # 保存审查记录
            try:
                conv_id = save_conversation("逻辑校验官", f"审查: {question}", review, r_model, r_tokens)
                save_agent_memory(conv_id, "逻辑校验官", f"审查: {question}", review)
            except Exception as mem_err:
                logger.error(f"[逻辑校验官] 审查记忆保存失败: {mem_err}")
            
            # 发送到飞书
            webhook_url = AGENT_WEBHOOKS["逻辑校验官"]
            if webhook_url:
                await send_feishu_card(webhook_url, "逻辑校验官", review)
        except Exception as e:
            review_result = f"逻辑校验出错: {e}"
    
    return JSONResponse({
        "code": 0,
        "msg": "ok",
        "data": {
            "question": question,
            "results": results,
            "review": review_result
        }
    })


@app.get("/api/history")
async def api_history(limit: int = 20):
    """查看消息历史（供逻辑校验官使用）"""
    recent = MESSAGE_HISTORY[-limit:]
    return JSONResponse({
        "code": 0,
        "data": {
            "total": len(MESSAGE_HISTORY),
            "history": recent
        }
    })


@app.delete("/api/history")
async def clear_history():
    """清空消息历史"""
    global MESSAGE_HISTORY
    MESSAGE_HISTORY = []
    return JSONResponse({"code": 0, "msg": "历史已清空"})


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
