#!/usr/bin/env python3
"""x_send.py — the outbox sender. Root, supervised, the only holder of the keys.

Product Hunt has no write API, so its agent had to drive a browser and could
never hold a credential at all. X hands out API keys, and the lazy version of
this file would put them in the agent's environment and let the turn call the
API itself. That would be the first time one of these agents held a live
credential to the owner's public voice in a process whose input is a stranger's
tweet -- and a stolen X key is not something we can revoke for him.

So the split is: the agent composes, this posts.

    the turn (uid 10000)                    this service (root)
      writes /var/lib/hermes/x/outbox/*.json  reads it, checks it, signs it
      reads  /var/lib/hermes/x/sent/*.json    writes the result back

The keys are read from a root-only file and never enter the agent's
environment. A prompt injection that gets everything it asks for still gets a
tweet -- deletable, rate-limited, and inside the guards below -- not the
account.

The guards live HERE and not in the prompt, for the reason the last generation
proved twice: a brake the model's own shell can drive is not a brake. X_ARMED
is the same idea. Off, every send is validated, composed, written back as
`held`, and not posted; the owner turns it on where the container is started,
not by telling the agent to.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import uuid

from x_media import read_image

HOME = pathlib.Path(os.environ.get("X_STATE_DIR", "/var/lib/hermes/x"))
OUTBOX = pathlib.Path(os.environ.get("X_OUTBOX", str(HOME / "outbox")))
SENT = pathlib.Path(os.environ.get("X_SENT", str(HOME / "sent")))
# What the agent reads to know it is not set up yet. A service standing down
# writes its complaint to a log the agent cannot open; this file is the same
# sentence somewhere a turn can act on.
SETUP = pathlib.Path(os.environ.get("X_SETUP_NEEDED", str(HOME / "setup-needed.json")))
MEDIA = pathlib.Path(os.environ.get("X_MEDIA", str(HOME / "media")))
CHAT_IMAGES = pathlib.Path(os.environ.get("HERMES_HOME", "/var/lib/hermes")) / "cache/images"
CACHE_OWNER_UID = 10000
LEDGER = pathlib.Path(os.environ.get("X_LEDGER", str(HOME / "answered.json")))
ENV_FILE = pathlib.Path(os.environ.get("X_API_ENV", "/var/lib/plow/x-api.env"))
TICK_S = int(os.environ.get("X_SEND_TICK_S", "5"))
# Seconds between two posts. A thread is several in a row on purpose, so this
# is a floor against a loop, not a posting cadence.
MIN_GAP_S = int(os.environ.get("X_MIN_GAP_S", "5"))
# The published brake. Anything but "1" means compose, check, and hold.
ARMED = os.environ.get("X_ARMED", "").strip() == "1"
MAX_LEN = 280
UPLOAD_URL = "https://upload.x.com/1.1/media/upload.json"
TWEETS_URL = "https://api.x.com/2/tweets"


def declare_setup_needed(missing: list[str]) -> None:
    """Say what is missing, where the agent will look for it.

    Written by root and world-readable on purpose: the turn that has to go and
    fix this runs as the agent, and it cannot be told by a log line.
    """
    SETUP.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETUP.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "missing": missing,
        "credentials_file": str(ENV_FILE),
        "note": "This container has no working X credentials. See 'Setting "
                "yourself up' in your instructions: what you cannot get from "
                "the owner's vault, ask him for -- and ask once, plainly.",
    }, indent=2))
    os.chmod(tmp, 0o644)
    tmp.replace(SETUP)


def read_env(path: pathlib.Path) -> dict:
    out = {}
    try:
        text = path.read_text()
    except OSError as exc:
        print(f"[x-send] cannot read {path}: {exc}", file=sys.stderr)
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def oauth_header(method: str, url: str, keys: dict) -> str:
    """OAuth1 for a request with no form-encoded body.

    Both calls here carry either JSON or multipart, and neither goes into the
    signature base string -- which is why this file uses multipart for the
    media upload rather than the base64 form field the docs show first.
    """
    oauth = {
        "oauth_consumer_key": keys["X_API_KEY"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": keys["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    enc = lambda s: urllib.parse.quote(str(s), safe="~")
    param_str = "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(oauth.items()))
    base = "&".join([method, enc(url), enc(param_str)])
    signing_key = f"{enc(keys['X_API_SECRET'])}&{enc(keys['X_ACCESS_TOKEN_SECRET'])}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(oauth.items()))


def api(method: str, url: str, keys: dict, body: bytes, content_type: str) -> dict:
    request = urllib.request.Request(
        url, data=body, method=method,
        headers={"Authorization": oauth_header(method, url, keys),
                 "Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:400] if hasattr(exc, "read") else str(exc)
        return {"error": f"HTTP {exc.code}", "detail": detail}
    except Exception as exc:
        return {"error": str(exc)}


def upload_image(image, keys: dict) -> str | None:
    """Upload the validated, immutable byte snapshot."""
    filename, content_type, data = image
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data, b"\r\n", f"--{boundary}--\r\n".encode(),
    ])
    result = api("POST", UPLOAD_URL, keys, body, f"multipart/form-data; boundary={boundary}")
    media_id = result.get("media_id_string")
    if not media_id:
        print("[x-send] X did not accept the image upload", file=sys.stderr)
    return media_id


def upload(name: str, keys: dict) -> str | None:
    """Compatibility entry point for callers uploading a single image."""
    try:
        image = read_image(name, MEDIA, CHAT_IMAGES, CACHE_OWNER_UID)
    except ValueError as exc:
        print(f"[x-send] {exc}", file=sys.stderr)
        return None
    return upload_image(image, keys)


def refuse(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def check(item: dict, ledger: dict) -> dict | None:
    """Everything that decides whether this may go out. None means it may."""
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        return refuse("empty text")
    if len(text) > MAX_LEN:
        return refuse(f"{len(text)} characters, the limit is {MAX_LEN}")
    reply_to = item.get("reply_to")
    if reply_to is not None and not str(reply_to).isdigit():
        return refuse("reply_to is not a tweet id")
    # The ledger, not the model's reading of the thread. On Product Hunt the
    # page check was the only guard and it missed once, in public.
    if reply_to and str(reply_to) in ledger:
        return refuse(f"{reply_to} was already answered by {ledger[str(reply_to)]}")
    media = item.get("media", [])
    if media is None:
        media = []
    if not isinstance(media, list) or len(media) > 4:
        return refuse("media must be a list of at most 4 image references")
    return None


def finish(path: pathlib.Path, result: dict) -> None:
    """Write the result where the agent can read it, then drop the request."""
    SENT.mkdir(parents=True, exist_ok=True)
    out = SENT / path.name
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    os.chmod(tmp, 0o644)         # the agent reads this; only root writes it
    tmp.replace(out)
    path.unlink(missing_ok=True)
    print(f"[x-send] {path.name}: {result.get('status')} "
          f"{result.get('id') or result.get('reason') or ''}", flush=True)


def remember(reply_to: str, tweet_id: str) -> None:
    """comment answered -> reply posted. The producer never queues these again."""
    if not reply_to:
        return
    ledger = {}
    try:
        ledger = json.loads(LEDGER.read_text())
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[x-send] ledger unreadable ({exc}); starting a new one", file=sys.stderr)
    ledger[str(reply_to)] = tweet_id
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2))
    os.chmod(tmp, 0o644)
    tmp.replace(LEDGER)


def send_one(path: pathlib.Path, keys: dict, ledger: dict) -> bool:
    """True if something was actually posted (so the caller can pace itself)."""
    try:
        item = json.loads(path.read_text())
    except Exception as exc:
        finish(path, refuse(f"unreadable request: {exc}"))
        return False
    if not isinstance(item, dict):
        finish(path, refuse("request is not an object"))
        return False

    problem = check(item, ledger)
    if problem:
        finish(path, problem)
        return False

    # Validate every attachment before any network call, including held mode.
    # Missing/invalid images must never silently become a text-only post.
    try:
        images = [read_image(ref, MEDIA, CHAT_IMAGES, CACHE_OWNER_UID)
                  for ref in item.get("media") or []]
    except ValueError as exc:
        finish(path, refuse(str(exc)))
        return False

    if not ARMED:
        # Composed, checked, and not posted. The owner arms this where the
        # container is started; nothing the agent can say switches it on.
        finish(path, {"status": "held", "reason": "X_ARMED is not 1",
                      "text": item["text"], "reply_to": item.get("reply_to"),
                      "media": item.get("media") or []})
        return False

    media_ids = []
    for image in images:
        media_id = upload_image(image, keys)
        if not media_id:
            finish(path, refuse("X could not upload the image; no post was published."))
            return False
        media_ids.append(media_id)

    payload = {"text": item["text"]}
    if item.get("reply_to"):
        payload["reply"] = {"in_reply_to_tweet_id": str(item["reply_to"])}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}

    result = api("POST", TWEETS_URL, keys, json.dumps(payload).encode(), "application/json")
    tweet_id = (result.get("data") or {}).get("id")
    if not tweet_id:
        # Kept as a failure the agent can read, not a retry: a send whose
        # outcome we cannot see must never be repeated automatically. That is
        # how a double-post happens.
        finish(path, {"status": "failed", "reason": result.get("error", "no id returned"),
                      "detail": str(result)[:400]})
        return False

    handle = keys.get("X_HANDLE", "i").lstrip("@")
    finish(path, {"status": "sent", "id": tweet_id,
                  "url": f"https://x.com/{handle}/status/{tweet_id}",
                  "reply_to": item.get("reply_to")})
    remember(str(item.get("reply_to") or ""), tweet_id)
    return True


def main() -> int:
    keys = read_env(ENV_FILE)
    missing = [n for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
                           "X_ACCESS_TOKEN_SECRET") if not keys.get(n)]
    if missing:
        # A missing credential is a setup mistake, and a service that retries
        # it every 5s only buries the line that says so. It is also not
        # necessarily the owner's mistake to fix -- the agent is expected to go
        # and get these -- so it is written down where a turn can read it.
        print(f"[x-send] {ENV_FILE} is missing {', '.join(missing)} -- standing down",
              file=sys.stderr)
        declare_setup_needed(missing)
        return 1
    # Set up now. Clear the flag rather than leaving a stale one that sends the
    # agent off to re-do an account it already has.
    SETUP.unlink(missing_ok=True)
    if not ARMED:
        print("[x-send] X_ARMED is not 1: composing and holding, posting nothing",
              flush=True)

    OUTBOX.mkdir(parents=True, exist_ok=True)
    last_post = 0.0
    while True:
        ledger = {}
        try:
            ledger = json.loads(LEDGER.read_text())
        except FileNotFoundError:
            pass
        except Exception:
            pass
        for path in sorted(OUTBOX.glob("*.json")):
            if time.time() - last_post < MIN_GAP_S:
                break
            if send_one(path, keys, ledger):
                last_post = time.time()
                ledger = {}
                try:
                    ledger = json.loads(LEDGER.read_text())
                except Exception:
                    pass
        time.sleep(TICK_S)


if __name__ == "__main__":
    sys.exit(main())
