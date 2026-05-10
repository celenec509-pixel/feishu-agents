# 四Agent飞书机器人 — 角色最优匹配 + "三只虾"(Claude)整合

## 最终配置

```
产品战略官 ── GPT-4o (OpenAI)          ─── 全球商业案例最丰富
用户体验官 ── Kimi 128K (Moonshot)     ─── 中文共情+128K长文本
数据研究员 ── DeepSeek V4 Reasoner     ─── 推理+思考链透明
逻辑校验官 ── Claude 3.5 Sonnet        ─── "三只虾"主力，审查最强
                     ↑
              三只Claude的核心位置
```

## 为什么Claude放在逻辑校验官？

| Claude特性 | 逻辑校验官需求 | 匹配度 |
|-----------|-------------|:---:|
| 安全审查能力世界级 | 需要严格审查其他Agent结论 | ⭐⭐⭐⭐⭐ |
| 逻辑推理严谨 | 有效论证/无效论证二分类 | ⭐⭐⭐⭐⭐ |
| 长上下文200K+ | 需要同时审查多个Agent的长回复 | ⭐⭐⭐⭐⭐ |
| 不迎合、不附和 | 独立审查，不讲面子 | ⭐⭐⭐⭐⭐ |
| Constitutional AI | 内置规则约束，审查标准统一 | ⭐⭐⭐⭐⭐ |

**这是Claude Sonnet在所有角色中匹配度最高的位置。**

## "三只虾"完整分工

| Claude版本 | 角色 | 使用场景 |
|-----------|------|---------|
| **Sonnet** | 逻辑校验官（主力） | 每次审查自动调用 |
| **Opus** | 产品战略官深度模式 | 复杂战略分析时手动切换 |
| **Haiku** | 数据研究员快速模式 | 简单数据查询时手动切换 |

## API Key获取

| 厂商 | 注册地址 | 免费额度 | 用途 |
|------|---------|:---:|:---|
| **OpenAI** | platform.openai.com | $5 | 产品战略官 |
| **Moonshot** | platform.moonshot.cn | 15元 | 用户体验官 |
| **DeepSeek** | platform.deepseek.com | 500万tokens | 数据研究员 |
| **Anthropic** | console.anthropic.com | $5 | 逻辑校验官(Claude) |

## 快速部署

1. 获取4个API Key（含Anthropic）
2. 填写 `.env` 配置
3. 部署服务
4. 配置飞书Outgoing

## 使用方法

```
@产品战略官 曲面雕刻应该作为核心卖点吗？       ← GPT-4o
@用户体验官 P1用户对首件保障的真实需求？         ← Kimi 128K
@数据研究员 348条帖子中曲面需求规模？            ← DeepSeek V4
@逻辑校验官 审查以上                             ← Claude 3.5 Sonnet
```

逻辑校验官由Claude Sonnet驱动，提供世界级逻辑审查能力。
