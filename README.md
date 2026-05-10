# 四Agent飞书消息路由服务

产品战略官 | 用户体验官 | 数据研究员 | 逻辑校验官

## 架构概览

```
用户@机器人(飞书群)
       |
       v
飞书服务器 --- Outgoing Webhook ---> 本服务 (:8000)
                                         |
                    +--------------------+--------------------+
                    |                    |                    |
            解析@的机器人名称      调用LLM生成回复       通过Webhook发回飞书
                    |                    |                    |
               /webhook/产品战略官   GPT-4/DeepSeek等    产品战略官Webhook
               /webhook/用户体验官                       用户体验官Webhook
               /webhook/数据研究员                       数据研究员Webhook
               /webhook/逻辑校验官                       逻辑校验官Webhook
```

## 快速开始

### 第一步：在飞书创建4个自定义机器人

1. 打开飞书群 → 群设置 → 群机器人 → 添加机器人
2. 选择 **自定义机器人**
3. 依次添加4个机器人：

| 机器人名称 | 头像建议 | 角色 |
|-----------|---------|------|
| `产品战略官` | 🔴 红色 | 产品战略+想象力分析 |
| `用户体验官` | 🟢 绿色 | 用户共情+场景分析 |
| `数据研究员` | 🟡 黄色 | 全维度数据验证 |
| `逻辑校验官` | ⚫ 黑色 | 逻辑审查+质疑 |

4. 保存每个机器人的 **Webhook地址**（格式: `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx`）

### 第二步：配置 Outgoing（接收@消息）

每个机器人的 Outgoing URL 配置（替换为你的服务域名/IP）：

| 机器人 | Outgoing URL |
|-------|-------------|
| 产品战略官 | `https://your-domain.com/webhook/产品战略官` |
| 用户体验官 | `https://your-domain.com/webhook/用户体验官` |
| 数据研究员 | `https://your-domain.com/webhook/数据研究员` |
| 逻辑校验官 | `https://your-domain.com/webhook/逻辑校验官` |

> 如果没有公网域名，可以使用 [ngrok](https://ngrok.com/) 或 [cloudflare tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) 暴露本地服务。

### 第三步：部署服务

#### 方式A：Docker Compose 部署（推荐）

```bash
# 1. 进入项目目录
cd feishu-agents

# 2. 复制并编辑配置文件
cp .env.example .env
vi .env

# 3. 填写以下必填项：
# - LLM_API_KEY: 你的LLM API密钥
# - LLM_BASE_URL: LLM API地址（OpenAI/DeepSeek/Moonshot等）
# - LLM_MODEL: 模型名称（gpt-4o / deepseek-chat / moonshot-v1-32k）
# - WEBHOOK_产品战略官 等4个飞书Webhook地址

# 4. 启动服务
docker-compose up -d

# 5. 查看日志
docker-compose logs -f
```

#### 方式B：本地运行

```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的配置

# 4. 启动服务
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 第四步：验证测试

```bash
# 健康检查
curl http://localhost:8000/

# 直接调用API测试（不经过飞书）
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "产品战略官",
    "question": "曲面雕刻功能应该作为核心卖点还是辅助功能？"
  }'

# 三Agent并行分析 + 逻辑校验
curl -X POST http://localhost:8000/api/cross-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "question": "CBB模块化扩展是否值得在Gen2阶段投入？",
    "auto_review": true
  }'
```

### 第五步：在飞书群中使用

**单独@某个Agent：**
```
@产品战略官 曲面雕刻功能应该作为核心卖点还是辅助功能？

@用户体验官 P1用户对45分钟首件保障的真实需求是什么？

@数据研究员 348条帖子中曲面需求的真实规模是多少？

@逻辑校验官 审查以上
```

**三Agent并行分析 + 逻辑校验：**
```
@产品战略官 @用户体验官 @数据研究员
问题：CBB模块化扩展是否值得在Gen2阶段投入？
```
然后等三个Agent回答后：
```
@逻辑校验官 审查以上
```

## 支持的LLM提供商

| 提供商 | LLM_BASE_URL | LLM_MODEL 示例 |
|-------|-------------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`, `gpt-4o-mini` |
| Moonshot (月之暗面) | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 阿里云通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` |
| 智谱AI | `https://open.bigmodel.cn/api/paas/v4` | `glm-4` |
| 本地Ollama | `http://localhost:11434/v1` | `llama3:8b` |

## API 接口文档

### Webhook 接收端点

| 端点 | 说明 |
|------|------|
| `POST /webhook/产品战略官` | 接收产品战略官的@消息 |
| `POST /webhook/用户体验官` | 接收用户体验官的@消息 |
| `POST /webhook/数据研究员` | 接收数据研究员的@消息 |
| `POST /webhook/逻辑校验官` | 接收逻辑校验官的@消息 |

### API 调用端点

| 端点 | 说明 |
|------|------|
| `GET /` | 服务状态 |
| `GET /health` | 健康检查 |
| `POST /api/ask` | 直接提问单个Agent |
| `POST /api/cross-analysis` | 三Agent并行分析+逻辑校验 |
| `GET /api/history` | 查看消息历史 |
| `DELETE /api/history` | 清空消息历史 |

## 目录结构

```
feishu-agents/
├── main.py              # FastAPI 主服务
├── agents.py            # 四Agent System Prompt 配置
├── llm.py               # LLM API 调用封装
├── requirements.txt     # Python 依赖
├── Dockerfile           # Docker 构建
├── docker-compose.yml   # Docker Compose 配置
├── .env.example         # 环境变量模板
└── README.md            # 本文件
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 飞书收不到回复 | 检查 Webhook 地址是否正确；检查服务是否可公网访问 |
| LLM调用超时 | 增大 `LLM_TIMEOUT`；检查 API Key 是否有效 |
| Outgoing验证失败 | 检查飞书 Outgoing URL 是否配置正确；检查 Secret 配置 |
| 服务启动失败 | 检查 `.env` 文件是否存在；检查 `LLM_API_KEY` 是否已设置 |
| 卡片消息太长被截断 | 服务已自动截断至8000字符，如需更长请分页发送 |

## 安全建议

1. **使用HTTPS**：生产环境务必使用 HTTPS
2. **Outgoing Secret**：建议启用飞书 Outgoing 密钥验证
3. **IP白名单**：在飞书后台配置 Outgoing IP 白名单
4. **API Key保护**：不要在代码中硬编码API Key，使用环境变量
5. **访问控制**：API端点建议增加认证（可扩展）
