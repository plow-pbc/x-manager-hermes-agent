#!/usr/bin/env python3
"""The guards that cost a live incident each, pinned.

Every assertion here is one thing that went wrong in public on the Product Hunt
generation of this agent. Run: python3 -m unittest discover -s tests
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "x-shared" / "scripts"))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        os.environ.update({
            "X_STATE_DIR": str(self.dir),
            "X_QUEUE": str(self.dir / "queue"),
            "X_OUTBOX": str(self.dir / "outbox"),
            "X_SENT": str(self.dir / "sent"),
            "X_MEDIA": str(self.dir / "media"),
            "X_LEDGER": str(self.dir / "answered.json"),
            "X_STATE": str(self.dir / "state.json"),
            "X_LOCK": str(self.dir / "poller.lock"),
            "X_API_ENV": str(self.dir / "x-api.env"),
        })
        for name in ("x_run", "x_send"):
            sys.modules.pop(name, None)


class Delivery(Base):
    """The contract that cost the server 2111 duplicate replies."""

    def setUp(self):
        super().setUp()
        import x_run
        self.x_run = x_run

    def test_a_turn_that_did_not_run_does_not_advance_since_id(self):
        """The whole point of the batch rule: an event that was not delivered
        must be re-emitted next cycle, so since_id stays where it was."""
        self.x_run.credentials = lambda: {"X_BEARER_TOKEN": "b", "X_USER_ID": "me"}
        self.x_run.get_json = lambda *a, **k: {
            "data": [{"id": "1000", "author_id": "someone", "text": "is the plow hackathon open?",
                      "created_at": ""}],
            "includes": {"users": [{"id": "someone", "username": "asker"}]},
        }
        state = {}
        self.x_run.poll_once(state, emit=lambda event: False, now=0)
        self.assertNotIn("since_id", state)

        # And the mirror: when it lands, since_id moves to the newest id seen.
        self.x_run.poll_once(state, emit=lambda event: True, now=0)
        self.assertEqual(state["since_id"], "1000")

    def test_a_bare_mention_about_nothing_we_do_is_not_a_turn(self):
        """21 live mentions, zero about the hackathon: without this gate every
        crypto spam tweet fires a model turn."""
        self.x_run.credentials = lambda: {"X_BEARER_TOKEN": "b", "X_USER_ID": "me"}
        self.x_run.get_json = lambda *a, **k: {
            "data": [{"id": "2000", "author_id": "spammer", "text": "$PEPE 100x ser",
                      "created_at": ""}],
            "includes": {"users": [{"id": "spammer", "username": "spam"}]},
        }
        fired = []
        self.x_run.poll_once({}, emit=lambda e: fired.append(e) or True, now=0)
        self.assertEqual(fired, [])

    def test_a_reply_under_the_owners_own_tweet_skips_the_keyword_gate(self):
        """Somebody answering his launch thread is the traffic this exists for;
        a keyword gate there would drop the real questions."""
        self.x_run.credentials = lambda: {"X_BEARER_TOKEN": "b", "X_USER_ID": "me"}
        self.x_run.get_json = lambda *a, **k: {
            "data": [{"id": "3000", "author_id": "human", "text": "wait, when is it?",
                      "created_at": "", "referenced_tweets": [{"type": "replied_to", "id": "42"}]}],
            "includes": {"users": [{"id": "human", "username": "human"}],
                         "tweets": [{"id": "42", "author_id": "me"}]},
        }
        fired = []
        self.x_run.poll_once({}, emit=lambda e: fired.append(e) or True, now=0)
        self.assertEqual([e["kind"] for e in fired], ["reply_to_owner"])

    def test_a_fired_turn_is_reported_only_on_the_success_line(self):
        # `hermes cron run` exits 0 whether the turn ran or died. Taking rc at
        # face value marked a comment answered and threw the question away.
        class Result:
            returncode = 0
            stdout = "Ran now: failed.\n"
            stderr = ""

        self.x_run.subprocess.run = lambda *a, **k: Result()
        self.assertFalse(self.x_run.deliver({"id": "1", "text": "hi"}))

    def test_an_answered_tweet_is_never_queued_again(self):
        # True, not False: this one is finished. False would leave it before
        # since_id and re-emit it every cycle -- the loop that produced a
        # duplicate public reply.
        pathlib.Path(os.environ["X_LEDGER"]).write_text(json.dumps({"7": "8"}))
        fired = []
        self.x_run.subprocess.run = lambda *a, **k: fired.append(1)
        self.assertTrue(self.x_run.deliver({"id": "7", "text": "asked before"}))
        self.assertEqual(fired, [])


class Guards(Base):
    """The sender's checks. Server-side on purpose: a brake the model's own
    shell can drive is not a brake -- that one posted for real."""

    def setUp(self):
        super().setUp()
        import x_send
        self.x_send = x_send

    def refusal(self, item, ledger=None):
        return self.x_send.check(item, ledger or {})

    def test_over_280_characters_is_refused(self):
        self.assertIsNotNone(self.refusal({"text": "x" * 281}))

    def test_links_are_not_restricted_by_domain(self):
        for url in ["https://youtu.be/I1-izime3YE",
                    "https://www.youtube.com/watch?v=I1-izime3YE",
                    "https://any-new-site.example/path?q=value",
                    "https://subdomain.another-site.example/page",
                    "www.unlisted.example"]:
            with self.subTest(url=url):
                self.assertIsNone(self.refusal({"text": "See: " + url}))

    def test_a_tweet_already_answered_is_refused(self):
        self.assertIsNotNone(self.refusal({"text": "hi", "reply_to": "7"}, {"7": "8"}))

    def test_a_media_name_cannot_escape_the_media_directory(self):
        media = pathlib.Path(os.environ["X_MEDIA"])
        media.mkdir(parents=True, exist_ok=True)
        outside = self.dir / "secret.png"
        outside.write_bytes(b"not yours")
        self.assertIsNone(self.x_send.upload("../secret.png", {}))

    def test_unarmed_composes_and_posts_nothing(self):
        self.assertFalse(self.x_send.ARMED,
                         "X_ARMED must default off: the owner arms it, not a turn")
        outbox = pathlib.Path(os.environ["X_OUTBOX"])
        outbox.mkdir(parents=True, exist_ok=True)
        request = outbox / "one.json"
        request.write_text(json.dumps({"text": "hello"}))
        posted = []
        self.x_send.api = lambda *a, **k: posted.append(1) or {}
        self.x_send.send_one(request, {"X_HANDLE": "someone"}, {})
        self.assertEqual(posted, [], "an unarmed sender must not call the API")
        result = json.loads((pathlib.Path(os.environ["X_SENT"]) / "one.json").read_text())
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["text"], "hello")


if __name__ == "__main__":
    unittest.main()
