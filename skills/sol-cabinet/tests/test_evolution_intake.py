"""Synthetic unit fixtures for intake visibility; never production incident evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import evolve

class IntakeTests(unittest.TestCase):
    def record(self, root, number=1, task=1):
        eid='EV-'+f'{number:032x}'; iid='INC-'+f'{number:032x}'
        tests=root/'tests';tests.mkdir(exist_ok=True)
        (tests/'regression-cases.json').write_text(json.dumps([{'case_id':'RC-INTAKE-001','failure_type':'incident_not_recorded','cause':'execution_failure'}]))
        capture=root/'capture';capture.mkdir(exist_ok=True)
        artifact=capture/f'{number}.log';artifact.write_text('synthetic mechanical failure')
        item={'incident_id':iid,'time':'2026-09-13T00:00:00+00:00','failure_type':'incident_not_recorded','cause':'execution_failure','impact':'ordinary','evidence':[eid],'capabilities':['maintenance'],'repeated':False,'hits':1,'permission':'record'}
        data={'evidence_id':eid,'task_instance_id':'task-'+f'{task:032x}','failure_type':item['failure_type'],'artifact_path':artifact.name,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'source':'executor-capture','sanitized':True}
        (capture/(eid+'.json')).write_text(json.dumps(data))
        evolve.record(item,root,evidence=capture)
        return item

    def test_empty_status_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.assertEqual(evolve.status(root)['status'],'CLEAR')
            self.assertEqual(list(root.iterdir()),[])

    def test_ordinary_incident_visible_before_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.record(root)
            state=evolve.status(root)
            self.assertEqual(state['pending_count'],1)
            self.assertEqual(state['incidents'][0]['status'],'pending')
            self.assertEqual(state['candidates'],[])

    def test_repetition_uses_distinct_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.record(root,1,1);self.record(root,2,1)
            self.assertTrue(all(not i['repeated'] for i in evolve.status(root)['incidents']))
            self.record(root,3,2)
            self.assertTrue(all(i['independent_tasks']==2 and i['repeated'] for i in evolve.status(root)['incidents']))

    def test_closed_requires_valid_evidence_and_recurrence_reopens(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            p=root/'memory-evolution/proposals'/('RES-'+'a'*32+'.json')
            p.write_text(json.dumps({'resolution_id':'RES-'+'a'*32,'incident_id':incident['incident_id'],'evidence':incident['evidence'],'candidate_sha256':'a'*64,'test_run_id':'testrun-'+'a'*32,'review_ids':[],'required_test_ids':['RC-INTAKE-001']}))
            self.assertEqual(evolve.status(root)['pending_count'],1)
            # Isolate status coverage semantics; authentication/evidence validation stays in the existing verifier.
            with patch.object(evolve,'verify_evidence',return_value={'verdict':'PASS'}):
                self.assertEqual(evolve.status(root)['pending_count'],0)
                catalog=root/'tests/regression-cases.json'
                cases=json.loads(catalog.read_text())
                cases.append({'case_id':'RC-NEW-CURRENT','failure_type':'incident_not_recorded','cause':'execution_failure'})
                catalog.write_text(json.dumps(cases))
                self.assertEqual(evolve.status(root)['pending_count'],0)
                second=self.record(root,2,2)
                incident['evidence']+=second['evidence'];incident['hits']=2;incident['repeated']=True
                evolve.record(incident,root,evidence=root/'capture')
                self.assertEqual(evolve.status(root)['pending_count'],1)
                self.assertEqual(evolve.status(root)['pending_incident_count'],2)

    def test_resolve_rejects_stale_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            with patch.object(evolve,'system_digest',return_value='b'*64):
                with self.assertRaises(ValueError):
                    evolve.resolve(incident['incident_id'],{'candidate_sha256':'a'*64,'test_run_id':'testrun-'+'a'*32,'review_ids':[],'required_test_ids':['RC-INTAKE-001']},root/'capture',root)
            self.assertFalse(list((root/'memory-evolution/proposals').glob('RES-*')))

    def test_unrelated_passing_tests_cannot_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            resolution={'candidate_sha256':'a'*64,'test_run_id':'testrun-'+'a'*32,'review_ids':[],'required_test_ids':['unrelated-passing-test']}
            with patch.object(evolve,'system_digest',return_value='a'*64), patch.object(evolve,'verify_evidence',return_value={'verdict':'PASS'}) as verifier:
                with self.assertRaisesRegex(ValueError,'incident-specific'):
                    evolve.resolve(incident['incident_id'],resolution,root/'capture',root)
                verifier.assert_not_called()
            self.assertFalse(list((root/'memory-evolution/proposals').glob('RES-*')))

    def test_incident_mutation_at_lock_refuses_resolution(self):
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            @contextlib.contextmanager
            def changed_lock(_):
                changed=dict(incident);changed['impact']='high'
                (root/'memory-evolution/observations'/(incident['incident_id']+'.json')).write_text(json.dumps(changed))
                yield
            resolution={'candidate_sha256':'a'*64,'test_run_id':'testrun-'+'a'*32,'review_ids':[],'required_test_ids':['RC-INTAKE-001']}
            with patch.object(evolve,'system_digest',return_value='a'*64),patch.object(evolve,'verify_evidence'),patch.object(evolve,'lock',changed_lock):
                with self.assertRaisesRegex(ValueError,'incident changed'):
                    evolve.resolve(incident['incident_id'],resolution,root/'capture',root)
            self.assertFalse(list((root/'memory-evolution/proposals').glob('RES-*')))

    def test_candidate_mutation_at_lock_refuses_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            resolution={'candidate_sha256':'a'*64,'test_run_id':'testrun-'+'a'*32,'review_ids':[],'required_test_ids':['RC-INTAKE-001']}
            with patch.object(evolve,'system_digest',side_effect=['a'*64,'b'*64]),patch.object(evolve,'verify_evidence'):
                with self.assertRaisesRegex(ValueError,'candidate changed'):
                    evolve.resolve(incident['incident_id'],resolution,root/'capture',root)
            self.assertFalse(list((root/'memory-evolution/proposals').glob('RES-*')))

    def test_retained_evidence_is_reverified_before_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root);capture=root/'capture';rid='testrun-'+'a'*32
            (capture/(rid+'.json')).write_text(json.dumps({'artifact_path':'test.log'}))
            (capture/'test.log').write_text('synthetic test evidence')
            resolution={'candidate_sha256':'a'*64,'test_run_id':rid,'review_ids':[],'required_test_ids':['RC-INTAKE-001']}
            with patch.object(evolve,'system_digest',return_value='a'*64),patch.object(evolve,'verify_evidence',side_effect=[{'verdict':'PASS'},ValueError('copied evidence rejected')]) as verifier:
                with self.assertRaisesRegex(ValueError,'copied evidence rejected'):
                    evolve.resolve(incident['incident_id'],resolution,capture,root)
                self.assertEqual(verifier.call_count,2)
                self.assertNotEqual(verifier.call_args_list[0].args[0],verifier.call_args_list[1].args[0])
            self.assertFalse(list((root/'memory-evolution/proposals').glob('RES-*')))

    def test_candidate_status_visible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);incident=self.record(root)
            p=root/'memory-evolution/proposals/candidate.json'
            p.write_text(json.dumps({'incident_id':incident['incident_id'],'status':'pending-approval'}))
            self.assertEqual(evolve.status(root)['candidates'][0]['status'],'pending-approval')

if __name__=='__main__': unittest.main()
