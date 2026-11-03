"""Apolaki Memory MCP Server — exposes memory store as MCP tools.

Runs as a stdio MCP server for the Apolaki scaffold engine.
Tools: apolaki_store_memory, apolaki_search_memory, apolaki_graph_stats, apolaki_wiki_page, apolaki_context_prompt.
There is no drafting, queue or review tool: an MCP client gets Apolaki's memory, not its drafter.

House rules can't be written here (2026-11-02 review). Every active memory of type brand or guideline goes into the
system prompt in full, as a standing rule a brief can't lift, so only a person sets them: at the interactive agent's
/rule command, or in Python with ApolakiAgent.remember(text, memory_type="guideline"). apolaki_store_memory refuses
those types and anything else outside STORABLE_TYPES, and checks the rest of its schema, before anything is stored.
What it would store is screened as outside text too (apolaki.intake, Garuda layer 1): a hit is quarantined for a
person and refused. The store is opened when a tool first needs it, not at import.
"""
from __future__ import annotations

import json
import sys
import logging
from datetime import datetime, timezone

from .memory_store import ApolakiMemoryStore
from .. import intake

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("apolaki-memory")

_store = None


def get_store() -> ApolakiMemoryStore:
    global _store
    if _store is None:
        _store = ApolakiMemoryStore()
    return _store


# What apolaki_store_memory accepts; the schema offers exactly these. Not brand or guideline: those are house rules.
STORABLE_TYPES = ("observation", "decision", "campaign", "audience", "content", "strategy", "team", "project")
HOUSE_RULE_TYPES = ("brand", "guideline")       # the agent's own list (agent.HOUSE_RULE_TYPES); tested to match


def store_arguments(args: dict) -> dict:
    """apolaki_store_memory's arguments, checked against its schema. Raises ValueError, before anything is stored, on
    a house-rule type or any type outside STORABLE_TYPES, and on content, significance, tags or source of the wrong
    kind."""
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be non-empty text")
    memory_type = args.get("memory_type", "observation")
    if memory_type in HOUSE_RULE_TYPES:
        raise ValueError(f"memory_type {memory_type!r} is a house rule: it would go into every system prompt as a "
                         f"standing rule, so it is never written over MCP. A person sets house rules at the agent's "
                         f"/rule command (python -m apolaki.agent.agent)")
    if not isinstance(memory_type, str) or memory_type not in STORABLE_TYPES:
        raise ValueError(f"memory_type must be one of {STORABLE_TYPES}, not {memory_type!r}")
    significance = args.get("significance", 0.5)
    # not 0 <= x <= 1 is also true for NaN, which compares false with everything
    if isinstance(significance, bool) or not isinstance(significance, (int, float)) or not 0 <= significance <= 1:
        raise ValueError(f"significance must be a number from 0 to 1, not {significance!r}")
    tags = args.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError(f"tags must be a list of text, not {tags!r}")
    source = args.get("source", "")
    if not isinstance(source, str):
        raise ValueError(f"source must be text, not {source!r}")
    return {"content": content, "memory_type": memory_type, "significance": significance, "tags": tags,
            "source": source}

