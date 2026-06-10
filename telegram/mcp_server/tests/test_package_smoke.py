from codex_telegram import server


def test_server_exports_mcp_instance():
    assert server.mcp.name == "telegram"
