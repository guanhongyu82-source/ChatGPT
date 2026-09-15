"""Synthetic event replay, not proof of a trusted live host hook."""
from pathlib import Path
import sys,json,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_delivery_hook as hook
class HookTests(unittest.TestCase):
 def event(self,root,**kw):
  v={'cwd':str(root),'session_id':'test-session-123','hook_event_name':'UserPromptSubmit','prompt':'$sol-cabinet test','model':'selected-model'};v.update(kw);return v
 def test_unrelated_prompt_zero_write(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);self.assertEqual(hook.handle(self.event(r,prompt='你好'),r/'state',r),{});self.assertFalse((r/'state').exists())
 def test_prompt_injects_without_storing_content(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);v=hook.handle(self.event(r,prompt='$sol-cabinet SENSITIVE-TEXT'),r/'state',r)
   context=v['hookSpecificOutput']['additionalContext']
   self.assertIn('预期交付物',context);self.assertIn('目标文件夹',context);self.assertNotIn('预计耗时',context)
   self.assertNotIn('SENSITIVE-TEXT',''.join(p.read_text() for p in (r/'state').glob('*.json')))
 def test_missing_contract_blocks_once_then_stops(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);hook.handle(self.event(r),r/'state',r);e=self.event(r,hook_event_name='Stop',last_assistant_message='完成检查，耗时1秒 [文稿](/a.docx)')
   self.assertEqual(hook.handle(e,r/'state',r)['decision'],'block');self.assertIs(hook.handle(e,r/'state',r)['continue'],False)
 def test_analysis_completion_clears_state(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);hook.handle(self.event(r),r/'state',r)
   path=hook.state_file('test-session-123',r/'state');state=json.loads(path.read_text());state['mode']='analysis';hook.save(path,state)
   self.assertEqual(hook.handle(self.event(r,hook_event_name='Stop',last_assistant_message='检查完成，耗时1秒'),r/'state',r),{})
   self.assertEqual(list((r/'state').iterdir()),[])
 def test_outside_root_and_invalid_id(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);self.assertEqual(hook.handle(self.event(r,cwd='/outside'),r/'state',r),{})
   with self.assertRaises(ValueError):hook.handle(self.event(r,session_id='../escape'),r/'state',r)
 def test_changed_contract_not_reused(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);p=r/'contract.json';p.write_text('{}');hook.register('test-session-123',p,r/'state',r);p.write_text('{"changed":true}')
   result=hook.handle(self.event(r,hook_event_name='Stop',last_assistant_message='检查完成，耗时1秒'),r/'state',r)
   self.assertIn('变更',result['reason'])
 def test_unregistered_plain_zip_cannot_silently_pass(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);hook.handle(self.event(r),r/'state',r)
   result=hook.handle(self.event(r,hook_event_name='Stop',last_assistant_message='检查完成，耗时1秒，成品 /tmp/result.zip'),r/'state',r)
   self.assertEqual(result['decision'],'block')
 def test_new_turn_resets_terminal_retry_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);hook.handle(self.event(r,turn_id='old'),r/'state',r)
   stop=self.event(r,hook_event_name='Stop',last_assistant_message='检查完成，耗时1秒')
   hook.handle(stop,r/'state',r);hook.handle(stop,r/'state',r)
   hook.handle(self.event(r,turn_id='new',prompt='继续完成'),r/'state',r)
   self.assertEqual(hook.handle(stop,r/'state',r)['decision'],'block')
 def test_registered_real_contract_runs_gate(self):
  from test_delivery_rules import DeliveryRules
  case=DeliveryRules('test_host_output_and_honest_deferred_archive_pass');case.setUp()
  try:
   r=case.root;state_root=r/'state';p=r/'contract.json'
   # The contract is fixture data; the registered artifact and review use actual bytes/hashes.
   case.c['retention'].setdefault('retained_reason',{}).update({str(p):'gate contract',str(case.evidence):'independent review',str(state_root):'hook test runtime'})
   p.write_text(json.dumps(case.c));hook.register('test-session-123',p,state_root,r)
   summary=f'核验完成，交付文件 {case.artifact}，目录状态已核对，耗时1秒'
   self.assertEqual(hook.handle(self.event(r,hook_event_name='Stop',last_assistant_message=summary),state_root,r),{})
  finally:case.doCleanups()
 def test_registered_file_summary_requires_artifact_and_folder_status(self):
  from test_delivery_rules import DeliveryRules
  case=DeliveryRules('test_host_output_and_honest_deferred_archive_pass');case.setUp()
  try:
   r=case.root;state_root=r/'state';p=r/'contract.json'
   case.c['retention'].setdefault('retained_reason',{}).update({str(p):'gate contract',str(case.evidence):'independent review',str(state_root):'hook test runtime'})
   p.write_text(json.dumps(case.c));hook.register('test-session-123',p,state_root,r)
   result=hook.handle(self.event(r,hook_event_name='Stop',last_assistant_message='核验完成，耗时1秒'),state_root,r)
   self.assertEqual(result['decision'],'block')
   self.assertTrue('实际成品' in result['reason'] or '目录' in result['reason'])
  finally:case.doCleanups()
 def test_terminal_reset_without_optional_turn_id(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);hook.handle(self.event(r),r/'state',r)
   stop=self.event(r,hook_event_name='Stop',last_assistant_message='核验完成，耗时1秒')
   hook.handle(stop,r/'state',r);hook.handle(stop,r/'state',r)
   hook.handle(self.event(r,prompt='继续'),r/'state',r)
   self.assertEqual(hook.handle(stop,r/'state',r)['decision'],'block')
if __name__=='__main__':unittest.main()
