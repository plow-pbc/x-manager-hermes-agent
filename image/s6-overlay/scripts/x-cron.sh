#!/bin/sh
# Make sure the job the producer fires exists.
#
# `hermes cron create` writes /var/lib/hermes/cron/jobs.json and NOTHING
# replays it: a fresh install has no job, so every `hermes cron run x-reply`
# comes back "Job with ID or name 'x-reply' not found" and the queue fills up
# while the poller looks healthy. That is exactly what happened here on
# 2026-09-09 -- a prompt-injection reply sat queued and unanswered, and the
# only thing that said so was a log line nobody was reading.
#
# The guards did hold: deliver() returned False, since_id did not advance, and
# the tweet was never marked answered. Correct, and still silent. So this runs
# at every boot and is idempotent -- the job is created if it is missing and
# left alone if it is there, because re-creating it would make a duplicate that
# fires twice.
set -eu

PATH=/command:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
export PATH

HERMES_HOME=/var/lib/hermes
JOBS="$HERMES_HOME/cron/jobs.json"
NAME=x-reply
export HERMES_HOME

if grep -q "\"$NAME\"" "$JOBS" 2>/dev/null; then
  echo "x-cron: $NAME is already registered" >&2
  exit 0
fi

# A turn is a real call through Plow, so it needs the tenant's own values --
# the same allowlist the poller carries, and for the same reason: without them
# this is an HTTP 401 and a job that was never created.
for _n in HERMES_CUSTOM_PLOW_API_KEY PLOW_AGENT_TOKEN PLOW_MCP_URL PLOW_API_BASE API_SERVER_KEY; do
  eval "$_n=\$(cat /run/s6/container_environment/$_n 2>/dev/null || true)"
  export "$_n"
done

# The schedule is a date that never arrives on purpose. The producer is the
# trigger -- `hermes cron run x-reply` -- and a job that also fired on a clock
# would work the queue twice.
/command/s6-setuidgid hermes env \
  HOME="$HERMES_HOME" HERMES_HOME="$HERMES_HOME" \
  HERMES_CUSTOM_PLOW_API_KEY="$HERMES_CUSTOM_PLOW_API_KEY" PLOW_AGENT_TOKEN="$PLOW_AGENT_TOKEN" \
  PLOW_MCP_URL="$PLOW_MCP_URL" PLOW_API_BASE="$PLOW_API_BASE" API_SERVER_KEY="$API_SERVER_KEY" \
  /opt/hermes/bin/hermes cron create --name "$NAME" --deliver origin "0 5 1 1 *" \
  "$(cat /opt/plow/x-shared/x-reply.prompt)" \
  || echo "x-cron: could not create $NAME -- the queue will fill until it exists" >&2

exit 0
