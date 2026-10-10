"""The Creator's build step against a stub Plow: what it asks for, and what it refuses to send."""
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "runtime"))
import build  # noqa: E402

DEFINITION = json.dumps({"pas": 0, "name": "HN Morning", "job": "Texts a summary.", "instructions": "Three lines."})
LINES = [
    {"uid": "ln_p1", "provider_type": "imessage", "provider_key": "+15550000001", "display_name": "Willow", "agent_uid": "a1", "available": False},
    {"uid": "ln_p6", "provider_type": "imessage", "provider_key": "+15550000006", "display_name": "Oak", "agent_uid": None, "available": True},
    {"uid": "ln_p7", "provider_type": "imessage", "provider_key": "+15550000007", "display_name": "Cedar", "agent_uid": "a7", "available": False},
    {"uid": "ln_p8", "provider_type": "imessage", "provider_key": "+15550000008", "display_name": "Maple", "agent_uid": "a8", "available": False},
    {"uid": "ln_e_oak", "provider_type": "email", "provider_key": "oak@example.com", "display_name": "Oak", "agent_uid": None, "available": False},
]
MESSAGES = [  # newest first, as Plow lists them
    {"uid": "msg_out", "direction": "outbound"},
    {"uid": "msg_ask", "direction": "inbound"},
    {"uid": "msg_old", "direction": "inbound"},
]


class Plow(BaseHTTPRequestHandler):
    posted: list = []

    def answer(self, body):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.path == "/v1/agents/me":
            self.answer({"line": {"uid": "ln_p1"}})
        elif self.path == "/v1/lines":
            self.answer({"data": LINES})
        elif self.path == "/v1/chats/cht_home/messages?limit=20":
            self.answer({"data": MESSAGES})
        else:
            self.send_error(404)

    def do_POST(self):
        Plow.posted.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.answer({"code": "BX7Q2", "line_uid": "ln_p6", "number": "+1 555-000-0006", "expires_at": "2026-10-11T00:00:00Z"})

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def plow(tmp_path, monkeypatch):
    Plow.posted = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Plow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("PLOW_API_BASE", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_home")
    monkeypatch.setattr(build, "LEDGER", tmp_path / "builds.json")
    yield
    server.shutdown()


def test_build_asks_plow_for_a_code_on_the_owners_newest_message_and_remembers_it():
    assert build.build("oak", DEFINITION) == {"code": "BX7Q2", "number_name": "Oak", "number": "+1 555-000-0006"}
    assert Plow.posted == [
        (
            "/v1/auth/agent-invites/opportunities/build",
            {"chat_id": "cht_home", "message_id": "msg_ask", "line_uid": "ln_p6", "settings": {"definition": DEFINITION}},
        )
    ]
    assert build.show("Oak") == DEFINITION


def test_lines_tell_free_numbers_from_mine_and_my_builds():
    build.LEDGER.write_text(json.dumps({"ln_p8": {"name": "Bill Buddy", "definition": DEFINITION}}))
    assert [(row["name"], row["state"]) for row in build.lines()] == [
        ("Willow", "me"),
        ("Oak", "free"),
        ("Cedar", "busy"),
        ("Maple", "built: Bill Buddy"),
    ]


@pytest.mark.parametrize(
    ("number", "raw", "reason"),
    [
        ("Oak", '{"pas": 0, "name": "x"}', "missing field"),
        ("Pine", DEFINITION, "no number named 'Pine'"),
    ],
)
def test_nothing_reaches_plow_without_a_valid_definition_and_a_real_number(number, raw, reason):
    with pytest.raises(SystemExit, match=reason):
        build.build(number, raw)
    assert Plow.posted == []
