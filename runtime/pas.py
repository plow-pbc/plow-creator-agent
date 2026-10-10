"""Plow Agent Schema v0: the definition every agent Plow Creator builds is made of.

One file, so the Creator's build step and the boot check a definition by the same rules:

- parse() turns a definition string into a checked definition, or raises ValueError
  naming the reason.
- `pas.py apply` runs as root from cont-init, before plow-init. It reads this agent's
  `definition` setting from Plow and writes the persona that plow-init composes into
  SOUL.md.

The definition lives in Plow, in the agent's `definition` setting, and never on this disk.
That makes a restart the update. An empty definition means this agent is Plow Creator
itself.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

MAX_BYTES = 8192
FIELDS = {"pas", "name", "job", "instructions", "greeting"}
REQUIRED = {"pas", "name", "job", "instructions"}

# plow-init composes SOUL.md on every boot from the base persona followed by this file.
PERSONA = "/opt/hermes/plow-seed/persona.md"
CREATOR = "/opt/plow-creator/creator.md"


def _text(source: dict, key: str, limit: int, *, one_line: bool = True, required: bool = True) -> str | None:
    value = source.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    if len(value) > limit:
        raise ValueError(f"{key} is longer than {limit} characters")
    if one_line and "\n" in value.strip():
        raise ValueError(f"{key} must be one line")
    return value.strip()


def parse(raw: str) -> dict:
    """A checked definition, or ValueError with a reason short enough to show the owner."""
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"the definition is larger than {MAX_BYTES} bytes")
    try:
        definition = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("the definition is not valid JSON") from None
    if not isinstance(definition, dict):
        raise ValueError("the definition must be a JSON object")
    # Field names are the owner's text, so a reason quotes at most 40 characters of one.
    if unknown := definition.keys() - FIELDS:
        raise ValueError(f"unknown field {sorted(unknown)[0][:40]!r}")
    if missing := REQUIRED - definition.keys():
        raise ValueError(f"missing field {sorted(missing)[0]!r}")
    if type(definition["pas"]) is not int or definition["pas"] != 0:
        raise ValueError("pas must be 0")
    return {
        "pas": 0,
        "name": _text(definition, "name", 60),
        "job": _text(definition, "job", 300),
        "instructions": _text(definition, "instructions", MAX_BYTES, one_line=False),
        "greeting": _text(definition, "greeting", 300, required=False),
    }


def render(definition: dict) -> str:
    greeting = definition["greeting"] or f"Hi, I'm {definition['name']}. {definition['job']}"
    return (
        f"# {definition['name']}\n\n"
        f"You are {definition['name']}, an agent your owner had Plow Creator build for them.\n"
        f"Your job: {definition['job']}\n\n"
        f"{definition['instructions']}\n\n"
        "## Your first reply\n\n"
        "The first time your owner texts you, even if the text is only a setup code, reply with exactly this:\n\n"
        f"{greeting}\n"
    )


def fallback(reason: str) -> str:
    return (
        "# Agent that could not load its setup\n\n"
        f"This agent's definition could not be used: {reason}.\n\n"
        "To every message, reply in one line that your setup is broken and that your owner can ask "
        "Plow Creator to rebuild you. Do nothing else, and never act as any other agent.\n"
    )


def persona_for(identity: dict | None, creator: str) -> str:
    """The persona for this boot. `identity` is Plow's /v1/agents/me, or None when Plow never confirmed it.

    Never the persona of a previous boot. An agent that cannot learn what it is says so;
    it does not carry on as what it was.
    """
    if identity is None:
        return fallback("Plow did not confirm this agent at boot, and a restart tries again")
    entry = (identity.get("agent") or {}).get("settings", {}).get("definition")
    raw = entry.get("value") if isinstance(entry, dict) else None
    if raw is None or raw == "":
        return creator
    if not isinstance(raw, str):
        return fallback("the definition must be text")
    try:
        return render(parse(raw))
    except ValueError as error:
        return fallback(str(error))


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to wherever it points. plow-init refuses them too."""

    def redirect_request(self, *args, **kwargs):
        return None


def ask_plow(base: str, bearer: str, *, attempts: int = 24, delay: float = 5.0) -> dict | None:
    """Plow's /v1/agents/me, retrying what waiting could fix for about two minutes.

    That covers a network that isn't up yet and a credential that answers 401 for about
    a minute after a rotation (plow-init waits that out too). A 404 or any other 4xx is
    an answer, so it gets no retry.
    """
    opener = urllib.request.build_opener(_RefuseRedirects)
    request = urllib.request.Request(
        base.rstrip("/") + "/v1/agents/me",
        headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
    )
    for attempt in range(attempts):
        try:
            with opener.open(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (401, 403, 429) and error.code < 500:
                return None
        except (OSError, ValueError):
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return None


def write(path: str, text: str) -> None:
    descriptor, staged = tempfile.mkstemp(prefix=".persona.", dir=os.path.dirname(path))
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(text)
    os.chmod(staged, 0o644)
    os.replace(staged, path)


def apply() -> None:
    """Never stops the boot. Any failure still writes a persona that says so."""
    try:
        with open(CREATOR, encoding="utf-8") as source:
            creator = source.read()
        base = os.environ.get("PLOW_API_BASE")
        # On exe.dev the integration in front of PLOW_API_BASE swaps this placeholder for the
        # agent's real credential. Without PLOW_API_BASE (a local run) there is nothing to
        # ask, so the agent is Plow Creator.
        identity = ask_plow(base, os.environ.get("PLOW_AGENT_TOKEN") or "proxied") if base else {}
        persona = persona_for(identity, creator)
    except Exception as error:
        print(f"pas: {type(error).__name__} while choosing the persona", file=sys.stderr)
        persona = fallback("the setup step failed at boot")
    write(PERSONA, persona)
    print(f"pas: persona = {persona.splitlines()[0][2:]}", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:] != ["apply"]:
        sys.exit("usage: pas.py apply")
    try:
        apply()
    except Exception as error:
        print(f"pas: could not write {PERSONA}: {type(error).__name__}", file=sys.stderr)
