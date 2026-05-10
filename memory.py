"""
四Agent记忆系统 — 每个Agent根据角色需求有不同的记忆策略

产品战略官：长期战略记忆（产品定位、竞品动态、战略决策）
用户体验官：用户画像记忆（用户旅程、情感地图、原声库）
数据研究员：数据库记忆（数据结论、缺口记录、分析方法论）
逻辑校验官：短期对话记忆（仅当前对话上下文）
"""

import os
import json
import sqlite3
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger("feishu-agents.memory")

# ============ 配置 ============
# Railway 用 /tmp，本地用 ./data
MEMORY_DB_PATH = os.environ.get("MEMORY_DB_PATH", "/tmp/memory.db")
MEMORY_MAX_ENTRIES = int(os.environ.get("MEMORY_MAX_ENTRIES", "1000"))
MEMORY_SUMMARY_THRESHOLD = int(os.environ.get("MEMORY_SUMMARY_THRESHOLD", "50"))

_db_initialized = False

# ============ 数据库初始化 ============

def _get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(MEMORY_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """初始化记忆数据库（延迟初始化，带错误处理）"""
    global _db_initialized
    if _db_initialized:
        return
    
    try:
        os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    except Exception:
        # Railway 等环境可能没有写权限，改用 /tmp
        pass
    
    conn = _get_conn()
    cursor = conn.cursor()
    
    # 通用记忆表（所有Agent共享的对话记录）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            model_used TEXT,
            tokens_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 产品战略官 — 长期战略记忆
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            -- product_position, competitor_intel, strategic_decision, trend_observation, risk_assessment
            content TEXT NOT NULL,
            source_conversation_id INTEGER,
            importance INTEGER DEFAULT 3,  -- 1-5, 5最高
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 用户体验官 — 用户画像与旅程记忆
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_experience_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            -- persona_profile, journey_map, emotion_data, verbatim_quote, cultural_insight, pain_point
            persona_id TEXT,  -- P1/P2/P3/P4
            content TEXT NOT NULL,
            scenario TEXT,    -- 场景标签
            emotion_tag TEXT, -- 情绪标签
            confidence INTEGER DEFAULT 3,  -- 1-5
            source_conversation_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 数据研究员 — 数据结论与缺口记忆
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS data_research_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            -- data_conclusion, data_gap, methodology, source_record, cross_validation
            topic TEXT NOT NULL,       -- 主题/关键词
            conclusion TEXT NOT NULL,   -- 结论
            evidence_level TEXT DEFAULT '推断',  -- 直接/推断/不足
            sample_size TEXT,           -- 样本量
            confidence TEXT,            -- 置信度
            data_sources TEXT,          -- 数据来源（JSON数组）
            related_agents TEXT,        -- 相关Agent（JSON数组）
            is_still_valid INTEGER DEFAULT 1,
            source_conversation_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 逻辑校验官 — 审查历史（短期，主要记录审查模式）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logic_review_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewed_agent TEXT NOT NULL,    -- 被审查的Agent
            topic TEXT NOT NULL,             -- 审查主题
            issues_found TEXT NOT NULL,      -- 发现的问题（JSON）
            credibility_score INTEGER,       -- 可信度评分
            review_summary TEXT,             -- 审查摘要
            source_conversation_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 记忆摘要表（防止上下文爆炸）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memory_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            summary_type TEXT NOT NULL,
            summary_content TEXT NOT NULL,
            period_start TIMESTAMP,
            period_end TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    _db_initialized = True
    logger.info(f"记忆数据库初始化完成: {MEMORY_DB_PATH}")


# ============ 对话记录 ============

def save_conversation(agent_name: str, question: str, answer: str, 
                      model_used: str = "", tokens_used: int = 0) -> int:
    """保存对话记录，返回记录ID"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO conversation_log (agent_name, question, answer, model_used, tokens_used)
            VALUES (?, ?, ?, ?, ?)
        ''', (agent_name, question[:2000], answer[:8000], model_used, tokens_used))
        conn.commit()
        conv_id = cursor.lastrowid
        conn.close()
        return conv_id
    except Exception as e:
        logger.error(f"保存对话记录失败: {e}")
        return 0


def get_recent_conversations(agent_name: str, limit: int = 10) -> List[Dict]:
    """获取指定Agent的近期对话"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM conversation_log 
            WHERE agent_name = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (agent_name, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取对话记录失败: {e}")
        return []


def get_all_recent_analysis(limit: int = 20) -> str:
    """获取近期所有分析Agent的对话（供逻辑校验官使用）"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM conversation_log 
            WHERE agent_name IN ('产品战略官', '用户体验官', '数据研究员')
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "暂无近期分析记录。"
        
        lines = []
        for i, row in enumerate(rows, 1):
            lines.append(
                f"【{i}】{row['agent_name']} ({row['model_used'] or 'unknown'})\n"
                f"问题：{row['question'][:200]}\n"
                f"回答：{row['answer'][:400]}...\n"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取分析记录失败: {e}")
        return "暂无近期分析记录。"


# ============ 产品战略官 — 长期战略记忆 ============

def save_strategic_memory(memory_type: str, content: str, 
                          source_conv_id: int = 0, importance: int = 3) -> bool:
    """保存战略记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO strategic_memory (memory_type, content, source_conversation_id, importance)
            VALUES (?, ?, ?, ?)
        ''', (memory_type, content[:4000], source_conv_id, importance))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"保存战略记忆失败: {e}")
        return False


def get_strategic_memory(memory_types: List[str] = None, 
                         limit: int = 20) -> List[Dict]:
    """获取战略记忆，可按类型筛选"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        
        if memory_types:
            placeholders = ','.join('?' * len(memory_types))
            cursor.execute(f'''
                SELECT * FROM strategic_memory 
                WHERE memory_type IN ({placeholders}) AND is_active = 1
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            ''', (*memory_types, limit))
        else:
            cursor.execute('''
                SELECT * FROM strategic_memory 
                WHERE is_active = 1
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取战略记忆失败: {e}")
        return []


def get_strategic_memory_context() -> str:
    """获取产品战略官的记忆上下文（注入prompt）"""
    memories = get_strategic_memory(limit=30)
    if not memories:
        return "暂无历史战略记忆。"
    
    sections = {
        'product_position': [],
        'competitor_intel': [],
        'strategic_decision': [],
        'trend_observation': [],
        'risk_assessment': [],
    }
    
    for m in memories:
        sections.get(m['memory_type'], []).append(m)
    
    lines = ["📚 历史战略记忆："]
    
    if sections['product_position']:
        lines.append("\n【产品定位演变】")
        for m in sections['product_position'][:5]:
            lines.append(f"  • {m['content'][:150]}")
    
    if sections['competitor_intel']:
        lines.append("\n【竞品动态】")
        for m in sections['competitor_intel'][:5]:
            lines.append(f"  • {m['content'][:150]}")
    
    if sections['strategic_decision']:
        lines.append("\n【战略决策记录】")
        for m in sections['strategic_decision'][:5]:
            lines.append(f"  • {m['content'][:150]}")
    
    if sections['trend_observation']:
        lines.append("\n【趋势观察】")
        for m in sections['trend_observation'][:3]:
            lines.append(f"  • {m['content'][:150]}")
    
    return "\n".join(lines)


def extract_and_save_strategic_memory(conv_id: int, agent_name: str, 
                                       question: str, answer: str) -> bool:
    """从对话中提取并保存战略记忆（产品战略官专用）"""
    if agent_name != "产品战略官":
        return False
    
    import re
    
    # 第一步：尝试提取结构化结论（带关键词标记的）
    patterns = [
        (r'定位[:：]\s*(.+?)(?:\n|$)', 'product_position'),
        (r'竞品[:：]\s*(.+?)(?:\n|$)', 'competitor_intel'),
        (r'战略[:：]\s*(.+?)(?:\n|$)', 'strategic_decision'),
        (r'趋势[:：]\s*(.+?)(?:\n|$)', 'trend_observation'),
        (r'风险[:：]\s*(.+?)(?:\n|$)', 'risk_assessment'),
        (r'🔴\s*(.+?)(?:\n|$)', 'strategic_decision'),
        (r'建议[:：]\s*(.+?)(?:\n|$)', 'strategic_decision'),
        (r'结论[:：]\s*(.+?)(?:\n|$)', 'strategic_decision'),
        (r'核心[:：]\s*(.+?)(?:\n|$)', 'product_position'),
        (r'差异化[:：]\s*(.+?)(?:\n|$)', 'product_position'),
    ]
    
    saved = False
    for pattern, mem_type in patterns:
        matches = re.findall(pattern, answer)
        for match in matches[:2]:
            if isinstance(match, tuple):
                match = match[0]
            if len(match) > 10:
                save_strategic_memory(mem_type, match.strip(), conv_id, importance=4)
                saved = True
    
    # 第二步：如果没有结构化标记，将核心结论作为整体记忆
    if not saved:
        # 提取第一个有意义的段落（至少30字）
        paragraphs = [p.strip() for p in answer.split('\n\n') if len(p.strip()) > 30]
        if paragraphs:
            save_strategic_memory('strategic_decision', 
                f"基于'{question[:50]}'的分析：{paragraphs[0][:300]}", 
                conv_id, importance=3)
            saved = True
    
    return saved


# ============ 用户体验官 — 用户画像记忆 ============

def save_ux_memory(memory_type: str, content: str, persona_id: str = "",
                   scenario: str = "", emotion_tag: str = "", 
                   confidence: int = 3, source_conv_id: int = 0) -> bool:
    """保存用户体验记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_experience_memory 
            (memory_type, persona_id, content, scenario, emotion_tag, confidence, source_conversation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (memory_type, persona_id, content[:4000], scenario, emotion_tag, confidence, source_conv_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"保存UX记忆失败: {e}")
        return False


def get_ux_memory(memory_types: List[str] = None, 
                  persona_id: str = "", limit: int = 20) -> List[Dict]:
    """获取用户体验记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        
        query = "SELECT * FROM user_experience_memory WHERE 1=1"
        params = []
        
        if memory_types:
            placeholders = ','.join('?' * len(memory_types))
            query += f" AND memory_type IN ({placeholders})"
            params.extend(memory_types)
        
        if persona_id:
            query += " AND persona_id = ?"
            params.append(persona_id)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取UX记忆失败: {e}")
        return []


def get_ux_memory_context(persona_id: str = "") -> str:
    """获取用户体验官的记忆上下文（注入prompt）"""
    memories = get_ux_memory(persona_id=persona_id, limit=30)
    if not memories:
        return "暂无历史用户记忆。"
    
    lines = ["📚 历史用户记忆："]
    
    # 按类型分组
    sections = {
        'persona_profile': "用户画像",
        'journey_map': "旅程地图",
        'emotion_data': "情感数据",
        'verbatim_quote': "用户原声",
        'cultural_insight': "文化洞察",
        'pain_point': "痛点记录",
    }
    
    for mem_type, label in sections.items():
        items = [m for m in memories if m['memory_type'] == mem_type]
        if items:
            lines.append(f"\n【{label}】")
            for m in items[:5]:
                prefix = f"[{m['persona_id']}] " if m['persona_id'] else ""
                lines.append(f"  • {prefix}{m['content'][:150]}")
    
    return "\n".join(lines)


def extract_and_save_ux_memory(conv_id: int, agent_name: str,
                                question: str, answer: str) -> bool:
    """从对话中提取并保存UX记忆（用户体验官专用）"""
    if agent_name != "用户体验官":
        return False
    
    import re
    
    # 第一步：提取结构化内容（引号原声、引用、用户故事）
    patterns = [
        (r'["""]([^"""]{15,300})["""]', 'verbatim_quote', ''),  # 中文/英文引号
        (r'>\s*(.{15,300}?)(?:\n|$)', 'verbatim_quote', ''),
        (r'P(\d)[\s\S]{10,200}?痛点', 'pain_point', 'P{}'),
        (r'P(\d)[\s\S]{10,200}?焦虑|frustration', 'emotion_data', 'P{}'),
        (r'P(\d)[\s\S]{20,300}?', 'persona_profile', 'P{}'),
        (r'💡\s*(.{15,300}?)(?:\n|$)', 'cultural_insight', ''),
        (r'用户故事[:：]\s*(.{15,300}?)(?:\n|$)', 'journey_map', ''),
        (r'(Sarah|Mike|Lisa)[\s\S]{15,300}?', 'persona_profile', ''),
    ]
    
    saved = False
    for pattern, mem_type, persona_fmt in patterns:
        matches = re.findall(pattern, answer)
        for match in matches[:3]:
            if isinstance(match, tuple):
                match = match[0]
            persona = ""
            if persona_fmt and match.startswith('P'):
                persona = persona_fmt.format(match)
            if len(match) > 15:
                save_ux_memory(mem_type, match.strip(), persona_id=persona, 
                              confidence=3, source_conv_id=conv_id)
                saved = True
    
    # 第二步：没有结构化标记时，保存整体用户洞察
    if not saved:
        paragraphs = [p.strip() for p in answer.split('\n\n') if len(p.strip()) > 30]
        if paragraphs:
            save_ux_memory('cultural_insight', 
                f"基于'{question[:50]}'的洞察：{paragraphs[0][:300]}",
                confidence=3, source_conv_id=conv_id)
            saved = True
    
    return saved


# ============ 数据研究员 — 数据结论记忆 ============

def save_data_memory(memory_type: str, topic: str, conclusion: str,
                     evidence_level: str = "推断", sample_size: str = "",
                     confidence: str = "", data_sources: List[str] = None,
                     related_agents: List[str] = None, 
                     source_conv_id: int = 0) -> bool:
    """保存数据研究记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO data_research_memory 
            (memory_type, topic, conclusion, evidence_level, sample_size, confidence, 
             data_sources, related_agents, source_conversation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (memory_type, topic[:200], conclusion[:4000], evidence_level,
              sample_size, confidence,
              json.dumps(data_sources or [], ensure_ascii=False),
              json.dumps(related_agents or [], ensure_ascii=False),
              source_conv_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"保存数据记忆失败: {e}")
        return False


def get_data_memory(memory_types: List[str] = None, 
                    topic: str = "", limit: int = 20) -> List[Dict]:
    """获取数据研究记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        
        query = "SELECT * FROM data_research_memory WHERE is_still_valid = 1"
        params = []
        
        if memory_types:
            placeholders = ','.join('?' * len(memory_types))
            query += f" AND memory_type IN ({placeholders})"
            params.extend(memory_types)
        
        if topic:
            query += " AND topic LIKE ?"
            params.append(f"%{topic}%")
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取数据记忆失败: {e}")
        return []


def get_data_memory_context(topic: str = "") -> str:
    """获取数据研究员的记忆上下文（注入prompt）"""
    memories = get_data_memory(topic=topic, limit=30)
    if not memories:
        return "暂无历史数据记忆。"
    
    lines = ["📚 历史数据记忆："]
    
    # 按类型分组
    sections = {
        'data_conclusion': "数据结论",
        'data_gap': "数据缺口",
        'methodology': "方法论",
        'cross_validation': "交叉验证",
    }
    
    for mem_type, label in sections.items():
        items = [m for m in memories if m['memory_type'] == mem_type]
        if items:
            lines.append(f"\n【{label}】")
            for m in items[:5]:
                badge = {"直接": "✅", "推断": "⚠️", "不足": "❓"}.get(m['evidence_level'], "")
                lines.append(f"  • [{m['topic'][:20]}] {badge} {m['conclusion'][:120]}")
    
    return "\n".join(lines)


def extract_and_save_data_memory(conv_id: int, agent_name: str,
                                  question: str, answer: str) -> bool:
    """从对话中提取并保存数据记忆（数据研究员专用）"""
    if agent_name != "数据研究员":
        return False
    
    import re
    
    # 第一步：提取结构化数据结论
    patterns = [
        (r'✅\s*(.{20,300}?)(?:\n|$)', 'data_conclusion', '直接'),
        (r'⚠️\s*(.{20,300}?)(?:\n|$)', 'data_conclusion', '推断'),
        (r'❓\s*(.{20,300}?)(?:\n|$)', 'data_gap', '不足'),
        (r'n=(\d+)[\s\S]{10,200}?结论[:：]\s*(.{20,200})', 'data_conclusion', '直接'),
        (r'建议补充\s*(.{10,200})', 'data_gap', '不足'),
        (r'数据[:：]\s*(.{20,300}?)(?:\n|$)', 'data_conclusion', '直接'),
        (r'结论[:：]\s*(.{20,300}?)(?:\n|$)', 'data_conclusion', '推断'),
        (r'交叉验证[:：]\s*(.{20,300}?)(?:\n|$)', 'cross_validation', '直接'),
    ]
    
    saved = False
    for pattern, mem_type, evidence in patterns:
        matches = re.findall(pattern, answer)
        for match in matches[:2]:
            if isinstance(match, tuple):
                topic = f"n={match[0]}"
                conclusion = match[1]
            else:
                topic = question[:50]
                conclusion = match
            
            save_data_memory(mem_type, topic, conclusion.strip(),
                           evidence_level=evidence, source_conv_id=conv_id)
            saved = True
    
    # 第二步：没有标记时，保存核心数据发现
    if not saved:
        paragraphs = [p.strip() for p in answer.split('\n\n') if len(p.strip()) > 30]
        if paragraphs:
            save_data_memory('data_conclusion', question[:50], paragraphs[0][:300],
                           evidence_level='推断', source_conv_id=conv_id)
            saved = True
    
    return saved


# ============ 逻辑校验官 — 短期审查记忆 ============

def save_logic_review(reviewed_agent: str, topic: str, issues_found: List[Dict],
                      credibility_score: int = 50, review_summary: str = "",
                      source_conv_id: int = 0) -> bool:
    """保存逻辑审查记忆"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO logic_review_memory 
            (reviewed_agent, topic, issues_found, credibility_score, review_summary, source_conversation_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (reviewed_agent, topic[:200], json.dumps(issues_found, ensure_ascii=False),
              credibility_score, review_summary[:1000], source_conv_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"保存审查记忆失败: {e}")
        return False


def get_logic_review_history(reviewed_agent: str = "", limit: int = 10) -> List[Dict]:
    """获取审查历史"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        
        if reviewed_agent:
            cursor.execute('''
                SELECT * FROM logic_review_memory 
                WHERE reviewed_agent = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (reviewed_agent, limit))
        else:
            cursor.execute('''
                SELECT * FROM logic_review_memory 
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取审查历史失败: {e}")
        return []


# ============ 记忆摘要（防止上下文爆炸） ============

def create_memory_summary(agent_name: str, summary_type: str, 
                          summary_content: str) -> bool:
    """创建记忆摘要"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO memory_summaries (agent_name, summary_type, summary_content)
            VALUES (?, ?, ?)
        ''', (agent_name, summary_type, summary_content[:8000]))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"创建记忆摘要失败: {e}")
        return False


def get_latest_summary(agent_name: str, summary_type: str = "") -> Optional[str]:
    """获取最新摘要"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        
        if summary_type:
            cursor.execute('''
                SELECT summary_content FROM memory_summaries
                WHERE agent_name = ? AND summary_type = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (agent_name, summary_type))
        else:
            cursor.execute('''
                SELECT summary_content FROM memory_summaries
                WHERE agent_name = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (agent_name,))
        
        row = cursor.fetchone()
        conn.close()
        return row['summary_content'] if row else None
    except Exception as e:
        logger.error(f"获取摘要失败: {e}")
        return None


# ============ 主入口：获取Agent记忆上下文 ============

def get_agent_memory_context(agent_name: str, question: str = "") -> str:
    """
    获取指定Agent的记忆上下文，用于注入prompt
    每个Agent返回其专属记忆格式
    """
    if agent_name == "产品战略官":
        return get_strategic_memory_context()
    elif agent_name == "用户体验官":
        # 尝试从问题中提取persona_id
        persona = ""
        for p in ["P1", "P2", "P3", "P4"]:
            if p in question:
                persona = p
                break
        return get_ux_memory_context(persona_id=persona)
    elif agent_name == "数据研究员":
        # 尝试从问题中提取topic关键词
        topic = question[:30] if len(question) > 10 else ""
        return get_data_memory_context(topic=topic)
    elif agent_name == "逻辑校验官":
        # 逻辑校验官主要用近期对话，不需要长期记忆
        return ""
    else:
        return ""


def save_agent_memory(conv_id: int, agent_name: str, 
                      question: str, answer: str) -> bool:
    """
    从对话中提取并保存记忆（各Agent专用）
    """
    if conv_id == 0:
        return False
    
    results = []
    
    if agent_name == "产品战略官":
        results.append(extract_and_save_strategic_memory(conv_id, agent_name, question, answer))
    elif agent_name == "用户体验官":
        results.append(extract_and_save_ux_memory(conv_id, agent_name, question, answer))
    elif agent_name == "数据研究员":
        results.append(extract_and_save_data_memory(conv_id, agent_name, question, answer))
    elif agent_name == "逻辑校验官":
        # 逻辑校验官不保存长期记忆，只保留对话记录
        pass
    
    return any(results)


# 初始化
try:
    init_memory_db()
except Exception as e:
    logger.error(f"记忆数据库初始化失败: {e}")