TOOLS = [
    {
        "name": "apolaki_store_memory",
        "description": "Store a new memory: campaign results, audience insights, content performance, strategic context, anything worth remembering across sessions. House rules (brand, guideline) are refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The memory content"},
                "memory_type": {
                    "type": "string",
                    "enum": list(STORABLE_TYPES),
                    "default": "observation",
                    "description": "Not brand or guideline: house rules are set by a person, never over MCP.",
                },
                "significance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                "source": {"type": "string", "default": ""},
            },
            "required": ["content"],
        },
    },
    {
        "name": "apolaki_search_memory",
        "description": "Search memories semantically with TGS-verified graph retrieval. Use for recalling brand voice, past campaigns, team context, project details, strategic decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "n_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                "memory_type": {"type": "string", "description": "Filter by type"},
                "use_graph": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
    },
    {
        "name": "apolaki_graph_stats",
        "description": "Knowledge graph statistics — entity counts, top entities, triple counts. Use for understanding what Apolaki knows structurally.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "apolaki_wiki_page",
        "description": "Generate or retrieve a wiki page for an entity. Creates interlinked markdown from the knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name": {"type": "string", "description": "Entity to generate wiki page for"},
            },
            "required": ["entity_name"],
        },
    },
    {
        "name": "apolaki_context_prompt",
        "description": "Get a session context prompt with top brand memories, recent decisions, and active campaigns. Load at session start.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_tool(name: str, args: dict) -> str:
    if name == "apolaki_store_memory":
        checked = store_arguments(args)          # raises before anything is stored
        # An MCP client is outside text: Garuda screens what it asks to store, before it can reach a prompt.
        screened = intake.screen("\n".join([checked["content"], checked["source"], *checked["tags"]]),
                                 source="mcp:apolaki_store_memory", kind="mcp memory")
        if not screened.ok:
            raise ValueError(f"not stored: the intake screen quarantined it for a person ({screened.quarantine_id}; "
                             f"Garuda layer 1 matched {len(screened.flags)} pattern(s))")
        store = get_store()
        mid = store.store(**checked)
        stats = store.stats()
        return json.dumps({
            "stored": mid,
            "total_memories": stats["memories"],
            "total_entities": stats["entities"],
        })

    elif name == "apolaki_search_memory":
        results = get_store().search(
            query=args["query"],
            n_results=args.get("n_results", 5),
            memory_type=args.get("memory_type"),
            use_graph=args.get("use_graph", True),
        )
        return json.dumps({
            "results": [
                {
                    "content": r.memory.content,
                    "type": r.memory.memory_type,
                    "significance": r.memory.significance,
                    "score": round(r.score, 4),
                    "source": r.source,
                    "verification": r.verification,
                    "graph_entities": r.graph_entities,
                    "tags": r.memory.tags,
                    "created_at": r.memory.created_at,
                }
                for r in results
            ],
            "count": len(results),
        })

    elif name == "apolaki_graph_stats":
        return json.dumps(get_store().stats())

    elif name == "apolaki_wiki_page":
        page = get_store().generate_wiki_page(args["entity_name"])
        if page:
            return page
        return f"No entity found for '{args['entity_name']}'"

    elif name == "apolaki_context_prompt":
        # Build session context from high-significance memories
        store = get_store()
        brand = store.search("brand voice principles identity", n_results=3, memory_type="brand", use_graph=False)
        strategy = store.search("current strategy priorities campaigns", n_results=3, memory_type="strategy", use_graph=False)
        recent = store.search("recent decisions outcomes", n_results=3, use_graph=False)

        sections = ["## Session Context (from memory)"]

        if brand:
            sections.append("\n### Brand Voice")
            for r in brand:
                sections.append(f"- {r.memory.content[:200]}")

        if strategy:
            sections.append("\n### Active Strategy")
            for r in strategy:
                sections.append(f"- {r.memory.content[:200]}")

        if recent:
            sections.append("\n### Recent Context")
            for r in recent:
                sections.append(f"- [{r.memory.memory_type}] {r.memory.content[:200]}")

        stats = store.stats()
        sections.append(f"\n*Memory: {stats['memories']} memories, {stats['entities']} entities, {stats['triples']} graph edges*")

        return "\n".join(sections)

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── MCP stdio protocol ──

def read_message() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def write_message(msg: dict):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def tool_result(req_id, params: dict) -> dict:
    """The JSON-RPC reply to one tools/call: a refusal or any other error goes back with isError set."""
    tool_name = params.get("name", "")
    tool_args = params.get("arguments", {})
    try:
        result = handle_tool(tool_name, tool_args)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}],
                                                           "isError": False}}
    except Exception as e:
        logger.exception("Tool error: %s", tool_name)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Error: {e}"}],
                                                           "isError": True}}


def main():
    logger.info("Apolaki Memory MCP starting...")
    stats = get_store().stats()
    logger.info("Loaded: %d memories, %d entities, %d triples", stats["memories"], stats["entities"], stats["triples"])

    while True:
        msg = read_message()
        if msg is None:
            break

        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "apolaki-memory", "version": "1.0.0"},
                },
            })

        elif method == "notifications/initialized":
            pass

        elif method == "tools/list":
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            })

        elif method == "tools/call":
            write_message(tool_result(req_id, msg.get("params", {})))

        elif method == "ping":
            write_message({"jsonrpc": "2.0", "id": req_id, "result": {}})

        else:
            if req_id is not None:
                write_message({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })


if __name__ == "__main__":
    main()
