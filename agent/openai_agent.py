"""Demo agent: OpenAI tool calling + the connector tools.

  python -m agent.openai_agent "Which products are out of stock?"
  python -m agent.openai_agent            # interactive
"""
import json
import sys
import time

import requests

from connector import config
from connector.tools import call_tool, openai_spec

SYSTEM = (
    "You are a read-only operations assistant for a WooCommerce store. Use the tools to answer "
    "questions about orders and inventory. You cannot modify anything (no refunds, edits, emails). "
    "Never guess IDs or numbers - call a tool. Customer contact details are masked; do not try to "
    "recover them. Be concise and state when results are paginated or truncated."
)


def openai_chat(messages, tools):
    key = config.openai_key()
    if key.startswith("PASTE_"):
        raise SystemExit("Set OPENAI_API_KEY in connector/config.py (or the OPENAI_API_KEY env var).")
    for attempt in range(4):
        r = requests.post(config.OPENAI_URL, timeout=60,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": config.OPENAI_MODEL, "messages": messages, "tools": tools,
                                "tool_choice": "auto", "temperature": 0})
        if r.status_code in (429, 500, 502, 503):
            time.sleep(float(r.headers.get("retry-after", 1 + attempt)))   # rate limit / transient error
            continue
        if not r.ok:
            raise SystemExit(f"OpenAI error {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]
    raise RuntimeError("OpenAI request failed repeatedly")


def run_agent(question, chat=openai_chat, max_steps=6, verbose=True, history=None):
    messages = history if history is not None else []
    if not messages:
        messages.append({"role": "system", "content": SYSTEM})
    messages.append({"role": "user", "content": question})
    tools = openai_spec()
    for _ in range(max_steps):
        msg = chat(messages, tools)
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v is not None})
        if not msg.get("tool_calls"):
            return msg.get("content", "")
        for tc in msg["tool_calls"]:
            name, raw = tc["function"]["name"], tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except ValueError:
                args = {}
            if verbose:
                print(f"  [tool] {name}({raw})", file=sys.stderr)
            out = json.dumps(call_tool(name, args), default=str)[:6000]
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
    return "Stopped: too many tool-call steps."


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(run_agent(" ".join(sys.argv[1:])))
    else:
        hist = []
        while True:
            try:
                q = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q:
                print(run_agent(q, history=hist))
