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
RUNNING = json.dumps({"pas": 0, "name": "Bill Buddy", "job": "Tracks bills.", "instructions": "Short replies."})
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
    seen: list = []
    redirect_lines = False

    def answer(self, body):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        Plow.seen.append(self.path)
        if self.path == "/v1/lines" and Plow.redirect_lines:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/followed")
            self.end_headers()
        elif self.path == "/v1/agents/me":
            self.answer({"line": {"uid": "ln_p1"}})
        elif self.path == "/v1/lines":
            self.answer({"data": LINES})
        elif self.path == "/v1/chats/cht_home/messages?limit=20":
            self.answer({"data": MESSAGES})
        elif self.path == f"{build.BUILD}/ln_p8":  # the agent I built on Maple; Cedar runs something else
            self.answer({"settings": {"definition": RUNNING, "verbose_output": False}})
        else:
            self.send_error(404)

    def do_POST(self):
        Plow.posted.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.answer({"code": "BX7Q2", "line_uid": "ln_p6", "number": "+1 555-000-0006", "expires_at": "2026-10-11T00:00:00Z"})

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def plow(monkeypatch):
    Plow.posted, Plow.seen, Plow.redirect_lines = [], [], False
    server = ThreadingHTTPServer(("127.0.0.1", 0), Plow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("PLOW_API_BASE", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_home")
    yield
    server.shutdown()


def test_build_asks_plow_for_a_code_on_the_owners_newest_message():
    assert build.build("oak", DEFINITION) == {"code": "BX7Q2", "number_name": "Oak", "number": "+1 555-000-0006"}
    assert Plow.posted == [
        (build.BUILD, {"chat_id": "cht_home", "message_id": "msg_ask", "line_uid": "ln_p6", "settings": {"definition": DEFINITION}})
    ]


def test_a_change_starts_from_what_the_agent_runs_now():
    assert build.show("Maple") == RUNNING
    with pytest.raises(SystemExit, match="no agent I built runs on Cedar"):
        build.show("Cedar")


def test_lines_tell_free_numbers_from_mine_and_my_builds():
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


def test_a_redirect_is_refused_so_the_credential_stays_with_plow():
    Plow.redirect_lines = True
    with pytest.raises(SystemExit, match="Plow answered 302"):
        build.lines()
    assert "/followed" not in Plow.seen
