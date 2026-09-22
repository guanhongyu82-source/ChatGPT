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
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

gate = load('delivery_gate')
classifier = load('classify_task')
archive = load('archive_originals')

class DeliveryRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / '2026-09-13_方案_协作机制_v1.docx'
        self.artifact.write_bytes(b'candidate')
        self.task_card = self.root / 'task-card.json'
        self.card = {
            'task_instance_id':'task-1',
            'deliverables':[{
                'artifact_id':'main-doc',
                'required':True,
                'format':'.docx',
                'target_role':'final',
                'target_directory':str(self.root),
                'filename_override':None,
            }],
        }
        self.write_task_card()
        digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.evidence = self.root / 'review.json'
        self.c = {'task_id':'task-1','t_level':4,'formal_normative_additions':True,
                  'opening_notice':True,'summary_present':True,'incident_present':False,
                  'timing':{'started_at':'2026-09-13T01:00:00Z','ended_at':'2026-09-13T01:05:00Z','basis':'user-message to pre-delivery'},
                  'storage':{'output_root':str(self.root),'archive_status':'deferred','archive_reason':'host fixes outputs path'},
                  'task_card':{'path':str(self.task_card),'sha256':hashlib.sha256(self.task_card.read_bytes()).hexdigest()},
                  'artifacts':[{'artifact_id':'main-doc','role':'final','path':str(self.artifact),'sha256':digest}],
                  'reviews':[{'reviewer_id':'reviewer-1','author_id':'lead','evidence_path':str(self.evidence),'candidate_sha256':{str(self.artifact):digest},'verdict':'PASS','must_fix':[]}],
                  'retention':{'process_root':None,'temporary_files':[],'retained_reason':{str(self.evidence):'required review evidence',str(self.task_card):'locked expected artifact contract'}}}
        self.c['reviews'][0]['source_ref']='tool:reviewer-1/message:result-1'
        self.write_evidence()
    def write_task_card(self):
        self.task_card.write_text(json.dumps(self.card,ensure_ascii=False))
    def relock_task_card(self):
        self.write_task_card()
        self.c['task_card']['sha256']=hashlib.sha256(self.task_card.read_bytes()).hexdigest()
    def write_evidence(self):
        review=self.c['reviews'][0]
        self.evidence.write_text(json.dumps({k:review[k] for k in ('reviewer_id','author_id','verdict','must_fix','candidate_sha256','source_ref')}))
        review['evidence_sha256']=hashlib.sha256(self.evidence.read_bytes()).hexdigest()
    def refresh_artifact_review(self):
        digest=hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.c['artifacts'][0]['path']=str(self.artifact)
        self.c['artifacts'][0]['sha256']=digest
        self.c['reviews'][0]['candidate_sha256']={str(self.artifact):digest}
        self.write_evidence()
    def test_expected_actual_baseline_passes(self):
        self.assertEqual(gate.check(self.c)['state'],'PASS')
    def test_required_expected_artifact_missing_fails(self):
        self.c['artifacts']=[]
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_unauthorized_extra_artifact_fails(self):
        extra=self.root/'2026-09-13_附件_额外材料_v1.pdf';extra.write_bytes(b'extra')
        self.c['artifacts'].append({'artifact_id':'extra','role':'final','path':str(extra),'sha256':hashlib.sha256(extra.read_bytes()).hexdigest()})
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_wrong_format_location_and_role_fail(self):
        bad=self.root/'2026-09-13_方案_协作机制_v1.pdf';bad.write_bytes(b'candidate')
        self.c['artifacts'][0].update(path=str(bad),sha256=hashlib.sha256(bad.read_bytes()).hexdigest())
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.c['artifacts'][0].update(path=str(self.artifact),sha256=hashlib.sha256(self.artifact.read_bytes()).hexdigest(),role='candidate')
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        sub=self.root/'other';sub.mkdir();moved=sub/self.artifact.name;self.artifact.rename(moved)
        self.c['artifacts'][0].update(path=str(moved),role='final',sha256=hashlib.sha256(moved.read_bytes()).hexdigest())
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_filename_override_comes_only_from_expected(self):
        self.card['deliverables'][0]['filename_override']='用户指定名称.docx'
        self.relock_task_card()
        renamed=self.root/'用户指定名称.docx';self.artifact.rename(renamed);self.artifact=renamed
        self.refresh_artifact_review()
        self.assertEqual(gate.check(self.c)['state'],'PASS')
        self.c['artifacts'][0]['user_filename_override']=True
        self.artifact.rename(self.root/'执行端自定名.docx');self.artifact=self.root/'执行端自定名.docx'
        self.refresh_artifact_review()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_task_card_change_without_relock_fails(self):
        self.card['deliverables'].append({'artifact_id':'new-required','required':True,'format':'.pdf','target_role':'final','target_directory':str(self.root),'filename_override':None})
        self.write_task_card()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
    def test_user_reduces_deliverables_and_relocks_passes(self):
        self.card['deliverables'].append({'artifact_id':'optional-pdf','required':False,'format':'.pdf','target_role':'final','target_directory':str(self.root),'filename_override':None})
        self.relock_task_card()
        self.assertEqual(gate.check(self.c)['state'],'PASS')
        self.card['deliverables']=self.card['deliverables'][:1]
        self.relock_task_card()
        self.assertEqual(gate.check(self.c)['state'],'PASS')
    def test_task_card_identity_and_duplicate_ids_fail(self):
        self.card['task_instance_id']='other-task';self.relock_task_card()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
        self.card['task_instance_id']='task-1';self.card['deliverables'].append(copy.deepcopy(self.card['deliverables'][0]));self.relock_task_card()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')
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
        p=self.root/'new.docx';self.artifact.rename(p);self.artifact=p
        self.refresh_artifact_review()
        self.assertEqual(gate.check(self.c)['state'],'FAIL')

