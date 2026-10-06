"""Portable contract regression; synthetic text, genuine exported contract shape."""
import hashlib
import json
import pytest
from scripts.corpus_pit_check import check_package, load_package


def package(tmp_path):
    records=[{'record_id':'fixture-1','platform':'eastmoney','content':{'text':'测试文本','author_id_hash':'fixture-author','author_hash_key_id':'fixture-v1'},'point_in_time':{'published_at':None,'available_at':'2026-10-06T10:00:00+08:00'},'observation':{'observed_at':'2026-10-06T10:00:00+08:00','like_count':1}}]
    raw=(json.dumps(records[0])+'\n').encode()
    (tmp_path/'mental_input.jsonl').write_bytes(raw)
    manifest={'contract_name':'equity-social-corpus','contract_version':'1.0.0','producer':{'name':'EquityCrawler','version':'0.2.3.1'},'target_file':'mental_input.jsonl','sha256':hashlib.sha256(raw).hexdigest(),'record_count':1}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    return tmp_path


def test_contract_unknown_publication_and_zero_api(tmp_path):
    result=check_package(package(tmp_path))
    assert result['pit_states']=={'PASS':1}
    assert result['publication_states']=={'UNKNOWN':1}
    assert result['input_maturity']=='CORPUS_PIT_VALIDATED'
    assert result['api_calls']==0 and result['human_completed']==0


def test_package_integrity_fails_closed(tmp_path):
    package(tmp_path)
    with (tmp_path/'mental_input.jsonl').open('a') as f:f.write('{}\n')
    with pytest.raises(ValueError,match='hash mismatch'):load_package(tmp_path)
