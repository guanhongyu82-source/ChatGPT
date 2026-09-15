#!/usr/bin/env python3
"""Bounded maintenance lifecycle, using Cabinet snapshot/evidence primitives.
Local integrity gates do not authenticate user or reviewer identity.
"""
from __future__ import annotations
import argparse, contextlib, fcntl, hashlib, json, os, re, subprocess, sys, tarfile, uuid, shutil
from datetime import datetime, timezone
from pathlib import Path
from record_evolution import write_observation  # legacy intake remains supported
from validate_evolution_proposal import system_digest, snapshot_metadata, validate_snapshot
from create_release_snapshot import create_snapshot, DEFAULT_OUTPUT_DIR
from verify_evidence import verify_evidence, _file
from sync_agent_runtime import _atomic_regular_write, _fsync_directory
from maintenance_boundary import guarded
ROOT = Path(__file__).resolve().parent.parent
CAUSES = {'execution_failure','rule_gap','rule_conflict','runtime_issue','noise'}
FAILURES = {'user-correction','missing-file','missing-object','missing-step','false-completion','quality-failure','misroute','agent-duty','serial-wait','duplicate-read','duplicate-check','rule-inactive','runtime-compatibility','quality-regression','task_underclassification','file_delivery_uncontrolled','incident_not_recorded'}
CAPS = {'routing','delivery','inspection','orchestration','installation','maintenance','writing'}
DIMENSIONS = {'fix','non_regression','boundary','quality','speed'}

def now(): return datetime.now(timezone.utc).isoformat()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
@guarded
def write(p, value):
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.parent.is_symlink() or p.is_symlink(): raise ValueError('unsafe state path')
    os.chmod(p.parent,0o700)
    _atomic_regular_write(p,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode(),0o600)
    _fsync_directory(p.parent)
