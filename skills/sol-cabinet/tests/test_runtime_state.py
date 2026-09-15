"""Focused regressions for GitHub/Runtime deployment-state separation."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / 'scripts' / 'deployment_state.py'
    spec = importlib.util.spec_from_file_location('sol_deployment_state_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load_module()


class RuntimeStateTests(unittest.TestCase):
    def valid_record(self, commit='a' * 40, digest='b' * 64, version='1.5.1'):
        return {
            'schema_version': 1,
            'record_kind': 'runtime-deployment-state',
            'repository': state.REPOSITORY,
            'repository_path': state.REPOSITORY_PATH,
            'source_commit': commit,
            'source_version': version,
            'source_system_sha256': digest,
            'runtime_root': str(ROOT.resolve()),
            'runtime_system_sha256': digest,
            'deployed_at': '2026-09-16T00:00:00+00:00',
            'verified_at': '2026-09-16T00:00:00+00:00',
        }

    def test_missing_state_is_untracked_not_guessed(self):
        self.assertEqual(state.classify(None, ROOT)['state'], 'UNTRACKED')

    def test_matching_runtime_is_synced(self):
        record = self.valid_record()
        with mock.patch.object(state, '_digest', return_value='b' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.1'):
            result = state.classify(record, ROOT, expected_commit='a' * 40)
        self.assertEqual(result['state'], 'SYNCED')
        self.assertEqual(result['source_commit'], 'a' * 40)

    def test_consistent_runtime_at_other_commit_is_stale(self):
        record = self.valid_record(commit='a' * 40)
        with mock.patch.object(state, '_digest', return_value='b' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.1'):
            result = state.classify(record, ROOT, expected_commit='c' * 40)
        self.assertEqual(result['state'], 'STALE')

    def test_changed_runtime_bytes_are_drifted(self):
        record = self.valid_record()
        with mock.patch.object(state, '_digest', return_value='d' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.1'):
            result = state.classify(record, ROOT)
        self.assertEqual(result['state'], 'DRIFTED')

    def test_changed_runtime_version_is_drifted(self):
        record = self.valid_record(version='1.5.1')
        with mock.patch.object(state, '_digest', return_value='b' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.2'):
            result = state.classify(record, ROOT)
        self.assertEqual(result['state'], 'DRIFTED')

    def test_capture_refuses_runtime_that_does_not_match_selected_source(self):
        with mock.patch.object(state, '_digest', return_value='d' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.1'):
            with self.assertRaises(ValueError):
                state.build_state('a' * 40, 'b' * 64, ROOT)

    def test_capture_binds_commit_version_and_digest(self):
        stamp = datetime(2026, 9, 16, tzinfo=timezone.utc)
        with mock.patch.object(state, '_digest', return_value='b' * 64), \
             mock.patch.object(state, '_version', return_value='1.5.1'):
            record = state.build_state('a' * 40, 'b' * 64, ROOT, now=stamp)
        self.assertEqual(record['source_commit'], 'a' * 40)
        self.assertEqual(record['source_version'], '1.5.1')
        self.assertEqual(record['source_system_sha256'], 'b' * 64)
        self.assertEqual(record['runtime_system_sha256'], 'b' * 64)

    def test_historical_snapshot_and_manifest_are_not_live_checker_inputs(self):
        checker = (ROOT / 'scripts/check_installation.py').read_text(encoding='utf-8')
        self.assertNotIn('installation-manifest.json', checker)
        self.assertNotIn('runtime-snapshot.json', checker)
        self.assertIn('deployment_state.classify', checker)

    def test_checker_separates_content_only_from_deployment_verdict(self):
        checker = (ROOT / 'scripts/check_installation.py').read_text(encoding='utf-8')
        self.assertIn('deployment_scope = expected_commit is not None', checker)
        self.assertIn('"scope": "deployment" if deployment_scope else "content-only"', checker)
        self.assertIn('if deployment_scope and runtime["state"] != "SYNCED"', checker)


if __name__ == '__main__':
    unittest.main()
