"""
飞书 Bot API 消息发送模块
使用 tenant_access_token 发送消息到群聊
"""

import os
import httpx
import logging
import time
from datetime import datetime

logger = logging.getLogger("feishu-agents.bot")

# ============ 应用凭证配置 ============
# 从环境变量读取4个应用的凭证
AGENT_APP_CREDENTIALS = {
    "产品战略官": {
        "app_id": os.environ.get("FEISHU_APPID_ZHANGLUE", os.environ.get("FEISHU_APPID_1", "cli_aa8a979d85381bc1")),
        "app_secret": os.environ.get("FEISHU_SECRET_ZHANGLUE", os.environ.get("FEISHU_SECRET_1", "hcNCjdXpVLEf5p41TgrPEhJlyyopqtxX")),
    },
    "用户体验官": {
        "app_id": os.environ.get("FEISHU_APPID_TIYAN", os.environ.get("FEISHU_APPID_2", "cli_aa8a9784bc381bd0")),
        "app_secret": os.environ.get("FEISHU_SECRET_TIYAN", os.environ.get("FEISHU_SECRET_2", "AKM7QBW3awqTk3sT5LizscYJfqxvCA1G")),
    },
    "数据研究员": {
        "app_id": os.environ.get("FEISHU_APPID_SHUJU", os.environ.get("FEISHU_APPID_3", "cli_aa8a97b6dd78dbdd")),
        "app_secret": os.environ.get("FEISHU_SECRET_SHUJU", os.environ.get("FEISHU_SECRET_3", "mqMq5ScQjDBrwhz5E9TBld3BfiklwlMmP")),
    },
    "逻辑校验官": {
        "app_id": os.environ.get("FEISHU_APPID_LUOJI", os.environ.get("FEISHU_APPID_4", "cli_aa8a97a2ee7a9bc4")),
        "app_secret": os.environ.get("FEISHU_SECRET_LUOJI", os.environ.get("FEISHU_SECRET_4", "rTkuST73tgsfVfKbtDMgJbqq0l33ll8i")),
    },
}

# token 缓存
_token_cache = {}


async def get_tenant_access_token(agent_name: str) -> str:
    """获取 tenant_access_token（带缓存）"""
    global _token_cache
    
    # 检查缓存
    if agent_name in _token_cache:
        cached = _token_cache[agent_name]
        if cached["expire_at"] > time.time() + 60:  # 提前60秒刷新
            return cached["token"]
    
    # 获取应用凭证
    creds = AGENT_APP_CREDENTIALS.get(agent_name)
    if not creds:
        raise ValueError(f"未找到应用凭证: {agent_name}")
    
    app_id = creds["app_id"]
    app_secret = creds["app_secret"]
    
    # 调用飞书API获取token
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret}
            )
            data = resp.json()
            
            if data.get("code") != 0:
                raise RuntimeError(f"获取token失败: {data}")
            
            token = data["tenant_access_token"]
            expire = data.get("expire", 7200)
            
            # 缓存token
            _token_cache[agent_name] = {
                "token": token,
                "expire_at": time.time() + expire
            }
            
            logger.info(f"[{agent_name}] 获取tenant_access_token成功")
            return token
            
    except Exception as e:
        logger.error(f"[{agent_name}] 获取tenant_access_token失败: {e}")
        raise


async def send_message_to_chat(agent_name: str, chat_id: str, content: str):
    """使用Bot API发送消息到群聊"""
    logger.info(f"[BOT] 开始发送: agent={agent_name}, chat_id={chat_id}, content_len={len(content)}")
    try:
        # 获取token
        logger.info(f"[BOT] 获取token...")
        token = await get_tenant_access_token(agent_name)
        logger.info(f"[BOT] token获取成功: {token[:20]}...")
        
        # 构建消息卡片
        color_map = {"产品战略官": "red", "用户体验官": "green", "数据研究员": "yellow", "逻辑校验官": "grey"}
        color = color_map.get(agent_name, "blue")
        
        # 构建卡片消息
        card_content = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🤖 {agent_name}"},
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content[:8000]}
                },
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                    ]
                }
            ]
        }
        
        # 调用飞书API发送消息
        logger.info(f"[BOT] 调用飞书API发送消息...")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card_content)
                }
            )
            
            result = resp.json()
            logger.info(f"[BOT] 飞书API响应: status={resp.status_code}, code={result.get('code')}, msg={result.get('msg', 'N/A')}")
            if result.get("code") == 0:
                logger.info(f"[{agent_name}] 消息发送成功")
                return True
            else:
                logger.error(f"[{agent_name}] 消息发送失败: {result}")
                return False
                
    except Exception as e:
        logger.error(f"[{agent_name}] 发送消息异常: {e}")
        return False


async def send_text_message(agent_name: str, chat_id: str, text: str):
    """使用Bot API发送纯文本消息"""
    try:
        token = await get_tenant_access_token(agent_name)
        
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text[:4000]})
                }
            )
            
            result = resp.json()
            if result.get("code") == 0:
                logger.info(f"[{agent_name}] 文本消息发送成功")
                return True
            else:
                logger.error(f"[{agent_name}] 文本消息发送失败: {result}")
                return False
                
    except Exception as e:
        logger.error(f"[{agent_name}] 发送文本消息异常: {e}")
        return False
