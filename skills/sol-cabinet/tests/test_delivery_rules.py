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
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
    def test_required_expected_artifact_missing_fails(self):
        self.c['artifacts']=[]
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_unauthorized_extra_artifact_fails(self):
        extra=self.root/'2026-09-13_附件_额外材料_v1.pdf';extra.write_bytes(b'extra')
        self.c['artifacts'].append({'artifact_id':'extra','role':'final','path':str(extra),'sha256':hashlib.sha256(extra.read_bytes()).hexdigest()})
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_wrong_format_location_and_role_fail(self):
        bad=self.root/'2026-09-13_方案_协作机制_v1.pdf';bad.write_bytes(b'candidate')
        self.c['artifacts'][0].update(path=str(bad),sha256=hashlib.sha256(bad.read_bytes()).hexdigest())
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.c['artifacts'][0].update(path=str(self.artifact),sha256=hashlib.sha256(self.artifact.read_bytes()).hexdigest(),role='candidate')
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        sub=self.root/'other';sub.mkdir();moved=sub/self.artifact.name;self.artifact.rename(moved)
        self.c['artifacts'][0].update(path=str(moved),role='final',sha256=hashlib.sha256(moved.read_bytes()).hexdigest())
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_filename_override_comes_only_from_expected(self):
        self.card['deliverables'][0]['filename_override']='用户指定名称.docx'
        self.relock_task_card()
        renamed=self.root/'用户指定名称.docx';self.artifact.rename(renamed);self.artifact=renamed
        self.refresh_artifact_review()
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
        self.c['artifacts'][0]['user_filename_override']=True
        self.artifact.rename(self.root/'执行端自定名.docx');self.artifact=self.root/'执行端自定名.docx'
        self.refresh_artifact_review()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_task_card_change_without_relock_fails(self):
        self.card['deliverables'].append({'artifact_id':'new-required','required':True,'format':'.pdf','target_role':'final','target_directory':str(self.root),'filename_override':None})
        self.write_task_card()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_user_reduces_deliverables_and_relocks_passes(self):
        self.card['deliverables'].append({'artifact_id':'optional-pdf','required':False,'format':'.pdf','target_role':'final','target_directory':str(self.root),'filename_override':None})
        self.relock_task_card()
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
        self.card['deliverables']=self.card['deliverables'][:1]
        self.relock_task_card()
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
    def test_task_card_identity_and_duplicate_ids_fail(self):
        self.card['task_instance_id']='other-task';self.relock_task_card()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.card['task_instance_id']='task-1';self.card['deliverables'].append(copy.deepcopy(self.card['deliverables'][0]));self.relock_task_card()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_apology_without_incident_record_fails(self):
        self.c['incident_present']=True
        self.c['incident_disposition']='已道歉并修复'
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_existing_incident_record_passes(self):
        self.c['incident_present']=True
        self.c['incident_disposition']='已修复并复用现有事故记录'
        record=self.root/'incident.json'
        record.write_text(json.dumps({'incident_id':'INC-'+'1'*32,'permission':'record','failure_type':'delivery-omission','evidence':['message:failure-1']}))
        self.c['incident_records']=[str(record)]
        self.c['retention']['retained_reason'][str(record)]='existing incident evidence'
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
        record.write_text(json.dumps({'incident_id':'INC-'+'1'*32,'permission':'record','failure_type':'delivery-omission','evidence':[]}))
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_unlisted_process_file_fails(self):
        process=self.root/'work'
        process.mkdir()
        stray=process/'forgotten.txt';stray.write_text('scratch')
        self.c['retention']['process_root']=str(process)
        self.c['retention']['retained_reason'][str(process)]='task evidence directory'
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.c['retention']['retained_reason'][str(stray)]='required diagnostic evidence'
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
    def test_unlisted_output_and_contract_exclusion(self):
        stray=self.root/'forgotten.txt';stray.write_text('scratch')
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.assertEqual(gate.check_components(self.c,contract_path=stray)['state'],'PASS')
    def test_changed_review_bytes_fail(self):
        self.evidence.write_text(self.evidence.read_text()+' ')
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_recorded_failure_cannot_be_overridden(self):
        record=json.loads(self.evidence.read_text())
        record['verdict']='FAIL'
        self.evidence.write_text(json.dumps(record))
        self.c['reviews'][0]['evidence_sha256']=hashlib.sha256(self.evidence.read_bytes()).hexdigest()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_missing_review_hash_and_source_reference_fail(self):
        saved=copy.deepcopy(self.c)
        self.c['reviews'][0].pop('evidence_sha256')
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.c=saved
        self.c['reviews'][0]['source_ref']=''
        self.write_evidence()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_cli_fails_closed_on_invalid_contract(self):
        contract=self.root/'contract.json'
        contract.write_text(json.dumps({'storage':{'output_root':17}}))
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/'delivery_gate.py'),'--contract',str(contract)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stdout)['state'],'FAIL')
    def test_host_output_and_honest_deferred_archive_pass(self):
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
    def test_formal_additions_cannot_take_bounded_shortcut(self):
        result = classifier.classify({'formal_normative_additions':True,'bounded_edit':True,'file_count':1})
        self.assertGreaterEqual(result['t_level'],4)
        self.assertFalse(result['bounded_edit_short_path'])
    def test_t3_formal_additions_fail(self):
        self.c['t_level']=3
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_missing_and_stale_review_fail(self):
        for mutation in ('missing','stale'):
            c=copy.deepcopy(self.c)
            if mutation=='missing': c['reviews']=[]
            else: self.artifact.write_bytes(b'changed')
            self.assertEqual(gate.check_components(c)['state'],'FAIL')
    def test_missing_opening_summary_and_incident_disposition_fail(self):
        for field in ('opening_notice','summary_present','incident_present'):
            c=copy.deepcopy(self.c)
            c[field]=(field=='incident_present')
            self.assertEqual(gate.check_components(c)['state'],'FAIL')
    def test_unexplained_timing_and_false_archive_fail(self):
        self.c['timing']={}
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.c['timing']={'unavailable_reason':'no reliable timestamp supplied'}
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
        self.c['storage']['archive_status']='done'
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
    def test_unjustified_temp_and_bad_name_fail(self):
        self.c['retention']['retained_reason'].pop(str(self.evidence))
        self.c['retention']['temporary_files']=[str(self.evidence)]
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')
        self.c['retention']['retained_reason'][str(self.evidence)]='required review evidence'
        self.assertEqual(gate.check_components(self.c)['state'],'PASS')
        p=self.root/'new.docx';self.artifact.rename(p);self.artifact=p
        self.refresh_artifact_review()
        self.assertEqual(gate.check_components(self.c)['state'],'FAIL')

