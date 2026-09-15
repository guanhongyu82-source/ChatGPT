#!/usr/bin/env python3
"""Scoped Codex prompt/Stop adapter. No network, prompt logging or model selection.

Requires host hook trust. Checks registered task files, not model truthfulness.
A second failure ends with a visible PARTIAL warning instead of an unbounded loop.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
from delivery_gate import check
from maintenance_boundary import guarded

BASE = Path('/Users/macbook/ChatGPT')
STATE = BASE / 'system/codex-home/sol-cabinet-runtime'
SID = re.compile(r'^[A-Za-z0-9_-]{8,100}$')
TRIGGER = re.compile(r'\$sol-cabinet|使用\s*sol\s*cabinet|交给\s*sol\s*cabinet|SC处理|<name>sol-cabinet</name>',re.I)
DELIVERY_CLAIM = re.compile(r'(?:成品|交付文件|保存为|下载|deliverable).{0,180}(?:/|\.[a-zA-Z0-9]{2,8})',re.I)
ARTIFACT = re.compile(r'\]\(<?(/[^\n)]+\.(?:docx|xlsx|pptx|pdf|md|csv|html))>?\)',re.I)

def state_file(session_id, state_root=STATE):
    if not isinstance(session_id,str) or not SID.fullmatch(session_id):
        raise ValueError('invalid session id')
    return state_root / (hashlib.sha256(session_id.encode()).hexdigest()+'.json')

@guarded
def save(path, state):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    temp=path.with_suffix('.tmp')
    with open(temp,'w',encoding='utf-8') as f:
        os.chmod(temp,0o600);json.dump(state,f,ensure_ascii=False)
    os.replace(temp,path)

@guarded
def register(session_id, contract, state_root=STATE, allowed_root=BASE):
    contract=Path(contract).resolve()
    if not contract.is_relative_to(allowed_root.resolve()) or not contract.is_file():
        raise ValueError('contract must exist inside the authorized working root')
    data=json.loads(contract.read_text())
    if not isinstance(data,dict):raise ValueError('contract must be object')
    path=state_file(session_id,state_root)
    state=json.loads(path.read_text()) if path.exists() else {'session_id':session_id,'model':None}
    state.update(mode='file',contract=str(contract),contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest())
    save(path,state)

@guarded
def handle(event,state_root=STATE,allowed_root=BASE):
    if not isinstance(event,dict):raise ValueError('event must be object')
    cwd=Path(event.get('cwd') or '/')
    if not cwd.resolve().is_relative_to(allowed_root.resolve()):return {}
    kind=event.get('hook_event_name')
    if kind not in ('UserPromptSubmit','Stop'):return {}
    path=state_file(event.get('session_id'),state_root)
    if kind=='UserPromptSubmit':
        triggered=bool(TRIGGER.search(event.get('prompt') or ''))
        previous=json.loads(path.read_text()) if path.exists() else {}
        if not triggered:
            if previous.get('terminal'):
                previous.update(blocked_once=False,terminal=False,turn_id=event.get('turn_id'),mode='undecided',contract=None)
                save(path,previous)
            return {}
        # Only opaque IDs and selected model; never persist the user prompt or attachments.
        save(path,{'session_id':event['session_id'],'turn_id':event.get('turn_id'),
                   'model':event.get('model'),'mode':'undecided','started_at':datetime.now(timezone.utc).isoformat()})
        return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':
          'Sol Cabinet 执行提醒：先简述T级及预计耗时；沿用当前模型，不自行换型。按当前宿主路径规则保存，成品规范命名，过程文件最小留存。文件交付前生成一份delivery-contract.json并调用 scripts/codex_delivery_hook.py --register --session-id '+event['session_id']+' --contract 绝对路径。Stop会校验登记文件；收尾写结果、核验、未完成项及实际耗时，有失误说明处置并按evolution-policy记录。无文件的分析答疑不虚造文件契约，调用同脚本 --analysis-only --session-id '+event['session_id']+' 明确无文件交付。'}}
    if not path.exists():return {}
    state=json.loads(path.read_text());last=event.get('last_assistant_message') or ''
    issues=[]
    contract=state.get('contract')
    if contract:
        p=Path(contract)
        if not p.resolve().is_relative_to(allowed_root.resolve()) or not p.is_file():issues.append('交付契约不存在或越界')
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=state.get('contract_sha256'):issues.append('交付契约变更后未重新登记')
        else:
            try:issues+=check(json.loads(p.read_text()),contract_path=p)['issues']
            except (OSError,ValueError,TypeError):issues.append('交付契约无法核验')
    elif state.get('mode')!='analysis':issues.append('未登记本次文件契约；无文件任务须显式声明analysis-only')
    elif DELIVERY_CLAIM.search(last) or '/outputs/' in last:issues.append('声明无文件分析但回复包含成品交付，须登记契约')
    if '耗时' not in last and 'elapsed' not in last.lower():issues.append('缺少实际耗时或不可核实的说明')
    if not any(s in last for s in ('完成','结果','核验','验证','检查','未完成','PARTIAL','BLOCKED')):issues.append('缺少结果与核验小结')
    model_changed=bool(state.get('model') and event.get('model') and state['model']!=event['model'])
    if issues:
        if event.get('stop_hook_active') or state.get('blocked_once'):
            state['terminal']=True;save(path,state)
            return {'continue':False,'stopReason':'Sol Cabinet delivery checks remain incomplete',
                    'systemMessage':'Sol Cabinet：PARTIAL，交付检查仍未通过；已停止自动重试以避免继续消耗。'+ '；'.join(issues[:5])}
        state['blocked_once']=True;save(path,state)
        return {'decision':'block','reason':'Sol Cabinet交付检查未通过：'+'；'.join(issues[:5])+'。只修复这些已授权缺项；不能补造开工提示、审核或归档状态。无法修复则明确PARTIAL，不得虚称完成。'}
    path.unlink()
    if model_changed:return {'systemMessage':'本任务模型与开工记录不同；钩子没有切换模型，需核对会话设置来源。'}
    return {}

@guarded
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--register',action='store_true');p.add_argument('--analysis-only',action='store_true');p.add_argument('--session-id');p.add_argument('--contract')
    a=p.parse_args()
    try:
        if a.analysis_only:
            path=state_file(a.session_id)
            state=json.loads(path.read_text()) if path.exists() else {'session_id':a.session_id,'model':None}
            state.update(mode='analysis',contract=None);save(path,state);return 0
        if a.register:
            if not a.contract:raise ValueError('contract required')
            register(a.session_id,a.contract);return 0
        print(json.dumps(handle(json.load(sys.stdin)),ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError) as exc:
        # A malformed hook event must be visible and never silently claim validation.
        print(json.dumps({'systemMessage':'Sol Cabinet钩子无法核验：'+type(exc).__name__},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
