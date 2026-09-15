"""Mechanical fixtures; only RC-INSTALL-001 originates from a real observed failure."""
import copy, importlib.util, json, sys, tempfile, unittest, hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import evolve
import check_installation as install
class EvolutionTests(unittest.TestCase):
    def incident(self):
        return {'incident_id':'INC-'+'1'*32,'time':'2026-09-12T00:00:00+00:00','failure_type':'runtime-compatibility','cause':'runtime_issue','impact':'high','evidence':['EV-'+'1'*32],'capabilities':['installation'],'repeated':False,'hits':1,'permission':'record'}
    def reviews(self, permission='auto'):
        return [{'permission':permission,'frozen_impact':False,'dimensions':{d:'PASS' for d in evolve.DIMENSIONS}} for _ in range(2)]
    def test_no_incident_no_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);self.assertEqual(evolve.changed(r,r),{});self.assertEqual(list(r.iterdir()),[])
    def test_incident_sensitive_text_rejected(self):
        i=self.incident();i['正文']='sensitive'
        with self.assertRaises(ValueError): evolve.validate_incident(i)
        i=self.incident();i['evidence']=['a business file path']
        with self.assertRaises(ValueError): evolve.validate_incident(i)
    def test_hits_not_inflatable(self):
        i=self.incident();i['hits']=2
        with self.assertRaises(ValueError): evolve.validate_incident(i)
    def test_record_never_generates_evo(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);e=r/'captures';e.mkdir();log=e/'capture.log';log.write_text('sanitized installation failure')
            capture={'evidence_id':'EV-'+'1'*32,'task_instance_id':'task-'+'1'*32,'failure_type':'runtime-compatibility','artifact_path':log.name,'artifact_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'source':'executor-capture','sanitized':True}
            (e/(capture['evidence_id']+'.json')).write_text(json.dumps(capture))
            result=evolve.record(self.incident(),r,evidence=e);self.assertIsNone(result['EVO'])
            self.assertFalse(list(Path(d).rglob('EVO-*')))
    def test_cage_cannot_self_amend(self):
        with self.assertRaises(ValueError): evolve.permission(ROOT,['memory-evolution/permission-cage.json'],{'permission':'approve','approval_ref':'turn-'+'a'*32},[])
    def test_gate_cannot_be_auto_by_name(self):
        with self.assertRaises(ValueError): evolve.permission(ROOT,['core/core.md'],{'permission':'auto','approval_ref':'turn-'+'a'*32},[])
    def test_semantic_review_required(self):
        with self.assertRaises(ValueError): evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto','approval_ref':'turn-'+'a'*32},[{'permission':'auto','frozen_impact':True}])
    def test_auto_path_without_finalize_cannot_release(self):
        with self.assertRaisesRegex(ValueError,'release approval'):
            evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto','approval_ref':None},self.reviews('auto'))
    def test_auto_path_with_candidate_bound_finalize_can_enter_release_gate(self):
        lane=evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto','approval_ref':'turn-'+'a'*32},self.reviews('auto'))
        self.assertEqual(lane,'auto')
    def test_release_approval_requires_explicit_finalize_and_current_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            evidence=Path(d);ref='turn-'+'a'*32;artifact=evidence/'approval.log';artifact.write_text('synthetic explicit user finalize fixture')
            changes={'scripts/check_installation.py':{'before':{'sha256':'1'},'after':{'sha256':'2'}}}
            proposal={'approval_ref':ref,'candidate_sha256':'c'*64,'base_sha256':'b'*64,'summary':'fix-execution-chain'}
            approval={'actor':'user','candidate_sha256':proposal['candidate_sha256'],'base_sha256':proposal['base_sha256'],'changes_sha256':hashlib.sha256(json.dumps(changes,sort_keys=True).encode()).hexdigest(),'approval_ref':ref,'purpose':proposal['summary'],'release_intent':'review-only','source':'executor-capture','approved':True,'artifact_path':artifact.name,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
            (evidence/(ref+'.json')).write_text(json.dumps(approval))
            with self.assertRaisesRegex(ValueError,'explicit finalize intent'): evolve.validate_release_approval(evidence,proposal,changes)
            approval['release_intent']='finalize-stable';(evidence/(ref+'.json')).write_text(json.dumps(approval))
            self.assertEqual(evolve.validate_release_approval(evidence,proposal,changes)['release_intent'],'finalize-stable')
            stale=dict(proposal);stale['candidate_sha256']='d'*64
            with self.assertRaisesRegex(ValueError,'current candidate'): evolve.validate_release_approval(evidence,stale,changes)
    def test_case_binding(self):
        self.assertEqual(len(evolve.cases_for(ROOT,self.incident(),['RC-INSTALL-001'])),1)
        with self.assertRaises(ValueError): evolve.cases_for(ROOT,self.incident(),['fake'])
    def test_user_owned_rule_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';m=json.loads((ROOT/'platform-adapter/installation-manifest.json').read_text())
            m['managed_rules']['user_owned']={str(install.GLOBAL_AGENTS):'0'*64};p.write_text(json.dumps(m))
            with patch.object(install,'INSTALL_MANIFEST',p):
                result=install.check()
            self.assertTrue(any(x['issue']=='user-owned-rule-changed-review-required' for x in result['issues']))
            m['managed_rules']['user_owned'][str(install.GLOBAL_AGENTS)]=install._sha256(install.GLOBAL_AGENTS);p.write_text(json.dumps(m))
            with patch.object(install,'INSTALL_MANIFEST',p): fixed=install.check()
            self.assertFalse(any(x['issue'] in {'managed-block-check-failed','user-owned-rule-changed-review-required'} for x in fixed['issues']))
    def test_failed_regression_cannot_verify(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);c=r/'candidate';e=r/'evidence';(c/'tests').mkdir(parents=True);(c/'scripts').mkdir()
            (c/'tests/test_failure.py').write_text('import unittest\nclass F(unittest.TestCase):\n def test_failure(self): self.fail("controlled fixture")\n')
            (c/'scripts/validate_structure.py').write_text('raise SystemExit(0)\n')
            result=evolve.regress(c,e);self.assertEqual(result['verdict'],'FAIL');self.assertFalse(list(r.rglob('EVO-*')))
            with self.assertRaises(ValueError): evolve.verify_evidence(e,result['candidate_sha256'],result['record_id'],[],['REG1','REG2'])
    def test_deleted_stable_capability_requires_approval(self):
        with self.assertRaises(ValueError): evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto','approval_ref':'turn-'+'a'*32},self.reviews('auto'),deletions=True)
    def test_metadata_hash_tracks_mode(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'file';p.write_text('same');p.chmod(0o600);before=evolve.metadata_hash(root);p.chmod(0o700)
            self.assertNotEqual(before,evolve.metadata_hash(root))
    def test_missing_case_never_passes(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);c=r/'candidate';e=r/'evidence';(c/'tests').mkdir(parents=True);(c/'scripts').mkdir()
            (c/'tests/test_hidden.py').write_text('class Hidden:\n def test_hidden(self): pass\n')
            (c/'scripts/validate_structure.py').write_text('raise SystemExit(0)\n')
            (c/'tests/regression-cases.json').write_text(json.dumps([{'case_id':'RC-HIDDEN','test':'test_hidden.py:test_hidden'}]))
            result=evolve.regress(c,e);self.assertEqual(result['test_results']['RC-HIDDEN'],'FAIL')
    def test_lifecycle_transaction_and_rollback(self):
        import subprocess
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tests/lifecycle_fixture.py'),str(ROOT)],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__': unittest.main()
