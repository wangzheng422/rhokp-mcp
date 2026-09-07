#!/usr/bin/env python3
# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Offline orchestration checks; mocked oc does not validate cluster admission."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallerTests(unittest.TestCase):
    def test_dry_run_preserves_tokens_and_never_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / 'key'
            key.write_text('x' * 32 + '\n')
            key.chmod(0o600)
            log = root / 'oc.log'
            mock = root / 'oc'
            mock.write_text('''#!/usr/bin/env python3
import base64, json, os, sys
args=sys.argv[1:]
with open(os.environ['TEST_OC_LOG'], 'a') as f: f.write(json.dumps(args)+'\\n')
if 'apply' in args and args[-1].endswith('/rhokp-openshift.yaml'):
 with open(args[-1]) as f: manifest=f.read()
 with open(os.environ['TEST_OC_MANIFEST'], 'w') as f: f.write(manifest)
if 'jsonpath={.data.token}' in args:
 print(base64.b64encode(b't'*64).decode())
elif 'jsonpath={.data.header}' in args:
 print(base64.b64encode(b'Bearer '+b't'*64).decode())
elif 'create' in args:
 print('apiVersion: v1\\nkind: Secret\\nmetadata:\\n  name: mock')
''')
            mock.chmod(0o700)
            rendered = root / 'rendered.yaml'
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], TEST_OC_LOG=str(log), TEST_OC_MANIFEST=str(rendered))
            script = Path(__file__).resolve().parents[1] / 'deploy/openshift/deploy.sh'
            result = subprocess.run(['bash', str(script), '--access-key-file', str(key),
                '--rhokp-image', 'registry.example/portal@sha256:'+'a'*64,
                '--mcp-image', 'registry.example/mcp@sha256:'+'b'*64,
                '--dry-run-only'], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('mcp_auth_action=preserved', result.stdout)
            self.assertNotIn('t'*64, result.stdout+result.stderr)
            self.assertNotIn('x'*32, result.stdout+result.stderr)
            import json
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            applies = [args for args in calls if 'apply' in args]
            self.assertTrue(applies)
            self.assertTrue(all('--dry-run=server' in args for args in applies))
            self.assertFalse(any('create' in args and
                ('rhokp-mcp-auth' in args or 'rhokp-mcp-server-auth' in args) for args in calls))
            self.assertFalse(any('configmap' in args for args in calls))
            # Controlled template output: exact indentation distinguishes portal
            # Pod security from MCP container security; no YAML package needed.
            baseline = rendered.read_text()
            self.assertEqual(baseline.count('\n        runAsNonRoot: true\n'), 1)
            self.assertNotIn('        runAsUser: 0\n', baseline)
            result = subprocess.run(result.args + ['--portal-run-as-root'], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(rendered.read_text(), baseline.replace(
                '\n        runAsNonRoot: true\n',
                '\n        runAsNonRoot: false\n        runAsUser: 0\n', 1))


if __name__ == '__main__':
    unittest.main()
