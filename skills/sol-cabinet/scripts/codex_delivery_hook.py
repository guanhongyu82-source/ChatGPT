#!/usr/bin/env python3
"""Scoped Codex prompt/Stop adapter. No network, prompt logging or model selection.

Requires host hook trust. Checks registered task files, not model truthfulness.
A first failure permits one targeted retry; a second failure enters TERMINAL_PARTIAL.
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
SHA256 = re.compile(r'^[0-9a-f]{64}$')
TRIGGER = re.compile(r'\$sol-cabinet|使用\s*sol\s*cabinet|交给\s*sol\s*cabinet|SC处理|<name>sol-cabinet</name>',re.I)
TASK_TRIGGER = re.compile(r'(?:\.pdf\b|\.docx\b|扫描\s*PDF|Word|Excel|PPT|通知|报告|材料|文件|表格).{0,120}(?:修改|整理|转换|形成|生成|核对|审稿|审查|分析|撰写|起草|制作|提取|翻译|校对|润色|改写|改成|改为)|(?:修改|整理|转换|形成|生成|核对|审稿|审查|分析|撰写|起草|制作|提取|翻译|校对|润色).{0,120}(?:文件|材料|报告|通知|表格|文字|段落|句子|文本|Word|PDF|PPT|Excel)|帮我|请帮|请把|请将|把.{0,80}(?:改|写|整理|生成|核对|审稿|分析|总结)|\b(?:please|can you)\b.{0,100}\b(?:edit|fix|rewrite|summarize|create|review|check|analyze|convert|build|prepare|draft|translate)\b|\b(?:edit|fix|rewrite|summarize|create|review|check|analyze|convert|build|prepare|draft|translate)\b',re.I)
DELIVERY_CLAIM = re.compile(r'(?:成品|交付文件|实际成品|保存为|下载|deliverable).{0,180}(?:/|\.[a-zA-Z0-9]{2,8})',re.I)
ARTIFACT = re.compile(r'\]\(<?(/[^\n)]+\.(?:docx|xlsx|pptx|pdf|md|csv|html))>?\)',re.I)
PHASES = {'AWAITING_DECLARATION','READY','RETRY_REQUIRED','TERMINAL_PARTIAL'}
MODES = {'undecided','file','analysis'}
INTAKE_PHASES = {'AWAITING_CARD','AWAITING_CONFIRMATION','EXECUTING','BUDGET_EXHAUSTED','AWAITING_NEXT_STAGE'}
STATE_KEYS = {
    'schema_version','session_id','turn_id','model','phase','mode','failure_count',
    'contract','contract_sha256','started_at','updated_at','intake_phase','intake_tier',
    'budget_seconds','execution_started_at','card_shown_at',
}
CONFIRM_START = {'a','a按方案开始','a按推荐方案开始','按方案开始','按推荐方案开始','确认开始','开始执行','yesstart'}
CANCEL_START = {'d','d取消','dcancel','取消','停止','终止','不做了','cancel'}
REAUTHORIZE = re.compile(r'继续|重新开始|再给.{0,12}(?:分钟|时间)|允许.{0,12}继续|授权.{0,12}继续|下一阶段|下阶段|stage\s*\d+',re.I)
CONTINUE_RE = re.compile(r'继续|下一阶段|下阶段|第[二三四五六七八九0-9]+阶段|开始.{0,8}阶段|stage\s*\d+',re.I)
STATUS_ONLY = re.compile(r'进度|状态|当前已有|总结当前|说明原因|为什么停|已有结果|交付当前|交付现有|当前阶段|\bstatus\b|\bprogress\b|\bsummarize.{0,40}(?:current|existing|so far|results)\b|\bcurrent results\b',re.I)
START_TIER = re.compile(r'级别\s*[:：]\s*T([1-4])',re.I)
START_ESTIMATE = re.compile(r'预计耗时\s*[:：]\s*(?:\d+\s*[-–—~至]\s*\d+|[≤<>]\s*\d+)\s*分钟',re.I)
START_BUDGET = re.compile(r'(?:执行预算(?:上限)?|本阶段预算)\s*[:：]\s*(\d{1,5})\s*分钟',re.I)
FUSE_MARKER = re.compile(r'执行熔断|execution fuse',re.I)


def _now():
    return datetime.now(timezone.utc).isoformat()


def state_file(session_id, state_root=STATE):
    if not isinstance(session_id,str) or not SID.fullmatch(session_id):
        raise ValueError('invalid session id')
    return state_root / (hashlib.sha256(session_id.encode()).hexdigest()+'.json')


def _valid_time(value):
    if not isinstance(value,str) or not value:return False
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None
    except ValueError:return False


def validate_state(state, session_id=None):
    if not isinstance(state,dict) or set(state)!=STATE_KEYS:raise ValueError('hook state schema mismatch')
    if state.get('schema_version')!=3:raise ValueError('unsupported hook state version')
    if not isinstance(state.get('session_id'),str) or not SID.fullmatch(state['session_id']):raise ValueError('invalid hook state session')
    if session_id is not None and state['session_id']!=session_id:raise ValueError('hook state session mismatch')
    if state.get('phase') not in PHASES or state.get('mode') not in MODES:raise ValueError('invalid hook state lifecycle')
    if type(state.get('failure_count')) is not int or not 0<=state['failure_count']<=2:raise ValueError('invalid hook failure count')
    if state.get('turn_id') is not None and not isinstance(state.get('turn_id'),(str,int)):raise ValueError('invalid hook turn id')
    if state.get('model') is not None and not isinstance(state.get('model'),str):raise ValueError('invalid hook model')
    if not _valid_time(state.get('started_at')) or not _valid_time(state.get('updated_at')):raise ValueError('invalid hook timestamps')
    if state.get('intake_phase') not in INTAKE_PHASES:raise ValueError('invalid intake phase')
    tier=state.get('intake_tier');budget=state.get('budget_seconds')
    if tier is not None and (type(tier) is not int or not 1<=tier<=4):raise ValueError('invalid intake tier')
    if budget is not None and (type(budget) is not int or not 60<=budget<=604800):raise ValueError('invalid execution budget')
    for key in ('execution_started_at','card_shown_at'):
        value=state.get(key)
        if value is not None and not _valid_time(value):raise ValueError('invalid intake timestamp')
    if state['intake_phase']=='AWAITING_CARD' and any(state.get(k) is not None for k in ('intake_tier','budget_seconds','execution_started_at','card_shown_at')):raise ValueError('awaiting-card state cannot hold a budget')
    if state['intake_phase']=='AWAITING_CONFIRMATION' and (tier is None or budget is None or state.get('execution_started_at') is not None or state.get('card_shown_at') is None):raise ValueError('confirmation state requires a shown card')
    if state['intake_phase']=='AWAITING_NEXT_STAGE' and (tier!=4 or budget is not None or state.get('execution_started_at') is not None or state.get('card_shown_at') is not None):raise ValueError('next-stage state requires completed T4 stage')
    if state['intake_phase'] in {'EXECUTING','BUDGET_EXHAUSTED'} and (tier is None or budget is None or state.get('execution_started_at') is None):raise ValueError('active intake state requires a confirmed budget')
    contract, digest = state.get('contract'), state.get('contract_sha256')
    if state['mode']=='file':
        if not isinstance(contract,str) or not contract or not isinstance(digest,str) or SHA256.fullmatch(digest) is None:raise ValueError('file hook state requires locked contract')
    else:
        if contract is not None or digest is not None:raise ValueError('non-file hook state cannot retain a contract')
    if state['phase']=='AWAITING_DECLARATION' and state['mode']!='undecided':raise ValueError('awaiting state must be undecided')
    if state['phase']=='READY' and state['mode']=='undecided':raise ValueError('ready state requires delivery mode')
    if state['phase']=='RETRY_REQUIRED' and state['failure_count']!=1:raise ValueError('retry state requires one prior failure')
    if state['phase']=='TERMINAL_PARTIAL' and state['failure_count']<2:raise ValueError('terminal state requires exhausted retry')
    return state


def load(path, session_id=None):
    if path.is_symlink():raise ValueError('unsafe hook state file')
    if not path.exists():return None
    if not path.is_file():raise ValueError('unsafe hook state file')
    state=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(state,dict) and state.get('schema_version')==2:
        state.update(schema_version=3,intake_phase='AWAITING_CARD',intake_tier=None,
                     budget_seconds=None,execution_started_at=None,card_shown_at=None)
    return validate_state(state,session_id)


@guarded
def save(path, state):
    validate_state(state,state.get('session_id'))
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    temp=path.with_suffix('.tmp')
    with open(temp,'w',encoding='utf-8') as f:
        os.chmod(temp,0o600);json.dump(state,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def _activation(event):
    stamp=_now()
    return {
        'schema_version':3,'session_id':event['session_id'],'turn_id':event.get('turn_id'),
        'model':event.get('model'),'phase':'AWAITING_DECLARATION','mode':'undecided',
        'failure_count':0,'contract':None,'contract_sha256':None,
        'started_at':stamp,'updated_at':stamp,'intake_phase':'AWAITING_CARD','intake_tier':None,
        'budget_seconds':None,'execution_started_at':None,'card_shown_at':None,
    }


@guarded
def register(session_id, contract, state_root=STATE, allowed_root=BASE):
    path=state_file(session_id,state_root);state=load(path,session_id)
    if state is None or state['phase']=='TERMINAL_PARTIAL':raise ValueError('active Sol Cabinet activation required before file registration')
    if state['intake_phase']!='EXECUTING':raise ValueError('user must confirm the task intake card before file registration')
    if state['mode']=='analysis':raise ValueError('analysis delivery mode is locked for this activation')
    contract=Path(contract).resolve()
    if not contract.is_relative_to(allowed_root.resolve()) or not contract.is_file():raise ValueError('contract must exist inside the authorized working root')
    data=json.loads(contract.read_text(encoding='utf-8'))
    if not isinstance(data,dict):raise ValueError('contract must be object')
    state.update(phase='READY',mode='file',contract=str(contract),contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),updated_at=_now())
    save(path,state)


@guarded
def declare_analysis(session_id, state_root=STATE):
    path=state_file(session_id,state_root);state=load(path,session_id)
    if state is None or state['phase']=='TERMINAL_PARTIAL':raise ValueError('active Sol Cabinet activation required before analysis declaration')
    if state['intake_phase']!='EXECUTING':raise ValueError('user must confirm the task intake card before analysis declaration')
    if state['mode']=='file':raise ValueError('file delivery mode cannot downgrade to analysis in the same activation')
    state.update(phase='READY',mode='analysis',contract=None,contract_sha256=None,updated_at=_now())
    save(path,state)


def _normalized_choice(value):
    return re.sub(r"\s+|[，,。.!！?？:：;；（）()【】\[\]]", "", value or "").lower()



def _card_budget(message):
    message=message or ""
    tier=START_TIER.search(message)
    budget=START_BUDGET.search(message)
    estimate=START_ESTIMATE.search(message)
    choices=re.search(r'请选择.{0,200}A.{0,80}B.{0,80}C.{0,80}D',message,re.S)
    if ('【任务启动】' not in message or not tier or not budget or not estimate or not choices
            or any(key not in message for key in ('预计交付','推荐路径'))):
        return None
    if int(tier.group(1))==4 and '本阶段' not in message:
        return None
    minutes=int(budget.group(1))
    if not 1<=minutes<=10080:
        return None
    level=int(tier.group(1))
    if minutes>{1:12,2:30,3:75,4:60}[level]:
        return None
    return level,minutes*60


def _valid_fuse_summary(message):
    text=message or ""
    return (bool(FUSE_MARKER.search(text))
            and ('预计' in text or '原预计' in text)
            and '预算' in text and ('阻塞' in text or '原因' in text)
            and ('当前已有' in text or '已有' in text)
            and ('PARTIAL' in text or '部分' in text or '未完成' in text))


def _elapsed(state):
    try:
        start=datetime.fromisoformat(state["execution_started_at"].replace("Z","+00:00"))
        return max(0.0,(datetime.now(timezone.utc)-start).total_seconds())
    except (TypeError,ValueError):
        return 0.0


def _expired(state):
    return state["intake_phase"]=="EXECUTING" and _elapsed(state)>=state["budget_seconds"]


def _deny_tool(reason):
    return {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
                                  "permissionDecisionReason":reason}}


def _intake_context(kind,text):
    return {"hookSpecificOutput":{"hookEventName":kind,"additionalContext":text}}


@guarded
def handle(event,state_root=STATE,allowed_root=BASE):
    if not isinstance(event,dict):raise ValueError('event must be object')
    cwd=Path(event.get('cwd') or '/')
    if not cwd.resolve().is_relative_to(allowed_root.resolve()):return {}
    kind=event.get('hook_event_name')
    if kind not in ('UserPromptSubmit','Stop','PreToolUse'):return {}
    session_id=event.get('session_id');path=state_file(session_id,state_root)

    if kind=='UserPromptSubmit':
        prompt=event.get('prompt') or ''
        triggered=bool(TRIGGER.search(prompt) or TASK_TRIGGER.search(prompt))
        previous=load(path,session_id)
        if triggered and (previous is None or previous['phase']=='TERMINAL_PARTIAL'):
            state=_activation(event);save(path,state)
            return _intake_context(kind,
              'Sol Cabinet 启动门：只用任务描述和可见文件元数据快速定 T1-T4；本轮只输出简短启动卡。用户明确选 A 前不读正文、不归档、不调用工具/Agent、不联网、不登记契约。卡片要列预计耗时、预计交付、推荐路径、预算上限和 A/B/C/D；B/C 重出卡，D 停止。预算从确认时计时；到期停止并报告 PARTIAL。')
        state=previous
        if state is None:return {}
        if state['phase']=='TERMINAL_PARTIAL':
            path.unlink();return {}
        state.update(turn_id=event.get('turn_id'),updated_at=_now())
        choice=_normalized_choice(prompt)
        if state['intake_phase']=='AWAITING_CONFIRMATION':
            if choice in CANCEL_START:
                path.unlink()
                return _intake_context(kind,'Sol Cabinet：用户已取消，本任务不执行。')
            if choice in CONFIRM_START:
                state.update(intake_phase='EXECUTING',execution_started_at=_now(),updated_at=_now())
                save(path,state)
                return _intake_context(kind,'用户已确认启动卡。现在开始计时；只按卡片目标和预算执行，纠偏沿用同一预算。预算到期不再调用工具或启动代理，只整理现有结果并报告执行熔断。')
            save(path,state)
            return _intake_context(kind,'Sol Cabinet 仍在等待启动确认。若用户调整了交付、速度或质量，只更新并重新显示启动卡；未收到明确 A/开始执行前不执行任何工作。')
        if state['intake_phase']=='AWAITING_CARD':
            save(path,state)
            return _intake_context(kind,'Sol Cabinet 尚未显示有效启动卡。本轮只生成 T1-T4 启动卡，不执行任务。')
        if state['intake_phase']=='AWAITING_NEXT_STAGE':
            if STATUS_ONLY.search(prompt) and not CONTINUE_RE.search(prompt):
                save(path,state)
                return _intake_context(kind,'T4 当前阶段已停止。只可说明已完成阶段和下一阶段建议；不得调用工具。')
            if CONTINUE_RE.search(prompt):
                state.update(intake_phase='AWAITING_CARD',intake_tier=None,budget_seconds=None,
                             execution_started_at=None,card_shown_at=None,phase='AWAITING_DECLARATION',
                             mode='undecided',failure_count=0,contract=None,contract_sha256=None,
                             updated_at=_now())
                save(path,state)
                return _intake_context(kind,'T4 上一阶段已停止。先为明确的下一阶段生成新启动卡和预算；等待用户重新确认后才能继续。')
            if triggered or TASK_TRIGGER.search(prompt):
                state=_activation(event);save(path,state)
                return _intake_context(kind,'T4 上一阶段已停止。新任务先生成 T1-T4 启动卡并等待确认。')
            path.unlink()
            return {}
        if state['intake_phase']=='BUDGET_EXHAUSTED':
            compact=_normalized_choice(prompt)
            if compact in CANCEL_START or re.search(r'(?:不再|不要|先不|停止|取消|终止).{0,12}继续',prompt):
                path.unlink()
                return _intake_context(kind,'Sol Cabinet：用户已终止超预算任务，不再续作。')
            if STATUS_ONLY.search(prompt) and not REAUTHORIZE.search(prompt):
                save(path,state)
                return _intake_context(kind,'预算已经熔断。只可基于现有上下文说明进度、阻塞原因和已有结果；不得调用工具。用户要求继续时须先重新授权并确认新预算卡。')
            if REAUTHORIZE.search(prompt) or triggered or TASK_TRIGGER.search(prompt):
                state=_activation(event);save(path,state)
                return _intake_context(kind,'旧任务预算已经熔断。新请求先生成新的 T1-T4 启动卡和预算；用户确认 A 前不得继续。')
            path.unlink()
            return {}
        if state['intake_phase']=='EXECUTING':
            if _expired(state):
                state.update(intake_phase='BUDGET_EXHAUSTED',updated_at=_now());save(path,state)
                return _intake_context(kind,'Sol Cabinet 执行预算已到。停止新增工具、Agent、读取、研究、重试和排障；只整理已有结果并报告执行熔断。')
            save(path,state)
            return _intake_context(kind,'本任务预算计时继续，用户纠偏不重置计时；保持原范围，预算到期立即停止新增执行。')
        return {}

    state=load(path,session_id)
    if state is None:return {}

    if kind=='PreToolUse':
        if state['intake_phase'] in {'AWAITING_CARD','AWAITING_CONFIRMATION'}:
            return _deny_tool('Sol Cabinet is waiting for an explicit start-card confirmation; no task tool may run yet.')
        if state['intake_phase'] in {'BUDGET_EXHAUSTED','AWAITING_NEXT_STAGE'}:
            return _deny_tool('Sol Cabinet execution budget is exhausted; report the fuse state without further tools.')
        if _expired(state):
            state.update(intake_phase='BUDGET_EXHAUSTED',updated_at=_now());save(path,state)
            return _deny_tool('Sol Cabinet execution budget is exhausted; stop new work and report current partial results.')
        if state['intake_tier']==1 and event.get('tool_name')=='Agent':
            return _deny_tool('T1 is lead-only; additional execution agents are outside the confirmed route.')
        return {}

    if state['intake_phase']=='AWAITING_CARD':
        card=_card_budget(event.get('last_assistant_message') or '')
        if card:
            state.update(intake_phase='AWAITING_CONFIRMATION',intake_tier=card[0],
                         budget_seconds=card[1],card_shown_at=_now(),updated_at=_now())
            save(path,state)
            return {'continue':False,'systemMessage':'Sol Cabinet 启动卡已显示；等待用户明确选择 A 后开工。'}
        if event.get('stop_hook_active'):
            return {'continue':False,'systemMessage':'Sol Cabinet 尚未显示有效启动卡；当前停止，不执行任务。'}
        return {'decision':'block','reason':'只显示简短的 T1-T4 任务启动卡，列预计耗时、交付、路径、预算和 A/B/C/D；不要调用工具或开始执行。'}
    if state['intake_phase']=='AWAITING_CONFIRMATION':
        card=_card_budget(event.get('last_assistant_message') or '')
        if card:
            state.update(intake_tier=card[0],budget_seconds=card[1],card_shown_at=_now(),updated_at=_now())
            save(path,state)
            return {'continue':False,'systemMessage':'修订后的启动卡已显示；等待用户明确选择 A 后开工。'}
        if event.get('stop_hook_active'):
            return {'continue':False,'systemMessage':'仍未收到启动卡确认；Sol Cabinet 保持停止。'}
        return {'decision':'block','reason':'用户尚未确认。只更新或重发启动卡；不要开始正文处理、调用工具或登记契约。'}
    if state['intake_phase']=='EXECUTING' and _expired(state):
        state.update(intake_phase='BUDGET_EXHAUSTED',updated_at=_now());save(path,state)
    if state['intake_phase']=='AWAITING_NEXT_STAGE':
        return {'continue':False,'systemMessage':'T4 阶段已停止；下一阶段需新的启动卡与确认。'}
    if state['intake_phase']=='BUDGET_EXHAUSTED':
        last=event.get('last_assistant_message') or ''
        if _valid_fuse_summary(last):
            return {'continue':False,'systemMessage':'Sol Cabinet 执行熔断已报告；停止自动续作，等待用户重新授权。'}
        if event.get('stop_hook_active'):
            return {'continue':False,'systemMessage':'Sol Cabinet 执行预算已耗尽；当前结果保持 PARTIAL，等待用户重新授权。'}
        return {'decision':'block','reason':'执行预算已到。不要再调用工具；仅返回熔断报告，列原预计、实际预算、阻塞原因、当前已有结果和 PARTIAL。'}

    if state['phase']=='TERMINAL_PARTIAL':
        return {'continue':False,'stopReason':'Sol Cabinet task is already terminal-partial',
                'systemMessage':'Sol Cabinet：PARTIAL，上一轮交付检查已耗尽自动重试；需新的显式 Sol Cabinet 触发才可重新激活。'}
    last=event.get('last_assistant_message') or '';issues=[]
    contract=state.get('contract')
    if state['mode']=='file':
        p=Path(contract)
        if not p.resolve().is_relative_to(allowed_root.resolve()) or not p.is_file():issues.append('交付契约不存在或越界')
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=state.get('contract_sha256'):issues.append('交付契约变更后未重新登记')
        else:
            try:
                checked=json.loads(p.read_text(encoding='utf-8'))
                issues+=check(checked,contract_path=p)['issues']
                actual=[a.get('path') for a in checked.get('artifacts',[]) if isinstance(a,dict)]
                if not actual or any(not isinstance(name,str) or name not in last for name in actual):
                    issues.append('完工小结必须列出当前契约的实际最终路径')
                linked=ARTIFACT.findall(last)
                if any(name not in actual for name in linked):
                    issues.append('完工小结包含不属于当前交付契约的成品链接')
            except (OSError,ValueError,TypeError):issues.append('交付契约无法核验')
    elif state['mode']=='analysis':
        if DELIVERY_CLAIM.search(last) or '/outputs/' in last:issues.append('声明无文件分析但回复包含成品交付，须登记契约')
    else:issues.append('未登记本次文件契约；无文件任务须显式声明analysis-only')
    if '耗时' not in last and 'elapsed' not in last.lower():issues.append('缺少实际耗时或不可核实的说明')
    if not any(s in last for s in ('完成','结果','核验','验证','检查','未完成','PARTIAL','BLOCKED')):issues.append('缺少结果与核验小结')
    if state['mode']=='file':
        if not (DELIVERY_CLAIM.search(last) or ARTIFACT.search(last) or '/outputs/' in last):issues.append('文件任务完工小结未列实际成品或路径')
        if not any(s in last for s in ('目录','文件夹','归档')):issues.append('文件任务完工小结缺少目录或归档状态')
        if not any(s in last for s in ('核验','验证','检查')):issues.append('文件任务完工小结缺少真实核验状态')
    model_changed=bool(state.get('model') and event.get('model') and state['model']!=event['model'])
    if issues:
        if event.get('stop_hook_active') or state['failure_count']>=1:
            state.update(phase='TERMINAL_PARTIAL',failure_count=2,updated_at=_now());save(path,state)
            return {'continue':False,'stopReason':'Sol Cabinet delivery checks remain incomplete',
                    'systemMessage':'Sol Cabinet：PARTIAL，交付检查仍未通过；已停止自动重试以避免继续消耗。'+ '；'.join(issues[:5])}
        state.update(phase='RETRY_REQUIRED',failure_count=1,updated_at=_now());save(path,state)
        return {'decision':'block','reason':'Sol Cabinet交付检查未通过：'+'；'.join(issues[:5])+'。只修复这些已授权缺项；不能补造开工提示、审核或归档状态。无法修复则明确PARTIAL，不得虚称完成。'}
    if state['intake_tier']==4:
        state.update(intake_phase='AWAITING_NEXT_STAGE',budget_seconds=None,
                     execution_started_at=None,card_shown_at=None,updated_at=_now())
        save(path,state)
        return {'systemMessage':'T4 当前阶段已完成并停止；需要继续时先给出新阶段启动卡并等待确认。'}
    path.unlink()
    if model_changed:return {'systemMessage':'本任务模型与开工记录不同；钩子没有切换模型，需核对会话设置来源。'}
    return {}


@guarded
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--register',action='store_true');p.add_argument('--analysis-only',action='store_true');p.add_argument('--session-id');p.add_argument('--contract')
    a=p.parse_args()
    try:
        if a.analysis_only:declare_analysis(a.session_id);return 0
        if a.register:
            if not a.contract:raise ValueError('contract required')
            register(a.session_id,a.contract);return 0
        print(json.dumps(handle(json.load(sys.stdin)),ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({'systemMessage':'Sol Cabinet钩子无法核验：'+type(exc).__name__},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
