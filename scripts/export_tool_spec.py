"""Regenerate mcp_tool_spec.json and openai_tool_spec.json from the registry."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from connector.tools import mcp_spec, openai_spec  # noqa: E402

(root / "mcp_tool_spec.json").write_text(json.dumps({"server": "woocommerce-readonly", "tools": mcp_spec()}, indent=2))
(root / "openai_tool_spec.json").write_text(json.dumps(openai_spec(), indent=2))
print("wrote mcp_tool_spec.json, openai_tool_spec.json")
