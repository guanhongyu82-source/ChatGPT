import copy
import json
import tempfile
import unittest
from pathlib import Path
from test_sol_cabinet import make_evidence, proposal_validator, improvement_manager, evolution, ROOT
import test_sol_cabinet as fixtures


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.proposal = dict(test_run_id='testrun-' + 'a' * 32,
                             independent_review_ids=['review-' + 'b' * 32, 'review-' + 'c' * 32],
                             candidate_sha256='d' * 64, required_test_ids=['A01'])
        make_evidence(self.path, self.proposal)

    def verify(self):
        p = self.proposal
        return proposal_validator.verify_evidence(self.path, p['candidate_sha256'], p['test_run_id'], p['independent_review_ids'], p['required_test_ids'])

    def mutate(self, index, **changes):
        key = [self.proposal['test_run_id'], *self.proposal['independent_review_ids']][index]
        path = self.path / (key + '.json')
        raw = json.loads(path.read_text()); raw.update(changes); path.write_text(json.dumps(raw))

    def test_real_record_passes(self):
        self.assertEqual(self.verify()['verdict'], 'PASS')

    def test_bad_records_fail_closed(self):
        for index, changes in [(0, {'verdict': 'FAIL'}), (0, {'exit_code': 1}),
            (0, {'exit_code': False}), (0, {'error_type': 'TimeoutError'}),
            (0, {'test_results': {}}), (0, {'test_results': {'A01': 'PASS', 'A02': 'FAIL'}}),
            (0, {'candidate_sha256': 'e' * 64}), (0, {'kind': 'review'}),
            (0, {'artifact_sha256': 'f' * 64}), (0, {'artifact_path': '../escape.log'}),
            (1, {'reviewer_id': None}), (2, {'reviewer_id': 'agent-' + '1' * 16}),
            (1, {'reviewer_id': 'agent-' + '0' * 16}), (1, {'independent': False})]:
            with self.subTest(changes=changes):
                make_evidence(self.path, self.proposal)
                self.mutate(index, **changes)
                with self.assertRaises(ValueError): self.verify()

    def test_review_requires_empty_must_fix_array(self):
        for index in (1, 2):
            for value in (None, "", {}, False, ["unresolved defect"]):
                with self.subTest(index=index, value=value):
                    make_evidence(self.path, self.proposal)
                    self.mutate(index, must_fix=value)
                    with self.assertRaises(ValueError): self.verify()
            make_evidence(self.path, self.proposal)
            record_id = self.proposal['independent_review_ids'][index - 1]
            path = self.path / (record_id + '.json')
            record = json.loads(path.read_text())
            del record['must_fix']
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError): self.verify()

    def test_real_canonical_tool_identities(self):
        self.mutate(1, reviewer_id='/root/reviewer_one', author_id='/root')
        self.mutate(2, reviewer_id='/root/reviewer_two', author_id='/root')
        self.assertEqual(self.verify()['verdict'], 'PASS')
        self.mutate(2, reviewer_id='/root/reviewer_one')
        with self.assertRaises(ValueError): self.verify()
        self.mutate(2, reviewer_id='/root')
        with self.assertRaises(ValueError): self.verify()

    def test_opaque_identity_bounds_and_controls(self):
        for field in ('reviewer_id', 'author_id'):
            for value in ('', '   ', 'x' * 257, '/root/\nreviewer', '/root/\x00reviewer', '/root/\u200breviewer', None, 7):
                with self.subTest(field=field, value=repr(value)):
                    make_evidence(self.path, self.proposal)
                    self.mutate(1, **{field: value})
                    with self.assertRaises(ValueError): self.verify()

    def test_missing_and_mutated_artifact_fail(self):
        log = self.path / (self.proposal['test_run_id'] + '.log')
        log.write_text('changed')
        with self.assertRaises(ValueError): self.verify()
        log.unlink()
        with self.assertRaises(ValueError): self.verify()

    def test_missing_record_and_duplicate_review_fail(self):
        record = self.path / (self.proposal['independent_review_ids'][0] + '.json')
        record.unlink()
        with self.assertRaises(ValueError): self.verify()
        self.proposal['independent_review_ids'] *= 2
        with self.assertRaises(ValueError): self.verify()

    def test_post_apply_requires_execution_phase(self):
        self.mutate(0, phase='candidate')
        p = self.proposal
        with self.assertRaises(ValueError):
            proposal_validator.verify_evidence(self.path, p['candidate_sha256'], p['test_run_id'], p['independent_review_ids'], ['A01'], require_post_apply=True)

    def test_pending_cannot_close_even_with_date(self):
        registry = json.loads((ROOT / 'memory-evolution/improvements.json').read_text())
        item = next(i for i in registry['items'] if i['verification_code'].startswith('pending-'))
        for status in ['CLOSED', 'VERIFIED']:
            with self.assertRaises(ValueError):
                improvement_manager.validate_item({**item, 'status': status, 'last_verified_date': '2026-09-07'})

    def test_persistence_denied_without_explicit_authorization(self):
        item = json.loads((ROOT / 'memory-evolution/improvements.json').read_text())['items'][0]
        with self.assertRaises(ValueError):
            improvement_manager.upsert_item(item, self.path / 'improvements.json', allow_test_output=True)
        self.assertFalse((self.path / 'improvements.json').exists())
        with self.assertRaises(ValueError):
            evolution.write_observation(fixtures.EvolutionTests().base_entry(), self.path / "observations", allow_test_output=True)
        self.assertFalse((self.path / "observations").exists())
        with self.assertRaises(ValueError):
            improvement_manager.retire_observations([], 'OL-001', registry_path=self.path / 'missing.json', allow_test_output=True)

if __name__ == '__main__': unittest.main()
