"""Coordination evidence in retrospective and as-of causal snapshots."""
import math
from collections import Counter
from scripts.jev_judge_v2 import features as legacy_features
from .context import SocialContextAdapter


def extract_features(comments, config):
    mode=config.get('coordination_mode','RETROSPECTIVE')
    if mode not in ('RETROSPECTIVE','PIT_CAUSAL'): raise ValueError('Unknown coordination mode')
    adapter=SocialContextAdapter();contexts=[adapter.adapt(c) for c in comments]
    retro=legacy_features([adapter.legacy_view(c) for c in contexts],config) if mode=='RETROSPECTIVE' else None
    rows=[]
    for i,c in enumerate(contexts):
        cutoff=c['available_timestamp'] if mode=='PIT_CAUSAL' else None
        valid=cutoff is not None and c['event_timestamp'] is not None and c['event_timestamp']<=cutoff
        if mode=='PIT_CAUSAL':
            visible=[j for j,x in enumerate(contexts) if valid and x['available_timestamp'] is not None and x['available_timestamp']<=cutoff and x['event_timestamp'] is not None and x['event_timestamp']<=cutoff]
            if not valid:
                rows.append({'coordination_mode':mode,'pit_state':'FAIL_MISSING_OR_INVALID_TIME','as_of':c['available_at'],'duplicate_cluster_size':0,'cluster_members':[],'cluster_id':None,'text_similarity_max':None,'template_reuse_ratio':None,'burst_zscore':None,'author_comment_count_1h':None,'author_comment_count_24h':None,'evidence_flags':[],'missing_features':['PIT_TIME_UNAVAILABLE'],'cluster':None,'same_direction_cluster_ratio':None})
                continue
            views=[adapter.legacy_view(contexts[j],cutoff) for j in visible];r=legacy_features(views,config)[visible.index(i)];group=[visible[j-1] for j in r['cluster_members']]
        else:
            visible=list(range(len(contexts)));r=retro[i];group=[j-1 for j in r['cluster_members']]
        peers=[j for j in visible if contexts[j]['platform']==c['platform']]
        anchor=cutoff if mode=='PIT_CAUSAL' else c['event_timestamp'];window=config['burst_window_minutes']*60
        known=[contexts[j]['event_timestamp'] for j in peers if contexts[j]['event_timestamp'] is not None]
        recent=[j for j in peers if anchor is not None and contexts[j]['event_timestamp'] is not None and 0<=anchor-contexts[j]['event_timestamp']<=window]
        span=max(known)-min(known) if len(known)>1 else 0;expected=len(known)*window/span if span>window else None
        r['burst_window_count']=len(recent) if anchor is not None else None
        r['burst_zscore']=(len(recent)-expected)/math.sqrt(expected) if expected and anchor is not None else None
        r['burst_score']=len(recent)/expected if expected and anchor is not None else None
        r['similar_text_in_window_count']=sum(j in group for j in recent) if anchor is not None else None
        r['evidence_flags']=[flag for flag in r['evidence_flags'] if flag!='SAMPLE_TIME_CONCENTRATION']
        if len(recent)>=5 and expected and len(recent)/expected>=3:
            r['evidence_flags'].append('SAMPLE_TIME_CONCENTRATION')
        for hours in (1,24):
            r[f'author_comment_count_{hours}h']=sum(contexts[j]['stable_author_key']==c['stable_author_key'] and contexts[j]['event_timestamp'] is not None and 0<=anchor-contexts[j]['event_timestamp']<=hours*3600 for j in peers) if c['stable_author_key'] is not None and anchor is not None else None
        r['template_reuse_ratio']=max(0,r['template_reuse_count']-1)/max(1,len(peers)-1)
        authors={contexts[j]['stable_author_key'] for j in group if contexts[j]['stable_author_key'] is not None};gt=[contexts[j]['event_timestamp'] for j in group if contexts[j]['event_timestamp'] is not None]
        cluster={'member_count':len(group),'unique_author_count':len(authors) if authors else None,'cross_author_similarity':r['cross_account_similarity'],'template_reuse':r['template_reuse_ratio'],'temporal_concentration':max(gt)-min(gt) if len(gt)>1 else None,'platform':c['platform'],'direction_homogeneity':None,'member_record_ids':[contexts[j]['record_id'] for j in group],'evidence_state':'INSUFFICIENT_EVIDENCE'}
        if len(group)>=3 and len(authors)>=3 and cluster['cross_author_similarity'] is not None and cluster['cross_author_similarity']>=config['similarity_threshold'] and cluster['temporal_concentration'] is not None and cluster['temporal_concentration']<=window:
            cluster['evidence_state']='SUSPECTED_COORDINATED'
        r.update(coordination_mode=mode,pit_state='PASS' if mode=='PIT_CAUSAL' else 'NOT_APPLICABLE',as_of=c['available_at'] if mode=='PIT_CAUSAL' else None,cluster_members=[j+1 for j in group],cluster_id=min(contexts[j]['record_id'] for j in group),cluster=cluster,same_direction_cluster_ratio=None,account_age_days=c['account_age_days'] if mode=='RETROSPECTIVE' else None,profile_features=c['profile_features'] if mode=='RETROSPECTIVE' else None)
        rows.append(r)
    return rows


def attach_cluster_directions(features,predictions):
    for f in features:
        labels=[predictions[j-1]['direction']['label'] for j in f['cluster_members'] if j<=len(predictions) and predictions[j-1]['status']=='SUCCESS']
        ratio=Counter(labels).most_common(1)[0][1]/len(labels) if labels else None
        f['same_direction_cluster_ratio']=ratio
        if f.get('cluster'): f['cluster']['direction_homogeneity']=ratio


def fuse(jev_probability,features,weights):
    similarity=features.get('text_similarity_max')
    components={'jev':jev_probability,'similarity':similarity if features['duplicate_cluster_size']>1 else 0.0 if similarity is not None else None,'burst':min(1,max(0,features['burst_zscore'])/5) if features.get('burst_zscore') is not None else None,'template':features.get('template_reuse_ratio'),'author':min(1,max(0,features['author_comment_count_1h']-1)/10) if features.get('author_comment_count_1h') is not None else None}
    available=sum(weights[k] for k,v in components.items() if v is not None)
    score=sum(weights[k]*v for k,v in components.items() if v is not None)/available if available else None
    return score,available,components
