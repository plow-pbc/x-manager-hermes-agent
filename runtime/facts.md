# AI Worth Using x Hermes Hackathon

Organizer-supplied context, shared by every installation of the X Hackathon
agent. These are event facts, independent of the installer's X account or Plow
line. The organizer confirmed the two-stage selection process below.

## Event and purpose

AI Worth Using is a podcast where guests teach Tom Preston-Werner, co-founder
of GitHub, how to use their products. The announcement names Peter Steinberger,
founder of OpenClaw, and Jesse Vincent, creator of Superpowers, as guests.

To celebrate the podcast launch, AI Worth Using and Plow (https://plow.co) are
collaborating on a Hermes hackathon. The goal is to learn how real people use
Hermes agents to solve real problems.

## What participants must build

- A Hermes agent that solves one real chore end to end: something people
  actually need completed, not a demo or mockup.
- A publicly available agent that others can install through the AI Worth Using
  Agent Index: https://aiworthusing.com/agent-index.
- An installation guide that lets others run it with their own accounts and
  credentials. Real user installs and reported usage count toward qualification.
- At least one of the listed open-source Plow tools: Plow Latch, Plow Chat, or
  the AI Worth Using client.
- All submissions must use the AI Worth Using client to report usage to the
  dashboard. That client is mandatory. The announcement says the Agent Index
  publicly tracks users and successful installs; agents must work for real users
  to rank on the leaderboard.

## Dates and two-stage selection

| Date | Milestone |
| --- | --- |
| September 9 | Hackathon launch; kickoff on Google Meet |
| September 16 | Submission deadline on the Agent Index |
| September 22 | Ranking cutoff: the top 10 by real user installs and reported usage qualify for final judging |
| September 23 | Plow Team evaluates the finalists and votes to determine the top 3 |

The leaderboard qualifies 10 finalists. A human-in-the-loop judging phase by the
Plow Team determines the final top 3. Leading the leaderboard does not
automatically win first prize.

The supplied announcement did not explicitly state the event year, kickoff or
cutoff times, or time zone. No Google Meet URL, detailed metric weighting or
voting rubric was supplied.

## Announced prizes and podcast opportunity

- First place after the final vote: Mac Studio (M5 Max), as named in the announcement.
- Second place after the final vote: Mac Mini (M6), as named in the announcement.
- The top 3 will be candidates to appear on the AI Worth Using Podcast with
  Tom Preston-Werner. Podcast participation is not guaranteed.

No additional hardware specifications, delivery dates, shipping restrictions,
cash alternatives, entry fee, age/country eligibility, or team-size rules were
supplied.

## Technical submission requirements

- Foundation: https://github.com/plow-pbc/plow-agents.
- Base image: https://github.com/plow-pbc/plow-hermes-agent.
- Working example: https://github.com/plow-pbc/life-assistant-hermes-agent.
- Reporting client: https://github.com/plow-pbc/agent-index-client.
- Standalone client:
  https://raw.githubusercontent.com/plow-pbc/agent-index-client/main/standalone/agent_index_client.py.

Each new submitted project has a unique Agent Index ID, registered once by its
publisher with a name and a one-line description. The Plow CLI's login
establishes the publisher's own account; lines lists available lines; mint
creates a credential for a chosen free line. The current CLI takes an explicit
line ID for minting.

Publisher registration uses the client's --register, --agent, --name and
--blurb options with that publisher's Plow credential. The --install-url option
links to the project's public installation instructions.

The project image includes the agent-index reporting service, following the
Life Assistant example. Its AGENT_ID matches the registered project ID.
Registration alone does not report usage; the reporter must be installed,
configured and running.

Installing an existing published agent is different from registering a new
submission. Each installer uses their own Plow and X accounts, credential,
home volume and installation reporting identity. Installers of this same agent
report to its existing project page; they do not claim the publisher's ID again.

## Support and links

- Public support landing page: https://aiworthusing.com/discord.
- Organizer-supplied Discord invite: https://discord.gg/mSHWKRqZP.
- Agent Index: https://aiworthusing.com/agent-index.
- Plow: https://plow.co.

The announcement mentioned podcast episodes and podcast information but supplied
no URLs for those labels.
