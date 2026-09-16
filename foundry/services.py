"""The outside services Foundry needs, and how a new user connects each one.

Kept as data so `foundry doctor`, the README and the skills all point at the same links.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

OPENAI_KEYS_URL = "https://platform.openai.com/api-keys"
CLAUDE_CONNECTORS_URL = "https://claude.ai/settings/connectors"

MCP_SERVERS: list[dict[str, str]] = [
    {
        "name": "Higgsfield",
        "needed_for": "generating the video clips in /foundry-build (seedance_2_5)",
        "url": "https://mcp.higgsfield.ai/mcp",
        "host": "mcp.higgsfield.ai",
        "account": "https://higgsfield.ai",
        "cli_name": "higgsfield",
    },
]

_LINE = re.compile(r"^(?P<name>.+?): (?P<url>\S+)(?: \((?P<transport>[^)]*)\))? - (?P<state>.+)$")


def connect_steps(server: dict[str, str]) -> list[str]:
    return [
        f"Connect the {server['name']} MCP server (needed for {server['needed_for']}):",
        f"  1. You need a {server['name']} account with credits: {server['account']}",
        f"  2. In claude.ai open {CLAUDE_CONNECTORS_URL}, choose 'Add custom connector', paste "
        f"{server['url']} and sign in to {server['name']}",
        f"     or, from a terminal: claude mcp add --transport http {server['cli_name']} {server['url']}",
        "  3. Run `foundry doctor` again; it checks the connection with `claude mcp list`",
    ]


def list_mcp(timeout: int = 90) -> list[dict[str, str]] | None:
    """Servers as Claude Code sees them, or None when that cannot be determined."""
    if not shutil.which("claude"):
        return None
    try:
        out = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None
    rows = []
    for line in out.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        state = m.group("state")
        status = ("connected" if "Connected" in state else
                  "needs_auth" if "authentication" in state.lower() else "failed")
        rows.append({"name": m.group("name"), "url": m.group("url"), "status": status, "raw": state})
    return rows


def mcp_status(server: dict[str, str], listed: list[dict[str, str]] | None) -> tuple[str, list[str]]:
    """(doctor status, detail lines) for one required server."""
    if listed is None:
        return "todo", ["Could not ask Claude Code which MCP servers are connected; make sure this one is."] \
            + connect_steps(server)
    match = next((r for r in listed if server["host"] in r["url"]), None)
    if match and match["status"] == "connected":
        return "ok", [f"connected as '{match['name']}' ({match['url']})"]
    if match and match["status"] == "needs_auth":
        return "todo", [f"'{match['name']}' is added but not signed in. Open Claude Code, run /mcp, choose "
                        f"{match['name']} and sign in (or reconnect it at {CLAUDE_CONNECTORS_URL})."]
    if match:
        return "todo", [f"'{match['name']}' is added but not reachable ({match['raw']}). Remove and re-add it:"] \
            + connect_steps(server)[1:]
    return "todo", connect_steps(server)
