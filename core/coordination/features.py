"""Extend preserved v2 sample features with fixed-window author metrics."""
import math
from scripts.jev_judge_v2 import features as legacy_features, stamp


def extract_features(comments, config):
    rows = legacy_features(comments, config)
    times = [stamp(c.get('create_time')) for c in comments]
    authors = [c.get('user_id') or c.get('uid') or c.get('author_id') for c in comments]
    for i, r in enumerate(rows):
        peers = [j for j, c in enumerate(comments) if c.get('platform') == comments[i].get('platform')]
        for hours in (1, 24):
            r[f'author_comment_count_{hours}h'] = sum(
                authors[j] is not None and str(authors[j]) == str(authors[i])
                and times[j] is not None and 0 <= times[i] - times[j] <= hours * 3600
                for j in peers
            ) if authors[i] is not None and times[i] is not None else None
        r['template_reuse_ratio'] = max(0, r['template_reuse_count'] - 1) / max(1, len(peers) - 1)
        known = [times[j] for j in peers if times[j] is not None]
        span = max(known) - min(known) if len(known) > 1 else 0
        expected = len(known) * config['burst_window_minutes'] * 60 / span if span > config['burst_window_minutes'] * 60 else None
        r['burst_zscore'] = (r['burst_window_count'] - expected) / math.sqrt(expected) if expected and r['burst_window_count'] is not None else None
        # Post-direction diagnostics only; never fed back into the current judge.
        r['same_direction_cluster_ratio'] = None
        r['account_age_days'] = comments[i].get('account_age_days')
        r['profile_features'] = comments[i].get('profile_features')
    return rows


def fuse(jev_probability, features, weights):
    similarity = features.get('text_similarity_max')
    components = {
        'jev': jev_probability,
        'similarity': similarity if features['duplicate_cluster_size'] > 1 else 0.0 if similarity is not None else None,
        'burst': min(1, max(0, features['burst_zscore']) / 5) if features.get('burst_zscore') is not None else None,
        'template': features.get('template_reuse_ratio'),
        'author': min(1, max(0, features['author_comment_count_1h'] - 1) / 10) if features.get('author_comment_count_1h') is not None else None,
    }
    available = sum(weights[k] for k, value in components.items() if value is not None)
    score = sum(weights[k] * value for k, value in components.items() if value is not None) / available if available else None
    return score, available, components
