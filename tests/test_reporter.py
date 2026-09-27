"""The supervised reporter uses the same installer setup as documented BYO."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReporterTests(unittest.TestCase):
    def test_fresh_install_uses_proxy_and_does_not_claim_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / 'environment'
            environment.mkdir()
            for key, value in {'PLOW_API_BASE': 'https://installer-proxy.example',
                               'PLOW_AGENT_TOKEN': 'fixture-token',
                               'AGENT_ID': 'danedelattre-x-manager'}.items():
                (environment / key).write_text(value)
            record = root / 'calls'
            runner = root / 'python'
            runner.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['RECORD'],'a') as f:
 f.write(json.dumps({'args':sys.argv[1:],'base':os.getenv('PLOW_API_BASE'),'token':os.getenv('PLOW_AGENT_TOKEN')})+'\\n')
raise SystemExit(3 if sys.argv[-1]=='status' else 0)
''')
            runner.chmod(0o755)
            source = (ROOT / 'image/s6-overlay/s6-rc.d/agent-index/run').read_text()
            source = source.replace('/run/s6/container_environment', str(environment))
            source = source.replace('/command/s6-setuidgid hermes', 'env')
            source = source.replace('/opt/hermes/.venv/bin/python3', str(runner))
            source = source.replace('/bin/sleep 3600', 'exit 0')
            subprocess.run(['/bin/sh'], input=source, text=True, check=True, timeout=5,
                           env={'PATH': os.environ['PATH'], 'RECORD': str(record)})
            calls = [json.loads(line) for line in record.read_text().splitlines()]
            self.assertEqual(len(calls), 3)
            setup = calls[1]
            self.assertEqual(setup['base'], 'https://installer-proxy.example')
            self.assertEqual(setup['token'], 'fixture-token')
            self.assertEqual(setup['args'], ['/opt/plow/x-shared/scripts/setup_index.py'])
            self.assertIsNone(calls[2]['token'])
