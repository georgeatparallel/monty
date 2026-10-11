# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic-monty==1.1.0", "mcp>=1.30,<2", "httpx>=0.28,<1"]
# ///
"""Exercise the sandbox callbacks through an in-memory MCP HTTP server."""

from __future__ import annotations

import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

import httpx
import main


class ExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_fetch_requests(self) -> None:
        requests: list[httpx.Request] = []
        real_client = httpx.AsyncClient

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return response(request)

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        output = io.StringIO()
        with patch.object(main.httpx, 'AsyncClient', client), redirect_stdout(output):
            await main.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['sources'], [{'title': 'Monty', 'url': 'https://pydantic.dev/docs/monty/'}])
        self.assertEqual(result['page']['results'][0]['excerpts'], ['Host functions run outside the sandbox.'])
        messages = [json.loads(request.content) for request in requests]
        self.assertEqual(
            [message['method'] for message in messages],
            ['initialize', 'notifications/initialized', 'tools/list', 'tools/call', 'tools/call'],
        )
        calls = [message['params'] for message in messages if message['method'] == 'tools/call']
        self.assertEqual([call['name'] for call in calls], ['web_search', 'web_fetch'])
        self.assertEqual(calls[1]['arguments']['urls'], ['https://pydantic.dev/docs/monty/'])
        self.assertEqual(calls[0]['arguments']['session_id'], calls[1]['arguments']['session_id'])
        self.assertNotIn('model_name', calls[0]['arguments'])
        for request in requests:
            self.assertEqual(str(request.url), main.MCP_URL)
            self.assertEqual(request.headers['User-Agent'], main.USER_AGENT)
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('x-api-key', request.headers)
            self.assertEqual(request.extensions['timeout']['read'], 30)

    async def test_tool_error_reaches_sandbox(self) -> None:
        real_client = httpx.AsyncClient

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(lambda request: response(request, error=True)), **kwargs)

        code = """
try:
    await web_search('test', ['test query'])
except RuntimeError as exc:
    message = str(exc)
message
"""
        output = io.StringIO()
        with (
            patch.object(main.httpx, 'AsyncClient', client),
            patch.object(main, 'SANDBOX_CODE', code),
            redirect_stdout(output),
        ):
            await main.main()
        self.assertEqual(json.loads(output.getvalue()), 'quota exhausted')

    async def test_cancellation_closes_client(self) -> None:
        started = asyncio.Event()
        clients: list[httpx.AsyncClient] = []
        real_client = httpx.AsyncClient

        async def handle(request: httpx.Request) -> httpx.Response:
            if json.loads(request.content)['method'] == 'tools/call':
                started.set()
                await asyncio.Event().wait()
            return response(request)

        def client(**kwargs: Any) -> httpx.AsyncClient:
            instance = real_client(transport=httpx.MockTransport(handle), **kwargs)
            clients.append(instance)
            return instance

        with patch.object(main.httpx, 'AsyncClient', client):
            task = asyncio.create_task(main.main())
            await asyncio.wait_for(started.wait(), timeout=10)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=10)
        self.assertTrue(clients[0].is_closed)


def response(request: httpx.Request, *, error: bool = False) -> httpx.Response:
    """Serve initialization, discovery, and the two tools without a network connection."""
    message = json.loads(request.content)
    method = message['method']
    result: dict[str, Any]
    if method == 'notifications/initialized':
        return httpx.Response(202)
    if method == 'initialize':
        result = {
            'protocolVersion': message['params']['protocolVersion'],
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'test-search-server', 'version': '1.0'},
        }
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'inputSchema': {'type': 'object'}} for name in ['web_search', 'web_fetch']]}
    elif error:
        result = {'isError': True, 'content': [{'type': 'text', 'text': 'quota exhausted'}]}
    elif message['params']['name'] == 'web_search':
        result = {
            'content': [],
            'structuredContent': {'results': [{'title': 'Monty', 'url': 'https://pydantic.dev/docs/monty/'}]},
        }
    else:
        result = {
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps({'results': [{'excerpts': ['Host functions run outside the sandbox.']}]}),
                }
            ],
        }
    return httpx.Response(200, json={'jsonrpc': '2.0', 'id': message['id'], 'result': result})


if __name__ == '__main__':
    unittest.main()
