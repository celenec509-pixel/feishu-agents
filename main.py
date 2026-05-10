"""极简测试服务器 - 验证飞书事件订阅"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json

app = FastAPI()

@app.get("/")
def root():
    return {"status": "running"}

@app.post("/webhook/{agent_name}")
async def webhook(agent_name: str, request: Request):
    body = await request.json()
    
    # 处理飞书 challenge 验证
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge")})
    
    # 处理消息事件 - 立即返回，后台处理
    return JSONResponse({"challenge": body.get("challenge", ""), "code": 0, "msg": "ok"})
