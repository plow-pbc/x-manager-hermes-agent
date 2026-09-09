#!/usr/bin/env python3
"""Provision this install's usage key without changing the publisher's page."""
import importlib.util
import json
import os
import pathlib
import re
import secrets
import sys
import urllib.parse
import urllib.request

from x_send import read_env


def provision(client, agent):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", agent):
        raise SystemExit("Set AGENT_ID to the existing published agent ID.")
    client.use_index()
    client.hold_state_lock()
    # The pinned client refuses corrupt/unreadable state. Never replace it.
    if client.load_state().get("key"):
        print("Agent Index: this install already has a key; unchanged.")
        return
    request = urllib.request.Request(
        client.API + "/v1/agent?" + urllib.parse.urlencode({"agent_id": agent}),
        headers={"accept": "application/json"},
    )
    with client._open_no_redirect(request) as response:
        registered = json.loads(response.read())
    if registered.get("agent_id") != agent:
        raise SystemExit("Agent Index: the requested published agent was not found.")
    assertion = client.index_assertion()
    install = secrets.token_hex(16)
    code, result = client._post(
        client.API + "/v1/keys", {"label": agent, "install_id": install}, assertion,
    )
    if (code != 200 or not isinstance(result, dict)
            or not client.AGENT_KEY.fullmatch(str(result.get("key", "")))
            or result.get("install_id") != install
            or not client.INSTALL_ID.fullmatch(install)):
        raise SystemExit("Agent Index: invalid key response; no state saved.")
    client.save_private(client.state_path(), json.dumps({
        "install_id": install, "key": result["key"],
    }))
    print("Agent Index: install key saved; publisher page unchanged.")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this setup through the documented Compose command as root.")
    credentials = read_env(pathlib.Path("/var/lib/plow/credentials.host"))
    token = credentials.get("PLOW_AGENT_TOKEN", "")
    if not token:
        raise SystemExit("Mounted plow-credentials has no PLOW_AGENT_TOKEN.")
    os.environ["PLOW_AGENT_TOKEN"] = token
    os.environ["PLOW_API_BASE"] = credentials.get("PLOW_API_BASE", "https://api.plow.co")
    os.environ["HOME"] = os.environ["HERMES_HOME"] = "/var/lib/hermes"
    os.setgroups([])
    os.setgid(10000)
    os.setuid(10000)
    spec = importlib.util.spec_from_file_location(
        "agent_index_client", "/opt/plow/agent-index-client.py",
    )
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    try:
        provision(client, os.environ.get("AGENT_ID", ""))
    except Exception as exc:
        # Network exceptions may carry request data: report only their class.
        raise SystemExit("Agent Index setup failed: " + type(exc).__name__) from None
    finally:
        os.environ.pop("PLOW_AGENT_TOKEN", None)


if __name__ == "__main__":
    main()
