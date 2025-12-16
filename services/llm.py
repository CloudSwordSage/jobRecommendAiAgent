# -*- coding: utf-8 -*-
# @Time    : 2025/11/24 15:29:47
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : llm.py
# @License : Apache-2.0
# @Desc    : LLM服务

import contextlib
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, AsyncGenerator, AsyncIterator, Any, Tuple

from config import Config
from config.config import (
    PORTRAIT_SYSTEM_PROMPT,
    COMPRESS_SYSTEM_PROMPT,
    NAMING_SYSTEM_PROMPT,
)
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk, ChatCompletion
from MCP import vector_service
from services.telemetry import capture_exception

from neo4j import AsyncSession

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession as DBAsyncSession
from model.session import Session

DouBao: AsyncOpenAI | None = None
DeepSeek: AsyncOpenAI | None = None


def init_llm():
    global DouBao, DeepSeek
    DouBao = AsyncOpenAI(
        api_key=Config.doubao_api_key, base_url=Config.doubao_api_base_url
    )
    DeepSeek = AsyncOpenAI(
        api_key=Config.deepseek_api_key, base_url=Config.deepseek_api_base_url
    )


async def chat_doubao(
    messages: List[Dict[str, str]], stream: bool = True
) -> AsyncGenerator[str, None]:
    response: AsyncIterator[ChatCompletionChunk] = await DouBao.chat.completions.create(
        model=Config.doubao_model_name,
        messages=messages,
        stream=stream,
        temperature=0.7,
        extra_body={"thinking": {"type": "disabled"}},
    )
    if not stream:
        yield response.choices[0].message.content.strip()
        return
    async for chunk in response:
        yield chunk.choices[0].delta.content


async def chat_deepseek(
    messages: List[Dict[str, str]], stream: bool = True
) -> AsyncGenerator[str, None]:
    response: AsyncIterator[ChatCompletionChunk] = (
        await DeepSeek.chat.completions.create(
            model=Config.deepseek_model_name,
            messages=messages,
            stream=stream,
            temperature=0,
        )
    )
    if not stream:
        yield response.choices[0].message.content.strip()
        return
    async for chunk in response:
        yield chunk.choices[0].delta.content


async def job_search_topn(query: str, topn: int) -> List[Dict]:
    """
    基于查询字符串搜索topn个岗位

    Args:
        query (str): 搜索查询字符串
        topn (int): 返回的岗位数量

    Returns:
        List[Dict]: 包含岗位信息的字典列表
    Example:
        >>> await job_search_topn("数据分析师", 3)
        [
            {
                "jid": 岗位id,
                "score": l2分数,
                "job_title": 岗位标题,
                "job_description_requirements": 岗位描述要求,
                "company_name": 公司名称,
                "salary": 薪资,
                "location": 工作地点,
                "edu_requirement": 学历要求,
                "exp_requirement": 经验要求,
                "company_type": 公司类型,
                "company_industry": 公司行业,
            },
            ...
        ]
    """
    print(f"job_search_topn: query={query}, topn={topn}")
    print(f"job_vector_service is None: {vector_service.job_vector_service is None}")
    if not vector_service.job_vector_service:
        return []
    return await vector_service.job_vector_service.search_async(query, topn)


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat") and callable(getattr(value, "isoformat")):
        with contextlib.suppress(Exception):
            return value.isoformat()
    if hasattr(value, "iso_format") and callable(getattr(value, "iso_format")):
        with contextlib.suppress(Exception):
            return value.iso_format()
    if hasattr(value, "to_native") and callable(getattr(value, "to_native")):
        with contextlib.suppress(Exception):
            native = value.to_native()
            return _to_jsonable(native)
    return str(value)


def _jsonify_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _to_jsonable(v) for k, v in props.items()}


def _sanitize_label(label: str) -> str:
    if not label:
        return "Unknown"
    cleaned_parts: list[str] = []
    for ch in label:
        if ch.isalnum() or ch == "_":
            cleaned_parts.append(ch)
        else:
            cleaned_parts.append("_")
    out = "".join(cleaned_parts).lstrip("_") or "Unknown"
    if not (out[0].isalpha() or out[0] == "_"):
        out = f"L_{out}"
    return out


def _sanitize_rel_type(rel_type: str) -> str:
    if not rel_type:
        return "RELATED_TO"
    cleaned_parts: list[str] = []
    for ch in rel_type:
        if ch.isalnum() or ch == "_":
            cleaned_parts.append(ch)
        else:
            cleaned_parts.append("_")
    return "".join(cleaned_parts).lstrip("_") or "RELATED_TO"


