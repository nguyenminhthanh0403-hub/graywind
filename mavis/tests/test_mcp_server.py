import pytest

import mcp_server


@pytest.mark.asyncio
async def test_both_tools_are_registered_with_distinct_descriptions():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}

    assert names == {"ask_graywind", "query_bullion"}

    by_name = {t.name: t for t in tools}
    assert "Graywind" in by_name["ask_graywind"].description
    assert "Bullion" in by_name["query_bullion"].description
    # Both descriptions must be honest that retrieval is merged -- neither
    # tool can see only its own namesake's data.
    assert "merged" in by_name["ask_graywind"].description.lower()
    assert "merged" in by_name["query_bullion"].description.lower()


def test_server_name_is_mavis():
    assert mcp_server.mcp.name == "mavis"
