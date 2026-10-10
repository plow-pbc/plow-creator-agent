"""Plow Creator's build step: a checked definition becomes a code the owner texts to switch the agent on.

    build.py lines                          the owner's numbers: free, built by me (with its name), mine, or busy
    build.py build NUMBER < definition.json  a code for NUMBER (its name, like Oak) carrying the definition
    build.py show NUMBER                    the definition I last built for NUMBER, to change it

Plow mints a code only for the owner's own message, and redeems it only when the owner texts it to that
number: this script never creates an agent itself. The owner's ask is their newest message in our 1:1 chat.
Stdlib only; PLOW_API_BASE, PLOW_AGENT_TOKEN and PLOW_HOME_CHANNEL come from the environment, as for the
Plow plugin's own scripts.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pas  # noqa: E402

# In the agent's home, so it survives restarts and definition changes; it is mine, not the owner's data.
LEDGER = pathlib.Path(os.environ.get("HERMES_HOME", "/var/lib/hermes")) / "plow-creator" / "builds.json"


def call(method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        os.environ["PLOW_API_BASE"].rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ.get('PLOW_AGENT_TOKEN') or 'proxied'}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"Plow answered {error.code}: {error.read().decode(errors='replace')[:300]}")


def ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text())
    except FileNotFoundError:
        return {}


def numbers() -> list[dict]:
    """Phone lines only; the email mailboxes share these names."""
    return [line for line in call("GET", "/v1/lines")["data"] if line.get("provider_type") == "imessage"]


def number_named(name: str) -> dict:
    line = next((line for line in numbers() if (line.get("display_name") or "").casefold() == name.casefold()), None)
    if line is None:
        sys.exit(f"no number named {name!r}; run `build.py lines`")
    return line


def lines() -> list[dict]:
    mine = call("GET", "/v1/agents/me")["line"]["uid"]
    built = ledger()
    rows = []
    for line in numbers():
        if line["uid"] == mine:
            state = "me"
        elif line.get("agent_uid") and line["uid"] in built:
            state = f"built: {built[line['uid']]['name']}"
        elif line["available"]:
            state = "free"
        else:
            state = "busy"
        rows.append({"name": line["display_name"], "number": line["provider_key"], "state": state})
    return rows


def build(name: str, raw: str) -> dict:
    try:
        definition = pas.parse(raw)
    except ValueError as error:
        sys.exit(f"definition not built: {error}")
    line = number_named(name)
    home = os.environ["PLOW_HOME_CHANNEL"]
    ask = next((m for m in call("GET", f"/v1/chats/{home}/messages?limit=20")["data"] if m["direction"] == "inbound"), None)
    if ask is None:
        sys.exit("no message from your owner to build from")
    answer = call(
        "POST",
        "/v1/auth/agent-invites/opportunities/build",
        {"chat_id": home, "message_id": ask["uid"], "line_uid": line["uid"], "settings": {"definition": raw}},
    )
    built = ledger()
    built[line["uid"]] = {"name": definition["name"], "definition": raw}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(built, indent=1))
    return {"code": answer["code"], "number_name": line["display_name"], "number": answer["number"]}


def show(name: str) -> str:
    entry = ledger().get(number_named(name)["uid"])
    if entry is None:
        sys.exit(f"I have not built anything on {name}")
    return entry["definition"]


if __name__ == "__main__":
    verb, *rest = sys.argv[1:] or ["help"]
    if verb == "lines" and not rest:
        print(json.dumps(lines(), indent=1))
    elif verb == "build" and len(rest) == 1:
        print(json.dumps(build(rest[0], sys.stdin.read())))
    elif verb == "show" and len(rest) == 1:
        print(show(rest[0]))
    else:
        sys.exit(__doc__)
