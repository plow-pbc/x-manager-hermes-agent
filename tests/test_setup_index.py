"""New installers obtain their own key without claiming the publisher's ID."""
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "x-shared/scripts"))
import setup_index


class IndexSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / "state.json"
        self.client = Mock()
        self.client.API = "https://index.example"
        self.client.AGENT_KEY = re.compile(r"aik_[A-Za-z0-9_-]{20,128}")
        self.client.INSTALL_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
        self.client.load_state.side_effect = lambda: (
            json.loads(self.path.read_text()) if self.path.exists() else {})
        self.client.state_path.return_value = str(self.path)
        self.client.save_private.side_effect = lambda path, text: pathlib.Path(path).write_text(text)
        self.client._open_no_redirect.side_effect = lambda req: io.BytesIO(
            b'{"agent_id":"danedelattre-x-manager"}')
        self.client._post.side_effect = lambda url, body, auth: (
            200, {"key": "aik_" + "a" * 43, "install_id": body["install_id"]})

    def run_setup(self):
        setup_index.provision(self.client, "danedelattre-x-manager")

    def test_only_mints_install_key_and_second_run_is_unchanged(self):
        self.run_setup()
        original = self.path.read_bytes()
        self.run_setup()
        self.assertEqual(self.path.read_bytes(), original)
        self.client._post.assert_called_once()
        self.assertEqual(self.client._post.call_args.args[0], "https://index.example/v1/keys")
        self.assertEqual(self.client._open_no_redirect.call_args.args[0].get_method(), "GET")

    def test_invalid_response_never_saves_state(self):
        for response in [(200, {"key": "bad", "install_id": "wrong"}),
                         (200, {"key": "aik_" + "a" * 43, "install_id": "wrong"}),
                         (403, {})]:
            with self.subTest(response=response):
                self.client._post.side_effect = None
                self.client._post.return_value = response
                with self.assertRaises(SystemExit):
                    self.run_setup()
                self.assertFalse(self.path.exists())

    def test_corrupt_state_prevents_network_and_remint(self):
        self.path.write_text("invalid JSON")
        with self.assertRaises(ValueError):
            self.run_setup()
        self.client._open_no_redirect.assert_not_called()
        self.client._post.assert_not_called()

    def test_unknown_agent_prevents_mint(self):
        self.client._open_no_redirect.side_effect = lambda req: io.BytesIO(b'{}')
        with self.assertRaises(SystemExit):
            self.run_setup()
        self.client._post.assert_not_called()
        self.assertFalse(self.path.exists())
