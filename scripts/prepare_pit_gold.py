"""Prepare blind human annotation packs against the frozen PIT baseline; no API."""
import argparse
import hashlib
import html
import json
import random
from collections import Counter
from functools import lru_cache
from pathlib import Path
from core.coordination.context import SocialContextAdapter
from core.coordination.features import extract_features
from scripts.corpus_pit_check import load_package
from scripts.jev_judge_v2 import features as retrospective_features
import scripts.jev_judge_v2 as legacy

BASELINE='12439cdab9f83c68b2586e59af9890db792aea13'
LABELS={'COORDINATION_PIT':['NO_COORDINATION_EVIDENCE','SUSPECTED_COORDINATED','INSUFFICIENT_EVIDENCE'], 'DIRECTION':['BULLISH','BEARISH','NEUTRAL','UNCLEAR','NOT_APPLICABLE']}


def exact_dev_groups(rows, target, rng):
    groups={}
    for r in rows:groups.setdefault(r['partition_group'],[]).append(r)
    keys=sorted(groups);rng.shuffle(keys);reachable={0:[]}
    for key in keys:
        for n,chosen in list(reachable.items())[::-1]:
            total=n+len(groups[key])
            if total<=target and total not in reachable:reachable[total]=chosen+[key]
    if target not in reachable:raise ValueError('Exact development size incompatible with near-duplicate groups')
    return set(reachable[target])


