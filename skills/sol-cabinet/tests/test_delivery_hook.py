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
 def confirm(self,root,state_root,tier=1,budget=12):
  if self.state(state_root) is None:self.activate(root,state_root)
  stage="（本阶段）" if tier==4 else ""
  card="\n".join([
   "【任务启动】",
   f"级别：T{tier}",
   "预计耗时：>60 分钟" if tier==4 else "预计耗时：5–10 分钟",
   "预计交付：测试",
   "推荐路径：主代理直接执行",
   f"执行预算上限：{budget} 分钟{stage}",
   "请选择：A 按方案开始 / B 调整交付 / C 调整要求 / D 取消",
  ])
  shown=hook.handle(self.stop(root,last_assistant_message=card),state_root,root)
  self.assertIs(shown["continue"],False)
  hook.handle(self.event(root,prompt="A 按方案开始"),state_root,root)
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
   self.assertIn('T1-T4',context);self.assertIn('用户明确选 A',context)
   self.assertEqual(state['schema_version'],3);self.assertEqual(state['intake_phase'],'AWAITING_CARD')
   self.assertEqual(state['phase'],'AWAITING_DECLARATION');self.assertEqual(state['mode'],'undecided');self.assertEqual(state['failure_count'],0)
   self.assertNotIn('SENSITIVE-TEXT',''.join(p.read_text() for p in (r/'state').glob('*.json')))
 def test_ordinary_office_requests_enter_intake_without_explicit_sol_name(self):
  prompts=[
   '把这份扫描 PDF 转成可编辑 Word，再审稿并生成带修订痕迹的 Word。',
   '帮我把这篇 1500 字通知修改得更正式。',
   '根据 8 份材料形成一份 5000 字综合报告，并核对主要数据。',
   '整理并统一修改 80 份文件，生成总目录、问题清单和最终版本。',
  ]
  for prompt in prompts:
   with self.subTest(prompt=prompt):
    with tempfile.TemporaryDirectory() as d:
     r=Path(d);state_root=r/'state'
     result=hook.handle(self.event(r,prompt=prompt),state_root,r)
     self.assertIn('启动门',result['hookSpecificOutput']['additionalContext'])
     self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_CARD')
  with tempfile.TemporaryDirectory() as d:
   r=Path(d)
   self.assertEqual(hook.handle(self.event(r,prompt='你好，今天几号？'),r/'other-state',r),{})

 def test_tools_are_blocked_until_confirmation_and_after_budget(self):
  from datetime import datetime, timezone, timedelta
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root)
   pre=self.event(r,hook_event_name='PreToolUse',tool_name='Bash',tool_input={'command':'touch x'})
   self.assertEqual(hook.handle(pre,state_root,r)['hookSpecificOutput']['permissionDecision'],'deny')
   self.confirm(r,state_root,budget=1)
   self.assertEqual(hook.handle(pre,state_root,r),{})
   agent_call=self.event(r,hook_event_name='PreToolUse',tool_name='Agent',tool_input={})
   self.assertEqual(hook.handle(agent_call,state_root,r)['hookSpecificOutput']['permissionDecision'],'deny')
   state=self.state(state_root);state['execution_started_at']=(datetime.now(timezone.utc)-timedelta(seconds=61)).isoformat()
   hook.save(hook.state_file('test-session-123',state_root),state)
   denied=hook.handle(pre,state_root,r)
   self.assertEqual(denied['hookSpecificOutput']['permissionDecision'],'deny')
   self.assertEqual(self.state(state_root)['intake_phase'],'BUDGET_EXHAUSTED')
   status=hook.handle(self.event(r,turn_id='turn-2',prompt='请总结当前已有结果'),state_root,r)
   self.assertIn('只可基于现有上下文',status['hookSpecificOutput']['additionalContext'])
   self.assertEqual(self.state(state_root)['intake_phase'],'BUDGET_EXHAUSTED')
   report='【执行熔断】原预计5–10分钟；已达到1分钟预算；阻塞原因：版式恢复未完成；当前已有文本恢复稿，PARTIAL。'
   stopped=hook.handle(self.stop(r,last_assistant_message=report),state_root,r)
   self.assertIs(stopped['continue'],False)
   renewed=hook.handle(self.event(r,turn_id='turn-2',prompt='$sol-cabinet 继续一次'),state_root,r)
   self.assertIn('启动卡和预算',renewed['hookSpecificOutput']['additionalContext'])
   self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_CARD')

 def test_card_requires_all_fields_and_t4_stage_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root)
   incomplete="\n".join(["【任务启动】","级别：T1","预计交付：测试","推荐路径：主代理",
                       "执行预算上限：12分钟","请选择：A 开始 / B 调整 / C 调整 / D 取消"])
   result=hook.handle(self.stop(r,last_assistant_message=incomplete),state_root,r)
   self.assertEqual(result['decision'],'block')
   invalid_t4="\n".join(["【任务启动】","级别：T4","预计耗时：>60分钟","预计交付：阶段成果",
                         "推荐路径：分阶段","执行预算上限：60分钟","请选择：A 开始 / B 调整 / C 调整 / D 取消"])
   result=hook.handle(self.stop(r,last_assistant_message=invalid_t4),state_root,r)
   self.assertEqual(result['decision'],'block')
   valid_t4=invalid_t4.replace("执行预算上限：60分钟","执行预算上限：60分钟（本阶段）")
   result=hook.handle(self.stop(r,last_assistant_message=valid_t4),state_root,r)
   self.assertIs(result['continue'],False)
   self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_CONFIRMATION')

 def test_t4_stage_completion_requires_a_new_card(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root,tier=4,budget=60)
   hook.declare_analysis('test-session-123',state_root)
   stopped=hook.handle(self.stop(r,last_assistant_message='阶段一完成，已交付结果并核验，耗时20分钟。'),state_root,r)
   self.assertIn('新阶段启动卡',stopped['systemMessage'])
   self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_NEXT_STAGE')
   pre=self.event(r,hook_event_name='PreToolUse',tool_name='Bash',tool_input={'command':'touch x'})
   self.assertEqual(hook.handle(pre,state_root,r)['hookSpecificOutput']['permissionDecision'],'deny')
   next_card=hook.handle(self.event(r,turn_id='turn-2',prompt='继续第二阶段'),state_root,r)
   self.assertIn('新启动卡',next_card['hookSpecificOutput']['additionalContext'])
   self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_CARD')

 def test_confirmation_acceptance_is_explicit_and_cancel_clears_state(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.activate(r,state_root)
   card="\n".join(["【任务启动】","级别：T1","预计耗时：5–10分钟","预计交付：测试",
                   "推荐路径：主代理","执行预算上限：12分钟",
                   "请选择：A 按方案开始 / B 调整交付 / C 调整要求 / D 取消"])
   hook.handle(self.stop(r,last_assistant_message=card),state_root,r)
   refused=hook.handle(self.event(r,prompt='也许先不要开始'),state_root,r)
   self.assertIn('仍在等待',refused['hookSpecificOutput']['additionalContext'])
   self.assertEqual(self.state(state_root)['intake_phase'],'AWAITING_CONFIRMATION')
   hook.handle(self.event(r,prompt='D 取消'),state_root,r)
   self.assertIsNone(self.state(state_root))

 def test_registration_requires_active_activation(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);p=r/'contract.json';p.write_text('{}')
   self.activate(r,r/'state')
   with self.assertRaisesRegex(ValueError,'confirm'):hook.register('test-session-123',p,r/'state',r)
   with self.assertRaisesRegex(ValueError,'confirm'):hook.declare_analysis('test-session-123',r/'state')
   self.confirm(r,r/'state');hook.declare_analysis('test-session-123',r/'state')
 def test_file_registration_moves_to_ready_and_locks_contract(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}')
   self.confirm(r,state_root);hook.register('test-session-123',p,state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['mode'],'file');self.assertEqual(state['failure_count'],0)
   self.assertEqual(state['contract'],str(p.resolve()));self.assertEqual(len(state['contract_sha256']),64)
 def test_analysis_declaration_moves_to_ready_without_contract(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);hook.declare_analysis('test-session-123',state_root);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['mode'],'analysis');self.assertIsNone(state['contract'])
 def test_file_mode_cannot_downgrade_to_analysis(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.confirm(r,state_root);hook.register('test-session-123',p,state_root,r)
   with self.assertRaisesRegex(ValueError,'cannot downgrade'):hook.declare_analysis('test-session-123',state_root)
   self.assertEqual(self.state(state_root)['mode'],'file')
 def test_analysis_mode_cannot_switch_to_file(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.confirm(r,state_root);hook.declare_analysis('test-session-123',state_root)
   with self.assertRaisesRegex(ValueError,'locked'):hook.register('test-session-123',p,state_root,r)
   self.assertEqual(self.state(state_root)['mode'],'analysis')
 def test_missing_declaration_blocks_once_then_enters_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);e=self.stop(r,last_assistant_message='完成检查，耗时1秒 [文稿](/a.docx)')
   first=hook.handle(e,state_root,r);self.assertEqual(first['decision'],'block');self.assertEqual(self.state(state_root)['phase'],'RETRY_REQUIRED');self.assertEqual(self.state(state_root)['failure_count'],1)
   second=hook.handle(e,state_root,r);self.assertIs(second['continue'],False);self.assertEqual(self.state(state_root)['phase'],'TERMINAL_PARTIAL');self.assertEqual(self.state(state_root)['failure_count'],2)
 def test_reregister_after_failure_does_not_reset_retry_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);hook.handle(self.stop(r),state_root,r)
   p=r/'contract.json';p.write_text('{}');hook.register('test-session-123',p,state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'READY');self.assertEqual(state['failure_count'],1)
   result=hook.handle(self.stop(r),state_root,r);self.assertIs(result['continue'],False);self.assertEqual(self.state(state_root)['phase'],'TERMINAL_PARTIAL')
 def test_terminal_stop_is_idempotently_non_retrying(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   again=hook.handle(e,state_root,r);self.assertIs(again['continue'],False);self.assertIn('重新激活',again['systemMessage'])
 def test_terminal_does_not_leak_into_unrelated_next_prompt(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   self.assertEqual(hook.handle(self.event(r,turn_id='turn-2',prompt='今天天气怎么样'),state_root,r),{})
   self.assertIsNone(self.state(state_root));self.assertEqual(hook.handle(self.stop(r,turn_id='turn-2'),state_root,r),{})
 def test_terminal_requires_explicit_retrigger_for_fresh_budget(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);e=self.stop(r);hook.handle(e,state_root,r);hook.handle(e,state_root,r)
   hook.handle(self.event(r,turn_id='turn-2',prompt='$sol-cabinet 继续'),state_root,r);state=self.state(state_root)
   self.assertEqual(state['phase'],'AWAITING_DECLARATION');self.assertEqual(state['failure_count'],0);self.assertEqual(state['turn_id'],'turn-2')
 def test_analysis_completion_clears_state(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);hook.declare_analysis('test-session-123',state_root)
   self.assertEqual(hook.handle(self.stop(r),state_root,r),{});self.assertEqual(list(state_root.iterdir()),[])
 def test_analysis_cannot_claim_file_delivery(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root);hook.declare_analysis('test-session-123',state_root)
   result=hook.handle(self.stop(r,last_assistant_message='核验完成，耗时1秒，交付文件 /tmp/result.pdf'),state_root,r)
   self.assertEqual(result['decision'],'block');self.assertIn('声明无文件分析',result['reason'])
 def test_outside_root_and_invalid_id(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);self.assertEqual(hook.handle(self.event(r,cwd='/outside'),r/'state',r),{})
   with self.assertRaises(ValueError):hook.handle(self.event(r,session_id='../escape'),r/'state',r)
 def test_changed_contract_not_reused(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';p=r/'contract.json';p.write_text('{}');self.confirm(r,state_root);hook.register('test-session-123',p,state_root,r);p.write_text('{"changed":true}')
   result=hook.handle(self.stop(r),state_root,r);self.assertIn('变更',result['reason'])
 def test_unregistered_plain_zip_cannot_silently_pass(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);state_root=r/'state';self.confirm(r,state_root)
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
   r=case.base;state_root=r/'state';p=Path(case.result['contract']);self.confirm(r,state_root)
   hook.register('test-session-123',p,state_root,r)
   summary=f"核验完成，交付文件 {case.result['artifacts'][0]['path']}，目录状态已核对，耗时1秒"
   self.assertEqual(hook.handle(self.stop(r,last_assistant_message=summary),state_root,r),{})
  finally:case.doCleanups()

 def test_stale_or_wrong_summary_path_is_blocked(self):
  from test_delivery_rules import TaskLifecycleRules
  case=TaskLifecycleRules('test_t1_initial_task_creates_b01_v1_and_final_pass');case.setUp()
  try:
   case.prepare(1);case.publish()
   r=case.base;state_root=r/'state';self.confirm(r,state_root)
   hook.register('test-session-123',Path(case.result['contract']),state_root,r)
   result=hook.handle(self.stop(r,last_assistant_message='FINAL PASS 未完成项：无 核验完成，交付文件 /wrong/nonexistent.pdf，归档完成，耗时1秒'),state_root,r)
   self.assertEqual(result['decision'],'block')
  finally:case.doCleanups()
 def test_registered_file_summary_requires_artifact_and_folder_status(self):
  from test_delivery_rules import DeliveryRules
  case=DeliveryRules('test_host_output_and_honest_deferred_archive_pass');case.setUp()
  try:
   r=case.root;state_root=r/'state';p=r/'contract.json';self.confirm(r,state_root)
   case.c['retention'].setdefault('retained_reason',{}).update({str(p):'gate contract',str(case.evidence):'independent review',str(state_root):'hook test runtime'})
   p.write_text(json.dumps(case.c));hook.register('test-session-123',p,state_root,r)
   result=hook.handle(self.stop(r,last_assistant_message='核验完成，耗时1秒'),state_root,r)
   self.assertEqual(result['decision'],'block');self.assertTrue('实际成品' in result['reason'] or '目录' in result['reason'])
  finally:case.doCleanups()


if __name__=='__main__':unittest.main()
