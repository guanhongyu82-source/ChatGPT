"""Focused regressions for the September delivery failures."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

gate = load('delivery_gate')
classifier = load('classify_task')

class DeliveryRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / '2026-09-13_方案_协作机制_v1.docx'
        self.artifact.write_bytes(b'candidate')
        digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.evidence = self.root / 'review.json'
        self.c = {'task_id':'task-1','t_level':4,'formal_normative_additions':True,
                  'opening_notice':True,'summary_present':True,'incident_present':False,
                  'timing':{'started_at':'2026-09-13T01:00:00Z','ended_at':'2026-09-13T01:05:00Z','basis':'user-message to pre-delivery'},
                  'storage':{'output_root':str(self.root),'archive_status':'deferred','archive_reason':'host fixes outputs path'},
                  'artifacts':[{'path':str(self.artifact),'sha256':digest}],
                  'reviews':[{'reviewer_id':'reviewer-1','author_id':'lead','evidence_path':str(self.evidence),'candidate_sha256':{str(self.artifact):digest},'verdict':'PASS','must_fix':[]}],
                  'retention':{'process_root':None,'temporary_files':[],'retained_reason':{str(self.evidence):'required review evidence'}}}
        self.c['reviews'][0]['source_ref']='tool:reviewer-1/message:result-1'
        self.write_evidence()
    def write_evidence(self):
        review=self.c['reviews'][0]
        self.evidence.write_text(json.dumps({k:review[k] for k in ('reviewer_id','author_id','verdict','must_fix','candidate_sha256','source_ref')}))
        review['evidence_sha256']=hashlib.sha256(self.evidence.read_bytes()).hexdigest()
    def test_apology_without_incident_record_fails(self):
        self.c['incident_present']=True
        self.c['incident_disposition']='已道歉并修复'
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_existing_incident_record_passes(self):
        self.c['incident_present']=True
        self.c['incident_disposition']='已修复并复用现有事故记录'
        record=self.root/'incident.json'
        record.write_text(json.dumps({'incident_id':'INC-'+'1'*32,'permission':'record','failure_type':'delivery-omission','evidence':['message:failure-1']}))
        self.c['incident_records']=[str(record)]
        self.c['retention']['retained_reason'][str(record)]='existing incident evidence'
        self.assertEqual(gate.check(self.c)['state'],'PASS')
        record.write_text(json.dumps({'incident_id':'INC-'+'1'*32,'permission':'record','failure_type':'delivery-omission','evidence':[]}))
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_unlisted_process_file_fails(self):
        process=self.root/'work'
        process.mkdir()
        stray=process/'forgotten.txt';stray.write_text('scratch')
        self.c['retention']['process_root']=str(process)
        self.c['retention']['retained_reason'][str(process)]='task evidence directory'
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.c['retention']['retained_reason'][str(stray)]='required diagnostic evidence'
        self.assertEqual(gate.check(self.c)['state'],'PASS')
    def test_unlisted_output_and_contract_exclusion(self):
        stray=self.root/'forgotten.txt';stray.write_text('scratch')
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.assertEqual(gate.check(self.c,contract_path=stray)['state'],'PASS')
    def test_changed_review_bytes_fail(self):
        self.evidence.write_text(self.evidence.read_text()+' ')
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_recorded_failure_cannot_be_overridden(self):
        record=json.loads(self.evidence.read_text())
        record['verdict']='FAIL'
        self.evidence.write_text(json.dumps(record))
        self.c['reviews'][0]['evidence_sha256']=hashlib.sha256(self.evidence.read_bytes()).hexdigest()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_missing_review_hash_and_source_reference_fail(self):
        saved=copy.deepcopy(self.c)
        self.c['reviews'][0].pop('evidence_sha256')
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.c=saved
        self.c['reviews'][0]['source_ref']=''
        self.write_evidence()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_cli_fails_closed_on_invalid_contract(self):
        contract=self.root/'contract.json'
        contract.write_text(json.dumps({'storage':{'output_root':17}}))
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/'delivery_gate.py'),'--contract',str(contract)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stdout)['state'],'FAIL')
    def test_host_output_and_honest_deferred_archive_pass(self):
        self.assertEqual(gate.check(self.c)['state'],'PASS')
    def test_formal_additions_cannot_take_bounded_shortcut(self):
        result = classifier.classify({'formal_normative_additions':True,'bounded_edit':True,'file_count':1})
        self.assertGreaterEqual(result['t_level'],4)
        self.assertFalse(result['bounded_edit_short_path'])
    def test_t3_formal_additions_fail(self):
        self.c['t_level']=3
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_missing_and_stale_review_fail(self):
        for mutation in ('missing','stale'):
            c=copy.deepcopy(self.c)
            if mutation=='missing': c['reviews']=[]
            else: self.artifact.write_bytes(b'changed')
            self.assertEqual(gate.check(c)['state'],'FAIL')
    def test_missing_opening_summary_and_incident_disposition_fail(self):
        for field in ('opening_notice','summary_present','incident_present'):
            c=copy.deepcopy(self.c)
            c[field]=(field=='incident_present')
            self.assertEqual(gate.check(c)['state'],'FAIL')
    def test_unexplained_timing_and_false_archive_fail(self):
        self.c['timing']={}
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.c['timing']={'unavailable_reason':'no reliable timestamp supplied'}
        self.assertEqual(gate.check(self.c)['state'],'PASS')
        self.c['storage']['archive_status']='done'
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_unjustified_temp_and_bad_name_fail(self):
        self.c['retention']['retained_reason'].pop(str(self.evidence))
        self.c['retention']['temporary_files']=[str(self.evidence)]
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.c['retention']['retained_reason'][str(self.evidence)]='required review evidence'
        self.assertEqual(gate.check(self.c)['state'],'PASS')
        p=self.root/'new.docx';self.artifact.rename(p)
        self.c['artifacts'][0]['path']=str(p)
        self.assertEqual(gate.check(self.c)['state'],'FAIL')

if __name__=='__main__':
    unittest.main()