def write_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def write_page(path, rows, task):
    # HTML is local only. Escaping '<' prevents closing the JSON script block.
    payload=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    title=html.escape(task)
    guide=('NO_COORDINATION_EVIDENCE：已有足够观测但未见协同证据；SUSPECTED_COORDINATED：多项行为证据支持疑似协调；INSUFFICIENT_EVIDENCE：证据不足或冲突。常见金融词、简短或负面表达不能单独证明协同。' if task=='COORDINATION_PIT' else 'BULLISH：明确看涨；BEARISH：明确看跌；NEUTRAL：明确横盘或平衡；UNCLEAR：方向歧义、疑问或期限冲突；NOT_APPLICABLE：没有目标证券价格立场。')
    template='''<!doctype html><meta charset="utf-8"><title>Human Gold</title>
<style>body{font:16px system-ui;margin:30px auto;max-width:1000px;background:#f5f6f8}article{background:white;padding:22px;border-radius:12px}pre{white-space:pre-wrap;word-break:break-word}button,select,input,textarea{padding:10px;margin:5px}textarea{width:90%;height:90px}.warning{color:#8a4b00}details{margin:12px}</style>
<h1>__TITLE__ 人工盲标</h1><p class="warning">无模型预测，无预填 Gold。先完成开发集；冻结集仅供独立人工标注，不用于调参。双人标注员不要交换答案。</p>
<p>__GUIDE__</p><label>标注员（真实标识）<input id="who" placeholder="annotator_A"></label><select id="split"><option>DEVELOPMENT</option><option>FROZEN</option></select><button id="export">导出本人 JSONL</button><input id="import" type="file" accept=".jsonl"><p>保存于当前页面；刷新前请导出。导入只能恢复同一标注员的结果。</p><p id="progress"></p><button id="prev">上一条</button><button id="next">下一条</button><article id="card"></article>
<script id="data" type="application/json">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent), labels=__LABELS__;
let index=0, answers={};const el=id=>document.getElementById(id);
const esc=s=>String(s??'未知').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function visible(){return rows.filter(r=>r.split===el('split').value)}
function key(r){return el('who').value.trim()+':'+r.sample_id}
function render(){const list=visible();index=Math.max(0,Math.min(index,list.length-1));const r=list[index];if(!r){el('card').textContent='空集合';return}
 const a=answers[key(r)]||{};el('progress').textContent=`${index+1}/${list.length}；本人已完成 ${rows.filter(x=>answers[key(x)]?.annotation_status==='COMPLETED').length}/${rows.length}`;
 el('card').innerHTML=`<h2>${esc(r.platform)} · ${esc(r.split)}</h2><p>样本 ${esc(r.sample_id)}；双人子集：${r.double_annotation?'是':'否'}</p><p>截止可用时间：${esc(r.available_at)}</p><p>目标标的：${esc(r.target_stock_code)} ${esc(r.target_stock_name)}；绑定关系：${esc(JSON.stringify(r.securities))}</p><pre>${esc(r.text)}</pre>`+
 (r.task==='COORDINATION_PIT'?`<details open><summary>截至当时的证据（未展示未来记录）</summary><pre>${esc(JSON.stringify(r.features,null,2))}</pre>${r.visible_cluster.map(c=>`<p>${esc(c.available_at)} · 作者 ${esc(c.author)}<br>${esc(c.text)}</p>`).join('')}</details>`:'<p>只标评论者对目标证券的价格／回报立场。纯事实或公告不自动看多；方向问题、歧义或冲突期限不算中性。多标的无法归属时记录歧义。</p>')+
 `<select id="label"><option value="">选择标签</option>${labels.map(l=>`<option ${a.label===l?'selected':''}>${l}</option>`).join('')}</select><textarea id="reason" placeholder="判断依据／歧义／证据缺口">${esc(a.rationale||'')}</textarea><button id="save">保存为人工完成</button>`;
 el('save').onclick=()=>{const who=el('who').value.trim(), label=el('label').value, rationale=el('reason').value.trim();if(!who||!label||!rationale){alert('请填写标注员、标签和依据');return}answers[key(r)]={sample_id:r.sample_id,text_sha256:r.text_sha256,task:r.task,split:r.split,label,rationale,annotator:who,annotation_status:'COMPLETED'};render()}}
el('split').onchange=()=>{index=0;render()};el('who').onchange=render;
el('next').onclick=()=>{index++;render()};el('prev').onclick=()=>{index--;render()};
el('export').onclick=()=>{const who=el('who').value.trim();if(!who){alert('先填标注员');return}const data=rows.map(r=>answers[key(r)]).filter(Boolean).map(r=>JSON.stringify(r)).join('\\n')+'\\n';const u=URL.createObjectURL(new Blob([data],{type:'application/x-ndjson'}));const a=document.createElement('a');a.href=u;a.download='annotations_'+who.replace(/[^a-zA-Z0-9_-]/g,'_')+'.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
el('import').onchange=async e=>{try{const who=el('who').value.trim();if(!who)throw Error('先填标注员');const incoming=(await e.target.files[0].text()).trim().split(/\\r?\\n/).filter(Boolean).map(JSON.parse);for(const a of incoming){const r=rows.find(x=>x.sample_id===a.sample_id);if(!r||a.annotator!==who||a.text_sha256!==r.text_sha256||!labels.includes(a.label))throw Error('样本或标注员不匹配')}for(const a of incoming)answers[who+':'+a.sample_id]=a;render()}catch(err){alert(err.message)}};render();
</script>'''
    path.write_text(template.replace('__TITLE__',title).replace('__DATA__',payload).replace('__LABELS__',json.dumps(LABELS[task])).replace('__GUIDE__',html.escape(guide)))


