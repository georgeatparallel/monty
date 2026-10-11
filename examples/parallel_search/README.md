# Web search through MCP host functions

Run a Monty sandbox that searches for documentation, keeps three source URLs, and fetches the first page.
The host connects to [Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp) over Streamable HTTP.
Anonymous search uses Fast mode; search and page fetching need no account or API key.
The free endpoint is intended for exploration and light use and has rate limits.

## Run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run from the repository root:

```bash
uv run --no-config --script examples/parallel_search/main.py
```

The script declares its dependencies and installs the released Monty 1.1.0 client and worker.
No Rust build, environment variables, saved credentials, or model API key are needed.
It prints source titles and URLs plus the fetched page excerpts as JSON.
Results vary with the live web.

For a development build, run `make dev-py` first, then:

```bash
uv run --group examples python examples/parallel_search/main.py
```

## Host boundary

The sandbox calls `web_search` and `web_fetch` through `AsyncMonty`'s `external_lookup`.
The MCP client, HTTP connection, and conversation identifier stay on the host.
Only strings containing tool results cross back into the sandbox, where `json.loads` processes them.
This example executes a fixed Python snippet; it does not run an LLM agent loop.

The host exposes two tools, connects only to `https://search.parallel.ai/mcp`, and sends no authentication header.
Search objectives and page URLs are sent to Parallel, which performs the search and fetching.
Do not include private data in those arguments.
Each MCP request has a 30-second timeout; the sandbox permits four host suspensions and a 90-second feed.
MCP tool errors propagate to the sandbox, and the context managers close the client and worker pool on exit.

## Local checks

The tests run the sandbox against an in-memory MCP HTTP server and make no live web calls:

```bash
uv run --no-config --script examples/parallel_search/test_main.py
```

They check request URLs, headers and timeouts, result processing, tool errors, and cancellation cleanup.
