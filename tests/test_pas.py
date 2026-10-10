"""The definition contract and the boot step that applies it."""
import json
import os
import pathlib
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "runtime"))
import pas  # noqa: E402

CREATOR = (pathlib.Path(__file__).resolve().parent.parent / "runtime" / "creator.md").read_text()
DEFINITION = {
    "pas": 0,
    "name": "HN Morning",
    "job": "Texts its owner a 3-line Hacker News summary every morning.",
    "instructions": "You send three lines, no links unless asked.",
    "greeting": "Hi, I'm HN Morning. First summary tomorrow 8 AM PT, or say 'now'.",
    "schedule": [{"cron": "0 8 * * *", "prompt": "Send today's summary."}],
}


def identity(value):
    return {"agent": {"settings": {"definition": {"type": "string", "title": "Agent definition", "value": value}}}}


def test_definition_becomes_the_persona():
    persona = pas.persona_for(identity(json.dumps(DEFINITION)), CREATOR)
    for text in ("# HN Morning", DEFINITION["job"], DEFINITION["instructions"], DEFINITION["greeting"]):
        assert text in persona
    assert pas.parse(json.dumps(DEFINITION))["schedule"] == [
        {"cron": "0 8 * * *", "prompt": "Send today's summary.", "tz": "America/Los_Angeles"}
    ]


@pytest.mark.parametrize("settings", [identity(""), identity(None), {"agent": {"settings": {}}}, {}])
def test_no_definition_is_plow_creator(settings):
    assert pas.persona_for(settings, CREATOR) == CREATOR


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("{not json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        (json.dumps({**DEFINITION, "model": "x"}), "unknown field 'model'"),
        (json.dumps({k: v for k, v in DEFINITION.items() if k != "job"}), "missing field 'job'"),
        (json.dumps({**DEFINITION, "pas": True}), "pas must be 0"),
        (json.dumps({**DEFINITION, "name": "two\nlines"}), "name must be one line"),
        (json.dumps({**DEFINITION, "instructions": "x" * 9000}), "larger than 8192 bytes"),
        (json.dumps({**DEFINITION, "schedule": [{"cron": "@daily", "prompt": "p"}]}), "5 numeric fields"),
        (json.dumps({**DEFINITION, "schedule": [{"cron": "0 8 * * *", "prompt": "p", "tz": "$(id)"}]}), "tz must be"),
        (json.dumps({**DEFINITION, "schedule": [{"cron": "0 8 * * *", "prompt": "p"}] * 6}), "at most 5 jobs"),
    ],
)
def test_bad_definition_says_so_and_never_becomes_creator(raw, reason):
    persona = pas.persona_for(identity(raw), CREATOR)
    assert reason in persona
    assert persona.startswith("# Agent that could not load its setup")


def test_plow_silent_is_never_creator_nor_a_previous_persona():
    persona = pas.persona_for(None, CREATOR)
    assert persona.startswith("# Agent that could not load its setup") and "did not confirm" in persona


class Plow(BaseHTTPRequestHandler):
    answers: list = []
    seen: list = []

    def do_GET(self):
        Plow.seen.append((self.path, self.headers.get("Authorization")))
        code, body = Plow.answers.pop(0) if Plow.answers else (200, identity(""))
        self.send_response(code)
        if code in (301, 302):
            # Back to this server, so a followed redirect shows up in `seen`.
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/followed")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def plow():
    Plow.answers, Plow.seen = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Plow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_boot_writes_the_persona_from_plow(plow, tmp_path, monkeypatch):
    Plow.answers = [(503, {}), (200, identity(json.dumps(DEFINITION)))]
    monkeypatch.setattr(pas, "PERSONA", str(tmp_path / "persona.md"))
    monkeypatch.setattr(pas, "CREATOR", str(pathlib.Path(__file__).resolve().parent.parent / "runtime" / "creator.md"))
    monkeypatch.setattr(pas.time, "sleep", lambda _: None)
    monkeypatch.setenv("PLOW_API_BASE", plow)
    monkeypatch.delenv("PLOW_AGENT_TOKEN", raising=False)
    pas.apply()
    written = tmp_path / "persona.md"
    assert written.read_text().startswith("# HN Morning")
    assert stat.S_IMODE(os.stat(written).st_mode) == 0o644
    # Retried the 503; the placeholder is what the exe.dev integration swaps for the real token.
    assert Plow.seen == [("/v1/agents/me", "Bearer proxied")] * 2


def test_boot_refuses_a_redirect(plow):
    Plow.answers = [(302, {})]
    assert pas.ask_plow(plow, "proxied", attempts=1) is None
    assert len(Plow.seen) == 1
