"""Chat attachments reach X without a writable library or privileged file reads."""
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'x-shared/scripts'))


class ChatMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        spec = importlib.util.spec_from_file_location('sender_media_test', ROOT / 'x-shared/scripts/x_send.py')
        self.sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sender)
        for name, folder in [('MEDIA', 'media'), ('CHAT_IMAGES', 'cache/images'),
                             ('OUTBOX', 'outbox'), ('SENT', 'sent')]:
            p = self.root / folder
            p.mkdir(parents=True)
            setattr(self.sender, name, p)
        self.sender.LEDGER = self.root / 'answered.json'
        self.sender.CACHE_OWNER_UID = os.getuid()
        self.sender.ARMED = True
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
        self.png = image.getvalue()
        self.cached = self.sender.CHAT_IMAGES / 'img_from_chat.png'
        self.cached.write_bytes(self.png)
        self.calls = []
        def api(method, url, keys, body, content_type):
            self.calls.append((url, body, content_type))
            if url == self.sender.UPLOAD_URL:
                return {'media_id_string': '321'}
            return {'data': {'id': '654'}}
        self.sender.api = api

    def request(self, media):
        p = self.sender.OUTBOX / 'request.json'
        p.write_text(json.dumps({'text': 'Hackathon announcement', 'reply_to': '123', 'media': media}))
        result = self.sender.send_one(p, {'X_HANDLE': 'owner'}, {})
        return result, json.loads((self.sender.SENT / p.name).read_text())

    def test_chat_image_is_uploaded_then_attached_to_the_post(self):
        posted, result = self.request([str(self.cached)])
        self.assertTrue(posted)
        self.assertEqual(result['status'], 'sent')
        self.assertIn(self.png, self.calls[0][1])
        self.assertIn(b'Content-Type: image/png', self.calls[0][1])
        self.assertEqual(json.loads(self.calls[1][1])['media'], {'media_ids': ['321']})
        self.assertEqual(json.loads(self.sender.LEDGER.read_text()), {'123': '654'})

    def test_preloaded_library_still_works(self):
        (self.sender.MEDIA / 'poster.png').write_bytes(self.png)
        self.assertTrue(self.request(['poster.png'])[0])

    def test_unarmed_validates_and_holds_without_uploading(self):
        self.sender.ARMED = False
        posted, result = self.request([str(self.cached)])
        self.assertFalse(posted)
        self.assertEqual(result['status'], 'held')
        self.assertEqual(self.calls, [])

    def test_invalid_second_image_prevents_all_uploads_and_text_only_posts(self):
        posted, result = self.request([str(self.cached), str(self.sender.CHAT_IMAGES / 'missing.png')])
        self.assertFalse(posted)
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_paths_outside_roots_and_traversal_are_refused(self):
        secret = self.root / 'secret.png'
        secret.write_bytes(self.png)
        for name in [str(secret), '../secret.png', str(self.sender.CHAT_IMAGES / '../secret.png'),
                     str(self.cached) + '/extra', 'https://example.com/image.png']:
            with self.subTest(name=name):
                self.assertEqual(self.request([name])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_file_symlink_and_directory_symlink_are_refused(self):
        other = self.root / 'private.png'
        other.write_bytes(self.png)
        self.cached.unlink()
        self.cached.symlink_to(other)
        self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        self.cached.unlink()
        self.sender.CHAT_IMAGES.rmdir()
        self.sender.CHAT_IMAGES.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.request([str(self.sender.CHAT_IMAGES / 'private.png')])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_non_image_oversize_and_non_string_are_refused_while_unarmed(self):
        self.sender.ARMED = False
        self.cached.write_text('not an image')
        self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        self.cached.write_bytes(self.png)
        import x_media
        with patch.object(x_media, 'MAX_IMAGE_BYTES', 16):
            self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        for value in [7, {}, True, 'bad\r\nheader.png']:
            self.assertEqual(self.request([value])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_cache_file_must_belong_to_agent_user(self):
        self.sender.CACHE_OWNER_UID = os.getuid() + 1
        self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_fifo_cannot_block_sender(self):
        self.cached.unlink()
        os.mkfifo(self.cached)
        self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_upload_failure_does_not_fall_back_to_text_only(self):
        self.sender.api = lambda *args: {'error': 'HTTP 403'}
        posted, result = self.request([str(self.cached)])
        self.assertFalse(posted)
        self.assertEqual(result['status'], 'refused')
        self.assertFalse(self.sender.LEDGER.exists())

    def test_upload_uses_validated_snapshot_even_if_file_changes(self):
        original = self.sender.api
        def api(*args):
            self.cached.write_text('changed after validation')
            return original(*args)
        self.sender.api = api
        self.assertTrue(self.request([str(self.cached)])[0])
        self.assertIn(self.png, self.calls[0][1])

    def test_falsy_malformed_media_cannot_turn_into_a_text_only_post(self):
        for value in [{}, '', False, 0]:
            with self.subTest(value=value):
                self.assertEqual(self.request(value)[1]['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_truncated_jpeg_is_refused_before_any_network_call(self):
        image = io.BytesIO()
        Image.new('RGB', (100, 100), 'blue').save(image, format='JPEG')
        self.cached.write_bytes(image.getvalue()[:-20])
        self.assertEqual(self.request([str(self.cached)])[1]['status'], 'refused')
        self.assertEqual(self.calls, [])
