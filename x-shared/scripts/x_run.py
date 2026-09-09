#!/usr/bin/env python3
"""x_run.py — the container's X producer.

Same shape as the Product Hunt replier's producer, and for the same reasons:
a plain-Python poller with no model in the loop, a queue file per event, one
Hermes turn fired only when a real event exists, and a persisted ledger that
decides what was already answered.

What X changes is the send path, and only that. Product Hunt has no write API,
so its agent drives a browser on the owner's Mac. X does have one, so nothing
here needs a browser or the owner's hands. The credential does NOT come with
that convenience: see x_send.py for where the keys live and why the agent
cannot read them.

Two kinds of inbound, deliberately not treated alike:

  a reply under one of the owner's own tweets   always queued
  a bare mention of the owner                   keyword gate

A live pass over @danedelattre's mentions found 21 of them and zero about the
hackathon -- crypto pump spam and old launch chatter. But somebody answering
the launch thread is not a mention, it is a conversation the owner started, and
a keyword gate there would drop the questions this agent exists to answer. One
request tells the two apart: a mention carrying `referenced_tweets.replied_to`
whose author is the owner is a reply to him.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERMES = os.environ.get("HERMES_BIN", "/opt/hermes/bin/hermes")
# The registered cron job whose prompt is "work the X queue". The poller does
# not compose a prompt: it fires a job somebody reviewed.
JOB = os.environ.get("X_JOB", "x-reply")
HOME = pathlib.Path(os.environ.get("X_STATE_DIR", "/var/lib/hermes/x"))
QUEUE = pathlib.Path(os.environ.get("X_QUEUE", str(HOME / "queue")))
# tweet_id -> reply_id, every mention this agent has ever answered. On Product
# Hunt the model's read of the page was the only guard against a re-queued
# comment, and it missed once, in public. A file is not a judgement call.
LEDGER = pathlib.Path(os.environ.get("X_LEDGER", str(HOME / "answered.json")))
STATE = pathlib.Path(os.environ.get("X_STATE", str(HOME / "poller-state.json")))
# One poller, structurally. Four were running at once inside the PH container
# because every restart left the old process alive; each re-emitted the others'
# events and spent its own share of the API budget. The lock is held for the
# life of the process and released by the kernel, which is what makes it
# survive a kill -9 the way a pidfile does not.
LOCK = pathlib.Path(os.environ.get("X_LOCK", str(HOME / "poller.lock")))
# What `hermes cron run` prints when the turn actually ran. It exits 0 either
# way, so this string is the only thing separating a turn from a failure.
OK_LINE = os.environ.get("X_OK_LINE", "Ran now: succeeded.")
# A reply here is an API call, not ninety browser round-trips, so it does not
# need the PH replier's 15 minutes -- but a turn that reads the thread first
# still takes minutes, and a cap that fires mid-run abandons it "unknown".
RUN_TIMEOUT_S = int(os.environ.get("X_RUN_TIMEOUT_S", "600"))
# Still queued this long after it arrived is stuck, not busy. A cron turn has
# no live adapter for the owner's chat, so its own report reaches a file nobody
# opens; this is the only path out of the container that reaches a person.
ALERT_AFTER_S = int(os.environ.get("X_ALERT_AFTER_S", "600"))
# 120s, not the PH replier's 30s. X's user-context mention timeline allows far
# fewer requests per 15 minutes than Product Hunt's point budget, and a mention
# is not a launch-day comment race. 15min/120s = 7 or 8 requests a window.
POLL_SEC = int(os.environ.get("POLL_SEC", "120"))
# An event older than this is history, not a question waiting on us: on first
# boot the mentions timeline hands back a backlog nobody wants answered now.
EVENT_TTL_S = int(os.environ.get("X_EVENT_TTL_S", "21600"))
UNTIL = os.environ.get("X_UNTIL", "").strip()
ENV_FILE = pathlib.Path(os.environ.get("X_API_ENV", "/var/lib/plow/x-api.env"))

CHAT_UID = os.environ.get("PLOW_HOME_CHANNEL", "")
API_BASE = os.environ.get("PLOW_API_BASE", "https://api.plow.co").rstrip("/")
PLOW_TOKEN = os.environ.get("PLOW_AGENT_TOKEN", "")

# ponytail: a keyword allowlist misses a bare mention phrased with none of
# these words. The upgrade path is to let the turn classify instead of the
# poller -- affordable only once mention volume is small enough that firing a
# turn per spam tweet is not the cost. Replies to the owner's own tweets do not
# go through this gate at all, which is where the real questions arrive.
KEYWORDS = [k for k in os.environ.get("X_KEYWORDS", "").split(",") if k] or [
    "hackathon", "plow", "latch", "agent index", "agentindex", "aiworthusing",
    "ai worth using", "luma", "kickoff", "leaderboard", "submission", "submit",
    "deadline", "prize", "hermes", "compete", "participate", "enter the",
    "sign up", "register", "rules", "judg",
]

_lock_handle = None


def claim_the_lock() -> bool:
    """True if this process is the poller. False means one already is."""
    global _lock_handle
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    _lock_handle = open(LOCK, "a+")          # kept open on purpose: closing frees it
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _lock_handle.seek(0)
        holder = _lock_handle.read().strip() or "unknown"
        print(f"[x-run] another poller already holds {LOCK} (pid {holder}); "
              "standing down rather than double-polling", file=sys.stderr)
        return False
    _lock_handle.seek(0)
    _lock_handle.truncate()
    _lock_handle.write(str(os.getpid()))
    _lock_handle.flush()
    return True


def read_env(path: pathlib.Path) -> dict:
    """KEY=VALUE without sourcing. These files hold unquoted values that break
    `source`, and sourcing a whole file to read two names is a bad trade."""
    out = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def credentials() -> dict:
    """The read-side keys. Only the bearer and the owner's user id are used
    here; posting happens in x_send.py, which is the only thing that touches
    the OAuth1 secrets."""
    env = dict(read_env(ENV_FILE))
    for name in ("X_BEARER_TOKEN", "X_USER_ID"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def load(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception as exc:
        print(f"[x-run] {path.name} unreadable ({exc}); treating as empty",
              file=sys.stderr)
        return default


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)


def parse_ts(value: str) -> float:
    if not value:
        return 0.0
    value = value.replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return time.mktime(time.strptime(value, fmt)) - time.timezone
        except ValueError:
            continue
    return 0.0


def past_deadline(now: float) -> bool:
    if not UNTIL:
        return False
    try:
        return now > time.mktime(time.strptime(UNTIL, "%Y-%m-%d"))
    except ValueError:
        print(f"[x-run] bad X_UNTIL {UNTIL!r}, ignoring", file=sys.stderr)
        return False


def get_json(url: str, headers=None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def tell_owner(text: str) -> bool:
    """One line into the owner's own chat. Best effort, never fatal."""
    if not (CHAT_UID and PLOW_TOKEN):
        return False
    request = urllib.request.Request(
        f"{API_BASE}/v1/chats/{CHAT_UID}/messages",
        data=json.dumps({"body": text}).encode(),
        headers={"Authorization": f"Bearer {PLOW_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20):
            return True
    except Exception as exc:  # a failed alert must never stop the poller
        print(f"[x-run] could not reach the owner's chat: {exc}", file=sys.stderr)
        return False


def deliver(event: dict) -> bool:
    """Queue one event and fire one turn. True only if the turn was fired.

    The contract that cost the server 2111 duplicate replies: the caller
    finalizes `since_id` only when every event in the batch returned True, so a
    turn that could not be fired must return False and be retried next tick.
    """
    tid = str(event.get("id") or "")
    if not tid:
        print("[x-run] event with no tweet id, dropping", file=sys.stderr)
        return False

    # Answered already: never queue it again. True, not False -- this one is
    # finished, and False would leave it before since_id and re-emit it every
    # cycle, which is the loop that produced a duplicate public reply on PH.
    done = load(LEDGER, {})
    if tid in done:
        print(f"[x-run] {tid} already answered by {done[tid]}; not queueing again",
              flush=True)
        return True

    QUEUE.mkdir(parents=True, exist_ok=True)
    path = QUEUE / f"{tid}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(event, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)

    try:
        result = subprocess.run(
            [HERMES, "cron", "run", JOB],
            capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
        )
    except FileNotFoundError:
        print(f"[x-run] {HERMES} not found; {tid} stays queued", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[x-run] firing {JOB} failed: {exc}; {tid} stays queued",
              file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"[x-run] {JOB} rc={result.returncode}: {result.stderr.strip()[:200]}",
              file=sys.stderr)
        return False

    # rc is not the answer. `hermes cron run` exits 0 whether the turn ran or
    # died -- a run that failed on auth still exited 0 and printed "Ran now:
    # failed.", and taking rc at face value threw the question away.
    out = (result.stdout or "") + (result.stderr or "")
    if OK_LINE not in out:
        tail = " ".join(out.split())[-200:]
        print(f"[x-run] {JOB} did not report success: {tail}", file=sys.stderr)
        return False
    print(f"[x-run] queued {tid} and fired {JOB}", flush=True)
    return True


def alert_stuck(now=time.time) -> None:
    """Tell the owner about an event queued too long, once each."""
    if not QUEUE.is_dir():
        return
    for path in sorted(QUEUE.glob("*.json")):
        flag = path.with_suffix(".alerted")
        if flag.exists():
            continue
        try:
            age = now() - path.stat().st_mtime
        except OSError:
            continue
        if age < ALERT_AFTER_S:
            continue
        if tell_owner(
            f"An X mention ({path.stem}) has been waiting {int(age // 60)} min "
            "and is still unanswered. It stays queued until it goes out."
        ):
            flag.write_text(str(int(now())))
            print(f"[x-run] told the owner about stuck {path.stem}", flush=True)


def poll_once(state: dict, emit=deliver, now: float | None = None) -> int:
    """One cycle: one request, then queue what it found."""
    now = time.time() if now is None else now
    alert_stuck()

    env = credentials()
    bearer, me = env.get("X_BEARER_TOKEN"), env.get("X_USER_ID")
    if not (bearer and me):
        raise RuntimeError(f"X_BEARER_TOKEN and X_USER_ID must be in {ENV_FILE}")

    params = {
        "max_results": "25",
        "tweet.fields": "created_at,author_id,conversation_id,referenced_tweets",
        "expansions": "author_id,referenced_tweets.id",
        "user.fields": "username",
    }
    since = state.get("since_id")
    if since:
        params["since_id"] = since
    data = get_json(
        f"https://api.x.com/2/users/{me}/mentions?" + urllib.parse.urlencode(params),
        {"Authorization": f"Bearer {bearer}"},
    )

    names = {u["id"]: u.get("username", "")
             for u in data.get("includes", {}).get("users", [])}
    # Who wrote the tweet each mention is replying to. This is what separates a
    # reply under the owner's own thread from a stranger shouting his handle.
    referenced = {t["id"]: t for t in data.get("includes", {}).get("tweets", [])}

    events, newest, skipped = [], since, 0
    for tweet in reversed(data.get("data", [])):   # oldest first: since_id ends newest
        tid = tweet["id"]
        # Tweet ids are numeric strings and sort by size, not lexically. A
        # non-numeric value in state (corrupt file, hand edit) would otherwise
        # crash the channel every cycle, silently.
        try:
            if newest is None or int(tid) > int(newest):
                newest = tid
        except (TypeError, ValueError):
            newest = tid

        if tweet.get("author_id") == me:           # never answer ourselves
            continue
        created = parse_ts(tweet.get("created_at"))
        if EVENT_TTL_S and created and (now - created) > EVENT_TTL_S:
            continue

        parent = None
        for ref in tweet.get("referenced_tweets") or []:
            if ref.get("type") == "replied_to":
                parent = referenced.get(ref.get("id"))
                break
        under_owner = bool(parent) and parent.get("author_id") == me

        text = tweet.get("text", "")
        if not under_owner and not any(k in text.lower() for k in KEYWORDS):
            skipped += 1
            continue

        events.append({
            "id": tid,
            "text": text.replace("\n", " "),
            "author": names.get(tweet.get("author_id"), ""),
            "author_id": tweet.get("author_id", ""),
            "created_at": tweet.get("created_at", ""),
            "conversation_id": tweet.get("conversation_id", ""),
            # The turn reads this to know which rules it is under: a reply in
            # the owner's own thread is someone he is talking to, a bare
            # mention is a stranger who found his handle. Neither is an
            # instruction, and this field says which, so the model does not
            # have to infer it from the text it is being asked to distrust.
            "kind": "reply_to_owner" if under_owner else "mention",
            "in_reply_to": (parent or {}).get("id", ""),
        })

    delivered_all = True
    for event in events:
        if not emit(event):
            delivered_all = False
    # Only advance since_id when every event in the batch actually landed. A
    # failed wake must be retried, and since_id is the only thing standing
    # between a question and silence.
    if newest and delivered_all:
        state["since_id"] = newest
    if skipped:
        print(f"[x-run] {skipped} bare mention(s) off-topic, skipped", flush=True)
    return len(events)


def main() -> int:
    state = load(STATE, {})
    while True:
        now = time.time()
        if past_deadline(now):
            print(f"[x-run] past X_UNTIL={UNTIL}, stopping", flush=True)
            return 0
        try:
            poll_once(state, now=now)
        except urllib.error.HTTPError as exc:
            # 429 is the rate limit and 5xx is X being X. Both pass; a poller
            # that dies on them turns a bad minute into a restart loop.
            print(f"[x-run] HTTP {exc.code} from X: {exc.reason}", file=sys.stderr)
        except Exception as exc:
            print(f"[x-run] cycle failed: {exc}", file=sys.stderr)
        save_state(state)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    # Stand down quietly, and with 0: a second poller is not a crash, and the
    # service must not be respawned into the same collision every cycle.
    if not claim_the_lock():
        sys.exit(0)
    sys.exit(main())
