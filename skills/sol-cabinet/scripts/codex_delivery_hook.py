#!/usr/bin/env python3
"""Task-scoped start, delivery, and Evolution lifecycle for Codex.

The hook keeps coded state only. Host trust and actual PreToolUse registration
are required; hooks are a workflow guardrail, not an OS sandbox.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from datetime import datetime, timezone
from maintenance_boundary import guarded

BASE = Path('/Users/macbook/ChatGPT')
STATE = BASE / 'system/codex-home/sol-cabinet-runtime'
SID = re.compile(r'^[A-Za-z0-9_-]{8,100}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
TRIGGER = re.compile(r'\$sol-cabinet|(?:使用|交给|执行|调用|启动)\s*sol\s*cabinet|SC处理|<name>sol-cabinet</name>', re.I)
DELIVERY_CLAIM = re.compile(r'(?:成品|交付文件|实际成品|保存为|下载|deliverable).{0,180}(?:/|\.[a-zA-Z0-9]{2,8})', re.I)
ARTIFACT = re.compile(r'\]\(<?(/[^\n)]+\.(?:docx|xlsx|pptx|pdf|md|csv|html|zip))>?\)', re.I)
PHASES = {'RECEIVED','CLASSIFIED','START_CARD_READY','EXECUTING','DELIVERY_PASSED',
          'EVOLUTION_REVIEW','RETRY_REQUIRED','TERMINAL_PARTIAL','FINISHED','CANCELLED'}
MODES = {'undecided','file','analysis'}
AUTH_SOURCES = {'user-confirmation','user-preauthorized'}
EVOLUTION_STATES = {'CLEAN','RECORDED','PENDING'}
STATE_KEYS = {
    'schema_version','session_id','turn_id','model','phase','mode','failure_count',
    'contract','contract_sha256','created_at','updated_at','started_at','finished_at',
    't_level','workflow_lane','authorization_source','delivery_verified',
    'delivery_verified_at','delivery_contract_sha256','evolution_status',
    'checkpoint_count','failure_type','cause','history_checked','history_error','history_match_count',
}
WRITE_TOOL = re.compile(r'(?:write|edit|create|delete|remove|move|rename|upload|send|submit|publish|commit|push|install|update|modify|archive|mkdir|copy|replace|apply_patch)', re.I)
READ_COMMANDS = {'cat','ls','pwd','rg','grep','head','tail','wc','stat','file','shasum','md5'}
READ_GIT = {'status','diff','log','show','rev-parse','ls-tree','ls-files','branch','tag'}
CONTROL_FLAGS = {'--classified','--card-ready','--confirm','--revise-card','--cancel','--reopen',
                 '--register','--analysis-only','--verify-delivery','--history','--checkpoint','--elapsed'}
DURATION = re.compile(r'(?:总耗时|耗时)\s*[:：]\s*(\d+(?:\.\d+)?)\s*(秒|s|seconds?|分钟|分|minutes?)', re.I)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value):
    if not isinstance(value,str) or not value:
        return None
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def state_file(session_id, state_root=STATE):
    if not isinstance(session_id,str) or not SID.fullmatch(session_id):
        raise ValueError('invalid session id')
    return Path(state_root)/(hashlib.sha256(session_id.encode()).hexdigest()+'.json')


def _route(tier):
    if tier <= 2: return 't1_t2_fast'
    if tier == 3: return 't3_focused'
    if tier <= 6: return 't4_t6_structured'
    if tier <= 8: return 't7_t8_high_control'
    return 't9_t10_stage_gated'


def _new_state(event):
    stamp=_now()
    return {
        'schema_version':3,'session_id':event['session_id'],'turn_id':event.get('turn_id'),
        'model':event.get('model'),'phase':'RECEIVED','mode':'undecided','failure_count':0,
        'contract':None,'contract_sha256':None,'created_at':stamp,'updated_at':stamp,
        'started_at':None,'finished_at':None,'t_level':None,'workflow_lane':None,
        'authorization_source':None,'delivery_verified':False,'delivery_verified_at':None,
        'delivery_contract_sha256':None,'evolution_status':None,'checkpoint_count':0,
        'failure_type':None,'cause':None,'history_checked':False,'history_error':False,'history_match_count':0,
    }


def _migrate_legacy(state):
    if not isinstance(state,dict) or state.get('schema_version')!=2:
        raise ValueError('unsupported hook state; fail closed')
    sid=state.get('session_id')
    if not isinstance(sid,str) or not SID.fullmatch(sid):
        raise ValueError('invalid legacy session')
    stamp=state.get('updated_at') or state.get('started_at') or _now()
    phase='TERMINAL_PARTIAL' if state.get('phase')=='TERMINAL_PARTIAL' else 'RECEIVED'
    migrated={
        'schema_version':3,'session_id':sid,'turn_id':state.get('turn_id'),'model':state.get('model'),
        'phase':phase,'mode':'undecided','failure_count':2 if phase=='TERMINAL_PARTIAL' else 0,
        'contract':None,'contract_sha256':None,'created_at':stamp,'updated_at':_now(),
        'started_at':None,'finished_at':None,'t_level':None,'workflow_lane':None,
        'authorization_source':None,'delivery_verified':False,'delivery_verified_at':None,
        'delivery_contract_sha256':None,'evolution_status':None,'checkpoint_count':0,
        'failure_type':None,'cause':None,'history_checked':False,'history_error':False,'history_match_count':0,
    }
    return validate_state(migrated,sid)


def validate_state(state, session_id=None):
    if not isinstance(state,dict) or set(state)!=STATE_KEYS:
        raise ValueError('hook state schema mismatch')
    if state.get('schema_version')!=3:
        raise ValueError('unsupported hook state version')
    if not isinstance(state.get('session_id'),str) or not SID.fullmatch(state['session_id']):
        raise ValueError('invalid hook session')
    if session_id is not None and state['session_id']!=session_id:
        raise ValueError('hook state session mismatch')
    if state.get('phase') not in PHASES or state.get('mode') not in MODES:
        raise ValueError('invalid hook lifecycle')
    if type(state.get('failure_count')) is not int or not 0<=state['failure_count']<=2:
        raise ValueError('invalid failure count')
    if state.get('turn_id') is not None and not isinstance(state.get('turn_id'),(str,int)):
        raise ValueError('invalid turn id')
    if state.get('model') is not None and not isinstance(state.get('model'),str):
        raise ValueError('invalid model')
    for key in ('created_at','updated_at'):
        if _parse_time(state.get(key)) is None: raise ValueError('invalid required timestamp')
    for key in ('started_at','finished_at','delivery_verified_at'):
        if state.get(key) is not None and _parse_time(state.get(key)) is None:
            raise ValueError('invalid optional timestamp')
    if state.get('t_level') is not None and (type(state['t_level']) is not int or not 1<=state['t_level']<=10):
        raise ValueError('invalid task level')
    if state.get('workflow_lane') is not None and state['workflow_lane']!=_route(state['t_level']):
        raise ValueError('workflow lane does not match task level')
    if state.get('authorization_source') is not None and state['authorization_source'] not in AUTH_SOURCES:
        raise ValueError('invalid authorization source')
    if type(state.get('delivery_verified')) is not bool or type(state.get('checkpoint_count')) is not int or state['checkpoint_count'] not in (0,1):
        raise ValueError('invalid finalization state')
    if type(state.get('history_match_count')) is not int or state['history_match_count']<0 or type(state.get('history_checked')) is not bool or type(state.get('history_error')) is not bool:
        raise ValueError('invalid history state')
    if (state.get('failure_type') is None)!=(state.get('cause') is None): raise ValueError('failure type and cause must be paired')
    if state.get('failure_type') is not None:
        import evolve
        if state['failure_type'] not in evolve.FAILURES or state['cause'] not in evolve.CAUSES: raise ValueError('unregistered failure taxonomy')
    contract,digest=state.get('contract'),state.get('contract_sha256')
    if state['mode']=='file':
        if not isinstance(contract,str) or not contract or not isinstance(digest,str) or not SHA256.fullmatch(digest):
            raise ValueError('file mode requires locked contract')
    elif contract is not None or digest is not None:
        raise ValueError('non-file mode cannot retain a contract')
    if state['delivery_verified']:
        if _parse_time(state.get('delivery_verified_at')) is None:
            raise ValueError('delivery verification timestamp required')
        if state['mode']=='file' and state.get('delivery_contract_sha256')!=digest:
            raise ValueError('delivery verification contract mismatch')
    if state['phase'] in {'EXECUTING','DELIVERY_PASSED','EVOLUTION_REVIEW','FINISHED'}:
        if _parse_time(state.get('started_at')) is None or state.get('authorization_source') not in AUTH_SOURCES:
            raise ValueError('execution requires a confirmed start')
    if state['phase'] in {'DELIVERY_PASSED','EVOLUTION_REVIEW','FINISHED'} and not state['delivery_verified']:
        raise ValueError('delivery gate must pass before later phases')
    if state['phase'] in {'EVOLUTION_REVIEW','FINISHED'} and (state['checkpoint_count']!=1 or state.get('evolution_status') is None):
        raise ValueError('Evolution Checkpoint required before finish')
    if state['phase']=='START_CARD_READY' and (state.get('t_level') is None or state.get('workflow_lane') is None):
        raise ValueError('start card requires classification')
    if state.get('evolution_status') not in EVOLUTION_STATES and not (isinstance(state.get('evolution_status'),str) and re.fullmatch(r'EVO-\d{8}-\d{6}',state['evolution_status'])):
        if state.get('evolution_status') is not None: raise ValueError('invalid Evolution status')
    if state['phase']=='RETRY_REQUIRED' and state['failure_count']!=1:
        raise ValueError('retry requires one prior failure')
    if state['phase']=='TERMINAL_PARTIAL' and state['failure_count']<2:
        raise ValueError('terminal state requires exhausted retry')
    if state['phase']=='FINISHED' and _parse_time(state.get('finished_at')) is None:
        raise ValueError('finished timestamp required')
    return state


def load(path, session_id=None):
    path=Path(path)
    if path.is_symlink(): raise ValueError('unsafe hook state file')
    if not path.exists(): return None
    if not path.is_file(): raise ValueError('unsafe hook state file')
    value=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(value,dict) and value.get('schema_version')==2:
        value=_migrate_legacy(value)
    return validate_state(value,session_id)


@guarded
def save(path,state):
    validate_state(state,state.get('session_id'))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(path.parent,0o700)
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with open(temp,'w',encoding='utf-8') as f:
        os.chmod(temp,0o600);json.dump(state,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def _state(session_id,state_root):
    path=state_file(session_id,state_root);value=load(path,session_id)
    if value is None: raise ValueError('active Cabinet state required')
    return path,value


@guarded
def classified(session_id,t_level,state_root=STATE):
    path,state=_state(session_id,state_root)
    if type(t_level) is not int or not 1<=t_level<=10: raise ValueError('t_level must be 1..10')
    if state['phase'] not in {'RECEIVED','CLASSIFIED'}: raise ValueError('classification is closed for this start card')
    state.update(phase='CLASSIFIED',t_level=t_level,workflow_lane=_route(t_level),updated_at=_now())
    save(path,state)
    return {'t_level':t_level,'workflow_lane':state['workflow_lane'],'start_card_required':True}


@guarded
def card_ready(session_id,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase']!='CLASSIFIED': raise ValueError('classify before preparing a start card')
    state.update(phase='START_CARD_READY',updated_at=_now())
    save(path,state)
    return {'phase':state['phase'],'awaiting':'user confirmation or explicit preauthorization'}


@guarded
def confirm(session_id,source,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase']!='START_CARD_READY': raise ValueError('a visible start card must precede confirmation')
    if source not in AUTH_SOURCES: raise ValueError('invalid confirmation source')
    stamp=_now()
    state.update(phase='EXECUTING',authorization_source=source,started_at=stamp,updated_at=stamp)
    save(path,state)
    return {'phase':'EXECUTING','started_at':stamp,'source':source}


@guarded
def revise_card(session_id,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase']!='START_CARD_READY': raise ValueError('only an unconfirmed card can be revised')
    state.update(phase='RECEIVED',t_level=None,workflow_lane=None,updated_at=_now())
    save(path,state)


@guarded
def cancel(session_id,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase'] not in {'RECEIVED','CLASSIFIED','START_CARD_READY'}:
        raise ValueError('only unstarted work can be cancelled')
    state.update(phase='CANCELLED',updated_at=_now())
    save(path,state)


@guarded
def register(session_id,contract,state_root=STATE,allowed_root=BASE):
    path,state=_state(session_id,state_root)
    if state['phase'] not in {'EXECUTING','RETRY_REQUIRED'} or state['delivery_verified']: raise ValueError('confirmation required before file registration')
    if state['mode']=='analysis': raise ValueError('analysis delivery mode is locked')
    requested=Path(contract)
    if requested.is_symlink(): raise ValueError('symlink contract is not permitted')
    contract=requested.resolve()
    if not contract.is_relative_to(Path(allowed_root).resolve()) or not contract.is_file():
        raise ValueError('contract must be a regular file inside the authorized working root')
    data=json.loads(contract.read_text(encoding='utf-8'))
    if not isinstance(data,dict): raise ValueError('contract must be object')
    state.update(mode='file',contract=str(contract),contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),updated_at=_now())
    save(path,state)


@guarded
def declare_analysis(session_id,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase'] not in {'EXECUTING','RETRY_REQUIRED'} or state['delivery_verified']: raise ValueError('confirmation required before analysis declaration')
    if state['mode']=='file': raise ValueError('file delivery mode is locked')
    state.update(mode='analysis',contract=None,contract_sha256=None,updated_at=_now())
    save(path,state)


def _delivery_check(state,allowed_root):
    if state['mode']=='file':
        p=Path(state['contract'])
        if not p.resolve().is_relative_to(Path(allowed_root).resolve()) or not p.is_file() or p.is_symlink():
            return {'state':'FAIL','issues':['delivery contract missing or out of scope']}
        if hashlib.sha256(p.read_bytes()).hexdigest()!=state['contract_sha256']:
            return {'state':'FAIL','issues':['delivery contract changed after registration']}
        try:
            from delivery_gate import check
            result=check(json.loads(p.read_text(encoding='utf-8')),contract_path=p)
        except (OSError,ValueError,TypeError) as exc:
            return {'state':'FAIL','issues':['delivery contract cannot be checked: '+type(exc).__name__]}
        return result
    if state['mode']=='analysis':
        return {'state':'PASS','issues':[]}
    return {'state':'FAIL','issues':['declare file or analysis delivery mode first']}


@guarded
def verify_delivery(session_id,state_root=STATE,allowed_root=BASE):
    path,state=_state(session_id,state_root)
    if state['phase'] in {'DELIVERY_PASSED','EVOLUTION_REVIEW','FINISHED'}:
        return {'state':'PASS','cached':True}
    if state['phase'] not in {'EXECUTING','RETRY_REQUIRED'} or state['delivery_verified']: raise ValueError('delivery gate must follow confirmed execution')
    result=_delivery_check(state,allowed_root)
    if result.get('state')=='PASS':
        stamp=_now();state.update(phase='DELIVERY_PASSED',delivery_verified=True,delivery_verified_at=stamp,
            delivery_contract_sha256=state['contract_sha256'],updated_at=stamp);save(path,state)
    return result


@guarded
def review_history(session_id,failure_type,cause,state_root=STATE,root=None):
    path,state=_state(session_id,state_root)
    if state['phase']!='DELIVERY_PASSED': raise ValueError('history review must follow the delivery gate')
    if state['history_checked']:
        if state['failure_type']!=failure_type or state['cause']!=cause: raise ValueError('history query is already locked')
        return {'status':'CACHED','idempotent':True,'history_match_count':state['history_match_count']}
    import evolve
    result=evolve.history(failure_type,cause,root or Path(__file__).resolve().parent.parent)
    matches=[x for x in result.get('incidents',[]) if x.get('same_cause')]
    state.update(failure_type=failure_type,cause=cause,history_checked=True,history_error=result.get('status')=='ERROR',
        history_match_count=len(matches),updated_at=_now())
    save(path,state)
    return {'status':result['status'],'history':matches,'history_match_count':len(matches),
            'evidence_warnings':result.get('evidence_warnings',[])}


@guarded
def reopen_delivery(session_id,state_root=STATE):
    path,state=_state(session_id,state_root)
    if state['phase']!='DELIVERY_PASSED': raise ValueError('only a pre-Evolution delivery pass can be reopened')
    state.update(phase='EXECUTING',delivery_verified=False,delivery_verified_at=None,
        delivery_contract_sha256=None,evolution_status=None,checkpoint_count=0,
        failure_type=None,cause=None,history_checked=False,history_error=False,
        history_match_count=0,updated_at=_now())
    save(path,state)
    return {'phase':'EXECUTING','started_at':state['started_at'],'start_time_reset':False}


@guarded
def checkpoint(session_id,status,failure_type=None,cause=None,incident_id=None,state_root=STATE,root=None):
    path,state=_state(session_id,state_root)
    if state['phase']=='EVOLUTION_REVIEW' or state['phase']=='FINISHED':
        return {'status':state['evolution_status'],'idempotent':True,'history_match_count':state['history_match_count']}
    if state['phase']!='DELIVERY_PASSED': raise ValueError('delivery gate must precede Evolution Checkpoint')
    if status not in EVOLUTION_STATES: raise ValueError('checkpoint status must be CLEAN, RECORDED, or PENDING')
    if status=='CLEAN':
        if failure_type is not None or cause is not None or incident_id is not None or state['history_checked'] or state['history_error']:
            raise ValueError('CLEAN cannot carry or read incident history')
        matches=[]
    else:
        if not state['history_checked'] or state['failure_type']!=failure_type or state['cause']!=cause:
            raise ValueError('review relevant history before classifying an incident')
        matches=[]
        if status=='RECORDED':
            if state['history_error']: raise ValueError('history verification failed; use PENDING')
            if not isinstance(incident_id,str) or not re.fullmatch(r'INC-[0-9a-f]{32}',incident_id):
                raise ValueError('RECORDED requires the recorded incident id')
            import evolve
            observation=Path(root or Path(__file__).resolve().parent.parent)/'memory-evolution/observations'/(incident_id+'.json')
            if not observation.is_file(): raise ValueError('incident record not verified; use PENDING')
            item=evolve.validate_incident(json.loads(observation.read_text(encoding='utf-8')))
            if item['failure_type']!=failure_type or item['cause']!=cause:
                raise ValueError('incident record does not match reviewed history query')
    state.update(phase='EVOLUTION_REVIEW',evolution_status=status,checkpoint_count=1,updated_at=_now())
    save(path,state)
    return {'status':status,'history_match_count':state['history_match_count']}


def elapsed(session_id,state_root=STATE,now=None):
    _,state=_state(session_id,state_root)
    start=_parse_time(state.get('started_at'))
    if start is None: return {'status':'NOT_STARTED','elapsed_seconds':None}
    end=_parse_time(now) if isinstance(now,str) else datetime.now(timezone.utc) if now is None else now
    return {'status':'RUNNING','started_at':start.isoformat(),'elapsed_seconds':max(0,round((end-start).total_seconds()))}


def _reported_elapsed(message):
    match=DURATION.search(message or '')
    if not match: return None
    value=float(match.group(1));unit=match.group(2).lower()
    return round(value*60) if unit in {'分钟','分','minute','minutes','m'} else round(value)


def _tool_input(event):
    value=event.get('tool_input') or {}
    return value if isinstance(value,dict) else {'raw':value}


def _safe_shell(command):
    if not isinstance(command,str) or not command.strip(): return False
    if any(token in command for token in (';','&&','||','>','<','|','`','$(', '\n','\r')): return False
    try: parts=shlex.split(command)
    except ValueError: return False
    if not parts: return False
    exe=Path(parts[0]).name
    if exe not in READ_COMMANDS: return False
    if exe in {'rg','grep'} and any(arg=='--pre' or arg.startswith('--pre=') or arg=='--pre-glob' for arg in parts[1:]):
        return False
    return True


def _control_command(tool_input):
    raw=tool_input.get('command') or tool_input.get('cmd') or ''
    if not isinstance(raw,str) or any(token in raw for token in (';','&&','||','>','<','|','`','$(', '\n','\r')): return False
    try: parts=shlex.split(raw)
    except ValueError: return False
    if len(parts)<3 or Path(parts[0]).name not in {'python','python3','python3.13','python3.14'}:
        return False
    index=2 if parts[1]=='-B' else 1
    if len(parts)<=index or Path(parts[index]).resolve()!=Path(__file__).resolve():
        return False
    args=parts[index+1:]
    actions=[a for a in args if a in CONTROL_FLAGS]
    if len(actions)!=1: return False
    value_flags={'--session-id','--tier','--source','--contract','--failure-type','--cause','--incident-id'}
    i=0
    while i<len(args):
        flag=args[i]
        if flag=='--checkpoint':
            if i+1>=len(args) or args[i+1] not in EVOLUTION_STATES: return False
            i+=2
            continue
        if flag in CONTROL_FLAGS:
            i+=1
            continue
        if flag not in value_flags or i+1>=len(args) or args[i+1].startswith('-'):
            return False
        i+=2
    return True


def _exec_source_writes(tool_input):
    source=tool_input.get('code') or tool_input.get('script') or tool_input.get('raw') if isinstance(tool_input,dict) else tool_input
    if not isinstance(source,str): return True
    # Permit only one literal shell call with a fixed, inspectable command.
    # JavaScript computed access, aliases, and additional expressions fail closed.
    match=re.fullmatch(
        r'\s*const\s+(\w+)\s*=\s*await\s+tools\.exec_command\(\{cmd:\s*("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')\}\);\s*text\(\1\.output\);\s*',
        source,re.S)
    if not match: return True
    literal=match.group(2)
    try: command=json.loads(literal) if literal.startswith('"') else ast.literal_eval(literal)
    except (ValueError,SyntaxError): return True
    return not (_control_command({'command':command}) or _safe_shell(command))


def _would_write(tool_name,tool_input):
    name=str(tool_name or '')
    if name in {'Bash','exec_command','functions.exec_command'}:
        return not (_control_command(tool_input) or _safe_shell(tool_input.get('command') or tool_input.get('cmd')))
    if name in {'functions.exec','exec'}:
        return _exec_source_writes(tool_input)
    # Unknown tools may have side effects; an explicit read allowlist is safer.
    if name in {'view_image','clock__curr_time','list_mcp_resources','list_mcp_resource_templates','read_mcp_resource'}:
        return False
    return True


def _deny(reason):
    return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                                  'permissionDecisionReason':reason}}


def _opening_context():
    return ('Sol Cabinet：先按 T1-T10 判级并给一张简短开工卡，含目标、范围、交付、验收、停止条件。'
            '直接执行授权仍先出卡，再登记预授权；否则等用户自然语言确认。确认前不得正式写入。')


def handle(event,state_root=STATE,allowed_root=BASE):
    if not isinstance(event,dict): raise ValueError('event must be object')
    cwd=Path(event.get('cwd') or '/')
    if not cwd.resolve().is_relative_to(Path(allowed_root).resolve()): return {}
    kind=event.get('hook_event_name');session_id=event.get('session_id')
    if kind not in {'UserPromptSubmit','PreToolUse','Stop'}: return {}
    path=state_file(session_id,state_root)
    if kind=='UserPromptSubmit':
        triggered=bool(TRIGGER.search(event.get('prompt') or ''))
        previous=load(path,session_id)
        if triggered:
            if previous is not None and previous['phase'] not in {'FINISHED','CANCELLED','TERMINAL_PARTIAL'}:
                previous.update(turn_id=event.get('turn_id'),updated_at=_now());save(path,previous)
                return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':
                    'Sol Cabinet 本任务仍处于 '+previous['phase']+'；沿用当前任务，不重置状态或计时。'}}
            state=_new_state(event);save(path,state)
            return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':_opening_context()}}
        if previous is None: return {}
        previous.update(turn_id=event.get('turn_id'),updated_at=_now());save(path,previous)
        if previous['phase']=='START_CARD_READY':
            return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':
                'Sol Cabinet 等待开工卡确认：先判断本条是否确认或修改范围；确认时调用 --confirm --source user-confirmation，改范围时调用 --revise-card。未确认不得写入。'}}
        if previous['phase'] in {'RECEIVED','CLASSIFIED'}:
            return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':_opening_context()}}
        return {}
    if kind=='PreToolUse':
        try: previous=load(path,session_id)
        except (OSError,ValueError,TypeError): return _deny('Sol Cabinet state unavailable; file-changing tool call blocked.')
        if previous is None or previous['phase']=='EXECUTING':
            return {}
        if previous['phase']=='RETRY_REQUIRED' and previous.get('started_at') and previous.get('authorization_source') and not previous['delivery_verified']:
            return {}
        if _would_write(event.get('tool_name'),_tool_input(event)):
            if previous['phase'] in {'DELIVERY_PASSED','EVOLUTION_REVIEW'}:
                return _deny('Sol Cabinet delivery gate has passed; writes are locked. Reopen the gate before any authorized correction.')
            return _deny('Sol Cabinet start is not confirmed; show the start card and wait for user confirmation before writing.')
        return {}
    try: state=load(path,session_id)
    except (OSError,ValueError,TypeError) as exc:
        return {'decision':'block','reason':'Sol Cabinet state is invalid; stop with PARTIAL and do not claim completion ('+type(exc).__name__+').'}
    if state is None: return {}
    if state['phase']=='TERMINAL_PARTIAL':
        return {'continue':False,'stopReason':'Sol Cabinet task is terminal-partial',
                'systemMessage':'Sol Cabinet：PARTIAL。需要用户显式开启新任务后才能重新进入执行。'}
    if state['phase'] in {'START_CARD_READY','CANCELLED','FINISHED'}: return {}
    issues=[]
    if state['phase']!='EVOLUTION_REVIEW' or state['checkpoint_count']!=1:
        issues.append('最终回复前必须通过交付门并执行一次 Evolution Checkpoint')
    if state['mode']=='file':
        contract=Path(state['contract'])
        if not contract.is_file() or contract.is_symlink() or not contract.resolve().is_relative_to(Path(allowed_root).resolve()):
            issues.append('交付契约不存在或越界')
        elif hashlib.sha256(contract.read_bytes()).hexdigest()!=state['contract_sha256']:
            issues.append('交付契约在验收后发生变化')
        else:
            try:
                data=json.loads(contract.read_text(encoding='utf-8'))
                paths=[item.get('path') for item in data.get('artifacts',[]) if isinstance(item,dict)]
                if not paths or any(not isinstance(name,str) or name not in (event.get('last_assistant_message') or '') for name in paths):
                    issues.append('完工小结必须列出当前契约的真实成品路径')
            except (OSError,ValueError,TypeError): issues.append('交付契约无法核验')
    elif state['mode']=='analysis':
        last=event.get('last_assistant_message') or ''
        if DELIVERY_CLAIM.search(last) or '/outputs/' in last: issues.append('无文件分析不能声称文件交付')
    else: issues.append('未声明本任务的文件或分析交付模式')
    last=event.get('last_assistant_message') or ''
    if not any(x in last for x in ('完成','结果','核验','验证','检查','PARTIAL','BLOCKED')):
        issues.append('缺少真实结果与验收小结')
    if '开工卡' not in last: issues.append('完工小结必须对照开工卡承诺项')
    if '目录' not in last and state['mode']=='file': issues.append('文件任务缺少最终目录状态')
    expected='进化：'+str(state.get('evolution_status') or '')
    if expected not in last: issues.append('完工小结缺少与 Checkpoint 一致的进化状态行')
    start=_parse_time(state.get('started_at'))
    if start is None:
        issues.append('启动时间未记录；必须如实标注“未记录（启动时间状态缺失）”并列为流程异常')
    else:
        seconds=max(0,(datetime.now(timezone.utc)-start).total_seconds())
        reported=_reported_elapsed(last)
        tolerance=max(15,min(60,seconds*0.05))
        if reported is None or abs(reported-seconds)>tolerance:
            issues.append('总耗时应按状态时间如实填写，约 '+str(round(seconds))+' 秒')
    model_changed=bool(state.get('model') and event.get('model') and state['model']!=event['model'])
    if model_changed: issues.append('模型与开工记录不同；Hook 没有切换模型，需如实说明来源')
    if issues:
        if event.get('stop_hook_active') or state['failure_count']>=1:
            state.update(phase='TERMINAL_PARTIAL',failure_count=2,updated_at=_now());save(path,state)
            return {'continue':False,'stopReason':'Sol Cabinet delivery checks remain incomplete',
                    'systemMessage':'Sol Cabinet：PARTIAL；终检仍未通过，已停止自动重试。'+ '；'.join(issues[:5])}
        state.update(phase='RETRY_REQUIRED',failure_count=1,updated_at=_now());save(path,state)
        return {'decision':'block','reason':'Sol Cabinet 收尾未通过：'+'；'.join(issues[:5])+'。只修正已授权缺项，不补造状态。'}
    state.update(phase='FINISHED',finished_at=_now(),updated_at=_now());save(path,state)
    return {}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-id')
    parser.add_argument('--classified',action='store_true')
    parser.add_argument('--card-ready',action='store_true')
    parser.add_argument('--confirm',action='store_true')
    parser.add_argument('--revise-card',action='store_true')
    parser.add_argument('--cancel',action='store_true')
    parser.add_argument('--register',action='store_true')
    parser.add_argument('--analysis-only',action='store_true')
    parser.add_argument('--verify-delivery',action='store_true')
    parser.add_argument('--history',action='store_true')
    parser.add_argument('--checkpoint',choices=['CLEAN','RECORDED','PENDING'])
    parser.add_argument('--failure-type');parser.add_argument('--cause');parser.add_argument('--incident-id')
    parser.add_argument('--source',choices=sorted(AUTH_SOURCES));parser.add_argument('--tier',type=int)
    parser.add_argument('--contract');parser.add_argument('--status',action='store_true');parser.add_argument('--elapsed',action='store_true')
    args=parser.parse_args()
    try:
        if args.classified: result=classified(args.session_id,args.tier)
        elif args.card_ready: result=card_ready(args.session_id)
        elif args.confirm: result=confirm(args.session_id,args.source)
        elif args.revise_card: result=revise_card(args.session_id)
        elif args.cancel: result=cancel(args.session_id)
        elif args.register:
            if not args.contract: raise ValueError('contract required')
            result=register(args.session_id,args.contract);result={'status':'REGISTERED'}
        elif args.analysis_only: declare_analysis(args.session_id);result={'status':'ANALYSIS_DECLARED'}
        elif args.verify_delivery: result=verify_delivery(args.session_id)
        elif args.history: result=review_history(args.session_id,args.failure_type,args.cause)
        elif args.checkpoint: result=checkpoint(args.session_id,args.checkpoint,args.failure_type,args.cause,args.incident_id)
        elif args.elapsed: result=elapsed(args.session_id)
        elif args.status:
            _,state=_state(args.session_id,STATE);result={k:state[k] for k in ('phase','mode','t_level','workflow_lane','started_at','finished_at','evolution_status','checkpoint_count')}
        else:
            raw=sys.stdin.read()
            try: event=json.loads(raw)
            except (ValueError,TypeError):
                result=_deny('Sol Cabinet hook input invalid; write blocked.')
            else:
                try: result=handle(event)
                except (OSError,ValueError,TypeError) as exc:
                    if event.get('hook_event_name')=='PreToolUse':
                        result=_deny('Sol Cabinet state unavailable; write blocked ('+type(exc).__name__+').')
                    elif event.get('hook_event_name')=='UserPromptSubmit' and TRIGGER.search(event.get('prompt') or ''):
                        result={'continue':False,'stopReason':'Sol Cabinet start state unavailable',
                                'systemMessage':'Sol Cabinet 开工状态无法安全保存，本任务未启动。'}
                    else:
                        result={'systemMessage':'Sol Cabinet钩子无法核验：'+type(exc).__name__}
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'REJECTED','reason':str(exc)},ensure_ascii=False))
        return 2


if __name__=='__main__': raise SystemExit(main())
