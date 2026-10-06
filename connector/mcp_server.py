"""MCP server (stdio). Run:  python -m connector.mcp_server"""
import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .tools import TOOLS, call_tool

server = Server("woocommerce-readonly")


@server.list_tools()
async def _list_tools():
    return [types.Tool(name=t.name, description=t.description, inputSchema=t.schema) for t in TOOLS]


@server.call_tool()
async def _call_tool(name: str, arguments: dict):
    result = await asyncio.to_thread(call_tool, name, arguments)   # client is blocking
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
