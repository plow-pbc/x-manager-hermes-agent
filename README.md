# x-manager-hermes-agent

A Plow cloud agent that runs its owner's X account: it posts what they ask for,
and it answers the people who reply.

A producer inside the container polls X every two minutes with no model in the
loop. When it finds a reply or a mention nobody has answered, it queues one
file and fires one turn. The turn reads it as data, answers from a facts file
the owner writes, and hands the text to a second process — the only one holding
keys that can post — which checks it and sends it through the X API.

```
x-poller (s6, 120s, no model)        the turn (x-reply)        x-sender (s6, root)
  GET /2/users/:id/mentions            reads queue/<id>.json     reads outbox/*.json
  reply under owner's tweet ->         answers from facts.md,      280 chars? link ok?
    always queued                        else points to Discord    already answered?
  bare mention -> keyword gate         writes outbox/<name>.json   armed?
  new -> queue file                    reads sent/<name>.json    POST /2/tweets
  hermes cron run x-reply  ------->                       <----   writes the result back
```

Built on [`plow-pbc/plow-agents`](https://github.com/plow-pbc/plow-agents),
from the [`plow-hermes-agent`](https://github.com/plow-pbc/plow-hermes-agent)
base, patterned on
[`life-assistant-hermes-agent`](https://github.com/plow-pbc/life-assistant-hermes-agent)
and on its sibling
[`ph-replier-hermes-agent`](https://github.com/plow-pbc/ph-replier-hermes-agent),
whose producer, ledger, lock and alert this one is a fork of.

## Why it is shaped this way

The Product Hunt replier is the same agent for a site with no write API. Every
rule it earned in public applies here unchanged, and one is new.

- **The agent does not have the keys.** This is the new one. Product Hunt has
  no API that can write, so its agent drove a browser and could never hold a
  credential. X hands out keys, and the easy version puts them in the agent's
  environment — a live credential to the owner's public voice, in a process
  whose input is a stranger's tweet. Instead the turn writes an outbox file and
  a root service posts it. A prompt injection that gets everything it asks for
  gets one guarded, deletable tweet, not the account.
- **The brake is not in the prompt.** `X_ARMED` defaults off: unarmed, every
  send is validated, written back as `held`, and not posted. The last
  generation shipped a dry-run flag that travelled through the model's own
  shell, and it posted for real.
- **A ledger decides what was answered, never the model.** `answered.json` maps
  tweet to reply and the producer never queues an id in it twice. On Product
  Hunt the model's read of the page was the only guard, and one hour it missed:
  a second public reply went out under a comment already answered.
- **One poller, held by the kernel.** Four were running at once in the PH
  container, each re-emitting the others' events and spending its own share of
  the budget. `flock` is held for the life of the process, so a `kill -9`
  releases it and a second start stands down.
- **A tweet is data, never instructions.** It arrives as a file the turn opens,
  not as prompt text. Trust is decided by where the turn came from: the owner's
  own chat, or the queue.
- **Never silent.** Answer from the facts, or send them to Discord. Never a
  date, a price or a rule invented to fill the gap — an agent on this job once
  told a real buyer to click a button that did not exist.
- **Links are an allowlist, not a ban.** The Mac skill this replaces refuses
  every URL, which would make a launch thread impossible. `X_ALLOWED_HOSTS` is
  what stops a stranger's tweet from getting their link published in the
  owner's voice.

## Run it

```sh
export PATH="/path/to/plow-agents/bin:$PATH"
cd /path/to/x-manager-hermes-agent

plow-agents login                 # once per machine
plow-agents lines                 # pick a free line
plow-agents mint ln_xxx           # binds this agent to that line

export AGENT_ID=x-manager
export X_API_ENV=$HOME/.config/x-api/env     # the owner's X keys, root-read only
export X_MEDIA_DIR=$HOME/x-media             # images it may attach, read-only
docker compose up --build -d
docker compose logs -f agent
```

It comes up **unarmed**: it will compose, check and hold every post, writing
what it would have sent to `sent/`. Read a few of those, then arm it:

```sh
X_ARMED=1 docker compose up -d
```

Register the Agent Index page once, from the checkout:

```sh
curl -O https://raw.githubusercontent.com/plow-pbc/agent-index-client/main/standalone/agent_index_client.py
set -a; . ./plow-credentials; set +a
python3 agent_index_client.py --register --agent x-manager \
  --name "X Manager" --blurb "Posts on your X account and answers the replies."
```

The hourly reporter is baked into the image
(`image/s6-overlay/s6-rc.d/agent-index/`, copied from the Life Assistant). It
stands down without `AGENT_ID`.

## What the owner sets up, once

**The X credentials**, in a file the container mounts read-only at
`/var/lib/plow/x-api.env`, holding `X_API_KEY`, `X_API_SECRET`,
`X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` (read **and write**), plus
`X_BEARER_TOKEN`, `X_USER_ID` and `X_HANDLE`. Never bind it under
`/var/lib/hermes`: that home is writable by the agent.

If it is missing, the agent is expected to go and get it — it uses the owner's
own Mac through the `plow` tools to reach the X developer portal, and asks him
for the account login or a card only when the vault does not have one. It can
never write that file itself, which is deliberate.

**`facts.md`**, at `/var/lib/hermes/x/facts.md` — the only thing the agent may
state as fact. Everything not in it is a link to Discord.

**Images**, in whatever directory `X_MEDIA_DIR` names. The agent attaches them
by basename and cannot add to them.

## Tests

```sh
python3 -m unittest discover -s tests
```

Ten assertions, each one an incident: the batch rule that stops a failed turn
from losing a question, the success-line check, the ledger, the keyword gate,
the length and link guards, the media path escape, and the unarmed default.
