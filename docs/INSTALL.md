# Install the X Hackathon agent on your own accounts

This guide installs a separate Hermes agent that answers replies on **your X
account**, using **your Plow account and line**. The AI Worth Using x Hermes hackathon
context comes bundled: dates, prizes, submission requirements, support links,
and the top-10 qualification followed by the Plow Team vote. You do not need Daniel's Mac,
SSH access, tokens, phone number, or X developer app.

Allow time to activate Plow and obtain X developer access. The software starts
with public posting disabled. You will review a held reply before enabling it.

## 1. Choose the computer that will run the agent

Use a Linux x86-64 server that can stay online. This is the tested platform for
this image. Install [Docker Engine with Compose](https://docs.docker.com/get-started/get-docker/),
Git, Python 3, and curl. Run these commands on that server, in a Bash-compatible
terminal. If you use a laptop to manage a server, all files and commands below
belong on the server, including the credential files.

```sh
docker info
docker compose version
git --version
python3 --version
curl --version
```

Docker must work as your current user. The pinned base image is amd64; this guide
has not verified Apple Silicon emulation or a native ARM build. A Mac is not
required for X replies: this agent uses the X API, not browser automation or Latch.

You also need:

- Your own phone capable of completing Plow's text-message activation.
- Your own X account and developer app with read/write access.
- API access and sufficient X credits for reads and posts. Check current terms
  and charges in [X's developer console](https://console.x.com/). Inference uses
  Plow and is subject to your Plow account's access and billing.

## 2. Download fresh copies

Choose a new directory for this installation. Do not copy somebody else's
running home volume, `.env`, `plow-credentials`, or reply ledger.

```sh
mkdir -p "$HOME/plow-projects"
cd "$HOME/plow-projects"
git clone https://github.com/plow-pbc/plow-agents.git
git clone https://github.com/plow-pbc/x-manager-hermes-agent.git
export PATH="$HOME/plow-projects/plow-agents/bin:$PATH"
cd "$HOME/plow-projects/x-manager-hermes-agent"
```

Run the rest of the commands from this agent directory. In a new terminal,
repeat the `export PATH` and `cd` commands. An old Plow CLI may call obsolete
endpoints; use the fresh checkout above.

## 3. Activate your own Plow account and choose a line

```sh
plow-agents login
```

The command prints a message and destination number. Send **that exact message
from your own phone**, then wait for the command to finish. This identifies your
account. Do not reuse activation codes or numbers from screenshots or this
project's development history.

```sh
plow-agents lines
```

If your account has no assistant line yet, run:

```sh
plow-agents login --new-line
plow-agents lines
```

Complete the new activation message if requested. Select a line marked `free`.
Replace `ln_YOUR_FREE_LINE` below with its actual ID:

```sh
plow-agents mint ln_YOUR_FREE_LINE
```

This creates `./plow-credentials` with mode 600. Keep it private. Mint **before**
starting Docker, otherwise a missing bind source can become a directory.

If every line is occupied, stop here and decide which of **your own** agents you
want to retire. `plow-agents revoke ln_LINE_TO_RETIRE` releases a self-hosted
agent's line; managed agents are removed in Plow. Do not delete all your agents
as an installation step. See the [Plow CLI guide](https://github.com/plow-pbc/plow-agents#develop-an-agent-locally).

## 4. Create your own X developer app and credentials

Sign into [console.x.com](https://console.x.com/) with the X account the agent
will operate. Complete developer enrollment and create an app describing your
use case. Configure **OAuth 1.0a Read and write** permissions, then generate the
API key/secret and the user access token/secret. If you change permissions after
issuing user tokens, re-authorize/regenerate those user tokens. Also generate
the app's bearer token. OAuth 2.0 Client ID/Secret are not substitutes for the
OAuth 1.0a credentials this implementation uses.

Follow X's current [getting access](https://docs.x.com/x-api/getting-started/getting-access)
and [app configuration](https://docs.x.com/fundamentals/developer-apps) instructions;
console labels can change. This guide uses tokens for your own account. Operating
a different person's account requires that person's OAuth authorization.

Create a private file **outside the checkout**:

```sh
umask 077
mkdir -p "$HOME/.config/x-manager"
export X_API_ENV="$HOME/.config/x-manager/x-api.env"
touch "$X_API_ENV"
chmod 600 "$X_API_ENV"
nano "$X_API_ENV"
```

Use your preferred text editor if `nano` is unavailable. Save these names with
**your actual values**, one per line, with no quotes, spaces around `=`, or
`export` prefixes. Never paste secret values into Git, a public issue, or chat.

```dotenv
X_API_KEY=YOUR_APP_API_KEY
X_API_SECRET=YOUR_APP_API_SECRET
X_ACCESS_TOKEN=YOUR_USER_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET=YOUR_USER_ACCESS_TOKEN_SECRET
X_BEARER_TOKEN=YOUR_APP_BEARER_TOKEN
X_USER_ID=
X_HANDLE=YOUR_HANDLE_WITHOUT_AT
```

| Name | Purpose |
| --- | --- |
| `X_API_KEY`, `X_API_SECRET` | Sign requests for your developer app; required. |
| `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` | Publish as your authorized account; required. |
| `X_BEARER_TOKEN` | Read mentions; required. |
| `X_USER_ID` | Numeric account ID; required at runtime, filled by the next check. |
| `X_HANDLE` | Reply URLs; optional at runtime, used here to verify the intended account. |

The following check authenticates **without posting**, verifies the handle,
records your numeric ID, and saves the current mentions cursor so an initial
installation does not replay old comments. Run it once for this fresh install:

```sh
mkdir -p .install media
chmod 755 media
python3 - <<'PY'
import json, os, pathlib, sys, urllib.error, urllib.request
sys.path.insert(0, 'x-shared/scripts')
from x_send import oauth_header, read_env
path = pathlib.Path(os.environ['X_API_ENV'])
keys = read_env(path)
required = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN',
            'X_ACCESS_TOKEN_SECRET', 'X_BEARER_TOKEN', 'X_HANDLE']
missing = [name for name in required if not keys.get(name)]
if missing:
    raise SystemExit('Missing values: ' + ', '.join(missing))
def get(url, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit('X API HTTP ' + str(e.code) + '; fix access before continuing.')
url = 'https://api.x.com/2/users/me'
user = get(url, {'Authorization': oauth_header('GET', url, keys)})['data']
if user['username'].lower() != keys['X_HANDLE'].lstrip('@').lower():
    raise SystemExit('The access token belongs to a different X handle; stop and correct it.')
lines = [line for line in path.read_text().splitlines() if not line.startswith('X_USER_ID=')]
path.write_text('\n'.join(lines) + '\nX_USER_ID=' + user['id'] + '\n')
path.chmod(0o600)
mentions = get('https://api.x.com/2/users/' + user['id'] + '/mentions?max_results=5',
               {'Authorization': 'Bearer ' + keys['X_BEARER_TOKEN']})
ids = [row['id'] for row in mentions.get('data', [])]
state = {'since_id': max(ids, key=int)} if ids else {}
pathlib.Path('.install/poller-state.json').write_text(json.dumps(state))
print('Verified @' + user['username'] + '; mentions readable; nothing posted.')
PY
```

Resolve errors before continuing. HTTP 401 usually means invalid credentials;
403 requires checking account/app permissions and endpoint eligibility; 402
requires checking billing/access; 429 means rate limited. Inspect the current
console and API response, not old saved account-status notes.

## 5. Configure this installation — hackathon context is included

```sh
cat > .env <<EOF_ENV
AGENT_ID=danedelattre-x-manager
X_ARMED=0
X_API_ENV=$X_API_ENV
X_MEDIA_DIR=$PWD/media
POLL_SEC=15
EOF_ENV
chmod 600 .env
```

The shared [hackathon facts](../runtime/facts.md) are included in the image and
appear at `/var/lib/hermes/x/facts.md` in a new home volume. Teammates do not
need to re-enter event details or copy the author's files. Read the bundled facts
to see exactly what the agent knows. Unknown serious questions go to the support
Discord; jokes receive a short answer without a link.

All replies under your own posts are eligible; bare mentions are keyword-filtered.
You can set comma-separated `X_KEYWORDS` in `.env` for your topic. If you allow a
new link destination, also set `X_ALLOWED_HOSTS` to the exact allowed domains.

Keep the `media` directory empty unless you want to provide your own images for
posts. Paths in `.env` must be absolute paths on the Docker host, not paths on
another laptop. Avoid a `~` prefix: Compose does not expand it as your home.

`AGENT_ID` is the **software's existing Agent Index page**, not your X handle,
Plow line ID, or personal installation ID. Keep `danedelattre-x-manager` when
installing this agent. Each installation gets its own reporting identity below.

## 6. Build and initialize a new home

```sh
docker compose config --quiet
BASE_IMAGE=$(awk '/^FROM / {print $2; exit}' Dockerfile)
docker pull "$BASE_IMAGE"
docker compose build
```

The explicit pull works around registries rejecting BuildKit's metadata lookup.
The Dockerfile checks the pinned reporter's checksum. On Linux, if the reporter
download fails with a bridge-network HTTP 503, retry with:

```sh
docker build --network host -t x-manager-hermes-agent-agent .
```

That tag assumes the clone directory above is `x-manager-hermes-agent` and you
have not overridden the Compose project name. Fix connectivity rather than
removing the checksum or substituting an unreviewed download.

Before starting the gateway, seed your fresh mentions cursor into the new
volume. The image already supplies the hackathon facts. This checks they exist
and refuses to overwrite an existing polling cursor:

```sh
docker compose run --rm --no-deps --entrypoint /bin/sh \
  -v "$PWD/.install:/install:ro" agent -c '
  set -eu
  test -s /var/lib/hermes/x/facts.md
  test ! -e /var/lib/hermes/x/poller-state.json
  install -o 10000 -g 10000 -m 0600 /install/poller-state.json /var/lib/hermes/x/poller-state.json
'
```

Now create a reporting key for **your installation**:

```sh
docker compose run --rm --no-deps \
  --entrypoint /opt/hermes/.venv/bin/python3 \
  agent /opt/plow/x-shared/scripts/setup_index.py
```

Expect a success message. This authenticates with your Plow credential and stores
a scoped key for usage and stories in your new home volume. It does **not** claim or edit the
publisher's Agent Index page. Repeating it preserves existing valid state; if it
reports corrupt state, stop and resolve that error rather than deleting it.

Do not run `--register --agent danedelattre-x-manager`: registration/editing of
that page is the publisher's job and another account will be refused. The hourly
reporter publishes day/model token counts, not prompts or conversation text.

## 7. Start with public posting disabled

```sh
docker compose up -d --no-build
docker compose ps
docker compose logs --tail 100 agent
```

Expect `plow-init: configured ...`, one `x-reply` job, and services running:

```sh
docker compose exec -T agent /bin/sh -c '
for service in hermes-gateway x-poller x-sender agent-index; do
  /command/s6-svstat /run/service/$service
done'
```

Text **the line you selected in step 3** from your own phone to test Plow chat.
On X, create a post on **your account** and have a different account reply to it.
Replies from your own account are deliberately ignored. Use a new comment made
after step 4; older comments were excluded by the initial cursor.

Inspect the proposed response:

```sh
docker compose exec -T --user 10000 agent /bin/sh -c \
  'find /var/lib/hermes/x/sent -name "*.json" -exec cat {} \;'
```

A result with `"status": "held"` means the sender validated it and did not post.
Check the text and the `reply_to` ID. Wait for the corresponding cron run to
finish before recreating the container:

```sh
docker compose exec -T --user 10000 \
  -e HOME=/var/lib/hermes -e HERMES_HOME=/var/lib/hermes \
  agent /opt/hermes/bin/hermes cron runs --limit 5
```

A healthy container alone is not proof that a reply was generated. Diagnose an
empty `sent` directory using the service logs before enabling public posting.

## 8. Enable replies and verify a real post

When the held response is correct and its run has completed, edit `.env`, change
`X_ARMED=0` to `X_ARMED=1`, then apply it:

```sh
nano .env
docker compose up -d --no-build
```

The held queue item remains unanswered. Arming does not automatically replay it;
run the queue explicitly with the same runtime credentials as the gateway:

```sh
docker compose exec -T agent \
  /usr/bin/env PATH=/command:/usr/local/bin:/usr/bin:/bin \
  /command/with-contenv /command/s6-setuidgid hermes \
  /usr/bin/env HOME=/var/lib/hermes HERMES_HOME=/var/lib/hermes \
  /opt/hermes/bin/hermes cron run x-reply
```

Expect a completed run and a `sent` result with an X URL. Open that URL and verify
that it is a reply from your account to the intended comment. Check that the
queue item disappears and the reply ledger records the mapping:

```sh
docker compose exec -T --user 10000 agent /bin/sh -c \
  'cat /var/lib/hermes/x/answered.json; ls /var/lib/hermes/x/queue'
```

Finally, have the other account send **another new comment**. It should be picked
up and answered automatically, without a manual queue run. That is the final
installation check: Plow chat works, the sender posts, and polling triggers a
real reply once. Keep the server and Docker running.

## Operation and troubleshooting

- **Pause:** `docker compose stop`. It keeps the home and ledger. To compose
  without publishing, set `X_ARMED=0` and recreate the container after the active
  run finishes.
- **Keep state:** do not use `docker compose down -v` during ordinary updates.
  It deletes the home, including the deduplication ledger and reporter identity.
  Keep one container/home per X account to avoid duplicate responders.
  Bundled facts initialize new volumes; rebuilding does not overwrite an
  existing volume's facts. Apply organizer updates explicitly to an existing
  installation after reviewing any local corrections.
- **No keys / HTTP 401:** check the mounted file on the Docker host, the exact
  variable names, and whether the tokens are current. Never print the key file
  into logs. The agent process must not be able to read the write credentials.
- **No reply:** check `x-poller` and `x-sender`, the `x-reply` job, the fresh
  comment's age, and whether it is a reply under your own post. Bare mentions
  outside the configured keywords are ignored. The initial lookback limit is
  six hours; this is not an all-history inbox importer.
- **"Job is already being fired" after a forced stop:** check cron execution
  history. This pinned Hermes version can leave a stale fire claim after an
  interrupted run. Do not repeatedly recreate the container or resend a possibly
  published reply. Verify the execution and X outcome before repairing that
  interrupted job; seek maintainer help if you cannot establish either.
- **Reporter cannot find `state.db` on first boot:** the gateway may still be
  creating it. The reporter retries hourly. Persistent errors or an Index 409
  require checking step 6, not claiming a different publisher's page.
- **Retire this installation:** stop it, run `plow-agents revoke` from this
  checkout to release its line, and retain the volume until you intentionally
  choose to delete its data.

This guide's runtime flow was exercised on Linux amd64. Automated tests cover
the sender's held mode, duplicate guard, and installer-key flow; another person's
paid X account or Apple Silicon host was not available for end-to-end testing.
