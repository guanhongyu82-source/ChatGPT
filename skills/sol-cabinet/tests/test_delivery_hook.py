"""Synthetic event replay, not proof of a trusted live host hook."""
from pathlib import Path
import sys,json,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_delivery_hook as hook


class HookTests(unittest.TestCase):
 def event(self,root,**kw):
  v={'cwd':str(root),'session_id':'test-session-123','turn_id':'turn-1','hook_event_name':'UserPromptSubmit','prompt':'$sol-cabinet test','model':'selected-model'};v.update(kw);return v
 def activate(self,root,state_root):
  return hook.handle(self.event(root),state_root,root)
 def state(self,state_root):
  p=hook.state_file('test-session-123',state_root);return json.loads(p.read_text()) if p.exists() else None
 def stop(self,root,**kw):
  base={'hook_event_name':'Stop','last_assistant_message':'核验完成，耗时1秒'};base.update(kw);return self.event(root,**base)
 def test_unrelated_prompt_zero_write(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);self.assertEqual(hook.handle(self.event(r,prompt='你好'),r/'state',r),{});self.assertFalse((r/'state').exists())
 def test_prompt_creates_explicit_activation_without_storing_content(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);v=hook.handle(self.event(r,prompt='$sol-cabinet SENSITIVE-TEXT'),r/'state',r)
   context=v['hookSpecificOutput']['additionalContext'];state=self.state(r/'state')
   self.assertIn('预期交付物',context);self.assertIn('目标文件夹',context);self.assertNotIn('预计耗时',context)
   self.assertIn('TERMINAL_PARTIAL',context);self.assertEqual(state['schema_version'],2)
   self.assertEqual(state['phase'],'AWAITING_DECLARATION');self.assertEqual(state['mode'],'undecided');self.assertEqual(state['failure_count'],0)
   self.assertNotIn('SENSITIVE-TEXT',''.join(p.read_text() for p in (r/'state').glob('*.json')))
 def test_registration_requires_active_activation(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);p=r/'contract.json';p.write_text('{}')
   with self.assertRaises(ValueError):hook.register('test-session-123',p,r/'state',r)
   with self.assertRaises(ValueError):hook.declare_analysis('test-session-123',r/'state')
 def test_file_registration_moves_to_ready_and_locks_contract(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}')
   self.activate(r,state_root);hook.register('test-session-123',p,state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['mode'],'file');self.assertEqual(state['failure_count'],0)
   self.assertEqual(state['contract'],str(p.resolve()));self.assertEqual(len(state['contract_sha256']),64)
 def test_analysis_declaration_moves_to_ready_without_contract(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);hook.declare_analysis('test-session-123',state_root);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['mode'],'analysis');self.assertIsNone(state['contract'])
 def test_file_mode_cannot_downgrade_to_analysis(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.activate(r,state_root);hook.register('test-session-123',p,state_root,r)
   with self.assertRaisesRegex(ValueError,'cannot downgrade'):hook.declare_analysis('test-session-123',state_root)
   self.assertEqual(self.state(state_root)['mode'],'file')
 def test_analysis_mode_cannot_switch_to_file(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.activate(r,state_root);hook.declare_analysis('test-session-123',state_root)
   with self.assertRaisesRegex(ValueError,'locked'):hook.register('test-session-123',p,state_root,r)
   self.assertEqual(self.state(state_root)['mode'],'analysis')
 def test_missing_declaration_blocks_once_then_enters_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);e=self.stop(r,last_assistant_message='完成检查，耗时1秒 [文稿](/a.docx)')
   first=hook.handle(e,state_root,r);self.assertEqual(first['decision'],'block');self.assertEqual(self.state(state_root)['phase'],'RETRY_REQUIRED');self.assertEqual(self.state(state_root)['failure_count'],1)
   second=hook.handle(e,state_root,r);self.assertIs(second['continue'],False);self.assertEqual(self.state(state_root)['phase'],'TERMINAL_PARTIAL');self.assertEqual(self.state(state_root)['failure_count'],2)
 def test_reregister_after_failure_does_not_reset_retry_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);hook.handle(self.stop(r),state_root,r)
   p=r/'contract.json';p.write_text('{}');hook.register('test-session-123',p,state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['failure_count'],1)
   result=hook.handle(self.stop(r),state_root,r);self.assertIs(result['continue'],False);self.assertEqual(self.state(state_root)['phase'],'TERMINAL_PARTIAL')
 def test_terminal_stop_is_idempotently_non_retrying(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   again=hook.handle(e,state_root,r);self.assertIs(again['continue'],False);self.assertIn('重新激活',again['systemMessage'])
 def test_terminal_does_not_leak_into_unrelated_next_prompt(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   self.assertEqual(hook.handle(self.event(r,turn_id='turn-2',prompt='今天天气怎么样'),state_root,r),{})
   self.assertIsNone(self.state(state_root));self.assertEqual(hook.handle(self.stop(r,turn_id='turn-2'),state_root,r),{})
 def test_terminal_requires_explicit_retrigger_for_fresh_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   hook.handle(self.event(r,turn_id='turn-2',prompt='$sol-cabinet 继续'),state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'AWAITING_DECLARATION');self.assertEqual(state['failure_count'],0);self.assertEqual(state['turn_id'],'turn-2')
 def test_analysis_completion_clears_state(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);hook.declare_analysis('test-session-123',state_root)
   self.assertEqual(hook.handle(self.stop(r),state_root,r),{});self.assertEqual(list(state_root.iterdir()),[])
 def test_analysis_cannot_claim_file_delivery(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root);hook.declare_analysis('test-session-123',state_root)
   result=hook.handle(self.stop(r,last_assistant_message='核验完成，耗时1秒，交付文件 /tmp/result.pdf'),state_root,r)
   self.assertEqual(result['decision'],'block');self.assertIn('声明无文件分析',result['reason'])
 def test_outside_root_and_invalid_id(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);self.assertEqual(hook.handle(self.event(r,cwd='/outside'),r/'state',r),{})
   with self.assertRaises(ValueError):hook.handle(self.event(r,session_id='../escape'),r/'state',r)
 def test_changed_contract_not_reused(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.activate(r,state_root);hook.register('test-session-123',p,state_root,r);p.write_text('{"changed":true}')
   result=hook.handle(self.stop(r),state_root,r);self.assertIn('变更',result['reason'])
 def test_unregistered_plain_zip_cannot_silently_pass(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root)
   result=hook.handle(self.stop(r,last_assistant_message='检查完成，耗时1秒，成品 /tmp/result.zip'),state_root,r);self.assertEqual(result['decision'],'block')
 def test_legacy_or_malformed_state_is_not_accepted(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';state_root.mkdir();p=hook.state_file('test-session-123',state_root);p.write_text('{"mode":"file"}')
   with self.assertRaises(ValueError):hook.handle(self.stop(r),state_root,r)
 def test_registered_real_contract_runs_gate(self):
  from test_delivery_rules import TaskLifecycleRules
  case=TaskLifecycleRules('test_t1_initial_task_creates_b01_v1_and_final_pass');case.setUp()
  try:
   case.prepare(4);case.publish()
   r=case.base;state_root=r/'state';p=Path(case.result['contract']);self.activate(r,state_root)
   hook.register('test-session-123',p,state_root,r)
   summary=f"核验完成，交付文件 {case.result['artifacts'][0]['path']}，目录状态已核对，耗时1秒"
   self.assertEqual(hook.handle(self.stop(r,last_assistant_message=summary),state_root,r),{})
  finally:case.doCleanups()

 def test_stale_or_wrong_summary_path_is_blocked(self):
  from test_delivery_rules import TaskLifecycleRules
  case=TaskLifecycleRules('test_t1_initial_task_creates_b01_v1_and_final_pass');case.setUp()
  try:
   case.prepare(1);case.publish()
   r=case.base;state_root=r/'state';self.activate(r,state_root)
   hook.register('test-session-123',Path(case.result['contract']),state_root,r)
   result=hook.handle(self.stop(r,last_assistant_message='FINAL PASS 未完成项：无 核验完成，交付文件 /wrong/nonexistent.pdf，归档完成，耗时1秒'),state_root,r)
   self.assertEqual(result['decision'],'block')
  finally:case.doCleanups()
 def test_registered_file_summary_requires_artifact_and_folder_status(self):
  from test_delivery_rules import DeliveryRules
  case=DeliveryRules('test_host_output_and_honest_deferred_archive_pass');case.setUp()
  try:
   r=case.root;state_root=r/'state';p=r/'contract.json';self.activate(r,state_root)
   case.c['retention'].setdefault('retained_reason',{}).update({str(p):'gate contract',str(case.evidence):'independent review',str(state_root):'hook test runtime'})
   p.write_text(json.dumps(case.c));hook.register('test-session-123',p,state_root,r)
   result=hook.handle(self.stop(r,last_assistant_message='核验完成，耗时1秒'),state_root,r)
   self.assertEqual(result['decision'],'block');self.assertTrue('实际成品' in result['reason'] or '目录' in result['reason'])
  finally:case.doCleanups()


if __name__=='__main__':unittest.main()
