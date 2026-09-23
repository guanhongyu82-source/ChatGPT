"""Synthetic hook replay. This proves state logic, not host hook trust."""
from pathlib import Path
import sys, json, tempfile, unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import codex_delivery_hook as hook


class HookTests(unittest.TestCase):
    def event(self, root, **kw):
        value={'cwd':str(root),'session_id':'test-session-123','turn_id':'turn-1',
               'hook_event_name':'UserPromptSubmit','prompt':'执行 Sol Cabinet 测试','model':'selected-model'}
        value.update(kw);return value

    def state(self, root):
        return json.loads(hook.state_file('test-session-123',root).read_text(encoding='utf-8'))

    def ready(self, root, state_root, tier=2):
        hook.handle(self.event(root),state_root,root)
        hook.classified('test-session-123',tier,state_root)
        hook.card_ready('test-session-123',state_root)

    def started(self, root, state_root, tier=2, source='user-confirmation'):
        self.ready(root,state_root,tier)
        hook.confirm('test-session-123',source,state_root)

    def test_explicit_invocation_creates_receipt_but_not_start_time(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);result=hook.handle(self.event(root),root/'state',root);state=self.state(root/'state')
            self.assertIn('开工卡',result['hookSpecificOutput']['additionalContext'])
            self.assertEqual(state['phase'],'RECEIVED');self.assertIsNone(state['started_at'])
            self.assertNotIn('prompt',state)

    def test_natural_confirmation_and_preauthorization_are_distinct_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            self.assertIsNone(self.state(state_root)['started_at'])
            result=hook.confirm('test-session-123','user-preauthorized',state_root)
            self.assertEqual(result['source'],'user-preauthorized')
            self.assertIsNotNone(self.state(state_root)['started_at'])

    def test_start_card_must_precede_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);hook.handle(self.event(root),root/'state',root)
            with self.assertRaisesRegex(ValueError,'visible start card'):
                hook.confirm('test-session-123','user-confirmation',root/'state')

    def test_pretool_denies_writes_before_confirmation_but_allows_read(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            write=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='Bash',
                tool_input={'command':'touch result.txt'}),state_root,root)
            read=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='Bash',
                tool_input={'command':'ls'}),state_root,root)
            self.assertEqual(write['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertEqual(read,{})
            config=json.loads((Path(__file__).resolve().parents[1]/'platform-adapter/lab-hooks.json').read_text(encoding='utf-8'))
            self.assertIn('PreToolUse',config['hooks'])
            self.assertIsNone(self.state(state_root)['started_at'])

    def test_exec_wrapper_blocks_nested_shell_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            safe=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='functions.exec',
                tool_input={'code':'const r = await tools.exec_command({cmd:"ls"}); text(r.output);'}),state_root,root)
            blocked=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='functions.exec',
                tool_input={'code':'const r = await tools.exec_command({cmd:"sed -i s/a/b/ file"});'}),state_root,root)
            self.assertEqual(safe,{})
            self.assertEqual(blocked['hookSpecificOutput']['permissionDecision'],'deny')

    def test_preconfirmation_tool_policy_fails_closed_on_indirect_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            cases=[
                ('exec_command',{'cmd':'sed -e "w /tmp/probe" input.txt'}),
                ('exec_command',{'cmd':'cp codex_delivery_hook.py /tmp/probe --elapsed'}),
                ('exec_command',{'cmd':'git branch --delete old'}),
                ('exec_command',{'cmd':'rg --pre=touch input'}),
                ('functions.exec',{'code':'await tools["apply_patch"]("*** Begin Patch");'}),
                ('functions.exec',{'code':'const c=["tou","ch /tmp/probe"].join(""); await tools["exec_command"]({cmd:c});'}),
                ('new_write_capable_tool',{'path':'/tmp/probe'}),
            ]
            for name,value in cases:
                with self.subTest(name=name,value=value):
                    result=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name=name,tool_input=value),state_root,root)
                    self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')

    def test_cancel_and_unstarted_retry_do_not_open_write_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            event=self.event(root,hook_event_name='PreToolUse',tool_name='apply_patch',tool_input={})
            hook.cancel('test-session-123',state_root)
            self.assertEqual(hook.handle(event,state_root,root)['hookSpecificOutput']['permissionDecision'],'deny')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            hook.handle(self.event(root,hook_event_name='Stop',last_assistant_message='partial'),state_root,root)
            self.assertIsNone(self.state(state_root)['started_at'])
            self.assertEqual(hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='apply_patch',tool_input={}),state_root,root)['hookSpecificOutput']['permissionDecision'],'deny')

    def test_control_command_requires_actual_hook_as_executable_target(self):
        valid='python3 -B '+str(Path(hook.__file__).resolve())+' --session-id test-session-123 --elapsed'
        self.assertTrue(hook._control_command({'cmd':valid}))
        self.assertFalse(hook._control_command({'cmd':'cp '+str(Path(hook.__file__).resolve())+' /tmp/probe --elapsed'}))
        self.assertFalse(hook._control_command({'cmd':'python3 -c pass --elapsed'}))

    def test_user_scope_change_invalidates_unconfirmed_card(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            hook.revise_card('test-session-123',state_root)
            self.assertEqual(self.state(state_root)['phase'],'RECEIVED')
            with self.assertRaises(ValueError):hook.confirm('test-session-123','user-confirmation',state_root)

    def test_user_can_cancel_before_any_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            hook.cancel('test-session-123',state_root)
            self.assertEqual(self.state(state_root)['phase'],'CANCELLED')
            self.assertIsNone(self.state(state_root)['started_at'])

    def test_analysis_mode_requires_confirmed_execution(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.ready(root,state_root)
            with self.assertRaisesRegex(ValueError,'confirmation required'):
                hook.declare_analysis('test-session-123',state_root)
            hook.confirm('test-session-123','user-confirmation',state_root)
            hook.declare_analysis('test-session-123',state_root)
            result=hook.verify_delivery('test-session-123',state_root,root)
            self.assertEqual(result['state'],'PASS')
            self.assertEqual(self.state(state_root)['phase'],'DELIVERY_PASSED')

    def test_delivery_gate_pass_is_reused_without_a_second_full_check(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root)
            hook.verify_delivery('test-session-123',state_root,root)
            blocked=hook.handle(self.event(root,hook_event_name='PreToolUse',tool_name='Bash',
                tool_input={'command':'touch after-gate.txt'}),state_root,root)
            self.assertEqual(blocked['hookSpecificOutput']['permissionDecision'],'deny')
            with mock.patch('delivery_gate.check',side_effect=AssertionError('duplicate gate')):
                self.assertEqual(hook.verify_delivery('test-session-123',state_root,root),{'state':'PASS','cached':True})

    def test_reopen_invalidates_delivery_pass_without_resetting_start(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root);hook.verify_delivery('test-session-123',state_root,root)
            before=self.state(state_root)['started_at']
            reopened=hook.reopen_delivery('test-session-123',state_root)
            self.assertEqual(reopened['phase'],'EXECUTING');self.assertFalse(reopened['start_time_reset'])
            state=self.state(state_root);self.assertEqual(state['started_at'],before);self.assertFalse(state['delivery_verified'])
            hook.verify_delivery('test-session-123',state_root,root)
            hook.checkpoint('test-session-123','CLEAN',state_root=state_root,root=root)
            with self.assertRaisesRegex(ValueError,'pre-Evolution'):
                hook.reopen_delivery('test-session-123',state_root)

    def test_clean_checkpoint_does_not_read_evolution_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root);hook.verify_delivery('test-session-123',state_root,root)
            with mock.patch('evolve.history',side_effect=AssertionError('CLEAN read history')):
                result=hook.checkpoint('test-session-123','CLEAN',state_root=state_root,root=root)
            self.assertEqual(result['status'],'CLEAN');self.assertEqual(self.state(state_root)['checkpoint_count'],1)

    def test_real_incident_requires_one_history_query_before_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root);hook.verify_delivery('test-session-123',state_root,root)
            history={'status':'EXACT_MATCH','incidents':[{'incident_id':'INC-'+'1'*32,'same_cause':True,'treatments':[]}], 'errors':[]}
            with mock.patch('evolve.history',return_value=history) as lookup:
                first=hook.review_history('test-session-123','incident_not_recorded','execution_failure',state_root,root)
                second=hook.review_history('test-session-123','incident_not_recorded','execution_failure',state_root,root)
                self.assertEqual(first['status'],'EXACT_MATCH');self.assertTrue(second['idempotent']);lookup.assert_called_once()
            final=hook.checkpoint('test-session-123','PENDING','incident_not_recorded','execution_failure',state_root=state_root,root=root)
            self.assertEqual(final['status'],'PENDING')
            state=self.state(state_root);self.assertTrue(state['history_checked']);self.assertEqual(state['history_match_count'],1)

    def test_checkpoint_is_idempotent_and_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root);hook.verify_delivery('test-session-123',state_root,root)
            hook.checkpoint('test-session-123','CLEAN',state_root=state_root,root=root)
            second=hook.checkpoint('test-session-123','CLEAN',state_root=state_root,root=root)
            self.assertTrue(second['idempotent']);self.assertEqual(self.state(state_root)['checkpoint_count'],1)

    def test_stop_writes_finished_at_only_after_delivery_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root);hook.verify_delivery('test-session-123',state_root,root)
            hook.checkpoint('test-session-123','CLEAN',state_root=state_root,root=root)
            seconds=hook.elapsed('test-session-123',state_root)['elapsed_seconds']
            summary=f'完成：测试。开工卡闭环：完成。验收：通过。未完成：无。总耗时：{seconds} 秒。进化：CLEAN'
            result=hook.handle(self.event(root,hook_event_name='Stop',last_assistant_message=summary),state_root,root)
            self.assertEqual(result,{})
            state=self.state(state_root);self.assertEqual(state['phase'],'FINISHED');self.assertIsNotNone(state['finished_at'])

    def test_missing_start_card_or_evolution_cannot_finish(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';self.started(root,state_root)
            hook.declare_analysis('test-session-123',state_root)
            summary='完成：测试。验收：通过。未完成：无。总耗时：1 秒。进化：CLEAN'
            result=hook.handle(self.event(root,hook_event_name='Stop',last_assistant_message=summary),state_root,root)
            self.assertEqual(result['decision'],'block')
            self.assertEqual(self.state(state_root)['phase'],'RETRY_REQUIRED')

    def test_real_file_contract_uses_existing_delivery_gate(self):
        from test_delivery_rules import TaskLifecycleRules
        case=TaskLifecycleRules('test_t1_initial_task_creates_b01_v1_and_final_pass');case.setUp()
        try:
            case.prepare(1);case.publish();root=case.base;state_root=root/'state'
            self.ready(root,state_root);hook.confirm('test-session-123','user-confirmation',state_root)
            hook.register('test-session-123',Path(case.result['contract']),state_root,root)
            self.assertEqual(hook.verify_delivery('test-session-123',state_root,root)['state'],'PASS')
        finally:case.doCleanups()

    def test_legacy_state_is_migrated_to_unstarted_fail_closed_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_root=root/'state';state_root.mkdir()
            old={'schema_version':2,'session_id':'test-session-123','turn_id':'turn-1','model':'m',
                 'phase':'READY','mode':'analysis','failure_count':0,'contract':None,'contract_sha256':None,
                 'started_at':'2026-09-23T00:00:00+00:00','updated_at':'2026-09-23T00:00:01+00:00'}
            hook.state_file('test-session-123',state_root).write_text(json.dumps(old))
            self.assertIsNone(hook.load(hook.state_file('test-session-123',state_root))['started_at'])
            event=self.event(root,hook_event_name='PreToolUse',tool_name='apply_patch',tool_input={'command':'patch'})
            self.assertEqual(hook.handle(event,state_root,root)['hookSpecificOutput']['permissionDecision'],'deny')


if __name__=='__main__':unittest.main()
