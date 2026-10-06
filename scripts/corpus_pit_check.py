"""Offline PIT integration check for frozen equity-social-corpus packages."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from core.coordination.features import extract_features
from core.coordination.context import SocialContextAdapter


def load_package(directory):
    root=Path(directory)
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('contract_name')!='equity-social-corpus' or manifest.get('contract_version')!='1.0.0':
        raise ValueError('Unsupported corpus contract')
    target=Path(manifest['target_file'])
    if target.name!=str(target):raise ValueError('Package target must be a basename')
    raw=(root/target).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Corpus hash mismatch')
    records=[json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(records)!=manifest['record_count']:raise ValueError('Corpus count mismatch')
    if len({r['record_id'] for r in records})!=len(records):raise ValueError('Duplicate corpus identity')
    return manifest,records


def check_package(directory):
    manifest,records=load_package(directory)
    contexts=[SocialContextAdapter().adapt(r) for r in records]
    states=Counter('PASS' if c['available_timestamp'] is not None and c['publication_time_state']!='INVALID' and (c['event_timestamp'] is None or c['event_timestamp']<=c['available_timestamp']) else 'FAIL_MISSING_OR_INVALID_TIME' for c in contexts)
    sample=[]
    for platform in sorted({r['platform'] for r in records}):
        sample.extend([r for r in records if r['platform']==platform][:10])
    cfg={'coordination_mode':'PIT_CAUSAL','similarity_threshold':.9,'burst_window_minutes':15}
    features=extract_features(sample,cfg)
    ordered=sorted(sample,key=lambda r: SocialContextAdapter().adapt(r)['available_timestamp'] or float('inf'))
    split=max(1,len(ordered)//2)
    invariant=extract_features(ordered[:split],cfg)==extract_features(ordered,cfg)[:split]
    return {'software_version':'3.2.2','contract_name':manifest['contract_name'],'contract_version':manifest['contract_version'],'producer':manifest['producer'],'record_count':len(records),'platform_counts':dict(Counter(r['platform'] for r in records)), 'pit_states':dict(states),'publication_states':dict(Counter(c['publication_time_state'] for c in contexts)),'feature_sample_count':len(sample),'feature_sample_pit_states':dict(Counter(f['pit_state'] for f in features)),'future_append_invariant':invariant,'input_maturity':'CORPUS_PIT_VALIDATED' if records and states['PASS']==len(records) and invariant and all(f['pit_state']=='PASS' for f in features) else 'CORPUS_PIT_CAPABLE','validation_scope':'PACKAGE_INTEGRITY_AND_TEMPORAL_FEATURES_ONLY','temporal_clock':'available_at','api_calls':0,'human_completed':0,'promotion_state':'RESEARCH_ONLY','annotation_status':'PENDING_HUMAN_ANNOTATION','semantic_accuracy_validated':False,'investment_signal_ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=check_package(args.package)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
