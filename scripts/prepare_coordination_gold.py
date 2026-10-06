"""Prepare high-signal/random human candidates without model-labelled Gold."""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from core.coordination.features import extract_features
from scripts.jev_benchmark import jsonl
from scripts.jev_pilot import dump


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output-dir',default='local/coordination_gold_200');args=p.parse_args()
    data=json.loads(Path(args.input).read_text());comments=data['comments'];cfg=json.loads(Path('configs/jev_321.json').read_text());fs=extract_features(comments,cfg);out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    target=out/'gold.jsonl'
    if target.exists():raise ValueError('Preserving existing annotation file; choose a new directory')
    ranked=sorted(range(len(comments)),key=lambda i:(-(max(0,fs[i]['duplicate_cluster_size']-1)+max(0,fs[i].get('burst_zscore') or 0)+fs[i]['template_reuse_ratio']),i))
    high=ranked[:min(100,len(comments))];rest=[i for i in range(len(comments)) if i not in high];rng=random.Random(42);rng.shuffle(rest);selected=high+rest[:min(100,len(rest))]
    group_key=lambda i:(comments[i].get('platform'),fs[i]['cluster_id'])
    group_sizes=Counter(group_key(i) for i in selected);groups=list(group_sizes);rng.shuffle(groups);dev=set();n=0
    for g in groups:
        if n+group_sizes[g]<=50:dev.add(g);n+=group_sizes[g]
    source_hash=hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
    rows=[]
    for i in selected:
        text=comments[i].get('text') or comments[i].get('comment') or ''
        rows.append({'sample_id':hashlib.sha256((source_hash+':'+str(i)).encode()).hexdigest(),'index':i+1,'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'platform':comments[i].get('platform'),'features':fs[i],'selection_stratum':'HIGH_SIGNAL_CANDIDATE' if i in high else 'RANDOM','split':'DEVELOPMENT' if group_key(i) in dev else 'FROZEN','gold_coordination':None,'annotator':None,'annotation_status':'PENDING'})
    jsonl(target,rows);dump(out/'manifest.json',{'n':len(rows),'source_sha256':source_hash,'split_counts':dict(Counter(r['split'] for r in rows)),'selection_counts':dict(Counter(r['selection_stratum'] for r in rows)),'human_completed':0,'seed':42,'coordination_mode':'RETROSPECTIVE','note':'Selection ranks evidence, not Gold. Same near-duplicate group never crosses splits. This deliberately selected sample is not representative prevalence.'})
    print('Prepared',len(rows),'pending human annotations')


if __name__=='__main__':main()
