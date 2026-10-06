"""EquityCrawler/legacy adapter. Never infer availability from event time."""
import hashlib
from datetime import datetime, timezone
import math


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.timestamp() if d.tzinfo else None
    except (TypeError, ValueError):
        return None


class SocialContextAdapter:
    def adapt(self, record):
        content, source, pit, obs = (record.get(k) or {} for k in ('content', 'source', 'pit', 'observation'))
        pit = record.get('point_in_time') or pit
        platform = source.get('platform') or record.get('platform') or 'UNKNOWN'
        author = content.get('author_id_hash') or record.get('author_id_hash') or record.get('user_id') or record.get('uid') or record.get('author_id')
        text = content.get('text') or record.get('text') or record.get('comment') or ''
        event = next((obj[key] for obj, key in ((pit, 'published_at'), (content, 'published_at'), (record, 'published_at'), (record, 'create_time'), (record, 'event_time')) if key in obj), None)
        available = pit.get('available_at') or record.get('available_at')
        observed = obs.get('observed_at') or obs.get('observation_at')
        rid = record.get('record_id') or record.get('cid') or hashlib.sha256((platform+':'+text+':'+str(event)).encode()).hexdigest()
        links = record.get('security_links') or record.get('securities') or []
        relation = record.get('subject_relation')
        if relation is None and len(links)==1:
            relation = links[0].get('subject_relation') or links[0].get('relation_type') or links[0].get('relation')
        hash_key = content.get('author_hash_key_id') or record.get('author_hash_key_id') or 'UNSPECIFIED'
        return {'stable_author_key': record.get('stable_author_key') or (f'{platform}:{hash_key}:{author}' if author is not None else None), 'publication_time_state': 'UNKNOWN' if event is None else 'KNOWN' if timestamp(event) is not None else 'INVALID', 'event_time': event, 'event_timestamp': timestamp(event), 'available_at': available, 'available_timestamp': timestamp(available), 'observation_at': observed, 'observation_timestamp': timestamp(observed), 'like_count': obs.get('like_count', record.get('like_count', record.get('digg_count'))), 'reply_count': obs.get('reply_count', record.get('reply_count')), 'platform':platform, 'record_id':str(rid), 'subject_relation':relation or 'UNKNOWN', 'text':text, 'title':content.get('title') or record.get('title'), 'account_age_days':record.get('account_age_days'), 'profile_features':record.get('profile_features')}

    def legacy_view(self, context, cutoff=None):
        observed = context['observation_timestamp']
        visible = cutoff is None or observed is not None and observed<=cutoff
        clock = context['available_timestamp'] if cutoff is not None else context['event_timestamp']
        event = datetime.fromtimestamp(clock, timezone.utc).isoformat() if clock is not None else None
        return {'text':context['text'], 'platform':context['platform'], 'cid':context['record_id'], 'author_id':context['stable_author_key'], 'create_time':event, 'digg_count':context['like_count'] if visible else None, 'reply_count':context['reply_count'] if visible else None, 'account_age_days':context['account_age_days'] if cutoff is None else None, 'profile_features':context['profile_features'] if cutoff is None else None}


def require_asdc_context(features):
    if features.get('coordination_mode')!='PIT_CAUSAL' or features.get('pit_state')!='PASS':
        raise ValueError('ASDC requires validated PIT_CAUSAL coordination features')
