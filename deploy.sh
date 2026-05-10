#!/bin/bash
# ============================================
# 四Agent飞书消息路由服务 — 一键部署脚本
# ============================================

set -e

echo "========================================"
echo "四Agent飞书消息路由服务 - 一键部署"
echo "========================================"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker 和 Docker Compose 已安装"
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "📝 首次运行，从模板创建 .env 配置文件..."
    cp .env.example .env
    echo "⚠️  请编辑 .env 文件，填入你的 LLM API Key 和飞书 Webhook 地址"
    echo "   命令: vi .env 或 nano .env"
    echo ""
    
    # 提示用户必须填写的字段
    echo "必填配置项:"
    echo "  1. LLM_API_KEY      - 你的大模型API密钥"
    echo "  2. LLM_BASE_URL     - API地址(如 https://api.deepseek.com/v1)"
    echo "  3. LLM_MODEL        - 模型名(如 deepseek-chat, gpt-4o)"
    echo "  4. WEBHOOK_*        - 4个飞书机器人的Webhook地址"
    echo ""
    exit 1
fi

# 检查关键环境变量是否已设置
source .env

if [ -z "$LLM_API_KEY" ] || [ "$LLM_API_KEY" = "sk-your-api-key-here" ]; then
    echo "❌ LLM_API_KEY 未配置，请先编辑 .env 文件"
    exit 1
fi

MISSING_WEBHOOK=0
for agent in "产品战略官" "用户体验官" "数据研究员" "逻辑校验官"; do
    var_name="WEBHOOK_${agent}"
    value="${!var_name}"
    if [ -z "$value" ] || [[ "$value" == *"xxxx"* ]]; then
        echo "⚠️  ${agent} 的 Webhook 未配置"
        MISSING_WEBHOOK=1
    fi
done

if [ $MISSING_WEBHOOK -eq 1 ]; then
    echo ""
    echo "⚠️  部分 Webhook 未配置，服务可以启动但对应机器人无法回复"
    echo "   建议编辑 .env 填入所有 Webhook 地址后再启动"
    echo ""
    read -p "是否继续启动? (y/N): " confirm
    if [[ ! $confirm =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

echo "✅ 配置检查通过"
echo ""

# 构建并启动
echo "🚀 构建并启动服务..."
docker-compose build
docker-compose up -d

echo ""
echo "========================================"
echo "✅ 服务部署成功！"
echo "========================================"
echo ""
echo "服务信息:"
echo "  状态检查: http://localhost:8000/"
echo "  健康检查: http://localhost:8000/health"
echo ""
echo "查看日志:"
echo "  docker-compose logs -f"
echo ""
echo "常用命令:"
echo "  停止: docker-compose down"
echo "  重启: docker-compose restart"
echo "  更新: docker-compose build --no-cache && docker-compose up -d"
echo ""

# 显示公网访问提示
echo "⚠️  飞书 Outgoing Webhook 需要公网可访问的地址"
echo "   如果没有公网IP，可使用以下内网穿透工具:"
echo "   - ngrok:    ngrok http 8000"
echo "   - Cloudflare Tunnel: cloudflared tunnel --url http://localhost:8000"
echo ""