class TaskLifecycleRules(unittest.TestCase):
    subject = '纪检监察_海勤工程'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/Users/macbook/ChatGPT/.scratch')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / gate.task_root_name('2026-09-22', self.subject)
        self.root.mkdir()
        (self.root / 'work').mkdir()
        (self.root / 'outputs').mkdir()
        self.incoming = self.base / 'incoming'
        self.incoming.mkdir()
        self.task_id = 'task-' + 'a' * 32
        self.versions = []

    def _source(self, name, payload, folder=None):
        directory = self.incoming if folder is None else self.base / folder
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_bytes(payload)
        return path

    def _archive(self, sources, batch_date):
        return archive.archive_originals(
            self.root,
            [('reference', source) for source in sources],
            allow_test_output=True,
            batch_date=batch_date,
        )

    def _add_version(self, formed_date, version, material_batches):
        self.assertEqual(gate.next_formal_version(self.root / 'outputs'), version)
        filename = f'{formed_date}_{self.subject}_{version}.pptx'
        (self.root / 'outputs' / filename).write_bytes(version.encode('ascii'))
        self.versions.append({
            'version': version,
            'formed_date': formed_date,
            'filename': filename,
            'material_batches': list(material_batches),
        })

    def _write_contract(self):
        current = self.versions[-1]
        current_path = self.root / 'outputs' / current['filename']
        manifest_path = self.root / '00_原稿' / '原稿清单.json'
        card = {
            'schema_version': 2,
            'task_instance_id': self.task_id,
            'lifecycle': {
                'task_root': str(self.root),
                'last_substantive_date': self.root.name[:10],
                'state': 'DELIVERED',
                'reopen_count': max(0, len(self.versions) - 1),
                'material_manifest': str(manifest_path),
                'material_batches': sorted({
                    batch for item in self.versions for batch in item['material_batches']
                }),
                'current_version': current['version'],
                'formal_versions': [
                    {
                        'version': item['version'],
                        'formed_date': item['formed_date'],
                        'material_batches': item['material_batches'],
                    }
                    for item in self.versions
                ],
            },
            'deliverables': [{
                'artifact_id': 'current-deck',
                'required': True,
                'format': '.pptx',
                'target_role': 'final',
                'target_directory': str(self.root / 'outputs'),
                'filename_override': None,
            }],
        }
        self.card_path = self.root / 'work' / 'task-card.json'
        self.card_path.write_text(json.dumps(card, ensure_ascii=False), encoding='utf-8')
        history = []
        for item in self.versions:
            path = self.root / 'outputs' / item['filename']
            history.append({
                'version': item['version'],
                'formed_date': item['formed_date'],
                'material_batches': item['material_batches'],
                'artifacts': [{
                    'path': str(path),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                }],
            })
        contract = {
            'task_id': self.task_id,
            't_level': 3,
            'formal_normative_additions': False,
            'opening_notice': True,
            'summary_present': True,
            'incident_present': False,
            'timing': {
                'started_at': '2026-09-22T01:00:00Z',
                'ended_at': '2026-09-22T01:05:00Z',
                'basis': 'task-lifecycle-fixture',
            },
            'storage': {
                'output_root': str(self.root / 'outputs'),
                'archive_status': 'done',
                'archive_root': str(self.root),
            },
            'task_card': {
                'path': str(self.card_path),
                'sha256': hashlib.sha256(self.card_path.read_bytes()).hexdigest(),
            },
            'artifacts': [{
                'artifact_id': 'current-deck',
                'role': 'final',
                'path': str(current_path),
                'sha256': hashlib.sha256(current_path.read_bytes()).hexdigest(),
            }],
            'reviews': [],
            'retention': {
                'process_root': str(self.root / 'work'),
                'temporary_files': [],
                'retained_reason': {str(self.card_path): 'locked expected artifact contract'},
            },
            'lifecycle': {
                'task_root': str(self.root),
                'task_id': self.task_id,
                'last_substantive_date': self.root.name[:10],
                'state': 'DELIVERED',
                'original_inputs_state': 'PASS',
                'material_manifest': str(manifest_path),
                'current_version': current['version'],
                'formal_versions': history,
                'finalization_gates': {name: 'PASS' for name in gate.FINALIZATION_GATES},
                'final_validation': 'PASS',
            },
        }
        self.contract_path = self.root / 'work' / 'delivery-contract.json'
        self.contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
        return contract

    def _final_pass(self):
        contract = self._write_contract()
        return gate.check(contract, contract_path=self.contract_path)

    def _build_v1(self):
        sources = [
            self._source('材料01.txt', b'one'),
            self._source('材料02.txt', b'two'),
            self._source('材料03.txt', b'three'),
            self._source('材料04.txt', b'four'),
        ]
        result = self._archive(sources, '2026-09-22')
        self.assertEqual(result['batch_id'], 'B01')
        self._add_version('2026-09-22', 'v1', ['B01'])

    def _build_v2_same_day(self):
        self._build_v1()
        extra = self._source('领导补充.txt', b'five')
        result = self._archive([extra], '2026-09-22')
        self.assertEqual(result['batch_id'], 'B02')
        self._add_version('2026-09-22', 'v2', ['B01', 'B02'])

    def test_t1_initial_task_creates_b01_v1_and_final_pass(self):
        self._build_v1()
        result = self._final_pass()
        self.assertEqual(result['state'], 'PASS', result['issues'])
        self.assertEqual(self.root.name, '2026-09-22_' + self.subject)
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v1.pptx').is_file())
        manifest = json.loads((self.root / '00_原稿' / '原稿清单.json').read_text(encoding='utf-8'))
        self.assertEqual([batch['batch_id'] for batch in manifest['batches']], ['B01'])

    def test_t2_same_day_supplement_keeps_root_and_v1_and_creates_v2(self):
        self._build_v2_same_day()
        result = self._final_pass()
        self.assertEqual(result['state'], 'PASS', result['issues'])
        self.assertEqual(self.root.name, '2026-09-22_' + self.subject)
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v1.pptx').is_file())
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v2.pptx').is_file())

    def test_t3_cross_day_reopen_keeps_task_id_and_history_and_creates_v3(self):
        self._build_v2_same_day()
        old_root = self.root
        new_root = old_root.parent / gate.task_root_name('2026-09-23', self.subject)
        old_root.rename(new_root)
        self.root = new_root
        sources = [
            self._source('跨日补充01.txt', b'six', 'incoming-day-2'),
            self._source('跨日补充02.txt', b'seven', 'incoming-day-2'),
            self._source('跨日补充03.txt', b'eight', 'incoming-day-2'),
        ]
        result = self._archive(sources, '2026-09-23')
        self.assertEqual(result['batch_id'], 'B03')
        self._add_version('2026-09-23', 'v3', ['B01', 'B02', 'B03'])
        final = self._final_pass()
        self.assertEqual(final['state'], 'PASS', final['issues'])
        self.assertEqual(self.task_id, 'task-' + 'a' * 32)
        self.assertEqual(len([p for p in self.base.iterdir() if p.name.startswith('2026-09-')]), 1)
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v1.pptx').is_file())
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v2.pptx').is_file())
        self.assertTrue((self.root / 'outputs' / '2026-09-23_纪检监察_海勤工程_v3.pptx').is_file())

    def test_t4_duplicate_hash_is_recorded_without_new_archive_or_batch(self):
        self._build_v1()
        duplicate = self._source('同内容不同名.txt', b'one', 'incoming-duplicate')
        result = self._archive([duplicate], '2026-09-22')
        self.assertEqual(result['new_count'], 0)
        self.assertEqual(result['duplicate_count'], 1)
        manifest = json.loads((self.root / '00_原稿' / '原稿清单.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['files']), 4)
        self.assertEqual(len(manifest['batches']), 1)
        self.assertEqual(manifest['duplicates'][-1]['status'], 'DUPLICATE_HASH')
        self.assertEqual(self._final_pass()['state'], 'PASS')

    def test_t5_same_name_different_content_keeps_both_and_enters_next_batch_version(self):
        self._build_v1()
        revised = self._source('材料01.txt', b'revised', 'incoming-revision')
        result = self._archive([revised], '2026-09-22')
        self.assertEqual(result['new_count'], 1)
        self.assertEqual(result['batch_id'], 'B02')
        self._add_version('2026-09-22', 'v2', ['B01', 'B02'])
        manifest = json.loads((self.root / '00_原稿' / '原稿清单.json').read_text(encoding='utf-8'))
        same_name = [item for item in manifest['files'] if item['source_name'] == '材料01.txt']
        self.assertEqual(len(same_name), 2)
        self.assertEqual(len({item['archived_relative_path'] for item in same_name}), 2)
        self.assertEqual(self._final_pass()['state'], 'PASS')

    def test_t6_unknown_input_blocks_archive_and_final_pass_without_deletion(self):
        self._build_v1()
        unknown_source = self._source('无法判断用途.bin', b'keep', 'incoming-unknown')
        with self.assertRaises(ValueError):
            archive.archive_originals(
                self.root, [('unknown', unknown_source)], allow_test_output=True,
                batch_date='2026-09-22',
            )
        self.assertTrue(unknown_source.is_file())
        unknown_item = self.root / '无法判断用途.bin'
        unknown_item.write_bytes(b'keep')
        result = self._final_pass()
        self.assertEqual(result['state'], 'FAIL')
        self.assertTrue(unknown_item.is_file())

    def test_e01_placeholder_task_root_cannot_pass_archive(self):
        self._build_v1()
        placeholder = self.root.parent / 'new-chat'
        self.root.rename(placeholder)
        self.root = placeholder
        result = self._final_pass()
        self.assertEqual(result['state'], 'FAIL')
        self.assertTrue((self.root / 'outputs' / '2026-09-22_纪检监察_海勤工程_v1.pptx').is_file())

if __name__=='__main__':
    unittest.main()
