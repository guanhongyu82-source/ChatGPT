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
        with self.assertRaises(ValueError): evolve.permission(ROOT,['core/core.md'],{'permission':'auto'},[])
    def test_semantic_review_required(self):
        with self.assertRaises(ValueError): evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto'},[{'permission':'auto','frozen_impact':True}])
    def test_case_binding(self):
        self.assertEqual(len(evolve.cases_for(ROOT,self.incident(),['RC-INSTALL-001'])),1)
        with self.assertRaises(ValueError): evolve.cases_for(ROOT,self.incident(),['fake'])
    def test_user_owned_rule_drift_is_rejected(self):
        # Exercise real checker with current external rules; no external writes.
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';m=json.loads((ROOT/'platform-adapter/installation-manifest.json').read_text())
            m['managed_rules']['user_owned']={str(install.GLOBAL_AGENTS):'0'*64};p.write_text(json.dumps(m))
            with patch.object(install,'INSTALL_MANIFEST',p):
                result=install.check()
            self.assertTrue(any(x['issue']=='user-owned-rule-changed-review-required' for x in result['issues']))
            # Positive repair: real user-owned governance accepted with exact hash.
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
        reviews=[{'permission':'auto','frozen_impact':False,'dimensions':{d:'PASS' for d in evolve.DIMENSIONS}}]*2
        with self.assertRaises(ValueError): evolve.permission(ROOT,['scripts/check_installation.py'],{'permission':'auto'},reviews,deletions=True)
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