def _extract_json_from_text(text: str) -> str:
    if "```" not in text:
        return text
    m = re.search(r"```[a-zA-Z]*\s*([\s\S]*?)```", text)
    return m[1].strip() if m else text


async def load_portrait_data(
    neo4j_session: AsyncSession, session_id: str
) -> Tuple[str, Dict[str, Any]]:
    """
    读取或创建用户画像根节点，返回 portrait_id（固定 uuid）和已有图谱。
    """
    safe_label = "S_" + session_id.replace("-", "_")
    portrait_id = "n1"

    query_root = f"""
    MERGE (p:Portrait:{safe_label} {{portrait_id: $portrait_id}})
    ON CREATE SET p.session_id = $session_id, p.timestamp = datetime()
    RETURN p.portrait_id AS portrait_id
    """
    result = await neo4j_session.run(
        query_root, portrait_id=portrait_id, session_id=session_id
    )
    record = await result.single()
    portrait_node_id = (
        record["portrait_id"] if record and "portrait_id" in record else portrait_id
    )

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    query_data = """
    MATCH (n)
    WHERE n.session_id = $session_id
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m.session_id = $session_id
    RETURN n, r, m
    """
    result_data = await neo4j_session.run(query_data, session_id=session_id)

    async for record in result_data:
        r = record["r"]
        m_node = record["m"]

        if n_node := record["n"]:
            nid = n_node.get("portrait_id") or str(n_node.id)
            if nid not in nodes:
                labels = [str(l) for l in n_node.labels if not str(l).startswith("S_")]
                label = labels[0] if labels else "Unknown"
                nodes[nid] = {
                    "id": nid,
                    "label": label,
                    "properties": _jsonify_properties(dict(n_node)),
                }

        if r is not None and m_node is not None:
            mid = m_node.get("portrait_id") or str(m_node.id)
            if mid not in nodes:
                labels = [str(l) for l in m_node.labels if not str(l).startswith("S_")]
                label = labels[0] if labels else "Unknown"
                nodes[mid] = {
                    "id": mid,
                    "label": label,
                    "properties": _jsonify_properties(dict(m_node)),
                }

            start_id = r.start_node.get("portrait_id") or str(r.start_node.id)
            end_id = r.end_node.get("portrait_id") or str(r.end_node.id)
            key = (start_id, end_id, r.type)
            props = _jsonify_properties(getattr(r, "_properties", {}) or {})
            if key in edges:
                edges[key].update(props)
            else:
                edges[key] = props

    edge_list = [
        {"source": s, "target": t, "type": rel_type, "properties": props}
        for (s, t, rel_type), props in edges.items()
    ]

    return portrait_node_id, {"nodes": list(nodes.values()), "edges": edge_list}


async def save_nodes_edges(
    neo4j_session: AsyncSession, session_id: str, nodes_edges: Dict[str, Any]
):
    """
    写入节点和边，保留边的完整属性。
    """
    safe_label = "S_" + session_id.replace("-", "_")

    for node in nodes_edges.get("nodes", []):
        node_id = node["id"]
        raw_label = node["label"]
        label = _sanitize_label(raw_label)
        props = (node.get("properties", {}) or {}).copy()
        for reserved in ("session_id", "id", "portrait_id"):
            props.pop(reserved, None)
        cypher = (
            f"MERGE (n:{label}:{safe_label} {{portrait_id: $id}}) "
            f"SET n.session_id = $session_id"
        )
        if props_str := ", ".join(f"{k}: ${k}" for k in props):
            cypher += f", n += {{{props_str}}}"
        result = await neo4j_session.run(
            cypher, id=node_id, session_id=session_id, **props
        )
        await result.consume()

    edges_dict: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for e in nodes_edges.get("edges", []):
        key = (e["source"], e["target"], e["type"])
        props = e.get("properties", {}) or {}
        if key in edges_dict:
            edges_dict[key].update(props)
        else:
            edges_dict[key] = props

    for (source, target, rel_type), props in edges_dict.items():
        rel_type_cypher = _sanitize_rel_type(rel_type)
        props = (props or {}).copy()
        for reserved in ("source", "target"):
            props.pop(reserved, None)
        props_str = ", ".join(f"{k}: ${k}" for k in props)
        cypher = f"""
        MATCH (a:{safe_label} {{portrait_id: $source}}), (b:{safe_label} {{portrait_id: $target}})
        MERGE (a)-[r:{rel_type_cypher}]->(b)
        """
        if props_str:
            cypher += f"SET r += {{{props_str}}}"
        result = await neo4j_session.run(cypher, source=source, target=target, **props)
        await result.consume()


