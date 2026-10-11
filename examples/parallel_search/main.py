# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic-monty==1.1.0", "mcp>=1.30,<2", "httpx>=0.28,<1"]
# ///
"""Search and fetch through host callbacks while Monty processes the results."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from pydantic_monty import AsyncMonty

MCP_URL = 'https://search.parallel.ai/mcp'
USER_AGENT = 'monty-parallel-search-example/1.0 (https://github.com/pydantic/monty)'

SANDBOX_CODE = """
import json

objective = 'Find the Monty documentation explaining sandbox isolation and host functions.'
queries = ['Pydantic Monty sandbox host functions']
search = json.loads(await web_search(objective, queries))
sources = [{'title': page['title'], 'url': page['url']} for page in search['results'][:3]]
if sources:
    page = json.loads(await web_fetch([sources[0]['url']], objective, queries))
else:
    page = {'results': []}
{'sources': sources, 'page': page}
"""


async def main() -> None:
    """Connect anonymously and give one sandbox two bounded host callbacks."""
    conversation_id = uuid4().hex
    async with httpx.AsyncClient(
        headers={'User-Agent': USER_AGENT},
        timeout=httpx.Timeout(30),
    ) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as mcp:
                await mcp.initialize()
                tools = await mcp.list_tools()
                if not {'web_search', 'web_fetch'} <= {tool.name for tool in tools.tools}:
                    raise RuntimeError('The MCP server does not provide web_search and web_fetch.')

                async def web_search(objective: str, search_queries: list[str]) -> str:
                    return await tool_json(
                        mcp,
                        'web_search',
                        {'objective': objective, 'search_queries': search_queries, 'session_id': conversation_id},
                    )

                async def web_fetch(urls: list[str], objective: str, search_queries: list[str]) -> str:
                    return await tool_json(
                        mcp,
                        'web_fetch',
                        {
                            'urls': urls,
                            'objective': objective,
                            'search_queries': search_queries,
                            'session_id': conversation_id,
                        },
                    )

                async with AsyncMonty() as pool:
                    async with pool.checkout(
                        limits={'max_suspensions': 4, 'max_feed_duration_secs': 90, 'max_memory': 20_000_000},
                    ) as sandbox:
                        result = await sandbox.feed_run(
                            SANDBOX_CODE,
                            external_lookup={'web_search': web_search, 'web_fetch': web_fetch},
                        )
                print(json.dumps(result, indent=2))


async def tool_json(session: ClientSession, name: str, arguments: dict[str, object]) -> str:
    """Return MCP JSON as a string that the sandbox can decode."""
    result = await session.call_tool(name, arguments)
    text = '\n'.join(block.text for block in result.content if isinstance(block, TextContent))
    if result.isError:
        raise RuntimeError(text or f'{name} failed')
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent)
    if not text:
        raise RuntimeError(f'{name} returned no text or structured content')
    return text


if __name__ == '__main__':
    asyncio.run(main())
