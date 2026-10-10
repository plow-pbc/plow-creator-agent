# plow-creator-agent -- what only this agent has.

[doc("Run the suite: the definition contract and the boot step that applies it.")]
test:
    uv run --no-project --python 3.13 --with pytest==8.4.2 pytest -q tests/