class TaskLifecycleRules(unittest.TestCase):
    """Real prepare/publish/check calls; fixtures never rename roots or rebuild history."""
    subject = '归档验收_持续任务'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/Users/macbook/ChatGPT/.scratch')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'new-chat'
        self.root.mkdir()
        self.incoming = self.base / 'incoming'
        self.incoming.mkdir()
        self.result = None

    def _source(self, name, content):
        folder = self.incoming / str(len(list(self.incoming.iterdir())))
        folder.mkdir()
        source = folder / name
        source.write_text(content, encoding='utf-8')
        return source

    def prepare(self, count=0, date='2026-09-22', inputs=None, revision=False):
        if inputs is None:
            inputs = [{'path': str(self._source('材料.txt', f'source-{date}-{i}-{len(list(self.incoming.iterdir()))}')),
                       'role': 'reference'} for i in range(count)]
        result = gate.prepare_task(self.root, self.subject, date, inputs, revision=revision)
        self.root = Path(result['task_root'])
        self.card_path = self.root / 'work/task-card.json'
        return result

    def publish(self, date='2026-09-22', invalid=False):
        card = json.loads(self.card_path.read_text())
        version = gate.next_formal_version(self.root / 'outputs')
        source = self.root / 'work' / ('draft-' + version + '.md')
        payload = '# Synthetic lifecycle fixture\n\n' + version + '\n'
        source.write_text(payload, encoding='utf-8')
        name = date + '_' + self.subject + '_' + version + '.md'
        def validate(artifacts):
            refs = {}
            for kind in ('content', 'final_validation'):
                checks = []
                for item in artifacts:
                    final = Path(item['path'])
                    self.assertTrue(final.is_file())
                    self.assertEqual(final.read_text(), payload)
                    checks.append('read final path UTF-8; exact candidate content preserved')
                record = {'verdict': 'FAIL' if invalid else 'PASS', 'must_fix': [],
                          'candidate_sha256': {a['path']: hashlib.sha256(Path(a['path']).read_bytes()).hexdigest()
                                               for a in artifacts},
                          'source_ref': 'unittest:actual-final-path-read', 'checks': checks}
                path = self.root / 'work' / (kind + '-' + version + '.json')
                path.write_text(json.dumps(record), encoding='utf-8')
                refs[kind] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            return refs
        self.result = gate.publish_version(self.card_path,
            [{'path': str(source), 'filename': name, 'artifact_id': 'main'}],
            validate, formed_date=date)
        self.assertEqual(self.check()['state'], 'PASS', self.check())
        return self.result

    def check(self, mutate=None):
        path = Path(self.result['contract'])
        c = json.loads(path.read_text())
        if mutate:
            mutate(c)
        return gate.check(c, path)

    def test_t1_initial_task_creates_b01_v1_and_final_pass(self):
        result = self.prepare(4)
        self.assertEqual(result['batch_id'], 'B01')
        self.assertEqual(self.root.name, '2026-09-22_' + self.subject)
        self.assertFalse((self.base / 'new-chat').exists())
        self.assertEqual(self.publish()['version'], 'v1')

    def test_t2_same_day_supplement_keeps_root_and_v1_and_creates_v2(self):
        identity = self.prepare(4)['task_id']
        first = self.publish()
        old = Path(first['artifacts'][0]['path'])
        original = old.read_bytes()
        root = self.root
        self.assertEqual(self.prepare(1)['batch_id'], 'B02')
        self.assertEqual(json.loads(self.card_path.read_text())['task_instance_id'], identity)
        self.assertEqual(self.root, root)
        self.assertEqual(self.publish()['version'], 'v2')
        self.assertEqual(old.read_bytes(), original)

    def test_t3_cross_day_reopen_keeps_task_id_and_history_and_creates_v3(self):
        identity = self.prepare(4)['task_id']
        self.publish()
        self.prepare(1)
        self.publish()
        old = self.root
        history = {p.name: p.read_bytes() for p in (old / 'outputs').iterdir()}
        result = self.prepare(3, '2026-09-23')
        self.assertEqual(result['task_id'], identity)
        self.assertEqual(result['batch_id'], 'B03')
        self.assertFalse(old.exists())
        self.assertEqual(self.root.name, '2026-09-23_' + self.subject)
        self.assertEqual(self.publish('2026-09-23')['version'], 'v3')
        for name, data in history.items():
            self.assertEqual((self.root / 'outputs' / name).read_bytes(), data)
        card = json.loads(self.card_path.read_text())
        self.assertEqual([v['material_batches'] for v in card['lifecycle']['formal_versions']],
                         [['B01'], ['B01', 'B02'], ['B01', 'B02', 'B03']])
        self.assertEqual(len([p for p in self.base.iterdir() if p.name.startswith('2026-')]), 1)

    def test_t4_duplicate_hash_is_recorded_without_new_archive_or_batch(self):
        p = self._source('original.txt', 'same')
        self.prepare(inputs=[{'path': str(p), 'role': 'reference'}])
        self.publish()
        root = self.root
        repeat = self._source('renamed.txt', 'same')
        r = self.prepare(date='2026-09-23', inputs=[{'path': str(repeat), 'role': 'reference'}])
        self.assertEqual(r['duplicate_count'], 1)
        self.assertEqual(r['new_count'], 0)
        self.assertEqual(self.root, root)
        manifest = json.loads((root / '00_原稿/原稿清单.json').read_text())
        self.assertEqual(len(manifest['files']), 1)
        self.assertEqual(len(manifest['batches']), 1)
        self.assertEqual(len(manifest['duplicates']), 1)
        self.assertEqual(self.check()['state'], 'PASS')

    def test_t5_same_name_different_content_keeps_both_and_enters_next_batch_version(self):
        self.prepare(inputs=[{'path': str(self._source('same.txt', 'old')), 'role': 'reference'}])
        self.publish()
        result = self.prepare(inputs=[{'path': str(self._source('same.txt', 'new')), 'role': 'reference'}])
        self.assertEqual(result['batch_id'], 'B02')
        self.publish()
        m = json.loads((self.root / '00_原稿/原稿清单.json').read_text())
        self.assertEqual(len(m['files']), 2)
        self.assertEqual({(self.root / f['archived_relative_path']).read_text() for f in m['files']}, {'old', 'new'})

    def test_t6_unknown_input_blocks_archive_and_final_pass_without_deletion(self):
        self.prepare(4)
        self.publish()
        p = self._source('unknown.bin', 'keep me')
        r = self.prepare(inputs=[{'path': str(p), 'role': 'unknown'}])
        self.assertEqual(r['state'], 'BLOCKED')
        self.assertTrue(p.exists())
        self.assertEqual(self.check()['state'], 'FAIL')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertTrue(p.exists())
        self.prepare(inputs=[{'path': str(p), 'role': 'reference'}])
        self.assertEqual(self.publish()['version'], 'v2')

    def test_t7_temporary_roots_cannot_finalize(self):
        self.prepare(1)
        self.publish()
        for name in ('new-chat', 'temp', 'tmp', 'untitled', 'working', '未命名', '临时',
                     '2026-09-22_new-chat', '2026-09-22_new-chat-2',
                     '2026-09-22_final2', '2026-09-22_最终版最新版'):
            with self.subTest(name=name):
                self.assertEqual(self.check(lambda c: c['lifecycle'].update(task_root=str(self.base / name)))['state'], 'FAIL')
        for status in ('deferred', 'not_applicable'):
            self.assertEqual(self.check(lambda c: c['storage'].update(archive_status=status))['state'], 'FAIL')

    def test_historical_byte_tamper_cannot_be_rebased(self):
        self.prepare(1)
        self.publish()
        path = Path(self.result['artifacts'][0]['path'])
        path.write_text('corrupt')
        self.assertEqual(self.check()['state'], 'FAIL')
        with self.assertRaises(ValueError):
            self.prepare(1)
        cpath = Path(self.result['contract'])
        c = json.loads(cpath.read_text())
        c['lifecycle']['formal_versions'][0]['artifacts'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(gate.check(c, cpath)['state'], 'FAIL')

    def test_historical_original_tamper_cannot_be_rebased(self):
        self.prepare(1)
        self.publish()
        mpath = self.root / '00_原稿/原稿清单.json'
        m = json.loads(mpath.read_text())
        archived = self.root / m['files'][0]['archived_relative_path']
        archived.write_text('evil')
        m['files'][0]['source_sha256'] = hashlib.sha256(archived.read_bytes()).hexdigest()
        m['files'][0]['archived_sha256'] = m['files'][0]['source_sha256']
        m['files'][0]['size_bytes'] = archived.stat().st_size
        mpath.write_text(json.dumps(m))
        self.assertEqual(self.check()['state'], 'FAIL')
        with self.assertRaises(ValueError):
            self.prepare(1)

    def test_title_only_request_keeps_delivered_physical_root(self):
        self.prepare(1)
        self.publish()
        root = self.root
        result = gate.prepare_task(root, '仅调整标题', '2026-09-23', [])
        self.root = Path(result['task_root'])
        self.assertEqual(self.root, root)
        self.assertEqual(json.loads(self.card_path.read_text())['lifecycle']['state'], 'DELIVERED')
        self.assertEqual(self.check()['state'], 'PASS')

    def test_bad_final_evidence_rolls_back_only_attempt_then_retry(self):
        self.prepare(1)
        with self.assertRaises(ValueError):
            self.publish(invalid=True)
        self.assertEqual(list((self.root / 'outputs').iterdir()), [])
        self.assertEqual(json.loads(self.card_path.read_text())['lifecycle']['formal_versions'], [])
        self.assertEqual(self.publish()['version'], 'v1')

    def test_explicit_revision_is_traced_and_history_not_overwritten(self):
        self.prepare(inputs=[{'path': str(self._source('same.txt', 'old')), 'role': 'reference'}])
        self.publish()
        mpath = self.root / '00_原稿/原稿清单.json'
        before = json.loads(mpath.read_text())['files'][0]['archived_relative_path']
        self.prepare(inputs=[{'path': str(self._source('same.txt', 'revised')), 'role': 'reference', 'supersedes': before}])
        self.publish()
        self.assertEqual(json.loads(mpath.read_text())['files'][1]['supersedes'], before)

    def test_report_missing_or_wrong_path_and_gate_fail_rejected(self):
        self.prepare(1)
        self.publish()
        report = Path(self.result['report'])
        original = report.read_bytes()
        report.unlink()
        self.assertEqual(self.check()['state'], 'FAIL')
        report.write_bytes(original)
        for key in gate.FINALIZATION_GATES:
            self.assertEqual(self.check(lambda c: c['lifecycle']['finalization_gates'].update({key: 'FAIL'}))['state'], 'FAIL')
        wrong = json.loads(original)
        wrong['task_root'] = '/old/path'
        report.write_text(json.dumps(wrong))
        self.assertEqual(self.check()['state'], 'FAIL')

    def test_unknown_root_and_undeclared_output_preserved(self):
        self.prepare(1)
        self.publish()
        unknown = self.root / 'mystery.bin'
        unknown.write_bytes(b'keep')
        self.assertEqual(self.check()['state'], 'FAIL')
        self.assertEqual(unknown.read_bytes(), b'keep')
        unknown.unlink()
        preview = self.root / 'outputs/preview.png'
        preview.write_bytes(b'keep')
        self.assertEqual(self.check()['state'], 'FAIL')
        self.assertEqual(preview.read_bytes(), b'keep')


class MaterialIntegrityRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/Users/macbook/ChatGPT/.scratch')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / 'task'
        self.task.mkdir()
        self.source = self.root / 'one.txt'
        self.source.write_text('one')
        archive.archive_originals(self.task, [('reference', self.source)], allow_test_output=True)
        self.manifest = self.task / '00_原稿/原稿清单.json'

    def add(self, **kwargs):
        other = self.root / 'two.txt'
        other.write_text('two')
        return archive.archive_originals(self.task, [('reference', other)], allow_test_output=True, **kwargs)

    def test_existing_batch_cannot_change(self):
        before = self.manifest.read_bytes()
        with self.assertRaises(ValueError):
            self.add(batch_id='B01')
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_legacy_duplicate_hash_copies_survive_two_migrations(self):
        m = json.loads(self.manifest.read_text())
        first = m['files'][0]
        first.pop('material_batch_id')
        second = dict(first, source_role='template',
                      archived_relative_path='00_原稿/legacy-two.txt')
        (self.task / second['archived_relative_path']).write_bytes(self.source.read_bytes())
        self.manifest.write_text(json.dumps({'schema_version': 1, 'archive_state': 'PASS', 'files': [first, second]}))
        self.add()
        self.add()
        m = json.loads(self.manifest.read_text())
        self.assertEqual(len(m['files']), 3)
        self.assertEqual(m['batches'][0]['batch_id'], 'B00')
        self.assertTrue((self.task / second['archived_relative_path']).is_file())

    def test_batch_and_duplicate_relations_cannot_lie(self):
        original = self.manifest.read_bytes()
        m = json.loads(original)
        m['files'][0]['material_batch_id'] = 'B99'
        self.manifest.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            self.add()
        self.manifest.write_bytes(original)
        archive.archive_originals(self.task, [('reference', self.source)], allow_test_output=True)
        m = json.loads(self.manifest.read_text())
        m['duplicates'][0]['source_sha256'] = '0' * 64
        self.manifest.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            self.add()

    def test_supersedes_unknown_target_preserves_archive(self):
        before = self.manifest.read_bytes()
        with self.assertRaises(ValueError):
            self.add(supersedes={str(self.root / 'two.txt'): '00_原稿/missing.txt'})
        self.assertEqual(self.manifest.read_bytes(), before)

if __name__=='__main__':
    unittest.main()
