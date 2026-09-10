# The Plow cloud image for the X manager.
#
# The tag is an immutable `base-<sha>` naming one commit of plow-pbc/plow-hermes-agent,
# pinned by digest and never moved: every tenant VM inherits this exact
# filesystem while holding that owner's Plow credential, so a moving tag would
# substitute code underneath them.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-97034704867e0c8b982f8f3416ff5639b6023358@sha256:b1b860d63c9e60075d15394f1a9ae93af5200c00692d0cc93548f6a05e46cc4b

# Identity: only what is specific to this agent. plow-init writes the home's
# SOUL.md on every boot as the base persona followed by this file; nothing is
# COPYed to /var/lib/hermes/SOUL.md, which is overwritten at boot.
COPY runtime/persona.md /opt/hermes/plow-seed/persona.md
RUN chmod 0644 /opt/hermes/plow-seed/persona.md
COPY LICENSE NOTICE /usr/share/doc/x-manager/

# The producer and the sender, root-owned and out of the agent's reach.
#
# There is no copy of these under $HERMES_HOME on purpose. What the supervisor
# runs unattended must not be a file a turn can rewrite: everything under the
# agent's home belongs to uid 10000, and every input the producer handles is a
# stranger's tweet. x_send.py matters more than most -- it is the one process
# that reads keys able to post as the owner.
COPY x-shared/ /opt/plow/x-shared/
RUN chown -R root:root /opt/plow \
 && find /opt/plow -type d -exec chmod 0755 {} + \
 && find /opt/plow -type f -exec chmod 0644 {} +

# The usage reporter, fetched at build from the commit vendor/client.pin names
# and checked against the hash beside it. Fetched rather than committed because
# plow-pbc/agent-index-client owns that file; pinned rather than tracked from a
# branch because this runs inside an agent holding a live credential. The
# checksum is the second half: a sha in a URL is only as good as the host
# serving it.
COPY vendor/client.pin /opt/plow/agent-index-client.pin
RUN set -eu; \
    sha="$(sed -n 's/^sha=//p' /opt/plow/agent-index-client.pin)"; \
    want="$(sed -n 's/^sha256=//p' /opt/plow/agent-index-client.pin)"; \
    path="$(sed -n 's/^path=//p' /opt/plow/agent-index-client.pin)"; \
    curl -fsS --retry 3 --retry-delay 2 --retry-max-time 90 --max-time 60 -o /opt/plow/agent-index-client.py \
      "https://raw.githubusercontent.com/plow-pbc/agent-index-client/${sha}/${path}"; \
    got="$(sha256sum /opt/plow/agent-index-client.py | cut -d' ' -f1)"; \
    [ "$got" = "$want" ] || { echo "agent-index client is $got, pin says $want" >&2; exit 1; }; \
    chmod 0644 /opt/plow/agent-index-client.py

COPY image/s6-overlay/ /etc/s6-overlay/
RUN chmod 0755 /etc/s6-overlay/scripts/x-cron.sh

# The directories the two halves talk through. The organizer-supplied facts
# are bundled below, so a fresh installation already knows the hackathon.
#
# The permissions ARE the trust boundary, so they are not uniform:
#   queue    0700 agent   a stranger's words; the turn reads them as data
#   outbox   0700 agent   what the turn wants posted; root reads and checks it
#   sent     0755 root    the results, agent-readable, root-writable only
#   media    0755 root    images the owner mounts; the agent names them, never
#                         writes them
RUN install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/x \
 && install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/x/queue \
 && install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/x/outbox \
 && install -d -o root -g root -m 0755 /var/lib/hermes/x/sent \
 && install -d -o root -g root -m 0755 /var/lib/hermes/x/media

# Docker initializes a fresh home volume with the shared event context.
# Existing home volumes retain their own facts and reply ledger.
COPY --chown=10000:10000 runtime/facts.md /var/lib/hermes/x/facts.md
RUN chmod 0600 /var/lib/hermes/x/facts.md
