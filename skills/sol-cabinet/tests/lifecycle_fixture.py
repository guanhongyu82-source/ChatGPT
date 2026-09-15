"""Isolated promotion/rollback mechanics. All IDs/reviews here are synthetic fixtures."""
import hashlib,json,shutil,sys,tempfile
from pathlib import Path
source=Path(sys.argv[1])
with tempfile.TemporaryDirectory() as tmp:
    base=Path(tmp);root=base/'active';candidate=base/'candidate';evidence=base/'evidence';evidence.mkdir()
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('__pycache__','observations','proposals'))
    sys.path.insert(0,str(root/'scripts'))
    import evolve as e
    import create_release_snapshot as cs
    e.create_snapshot=lambda rid:cs.create_snapshot(rid,base/'backups',allow_test_output=True)
    # This fixture tests transaction gates, not production installation.
    (root/'scripts/check_installation.py').write_text('raise SystemExit(0)\n')
    incident={'incident_id':'INC-'+'1'*32,'time':'2026-09-12T00:00:00+00:00','failure_type':'runtime-compatibility','cause':'runtime_issue','impact':'high','evidence':['EV-'+'1'*32],'capabilities':['installation'],'repeated':False,'hits':1,'permission':'record'}
    e.write(root/'memory-evolution/observations'/('EV-'+'1'*32+'.json'),{'evidence_id':'EV-'+'1'*32,'task_instance_id':'task-'+'1'*32,'failure_type':'runtime-compatibility'})
    e.write(root/'memory-evolution/observations'/(incident['incident_id']+'.json'),incident)
    shutil.copytree(root,candidate);target=candidate/'examples/routing-examples.md';target.write_text(target.read_text()+'\nFixture correction.\n')
    sha=e.system_digest(candidate);mid=e.metadata_hash(candidate);test='testrun-'+'1'*32;reviews=['review-'+'2'*32,'review-'+'3'*32]
    for rid in [test,*reviews]:
        log=evidence/(rid+'.log');log.write_text('SYNTHETIC lifecycle gate fixture, not production evidence.\n')
        record={'record_id':rid,'kind':'test' if rid==test else 'review','candidate_sha256':sha,'verdict':'PASS','error_type':None,'source':'executor-capture','artifact_path':log.name,'artifact_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'metadata_sha256':mid}
        if rid==test:record.update(exit_code=0,test_results={'REG1':'PASS','REG2':'PASS','RC-INSTALL-001':'PASS'},phase='candidate')
        else:record.update(reviewer_id=rid,author_id='fixture-author',independent=True,must_fix=[],permission='auto',frozen_impact=False,dimensions={d:'PASS' for d in e.DIMENSIONS},sanitized_metadata=True)
        e.write(evidence/(rid+'.json'),record)
    proposal={'incident_id':incident['incident_id'],'case_ids':['RC-INSTALL-001'],'base_sha256':e.system_digest(root),'candidate_sha256':sha,'test_run_id':test,'review_ids':reviews,'permission':'auto','approval_ref':None,'summary':'non-core-wording','quality':'regression-pass','speed':'not-measured','sensitivity_checked':True,'contains_sensitive_content':False}
    # Failed regression is rejected before writes and cannot mint EVO.
    tr=e.read(evidence/(test+'.json'));tr['verdict']='FAIL';e.write(evidence/(test+'.json'),tr)
    try:e.promote(candidate,proposal,evidence);raise AssertionError('failed regression promoted')
    except ValueError:pass
    assert e.system_digest(root)==proposal['base_sha256'];assert not list((root/'memory-evolution/proposals').glob('EVO-*'))
    tr['verdict']='PASS';e.write(evidence/(test+'.json'),tr)
    release=e.promote(candidate,proposal,evidence);assert release['EVO'];assert e.system_digest(root)==sha
    # Tampered rollback path and later chmod must both be rejected without writes.
    path=root/'memory-evolution/proposals'/(release['EVO']+'.json');bad=dict(release);bad['changes']={'../escape':{'before':None,'after':None}};e.write(path,bad)
    try:e.rollback(release['EVO']);raise AssertionError('unsafe rollback accepted')
    except ValueError:pass
    e.write(path,release);live=root/'examples/routing-examples.md';mode=live.stat().st_mode&0o777;live.chmod(0o700)
    try:e.rollback(release['EVO']);raise AssertionError('chmod drift overwritten')
    except ValueError:pass
    live.chmod(mode);restored=e.rollback(release['EVO']);assert restored['rollback_of']==release['EVO'];assert e.system_digest(root)==proposal['base_sha256'];assert path.exists()
    print('PASS: failed regression rejected; promotion committed; unsafe rollback rejected; chmod drift rejected; rollback restored and original EVO retained')
