# X Manager

A Hermes agent that answers replies on your X account through Plow. It composes
from your facts, sends jokes a short response without a link, and uses a separate
root service to validate and publish through the X API.

**[Install on your own accounts — complete guide](docs/INSTALL.md)**

Start there even if you have never used Plow or the X developer API. The guide
covers account activation, your own credentials, a fresh Docker home, an unarmed
test, public replies, and per-installation Agent Index reporting.

[Agent Index page](https://aiworthusing.com/agent-index/danedelattre-x-manager)

## How it works

`x-poller` reads mentions and queues eligible comments. A Hermes `x-reply` turn
writes an outbox request. `x-sender` checks its length, allowed links, prior reply
ledger and the operator-controlled `X_ARMED` setting before posting. Write keys
are mounted outside the agent's home and are not handed to the model process.

Replies under the owner's posts are eligible; bare mentions are keyword-filtered.
The default persona is focused on Plow/hackathon questions, with Discord as the
fallback for unknown serious questions. Set your own facts and adapt the scope
before using it for an unrelated business.

The image builds from the digest-pinned
[Plow Hermes base](https://github.com/plow-pbc/plow-hermes-agent), using the
[Plow CLI](https://github.com/plow-pbc/plow-agents) and the
[Life Assistant example](https://github.com/plow-pbc/life-assistant-hermes-agent).
The hourly reporter sends day/model token counts to the existing publisher page;
each installer provisions a separate reporting identity without re-registering it.

## Development checks

```sh
python3 -m unittest discover -s tests
python3 -m compileall -q x-shared/scripts
```

`docs/context-for-next-agent.md` is historical maintainer handoff material. Its
references to existing credentials on a particular Mac are not installation
instructions. Use [the installation guide](docs/INSTALL.md) instead.
