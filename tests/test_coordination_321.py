import copy
import pytest
from core.coordination.context import SocialContextAdapter, require_asdc_context
from core.coordination.features import extract_features, fuse
from core.judges.pipeline_c import validate_unit
from evaluation.jev_metrics import bootstrap95


def config(mode='PIT_CAUSAL'):
    return {'coordination_mode':mode,'similarity_threshold':.9,'burst_window_minutes':15}


def record(n, minute, author=None):
    t=f'2026-10-06T10:{minute:02d}:00+08:00'
    return {'record_id':str(n),'platform':'eastmoney','content':{'text':'坚定看好明天涨停','author_id_hash':author,'author_hash_key_id':'v1'},'point_in_time':{'published_at':t,'available_at':t},'observation':{'like_count':12,'reply_count':3,'observed_at':t}}


def test_equity_context_fields_and_legacy():
    a=SocialContextAdapter().adapt(record(1,0,'hash1'))
    assert a['stable_author_key']=='eastmoney:v1:hash1'
    assert a['like_count']==12 and a['reply_count']==3 and a['event_timestamp']==a['available_timestamp']
    legacy=SocialContextAdapter().adapt({'cid':'1','user_id':'u','create_time':'2026-10-06T10:00:00+08:00','digg_count':2,'platform':'douyin'})
    assert legacy['like_count']==2 and legacy['available_at'] is None
    assert 'STABLE_AUTHOR_ID_MISSING' not in extract_features([record(1,0,'hash1')],config())[0]['missing_features']


def test_future_append_does_not_change_pit_features_or_score():
    past=[record(1,0,'a'),record(2,1,'b')]
    before=extract_features(past,config())
    after=extract_features(past+[record(i,i,'future'+str(i)) for i in range(3,15)],config())
    assert before==after[:2]
    weights={'jev':.35,'similarity':.25,'burst':.2,'template':.1,'author':.1}
    assert fuse(.2,before[0],weights)==fuse(.2,after[0],weights)
    require_asdc_context(before[0])
    retro=extract_features(past,config('RETROSPECTIVE'))
    with pytest.raises(ValueError): require_asdc_context(retro[0])


def test_late_arrival_and_missing_time_are_not_past_evidence():
    early=record(1,0,'a');late=record(2,0,'b');late['point_in_time']['available_at']='2026-10-06T11:00:00+08:00'
    assert extract_features([early,late],config())[0]==extract_features([early],config())[0]
    missing=copy.deepcopy(early);missing['point_in_time'].pop('available_at')
    f=extract_features([missing],config())[0]
    assert f['pit_state'].startswith('FAIL')
    with pytest.raises(ValueError):require_asdc_context(f)


def test_future_observation_and_hash_namespace():
    r=record(1,0,'a');r['observation']['observed_at']='2026-10-06T11:00:00+08:00'
    a=SocialContextAdapter();c=a.adapt(r)
    assert a.legacy_view(c,c['available_timestamp'])['digg_count'] is None
    r2=copy.deepcopy(r);r2['content']['author_hash_key_id']='v2'
    assert c['stable_author_key']!=a.adapt(r2)['stable_author_key']


def test_cluster_group_evidence():
    f=extract_features([record(i,i,'a'+str(i)) for i in range(3)],config('RETROSPECTIVE'))
    assert f[0]['cluster']['member_count']==3
    assert f[0]['cluster']['unique_author_count']==3
    assert f[0]['cluster']['evidence_state']=='SUSPECTED_COORDINATED'
    assert extract_features([record(1,0)],config())[0]['cluster']['evidence_state']=='INSUFFICIENT_EVIDENCE'


