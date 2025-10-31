#!/usr/bin/env python3
# chat_with_mcp_compat.py
from __future__ import annotations
import asyncio, json, os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

# ----- OpenAI -----
from openai import OpenAI

OA_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
oa = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = (
    "You are an AI DM assistant. You can call tools from an MCP server. "
    "Prefer calling tools over guessing. After each tool call, use the result."
)
MCP_CMD = os.environ.get(
    "MCP_CMD",
    "/Users/csinger/projects/agentic-dm/.venv/bin/python mcp-server/server.py",
)

# ----- MCP compatibility imports -----
CallToolRequest = None
try:
    # Newer SDK layout
    from mcp import ClientSession as NewClientSession
    from mcp.transport.stdio import StdioTransport as NewStdioTransport

    HAVE_NEW = True
except Exception:
    HAVE_NEW = False

try:
    # Older SDK layout
    from mcp.client.session import ClientSession as OldClientSession
    from mcp.client.stdio import StdioClientTransport as OldStdioTransport
    from mcp.types import CallToolRequest as OldCallToolRequest

    HAVE_OLD = True
    CallToolRequest = OldCallToolRequest
except Exception:
    HAVE_OLD = False

if not (HAVE_NEW or HAVE_OLD):
    raise RuntimeError("MCP SDK not found. Try: pip install -U mcp")


# ----- Small compatibility layer -----
class CompatTransport:
    def __init__(self, command: str):
        self.command = command
        self.impl = None

    async def start(self):
        if HAVE_NEW:
            self.impl = NewStdioTransport.create(self.command)
            # New transport has no explicit start; session.start() will spawn it
        elif HAVE_OLD:
            # Old transport uses __aenter__
            self.impl = OldStdioTransport(command=self.command)
            await self.impl.__aenter__()

    async def close(self):
        if HAVE_NEW and self.impl:
            await self.impl.close()
        elif HAVE_OLD and self.impl:
            await self.impl.__aexit__(None, None, None)


class CompatSession:
    def __init__(self, transport):
        if HAVE_NEW:
            self.impl = NewClientSession(transport.impl)
            self.mode = "new"
        else:
            self.impl = OldClientSession(transport.impl)
            self.mode = "old"

    async def start(self):
        if self.mode == "new":
            await self.impl.start()
        else:
            await self.impl.__aenter__()
            # Some very old builds needed explicit initialize():
            try:
                await self.impl.initialize()  # no-op if not present
            except Exception:
                pass

    async def close(self):
        if self.mode == "new":
            await self.impl.close()
        else:
            await self.impl.__aexit__(None, None, None)

    async def list_tools(self):
        return await self.impl.list_tools()

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        # New API: call_tool(name, args)
        if self.mode == "new":
            return await self.impl.call_tool(name, arguments or {})
        # Old API: call_tool(CallToolRequest)
        if CallToolRequest is None:
            raise RuntimeError("Old MCP detected but CallToolRequest missing.")
        req = CallToolRequest(name=name, arguments=arguments or {})
        return await self.impl.call_tool(req)


# ----- Bridge -----
class MCPTool:
    def __init__(self, name: str, description: str, schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.schema = schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }


class MCPBridge:
    def __init__(self, command: str):
        self.command = command
        self.transport: Optional[CompatTransport] = None
        self.session: Optional[CompatSession] = None

    async def __aenter__(self):
        self.transport = CompatTransport(self.command)
        await self.transport.start()
        self.session = CompatSession(self.transport)
        await self.session.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()
        if self.transport:
            await self.transport.close()

    async def list_tools(self) -> List[MCPTool]:
        res = await self.session.list_tools()
        tools = []
        for t in res.tools:
            tools.append(
                MCPTool(
                    name=t.name,
                    description=(getattr(t, "description", "") or t.name),
                    schema=(
                        getattr(t, "inputSchema", None)
                        or {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        }
                    ),
                )
            )
        return tools

    async def call(self, name: str, args: Dict[str, Any]) -> Any:
        result = await self.session.call_tool(name, args or {})
        # Normalize MCP content → Python object
        first_json = None
        texts: List[str] = []
        for c in result.content:
            ctype = getattr(c, "type", None)
            if ctype == "json" and first_json is None:
                first_json = getattr(c, "json", None)
            elif ctype == "text":
                txt = getattr(c, "text", "") or ""
                if txt:
                    texts.append(txt)
        if first_json is not None:
            return first_json
        return "\n".join(texts).strip()


# ----- Convert MCP tools → OpenAI function tools -----
def ensure_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    s = dict(schema or {})
    s.setdefault("type", "object")
    s.setdefault("properties", {})
    s.setdefault("additionalProperties", False)
    return s


def safe_name(name: str) -> str:
    return name.replace(".", "_")


def to_openai_tools(mcp_tools: List[MCPTool]) -> List[Dict[str, Any]]:
    out = []
    for t in mcp_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": safe_name(t.name),
                    "description": t.description or t.name,
                    "parameters": ensure_schema(t.schema),
                },
            }
        )
    return out


# ----- Chat loop -----
async def main():
    print("MCP command:", MCP_CMD)
    user_text = input("You: ").strip()

    async with MCPBridge(MCP_CMD) as mcp:
        tools = await mcp.list_tools()
        oa_tools = to_openai_tools(tools)
        name_map = {safe_name(t.name): t.name for t in tools}

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        while True:
            resp = oa.chat.completions.create(
                model=OA_MODEL,
                messages=messages,
                tools=oa_tools,
                tool_choice="auto",
                temperature=0.4,
            )
            msg = resp.choices[0].message

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    mcp_name = name_map.get(fn_name, fn_name)
                    result = await mcp.call(mcp_name, args)

                    messages.append({"role": "assistant", "tool_calls": [tc]})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": fn_name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                continue

            print("\nAssistant:\n" + (msg.content or "").strip() + "\n")
            break


if __name__ == "__main__":
    asyncio.run(main())
