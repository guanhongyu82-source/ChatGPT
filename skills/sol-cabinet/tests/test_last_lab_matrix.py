"""Twelve bounded lifecycle fixtures. Synthetic cases never claim live task A/B."""
from pathlib import Path
import hashlib, json, subprocess, sys, tempfile, unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import classify_task
import codex_delivery_hook as hook
import evolve


class LastLabMatrix(unittest.TestCase):
    def profile(self, **overrides):
        value={'file_count':0,'input_size_kb':0,'deliverable_count':1,'steps':1,'complexity':0}
        value.update(overrides);return value

    def event(self, root, **kw):
        value={'cwd':str(root),'session_id':'matrix-session-123','turn_id':'turn-1',
               'hook_event_name':'UserPromptSubmit','prompt':'执行 Sol Cabinet 回归','model':'fixture-model'}
        value.update(kw);return value

    def card(self,root,state,tier=2):
        hook.handle(self.event(root),state,root)
        hook.classified('matrix-session-123',tier,state)
        hook.card_ready('matrix-session-123',state)

    def start_analysis(self,root,state,tier=2,source='user-confirmation'):
        self.card(root,state,tier)
        hook.confirm('matrix-session-123',source,state)
        hook.declare_analysis('matrix-session-123',state)

    def test_case_01_simple_text_routes_to_minimal_fast_path(self):
        result=classify_task.classify(self.profile())
        self.assertEqual(result['t_level'],1)
        self.assertEqual(result['workflow']['lane'],'t1_t2_fast')
        self.assertEqual(result['workflow']['required_checks'],['one_joint_check'])

    def test_case_02_single_review_uses_focused_path(self):
        result=classify_task.classify(self.profile(complexity=3,steps=2))
        self.assertEqual(result['t_level'],3)
        self.assertEqual(result['workflow']['lane'],'t3_focused')

    def test_case_03_office_artifact_adds_structured_review(self):
        result=classify_task.classify(self.profile(office_artifact=True))
        self.assertGreaterEqual(result['t_level'],4)
        self.assertEqual(result['workflow']['lane'],'t4_t6_structured')
        self.assertGreaterEqual(result['review']['minimum_independent_reviewers'],1)

    def test_case_04_multifile_fact_task_uses_structured_path(self):
        result=classify_task.classify(self.profile(file_count=5,deliverable_count=2,steps=5,multi_source=True,fact_risk=True))
        self.assertGreaterEqual(result['t_level'],5)
        self.assertIn(result['workflow']['lane'],{'t4_t6_structured','t7_t8_high_control','t9_t10_stage_gated'})
        self.assertGreaterEqual(result['review']['minimum_independent_reviewers'],1)

    def test_case_05_high_risk_system_work_is_stage_gated(self):
        result=classify_task.classify(self.profile(system_build=True,long_running=True,high_risk=True,regulated=True))
        self.assertEqual(result['t_level'],10)
        self.assertEqual(result['workflow']['lane'],'t9_t10_stage_gated')
        self.assertEqual(result['review']['minimum_independent_reviewers'],2)

    def test_case_06_explicit_direct_authorization_starts_after_card(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';self.card(root,state)
            self.assertIsNone(hook.load(hook.state_file('matrix-session-123',state))['started_at'])
            hook.confirm('matrix-session-123','user-preauthorized',state)
            self.assertEqual(hook.load(hook.state_file('matrix-session-123',state))['phase'],'EXECUTING')
            self.assertEqual(hook.load(hook.state_file('matrix-session-123',state))['authorization_source'],'user-preauthorized')

    def test_case_07_unconfirmed_write_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';self.card(root,state)
            result=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='apply_patch',
                                          tool_input={'command':'patch'}),state,root)
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertIsNone(hook.load(hook.state_file('matrix-session-123',state))['started_at'])

    def test_case_08_risk_gate_overrides_requested_low_tier(self):
        result=classify_task.classify(self.profile(explicit_t=1,high_risk=True,regulated=True,sensitive=True,file_count=20,complexity=3,professional_roles=8,multi_angle=True,multi_source=True,needs_research=True,current_fact=True,fact_risk=True,office_artifact=True,multiple_deliverables=True))
        self.assertGreaterEqual(result['t_level'],6)
        self.assertEqual(result['workflow']['lane'],'t7_t8_high_control')

    def test_case_09_recurrence_finds_prior_fix_and_changed_module(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);obs=root/'memory-evolution/observations';props=root/'memory-evolution/proposals'
            obs.mkdir(parents=True);props.mkdir(parents=True)
            iid='INC-'+'1'*32;eid='EV-'+'2'*32
            item={'incident_id':iid,'time':'2026-09-20T00:00:00+00:00','failure_type':'task_underclassification',
                  'cause':'execution_failure','impact':'high','evidence':[eid],'capabilities':['routing'],
                  'repeated':False,'hits':1,'permission':'record'}
            capture={'evidence_id':eid,'task_instance_id':'task-'+'3'*32,'failure_type':item['failure_type'],
                     'artifact_path':'capture.json','artifact_sha256':'a'*64,'source':'executor-capture','sanitized':True}
            (obs/(iid+'.json')).write_text(json.dumps(item));(obs/(eid+'.json')).write_text(json.dumps(capture))
            evo={'EVO':'EVO-20260920-010203','incident':{'incident_id':iid,'evidence':[eid]},'post_apply':'PASS',
                 'evidence_dir':str(root/'evidence'),'after':'b'*64,'regression':'testrun-fixture','reviews':[],
                 'cases':[],'changes':[{'path':'scripts/classify_task.py'}],'summary':'improve-routing'}
            (props/(evo['EVO']+'.json')).write_text(json.dumps(evo))
            with mock.patch.object(evolve,'verify_evidence',return_value={}):
                result=evolve.history('task_underclassification','execution_failure',root)
            self.assertEqual(result['status'],'EXACT_MATCH')
            self.assertEqual(result['incidents'][0]['status'],'closed')
            self.assertIn('scripts/classify_task.py',result['incidents'][0]['treatments'][0]['changed_paths'])

    def test_case_10_repeated_calls_do_not_reset_start_or_replay_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';self.start_analysis(root,state)
            first=hook.load(hook.state_file('matrix-session-123',state))['started_at']
            hook.verify_delivery('matrix-session-123',state,root)
            hook.checkpoint('matrix-session-123','CLEAN',state_root=state,root=root)
            again=hook.checkpoint('matrix-session-123','CLEAN',state_root=state,root=root)
            self.assertEqual(first,hook.load(hook.state_file('matrix-session-123',state))['started_at'])
            self.assertTrue(again['idempotent']);self.assertEqual(hook.load(hook.state_file('matrix-session-123',state))['checkpoint_count'],1)

    def test_case_11_noise_is_clean_without_history_io(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';self.start_analysis(root,state)
            hook.verify_delivery('matrix-session-123',state,root)
            with mock.patch.object(evolve,'history',side_effect=AssertionError('unexpected history read')):
                result=hook.checkpoint('matrix-session-123','CLEAN',state_root=state,root=root)
            self.assertEqual(result['status'],'CLEAN')

    def test_case_12_failed_candidate_change_rolls_back_exactly(self):
        run=subprocess.run([sys.executable,'-B',str(ROOT/'tests/lifecycle_fixture.py'),str(ROOT)],
                           capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('rollback restored',run.stdout)


if __name__=='__main__':unittest.main()