@contextlib.contextmanager
@guarded
def lock(root):
    directory=root/'memory-evolution/proposals';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.is_symlink(): raise ValueError('unsafe state directory')
    fd=os.open(directory/'.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:
        fcntl.flock(fd,fcntl.LOCK_EX);yield directory

def validate_incident(i):
    fields={'incident_id','time','failure_type','cause','impact','evidence','capabilities','repeated','hits','permission'}
    if set(i)!=fields: raise ValueError('incident fields must be exact; no free text')
    if not re.fullmatch(r'INC-[0-9a-f]{32}',i['incident_id']): raise ValueError('invalid incident ID')
    datetime.fromisoformat(i['time'])
    if i['failure_type'] not in FAILURES or i['cause'] not in CAUSES or i['impact'] not in {'ordinary','high'}: raise ValueError('unregistered taxonomy')
    if not isinstance(i['capabilities'],list) or not i['capabilities'] or not set(i['capabilities'])<=CAPS: raise ValueError('invalid capabilities')
    e=i['evidence']
    if not isinstance(e,list) or not e or any(not re.fullmatch(r'EV-[0-9a-f]{32}',v) for v in e) or len(e)!=len(set(e)): raise ValueError('evidence must identify independent sanitized task captures')
    if type(i['hits']) is not int or i['hits']!=len(e) or type(i['repeated']) is not bool or i['repeated']!=(len(e)>1): raise ValueError('hits must derive from unique evidence')
    if i['permission']!='record': raise ValueError('observation cannot authorize modification')
    return i

@guarded
def record(i,root=ROOT,*,evidence=None):
    validate_incident(i)
    if evidence is None: raise ValueError('real task capture required')
    captures=[]
    for eid in i['evidence']:
        capture=read(_file(evidence,eid+'.json'))
        if set(capture)!={'evidence_id','task_instance_id','failure_type','artifact_path','artifact_sha256','source','sanitized'} or capture['evidence_id']!=eid or capture['failure_type']!=i['failure_type'] or capture['source']!='executor-capture' or capture['sanitized'] is not True: raise ValueError('invalid capture')
        if not re.fullmatch(r'task-[0-9a-f]{32}',capture['task_instance_id']): raise ValueError('invalid task identity')
        artifact=_file(evidence,capture['artifact_path'])
        if not artifact.stat().st_size or hashlib.sha256(artifact.read_bytes()).hexdigest()!=capture['artifact_sha256']: raise ValueError('capture artifact mismatch')
        captures.append({k:capture[k] for k in ('evidence_id','task_instance_id','failure_type','artifact_sha256','source','sanitized')})
    if len({c['task_instance_id'] for c in captures})!=i['hits']: raise ValueError('hits require independent task captures')
    with lock(root):
        p=root/'memory-evolution/observations'/f"{i['incident_id']}.json"
        if p.exists():
            old=read(p)
            if any(old[k]!=i[k] for k in ('failure_type','cause','capabilities')): raise ValueError('incident identity changed')
            if not set(old['evidence'])<=set(i['evidence']): raise ValueError('cannot erase evidence')
        for c in captures:
            target=p.parent/(c['evidence_id']+'.json')
            if target.exists() and read(target)!=c: raise ValueError('capture identity conflict')
            write(target,c)
        write(p,i)
    return {'status':'RECORDED','EVO':None}

def resolution_tests(root, incident, supplied):
    """Required tests come from the maintained case catalog, never caller preference."""
    catalog=read(_file(Path(root)/'tests','regression-cases.json'))
    required={case['case_id'] for case in catalog if case.get('failure_type')==incident['failure_type'] and case.get('cause')==incident['cause']}
    if not required: raise ValueError('incident has no registered regression case')
    if not isinstance(supplied,list) or not all(isinstance(v,str) for v in supplied) or not required<=set(supplied):
        raise ValueError('resolution missing incident-specific regression cases')
    return sorted(required|set(supplied))

@guarded
def resolve(incident_id, resolution, evidence, root=ROOT):
    """Close a directly maintained incident only with current, independent evidence."""
    if not re.fullmatch(r'INC-[0-9a-f]{32}', incident_id): raise ValueError('invalid incident ID')
    if set(resolution) != {'candidate_sha256','test_run_id','review_ids','required_test_ids'}:
        raise ValueError('resolution fields must be exact')
    if resolution['candidate_sha256'] != system_digest(root): raise ValueError('stale resolution')
    incident=validate_incident(read(_file(root/'memory-evolution/observations',incident_id+'.json')))
    required=resolution_tests(root,incident,resolution['required_test_ids'])
    verify_evidence(Path(evidence), resolution['candidate_sha256'], resolution['test_run_id'],
                    resolution['review_ids'], required)
    with lock(root):
        if resolution['candidate_sha256'] != system_digest(root): raise ValueError('candidate changed before resolution lock')
        current = validate_incident(read(_file(root/'memory-evolution/observations', incident_id+'.json')))
        if current != incident: raise ValueError('incident changed before resolution lock')
        record_id = 'RES-' + uuid.uuid4().hex
        for rid in [resolution['test_run_id'], *resolution['review_ids']]:
            rec = read(_file(Path(evidence), rid+'.json'))
            dest = root/'memory-evolution/proposals/evidence'/record_id
            write(dest/(rid+'.json'), rec)
            artifact = _file(Path(evidence), rec['artifact_path'])
            target = dest/rec['artifact_path'];target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _atomic_regular_write(target, artifact.read_bytes(), 0o600)
        verify_evidence(dest, resolution['candidate_sha256'], resolution['test_run_id'], resolution['review_ids'], required)
        if resolution['candidate_sha256'] != system_digest(root): raise ValueError('candidate changed during evidence capture')
        if read(_file(root/'memory-evolution/observations',incident_id+'.json')) != incident: raise ValueError('incident changed during evidence capture')
        value = {'resolution_id':record_id,'incident_id':incident_id,'evidence':incident['evidence'],
                 'time':now(),'kind':'direct-maintenance',**resolution}
        write(root/'memory-evolution/proposals'/(record_id+'.json'),value)
    return {'status':'RESOLVED','incident_id':incident_id,'resolution_id':record_id,'EVO':None}

def status(root=ROOT):
    """Read the actual intake and closure ledger without creating files."""
    root=Path(root); observations=root/'memory-evolution/observations'; proposals=root/'memory-evolution/proposals'
    incidents=[]; closed_evidence={}; candidates=[]; errors=[]
    for p in sorted(proposals.glob('*.json')):
        if p.name == 'pending.json': continue
        try:
            data=read(_file(proposals,p.name))
            if data.get('resolution_id'):
                if not re.fullmatch(r'RES-[0-9a-f]{32}',data['resolution_id']): raise ValueError('invalid resolution identity')
                evidence_dir=proposals/'evidence'/data['resolution_id']
                incident=validate_incident(read(_file(observations,data['incident_id']+'.json')))
                required=resolution_tests(root,incident,data['required_test_ids'])
                verify_evidence(evidence_dir,data['candidate_sha256'],data['test_run_id'],data['review_ids'],required)
                closed_evidence.setdefault(data['incident_id'],set()).update(data['evidence'])
            elif data.get('EVO') and not data.get('rollback_of'):
                rolled_back=any(read(q).get('rollback_of') == data['EVO'] for q in proposals.glob('*.json') if q.is_file() and not q.is_symlink())
                if not rolled_back and data.get('post_apply') == 'PASS':
                    verify_evidence(Path(data['evidence_dir']),data['after'],data['regression'],data['reviews'],['REG1','REG2',*[c['case_id'] for c in data['cases']]])
                    closed_evidence.setdefault(data['incident']['incident_id'],set()).update(data['incident']['evidence'])
            elif data.get('incident_id'):
                candidates.append({'incident_id':data['incident_id'],'status':data.get('status','candidate'),'record':p.name})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append({'record':p.name,'error':type(exc).__name__})
    tasks_by_failure={}
    for p in sorted(observations.glob('INC-*.json')):
        try:
            item=validate_incident(read(_file(observations,p.name)))
            task_ids=set()
            for eid in item['evidence']:
                capture=read(_file(observations,eid+'.json'))
                if capture['evidence_id'] != eid or capture['failure_type'] != item['failure_type'] or capture.get('sanitized') is not True:
                    raise ValueError('invalid incident capture')
                if not re.fullmatch(r'task-[0-9a-f]{32}',capture['task_instance_id']): raise ValueError('invalid task identity')
                task_ids.add(capture['task_instance_id'])
            if len(task_ids)!=item['hits']: raise ValueError('incident hits inconsistent')
            tasks_by_failure.setdefault(item['failure_type'],set()).update(task_ids)
            closed=set(item['evidence']) <= closed_evidence.get(item['incident_id'],set())
            incidents.append({'incident_id':item['incident_id'],'failure_type':item['failure_type'],'cause':item['cause'],
                              'impact':item['impact'],'hits':len(task_ids),'status':'closed' if closed else 'pending'})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append({'record':p.name,'error':type(exc).__name__})
    for item in incidents:
        item['independent_tasks']=len(tasks_by_failure[item['failure_type']])
        item['repeated']=item['independent_tasks']>=2
    closed_ids={i['incident_id'] for i in incidents if i['status']=='closed'}
    candidates=[c for c in candidates if c['incident_id'] not in closed_ids and c['status'] not in {'closed','withdrawn','cancelled'}]
    pending_groups={(i['failure_type'],i['cause']) for i in incidents if i['status']=='pending'}
    return {'status':'NEEDS_ATTENTION' if errors or candidates or any(i['status']=='pending' for i in incidents) or (proposals/'pending.json').exists() else 'CLEAR',
            'background_daemon':False,'deployment_pending':(proposals/'pending.json').exists(),
            'pending_count':len(pending_groups),'pending_incident_count':sum(i['status']=='pending' for i in incidents),'incidents':incidents,
            'candidates':candidates,'errors':errors}

def cases_for(root,incident,ids):
    cases=read(root/'tests/regression-cases.json')
    selected=[c for c in cases if c['case_id'] in ids]
    if not ids or len(selected)!=len(set(ids)): raise ValueError('missing regression case')
    for c in selected:
        if c['incident_id']!=incident['incident_id'] or c['cause']!=incident['cause'] or c['failure_type']!=incident['failure_type']: raise ValueError('case not bound to incident')
        if not all(c.get(k) for k in ('impact','trigger','correct_behavior','no_regression','pass_condition','test')): raise ValueError('incomplete case')
    return selected

@guarded
def regress(candidate,evidence):
    candidate=candidate.resolve();evidence=evidence.resolve()
    if evidence.is_relative_to(candidate): raise ValueError('evidence must be outside candidate')
    before=system_digest(candidate);rid='testrun-'+uuid.uuid4().hex
    results={};logs=[]
    commands=[('REG1',[sys.executable,'-B','-m','unittest','discover','-s',str(candidate/'tests'),'-p','test_*.py']),('REG2',[sys.executable,'-B',str(candidate/'scripts/validate_structure.py')])]
    for tid,cmd in commands:
        r=subprocess.run(cmd,cwd=candidate,capture_output=True,text=True,timeout=180)
        results[tid]='PASS' if r.returncode==0 else 'FAIL';logs.append(r.stdout+r.stderr)
        if tid=='REG1' and not re.search(r'Ran [1-9][0-9]* tests?',r.stderr): results[tid]='FAIL'
    runner = """import unittest,sys
suite=unittest.defaultTestLoader.discover(sys.argv[1],pattern=sys.argv[2])
def flatten(s):
 for x in s:
  if isinstance(x,unittest.TestSuite): yield from flatten(x)
  else: yield x
selected=[t for t in flatten(suite) if t.id().split('.')[-1]==sys.argv[3]]
if len(selected)!=1: raise SystemExit(2)
r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
raise SystemExit(0 if r.wasSuccessful() and not r.skipped and r.testsRun==len(selected) else 1)
"""
    catalog=candidate/'tests/regression-cases.json'
    if catalog.is_file():
        for case in read(catalog):
            module,method=case['test'].split(':')
            if not re.fullmatch(r'test_[a-z0-9_]+\.py',module) or not re.fullmatch(r'test_[a-z0-9_]+',method): raise ValueError('invalid case test')
            run=subprocess.run([sys.executable,'-B','-c',runner,str(candidate/'tests'),module,method],cwd=candidate,capture_output=True,text=True,timeout=60)
            results[case['case_id']]='PASS' if run.returncode==0 else 'FAIL';logs.append(run.stdout+run.stderr)
    if system_digest(candidate)!=before: raise ValueError('candidate changed during regression')
    evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    log=evidence/(rid+'.log');_atomic_regular_write(log,'\n'.join(logs).encode(),0o600)
    passed=all(v=='PASS' for v in results.values())
    result={'record_id':rid,'kind':'test','candidate_sha256':before,'verdict':'PASS' if passed else 'FAIL','error_type':None if passed else 'regression-failure','source':'executor-capture','artifact_path':log.name,'artifact_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'exit_code':0 if passed else 1,'test_results':results,'phase':'candidate','metadata_sha256':metadata_hash(candidate)}
    write(evidence/(rid+'.json'),result);return result

def permission(root,paths,proposal,reviews,*,deletions=False):
    cage=read(root/'memory-evolution/permission-cage.json')
    if any(any(p.startswith(prefix) for prefix in cage['self_protected_prefixes']) for p in paths): raise ValueError('self-protected: independent direct maintenance only')
    support = {p for p in paths if p == 'tests/regression-cases.json' or (p.startswith('tests/test_') and not (root/p).exists())}
    lane='auto' if not deletions and set(paths)-support<=set(cage['auto_paths']) else 'approve'
    if proposal.get('permission')!=lane: raise ValueError('permission mismatch')
    if not re.fullmatch(r'turn-[0-9a-f]{16,64}',proposal.get('approval_ref') or ''): raise ValueError('explicit candidate-bound release approval required')
    if len(reviews)<2: raise ValueError('two independent semantic reviews required')
    for r in reviews:
        if r.get('permission')!=lane or r.get('frozen_impact') is not False or r.get('dimensions')!={d:'PASS' for d in DIMENSIONS}: raise ValueError('semantic boundary/quality/speed review incomplete')
    return lane

def validate_release_approval(evidence,proposal,changes):
    approval=read(_file(evidence,proposal['approval_ref']+'.json'))
    expected={'actor':'user','candidate_sha256':proposal['candidate_sha256'],'base_sha256':proposal['base_sha256'],'changes_sha256':hashlib.sha256(json.dumps(changes,sort_keys=True).encode()).hexdigest(),'approval_ref':proposal['approval_ref'],'purpose':proposal['summary'],'release_intent':'finalize-stable','source':'executor-capture','approved':True}
    if any(approval.get(k)!=v for k,v in expected.items()): raise ValueError('release approval not bound to current candidate and explicit finalize intent')
    artifact=_file(evidence,approval.get('artifact_path'))
    if not artifact.stat().st_size or hashlib.sha256(artifact.read_bytes()).hexdigest()!=approval.get('artifact_sha256'): raise ValueError('approval artifact mismatch')
    return approval

def metadata_hash(root):
    return hashlib.sha256(json.dumps(snapshot_metadata(root),sort_keys=True).encode()).hexdigest()

def changed(base,candidate):
    a=snapshot_metadata(base);b=snapshot_metadata(candidate)
    return {p:{'before':a.get(p),'after':b.get(p)} for p in sorted(set(a)|set(b)) if a.get(p)!=b.get(p)}

@guarded
def promote(candidate,proposal,evidence,root=ROOT):
    candidate=candidate.resolve(); evidence=evidence.resolve()
    if candidate==root.resolve() or candidate.is_relative_to(root.resolve()) or evidence.is_relative_to(candidate): raise ValueError('candidate/evidence isolation required')
    with lock(root) as state:
        if (state/'pending.json').exists(): raise ValueError('unfinished deployment requires recovery')
        if system_digest(root)!=proposal['base_sha256'] or system_digest(candidate)!=proposal['candidate_sha256']: raise ValueError('stale base/candidate')
        changes=changed(root,candidate)
        if any(m['before'] and m['after'] and m['before']['mode']!=m['after']['mode'] for m in changes.values()): raise ValueError('mode changes require independent direct maintenance')
        if not changes: return {'status':'NO_CHANGE','EVO':None}
        i=validate_incident(read(_file(root/'memory-evolution/observations',proposal['incident_id']+'.json')))
        if i['cause']=='noise' or (i['hits']<2 and i['impact']!='high'): raise ValueError('record only: insufficient evidence or noise')
        captures=[read(_file(root/'memory-evolution/observations',eid+'.json')) for eid in i['evidence']]
        if len({c['task_instance_id'] for c in captures})!=i['hits'] or any(c['failure_type']!=i['failure_type'] for c in captures): raise ValueError('incident captures inconsistent')
        cases=cases_for(candidate,i,proposal['case_ids'])
        old_cases=read(root/'tests/regression-cases.json')
        new_cases=read(candidate/'tests/regression-cases.json')
        if any(c not in new_cases for c in old_cases): raise ValueError('existing regression cases are frozen')
        for path in changes:
            if path.startswith('tests/') and path!='tests/regression-cases.json' and (root/path).exists(): raise ValueError('existing tests cannot be weakened by evolution')
        verify_evidence(evidence,proposal['candidate_sha256'],proposal['test_run_id'],proposal['review_ids'],['REG1','REG2',*proposal['case_ids']])
        reviews=[read(_file(evidence,r+'.json')) for r in proposal['review_ids']]
        test=read(_file(evidence,proposal['test_run_id']+'.json'))
        if any(r.get('metadata_sha256')!=metadata_hash(candidate) for r in [test,*reviews]): raise ValueError('file metadata changed after review')
        lane=permission(root,list(changes),proposal,reviews,deletions=any(m['after'] is None for m in changes.values()))
        if proposal.get('sensitivity_checked') is not True or proposal.get('contains_sensitive_content') is not False or any(r.get('sanitized_metadata') is not True for r in reviews): raise ValueError('sanitized metadata review required')
        if proposal.get('quality') not in {'regression-pass','verified-improvement'} or proposal.get('speed') not in {'not-measured','expected-non-decrease','measured-improvement'}: raise ValueError('quality/speed must use fixed evidence codes')
        if proposal.get('summary') not in {'fix-runtime-compatibility','fix-execution-chain','improve-routing','reduce-duplicate-work','non-core-wording'}: raise ValueError('summary must use fixed code')
        validate_release_approval(evidence,proposal,changes)
        for c in cases:
            module,method=c['test'].split(':')
            if not re.fullmatch(r'test_[a-z0-9_]+\.py',module) or not re.fullmatch(r'test_[a-z0-9_]+',method): raise ValueError('invalid test binding')
            if 'def '+method+'(' not in (candidate/'tests'/module).read_text(): raise ValueError('case test absent')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S');evo='EVO-'+stamp
        if (state/(evo+'.json')).exists(): raise ValueError('EVO collision; retry later')
        rollback_id='snapshot-'+datetime.now(timezone.utc).strftime('%Y-%m-%d')+'-v'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        if root!=ROOT: raise ValueError('promotion root must be the installed source')
        snapshot,base=create_snapshot(rollback_id)
        validate_snapshot(snapshot,rollback_id,base)
        if base!=proposal['base_sha256']: raise ValueError('base changed before snapshot')
        saved={p:(root/p).read_bytes() if (root/p).exists() else None for p in changes}
        modes={p:(root/p).stat().st_mode & 0o777 if (root/p).exists() else 0o600 for p in changes}
        write(state/'pending.json',{'changes':changes,'rollback_id':rollback_id,'rollback_path':str(snapshot),'before':base,'after':proposal['candidate_sha256'],'EVO':evo})
        try:
            for p,meta in changes.items():
                target=root/p
                if meta['after'] is None: target.unlink()
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    _atomic_regular_write(target,(candidate/p).read_bytes(),meta['after']['mode'])
            if system_digest(root)!=proposal['candidate_sha256']: raise ValueError('post-apply hash mismatch')
            post=subprocess.run([sys.executable,'-B',str(root/'scripts/check_installation.py')],capture_output=True,text=True,timeout=60)
            if post.returncode!=0: raise ValueError('post-apply installation check failed')
            if system_digest(root)!=proposal['candidate_sha256']: raise ValueError('post-check candidate drift')
            capture=state/'evidence'/evo
            for rid in [proposal['test_run_id'],*proposal['review_ids'],proposal['approval_ref']]:
                rec=read(_file(evidence,rid+'.json'))
                write(capture/(rid+'.json'),rec)
                artifact=_file(evidence,rec['artifact_path'])
                dest=capture/rec['artifact_path'];dest.parent.mkdir(parents=True,exist_ok=True)
                _atomic_regular_write(dest,artifact.read_bytes(),0o600)
            _atomic_regular_write(capture/'post-apply.log',post.stdout.encode()+post.stderr.encode(),0o600)
            entry={'EVO':evo,'time':now(),'incident':i,'cases':cases,'root_cause':i['cause'],'changes':changes,'before':base,'after':system_digest(root),'summary':proposal['summary'],'quality':proposal['quality'],'speed':proposal['speed'],'evidence_dir':str(capture),'post_apply':'PASS','regression':proposal['test_run_id'],'reviews':proposal['review_ids'],'permission':lane,'user_approval':proposal['approval_ref'],'rollback_id':rollback_id,'rollback_path':str(snapshot)}
            write(state/(evo+'.json'),entry)
        except BaseException:
            for p,data in saved.items():
                if data is None: (root/p).unlink(missing_ok=True)
                else: _atomic_regular_write(root/p,data,modes[p])
            if system_digest(root)==base: (state/'pending.json').unlink()
            raise
        (state/'pending.json').unlink();_fsync_directory(state)
        return entry

@guarded
def rollback(evo,root=ROOT):
    if not re.fullmatch(r'EVO-\d{8}-\d{6}',evo): raise ValueError('invalid EVO')
    with lock(root) as state:
        if (state/'pending.json').exists(): raise ValueError('pending deployment requires recovery')
        e=read(_file(state,evo+'.json'))
        if system_digest(root)!=e['after']: raise ValueError('refuse rollback over later changes')
        snap=Path(e['rollback_path']);validate_snapshot(snap,e['rollback_id'],e['before'])
        with tarfile.open(snap,'r:gz') as archive:
            original=json.load(archive.extractfile('snapshot-manifest.json'))['files']
        current=snapshot_metadata(root)
        actual={p:{'before':original.get(p),'after':current.get(p)} for p in sorted(set(original)|set(current)) if original.get(p)!=current.get(p)}
        if actual!=e['changes']: raise ValueError('rollback changes do not match verified snapshot/current metadata')
        for p in actual:
            if Path(p).is_absolute() or '..' in Path(p).parts or (root/p).resolve().is_relative_to(root.resolve()) is False: raise ValueError('unsafe rollback path')
        saved={p:(root/p).read_bytes() if (root/p).exists() else None for p in e['changes']}
        write(state/'pending.json',{'rollback_of':evo,'changes':e['changes'],'rollback_id':e['rollback_id'],'rollback_path':str(snap),'before':e['before'],'after':e['after']})
        try:
            with tarfile.open(snap,'r:gz') as t:
                for p,m in e['changes'].items():
                    if m['before'] is None: (root/p).unlink()
                    else: _atomic_regular_write(root/p,t.extractfile('sol-cabinet/'+p).read(),m['before']['mode'])
            if system_digest(root)!=e['before']: raise ValueError('rollback verification failed')
            result={'rollback_of':evo,'time':now(),'status':'RESTORED','restored_sha256':e['before']}
            write(state/('rollback-'+evo+'.json'),result)
        except BaseException:
            for p,data in saved.items():
                if data is None: (root/p).unlink(missing_ok=True)
                else: _atomic_regular_write(root/p,data,e['changes'][p]['after']['mode'])
            if system_digest(root)==e['after']: (state/'pending.json').unlink()
            raise
        (state/'pending.json').unlink();return result

@guarded
def recover(root=ROOT):
    """Recover interrupted promotion to verified before state; never guess alien bytes."""
    with lock(root) as state:
        pending=state/'pending.json'
        if not pending.exists(): return {'status':'NO_PENDING','EVO':None}
        item=read(pending)
        if item.get('rollback_of'): raise ValueError('interrupted rollback: use verified snapshot and maintenance review; preserve pending')
        snap=Path(item['rollback_path']);validate_snapshot(snap,item['rollback_id'],item['before'])
        evo=item['EVO'];committed=state/(evo+'.json')
        if committed.exists():
            if system_digest(root)!=read(committed)['after']: raise ValueError('committed release diverged; manual recovery required')
            check=subprocess.run([sys.executable,'-B',str(root/'scripts/check_installation.py')],capture_output=True,timeout=60)
            if check.returncode: raise ValueError('committed release installation failed')
            pending.unlink();return {'status':'RECOVERED_COMMITTED','EVO':evo}
        current=snapshot_metadata(root)
        with tarfile.open(snap,'r:gz') as archive:
            original=json.load(archive.extractfile('snapshot-manifest.json'))['files']
            for path,meta in item['changes'].items():
                if Path(path).is_absolute() or '..' in Path(path).parts or not (root/path).resolve().is_relative_to(root.resolve()): raise ValueError('unsafe recovery path')
                if original.get(path)!=meta['before'] or current.get(path) not in (meta['before'],meta['after']): raise ValueError('recovery content changed; manual review required')
            for path in set(current)|set(original):
                if path not in item['changes'] and current.get(path)!=original.get(path): raise ValueError('unrelated changes prevent recovery')
            for path,meta in item['changes'].items():
                if meta['before'] is None: (root/path).unlink(missing_ok=True)
                else: _atomic_regular_write(root/path,archive.extractfile('sol-cabinet/'+path).read(),meta['before']['mode'])
        if system_digest(root)!=item['before']: raise ValueError('recovery digest mismatch')
        write(state/('recovery-'+evo+'.json'),{'status':'RESTORED_BEFORE_PROMOTION','time':now(),'snapshot':item['rollback_id']})
        pending.unlink();return {'status':'RECOVERED','EVO':None}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['record','regress','promote','rollback','recover','status','resolve']);p.add_argument('args',nargs='*');a=p.parse_args()
    try:
        if a.action=='record': result=record(read(Path(a.args[0])),evidence=Path(a.args[1]))
        elif a.action=='regress': result=regress(Path(a.args[0]),Path(a.args[1]))
        elif a.action=='promote': result=promote(Path(a.args[0]),read(Path(a.args[1])),Path(a.args[2]))
        elif a.action=='rollback': result=rollback(a.args[0])
        elif a.action=='recover': result=recover()
        elif a.action=='resolve': result=resolve(a.args[0],read(Path(a.args[1])),Path(a.args[2]))
        else: result=status()
        print(json.dumps(result,ensure_ascii=False,indent=2));return 1 if result.get('verdict')=='FAIL' else 0
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status':'REJECTED','EVO':None,'reason':str(exc)},ensure_ascii=False));return 2
if __name__=='__main__': raise SystemExit(main())