def test_pipeline_c_external_and_invalid_evidence():
    u={'subject_code':'600183','subject_relation':'EXTERNAL','evidence':{'quote':'CCL','start':0,'end':3}}
    assert validate_unit(u,'CCL新闻','688401')=='EXTERNAL_NO_TARGET_DIRECTION'
    u['subject_code']='688401';u['subject_relation']='UPSTREAM_DOWNSTREAM'
    assert validate_unit(u,'CCL新闻','688401')=='REVIEW_SUBJECT_RELATION'
    u['evidence']['quote']='伪造'
    assert validate_unit(u,'CCL新闻','688401')=='REVIEW_INVALID_EVIDENCE'


def test_pipeline_c_preserves_negation_context():
    import asyncio
    from core.judges.pipeline_c import judge_units
    from core.judges.base import JudgeContext
    class FakeJudge:
        async def judge_direction(self, unit, context):
            assert unit['text']=='不买黄金'
            assert unit['evidence']['quote']=='买黄金'
            class Result:
                def model_dump(self): return {'label':'NOT_APPLICABLE'}
            return Result()
    record={'text':'不买黄金','atomic_units':[{'unit_id':'u','subject_code':'X','subject_relation':'PRIMARY_SUBJECT','evidence':{'quote':'买黄金','start':1,'end':4}}]}
    context=JudgeContext(stock_code='X',stock_name='黄金',platform='test')
    assert asyncio.run(judge_units(FakeJudge(),record,context))[0]['direction']['label']=='NOT_APPLICABLE'


def test_bootstrap_pending_and_reproducible():
    assert bootstrap95([],['A','B'])['macro_f1'] is None
    pairs=[('A','A',{'A':.9,'B':.1}),('B','A',{'A':.6,'B':.4})]
    assert bootstrap95(pairs,['A','B'],iterations=20)==bootstrap95(pairs,['A','B'],iterations=20)


def test_judge_request_concurrency_limit(monkeypatch,tmp_path):
    import asyncio
    import threading
    import time
    import core.judges.jev as module
    active=0;peak=0;lock=threading.Lock()
    def transport(state,questions,cfg,cache,key,ledger):
        nonlocal active,peak
        with lock:
            active+=1;peak=max(peak,active)
        time.sleep(.005)
        with lock:active-=1
        ledger['successful_requests']+=1
        return {'model':'mock'}
    monkeypatch.setattr(module,'call',transport)
    ledger={'successful_requests':0}
    judge=module.JevJudge('dummy',{'concurrency':2},tmp_path,ledger)
    async def run():
        return await asyncio.gather(*(judge.request({'index':i},{}) for i in range(8)))
    assert len(asyncio.run(run()))==8
    assert peak==2 and ledger['successful_requests']==8


def test_unknown_publication_is_legal_but_invalid_or_future_is_not():
    r=record(1,0,'a');r['point_in_time']['published_at']=None
    f=extract_features([r],config())[0]
    assert f['pit_state']=='PASS' and f['publication_time_state']=='UNKNOWN'
    assert f['author_comment_count_1h']==1
    for bad in ('invalid', '2026-10-06T11:00:00+08:00'):
        r['point_in_time']['published_at']=bad
        assert extract_features([r],config())[0]['pit_state'].startswith('FAIL')


def test_pit_temporal_features_use_availability_clock():
    rows=[record(i,i,'same') for i in range(3)]
    for r in rows:r['point_in_time']['published_at']='2026-10-01T00:00:00+08:00'
    f=extract_features(rows,config())[-1]
    assert f['author_comment_count_1h']==3
    assert f['burst_window_count']==3
    assert f['cluster']['temporal_concentration']==120
    assert f['temporal_clock']=='available_at'


def test_same_cutoff_snapshot_reuse_is_isolated():
    rows=[record(i,0,str(i)) for i in range(3)]
    rows[-1]['point_in_time']['available_at']='2026-10-06T10:01:00+08:00'
    actual=extract_features(rows,config())
    assert actual[:2]==extract_features(rows[:2],config())
    assert actual[0]['cluster_members']==[1,2]
    assert actual[-1]['cluster_members']==[1,2,3]
