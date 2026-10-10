# Plow Creator

Text Plow Creator what agent you want. It asks a question or two, says back what it will build, and puts that agent on one of your own Plow numbers.

This repo is **one image** for both Plow Creator and every agent it builds. Each built agent is a Plow agent on this image whose brain is a setting. It never gets an image of its own:

- **Code** is this image: the Hermes base ([plow-hermes-agent](https://github.com/plow-pbc/plow-hermes-agent)) plus the files in `runtime/`.
- **Definition** is the agent's `definition` setting in Plow, a small JSON text. It is read at every boot.
- **Data** is the agent's home on its own disk. A restart or a definition change keeps it.

An empty `definition` means the agent is Plow Creator itself (`runtime/creator.md`).

## How a definition becomes an agent

1. Plow stores the definition as the agent's `definition` setting. The setting is declared on this image's catalog row and set by a build code or from the dashboard.
2. On boot, `/etc/cont-init.d/10-pas-apply` runs as root before any service starts. It reads `GET $PLOW_API_BASE/v1/agents/me` and writes `/opt/hermes/plow-seed/persona.md` from `agent.settings.definition.value`.
3. The base's `plow-init` then composes `SOUL.md` as the base persona followed by that file, the same way it composes every variant's persona.

A changed definition is a restart: Plow's `PATCH /v1/agents/{uid}/settings` reboots the same VM, so its number, chats and home stay.

An agent never comes up as something it can't confirm it is:
- If Plow doesn't confirm the agent within about two minutes, it boots saying its setup couldn't load.
- If the definition is broken, it boots saying so, with the reason.
- In neither case does it fall back to Plow Creator or to a previous boot's persona.

## The definition: Plow Agent Schema v0

`runtime/pas.py` is the contract. `runtime/creator.md` explains it to the model that writes definitions.

```json
{"pas": 0, "name": "HN Morning",
 "job": "Texts its owner a 3-line Hacker News summary every morning.",
 "instructions": "You send three lines, no links unless asked.",
 "greeting": "Hi, I'm HN Morning. Say 'now' for today's summary."}
```

- Fields are exactly these, and the whole definition is at most 8 KB.
- It holds no backend-specific field. The same definition can later be rendered for other agent runtimes; this image renders it for Hermes.

## Why the reader lives here and not in the base

Only this image takes its brain from data. When the base serves per-agent config itself ([plow-hermes-agent#132](https://github.com/plow-pbc/plow-hermes-agent/issues/132)), `10-pas-apply` is deleted in favour of it.

## Test

```sh
just test
```

## Build and run locally

```sh
docker build -t plow-creator .
docker run --rm -e PLOW_API_BASE=http://<a stub serving /v1/agents/me> plow-creator
```

Without `PLOW_API_BASE`, the container boots as Plow Creator.

## Status

- The image and its definition reader are here.
- Still to come: the Creator's build skill, and the Plow change that turns a definition into a build code ([plow-agents#45](https://github.com/plow-pbc/plow-agents/issues/45)).
