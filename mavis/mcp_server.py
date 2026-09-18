"""MCP server exposing MAVIS's /ask endpoint as two tools.

Run directly (`python mcp_server.py`) to serve over stdio -- this is what
`claude mcp add` points at. Registration lives outside this repo, in
Claude CLI's own MCP config (see docs/superpowers/plans/2026-09-18-mavis-mcp-wrapper.md
Task 4); this file never touches that config itself.
"""
from mcp.server.mcpserver import MCPServer

import mcp_tools

mcp = MCPServer(name="mavis")

mcp.add_tool(
    mcp_tools.ask_graywind,
    name="ask_graywind",
    description=(
        "Ask about Graywind's own live trading state: positions, tiers, "
        "gates, recent decisions, watchlist. Retrieval is merged with "
        "Bullion's financial-system map server-side, so citations may "
        "include both -- pick this tool when the question is really "
        "about Graywind's trading, not the broader financial system."
    ),
)

mcp.add_tool(
    mcp_tools.query_bullion,
    name="query_bullion",
    description=(
        "Ask about Bullion's audited financial-system map: nodes, links, "
        "causal claims about markets and macro plumbing. Retrieval is "
        "merged with Graywind's own trading-state facts server-side, so "
        "citations may include both -- pick this tool when the question "
        "is really about the financial system, not Graywind's trading."
    ),
)


if __name__ == "__main__":
    mcp.run()