def prepare(package, output):
    out=Path(output)
    if out.exists():raise ValueError('Preserve existing Gold; choose a new output directory')
    manifest,records=load_package(package);adapter=SocialContextAdapter();contexts=[adapter.adapt(r) for r in records]
    cfg={'coordination_mode':'PIT_CAUSAL','similarity_threshold':.9,'burst_window_minutes':15}
    # Memoize the exact ordered SequenceMatcher inputs; no altered similarity semantics.
    original=legacy.SequenceMatcher
    @lru_cache(maxsize=400000)
    def similarity(a,b):return original(None,a,b,autojunk=False).ratio()
    class CachedMatcher:
        def __init__(self, junk,a,b,autojunk=False):self.a=a;self.b=b
        def ratio(self):return similarity(self.a,self.b)
    try:
        legacy.SequenceMatcher=CachedMatcher
        fs=extract_features(records,cfg)
        groups=retrospective_features([adapter.legacy_view(c) for c in contexts],cfg)
    finally:legacy.SequenceMatcher=original
    if any(f['pit_state']!='PASS' for f in fs):raise ValueError('Gold requires all records PIT-valid')
    rng=random.Random(42);source=manifest['sha256']
    def row(i,task,stratum):
        c=contexts[i];r=records[i];text=c['text'];sample=hashlib.sha256((source+':'+task+':'+c['record_id']).encode()).hexdigest()
        result={'sample_id':sample,'task':task,'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'platform':c['platform'],'available_at':c['available_at'],'target_stock_code':r.get('stock_code'),'target_stock_name':r.get('stock_name'),'securities':r.get('securities',[]),'selection_stratum':stratum,'partition_group':str(groups[i]['cluster_id']),'gold_label':None,'annotator':None,'annotation_status':'PENDING','double_annotation':False}
        if task=='COORDINATION_PIT':
            result['features']={k:fs[i].get(k) for k in ('duplicate_cluster_size','template_reuse_ratio','burst_window_count','burst_zscore','author_comment_count_1h','author_comment_count_24h','cross_account_similarity','missing_features','temporal_clock')}
            result['visible_cluster']=[]
            for j1 in fs[i]['cluster_members']:
                x=contexts[j1-1]
                if x['available_timestamp']>c['available_timestamp']:raise ValueError('Future context leakage')
                result['visible_cluster'].append({'text':x['text'],'available_at':x['available_at'],'author':hashlib.sha256(x['stable_author_key'].encode()).hexdigest()[:16] if x['stable_author_key'] else None})
        return result
    ranked=sorted(range(len(records)),key=lambda i:(-(max(0,fs[i]['duplicate_cluster_size']-1)+max(0,fs[i].get('burst_zscore') or 0)+(fs[i].get('template_reuse_ratio') or 0)),i))
    high=ranked[:100];rest=[i for i in range(len(records)) if i not in high];rng.shuffle(rest)
    coord=[row(i,'COORDINATION_PIT','HIGH_SIGNAL_CANDIDATE' if i in high else 'RANDOM') for i in high+rest[:100]]
    dev=exact_dev_groups(coord,50,rng)
    for r in coord:r['split']='DEVELOPMENT' if r['partition_group'] in dev else 'FROZEN'
    direction=[]
    for platform,n in (('eastmoney',180),('taoguba',100),('xueqiu',20)):
        pool=[i for i,c in enumerate(contexts) if c['platform']==platform];rng.shuffle(pool)
        if len(pool)<n:raise ValueError('Insufficient platform sample')
        platform_rows=[row(i,'DIRECTION','PLATFORM_RANDOM') for i in pool[:n]]
        dev=exact_dev_groups(platform_rows,round(n*.3),rng)
        for r in platform_rows:r['split']='DEVELOPMENT' if r['partition_group'] in dev else 'FROZEN'
        direction.extend(platform_rows)
    out.mkdir(parents=True)
    summary={'baseline_commit':BASELINE,'source_record_count':len(records),'seed':42,'api_calls':0,'human_completed':0,'calibration_state':'BLOCKED_PENDING_HUMAN_DEV','frozen_evaluation_state':'NOT_STARTED','promotion_state':'RESEARCH_ONLY','tasks':{}}
    for task,rows in (('COORDINATION_PIT',coord),('DIRECTION',direction)):
        frozen=[r for r in rows if r['split']=='FROZEN'];rng.shuffle(frozen)
        for r in frozen[:50]:r['double_annotation']=True
        task_dir=out/task.lower();task_dir.mkdir()
        (task_dir/'gold.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        write_page(task_dir/'annotate.html',rows,task)
        summary['tasks'][task]={'n':len(rows),'split_counts':dict(Counter(r['split'] for r in rows)),'platform_counts':dict(Counter(r['platform'] for r in rows)),'selection_counts':dict(Counter(r['selection_stratum'] for r in rows)),'double_annotation_count':50,'labels':LABELS[task]}
    write_json(out/'manifest.json',dict(summary,source_sha256=source,contract_name=manifest['contract_name'],contract_version=manifest['contract_version'],producer=manifest['producer']))
    write_json(out/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',required=True);p.add_argument('--output-dir',required=True);args=p.parse_args()
    print(json.dumps(prepare(args.package,args.output_dir),ensure_ascii=False))


if __name__=='__main__':main()