async def generate_character_portrait(
    user_messages: List[Dict[str, str]], session_id: str, neo4j_session: AsyncSession
) -> Dict[str, Any]:
    """
    完整流程：读取、调用模型生成图谱、合并已有数据、落地 Neo4j。
    返回最终图谱 JSON。
    """
    if not user_messages:
        return {}

    user_messages = [
        m for m in user_messages if not m["content"].startswith("[TOOL_CALL]")
    ]

    portrait_node_id, existing_graph = await load_portrait_data(
        neo4j_session, session_id
    )
    history_message = "\n".join(f"{m['role']}: {m['content']}" for m in user_messages)

    messages = [
        {"role": "system", "content": PORTRAIT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"已有节点/边信息:\n{json.dumps(existing_graph, ensure_ascii=False)}\n"
                f"最新对话:\n{history_message}"
            ),
        },
    ]

    raw_output = ""
    async for chunk in chat_deepseek(messages, stream=False):
        raw_output += chunk

    try:
        cleaned_output = _extract_json_from_text(raw_output)
        new_graph = json.loads(cleaned_output)
    except Exception as e:
        capture_exception(e)
        print(f"Error parsing JSON: {raw_output}")
        return existing_graph

    if not new_graph.get("nodes", []) and not new_graph.get("edges", []):
        return existing_graph

    nodes_by_id = {n["id"]: n for n in existing_graph.get("nodes", [])}
    for n in new_graph.get("nodes", []):
        if n["id"] not in nodes_by_id:
            nodes_by_id[n["id"]] = n
        else:
            base_props = nodes_by_id[n["id"]].get("properties", {}) or {}
            new_props = n.get("properties", {}) or {}
            base_props.update(new_props)
            nodes_by_id[n["id"]]["properties"] = base_props

    edges_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for e in existing_graph.get("edges", []):
        key = (e["source"], e["target"], e["type"])
        edges_map[key] = e.get("properties", {}) or {}
    for e in new_graph.get("edges", []):
        key = (e["source"], e["target"], e["type"])
        props = e.get("properties", {}) or {}
        if key in edges_map:
            edges_map[key].update(props)
        else:
            edges_map[key] = props

    merged_graph = {
        "nodes": list(nodes_by_id.values()),
        "edges": [
            {"source": s, "target": t, "type": ty, "properties": props}
            for (s, t, ty), props in edges_map.items()
        ],
    }

    await save_nodes_edges(neo4j_session, session_id, merged_graph)
    return merged_graph


async def compress_message(user_messages: List[Dict[str, str]]) -> str:
    """
    压缩用户消息

    Args:
        user_messages (List[Dict[str, str]]): 用户消息列表

    Returns:
        str: 压缩后的消息
    """
    if not user_messages:
        return ""

    user_messages = [
        m for m in user_messages if not m["content"].startswith("[TOOL_CALL]")
    ]

    history_message = "\n".join(f"{m['role']}: {m['content']}" for m in user_messages)
    messages = [
        {"role": "system", "content": COMPRESS_SYSTEM_PROMPT},
        {"role": "user", "content": history_message},
    ]
    raw_output = ""
    async for chunk in chat_deepseek(messages, stream=False):
        raw_output += chunk
    return raw_output or ""


async def rename_session_name(
    user_messages: List[Dict[str, str]], session_id: str, db: DBAsyncSession
):
    """
    为会话命名

    Args:
        session_id (str): 会话ID
        db (DBAsyncSession): 数据库会话

    Returns:
        str: 会话名称
    """
    if not user_messages:
        return ""

    user_messages = [
        m for m in user_messages if not m["content"].startswith("[TOOL_CALL]")
    ]

    history_message = "\n".join(f"{m['role']}: {m['content']}" for m in user_messages)
    messages = [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": history_message},
    ]
    raw_output = ""
    async for chunk in chat_deepseek(messages, stream=False):
        raw_output += chunk

    print(raw_output)

    session: Session | None = await db.scalar(
        select(Session).where(Session.sid == session_id)
    )
    if not session:
        return ""

    session.session_name = raw_output.strip()
    await db.commit()
    return session.session_name
