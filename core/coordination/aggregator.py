"""Use explicit Choice masses, not 1 minus a binary coordination estimate."""
def weighted(rows, key):
    denominator = sum(r['coordination']['probabilities'][key] for r in rows)
    return {'score': sum(r['coordination']['probabilities'][key] * r['direction']['directional_score'] for r in rows) / denominator if denominator else None, 'weight_sum': denominator, 'n': len(rows)}


def aggregate(rows, minimum_effective_weight=10):
    relevant = [r for r in rows if r['status'] == 'SUCCESS' and r['direction']['relevant_probability'] >= .5]
    organic = weighted(relevant, 'ORGANIC')
    coordinated = weighted(relevant, 'SUSPECTED_COORDINATED')
    raw = coordinated['score'] - organic['score'] if coordinated['score'] is not None and organic['score'] is not None else None
    enough = min(organic['weight_sum'], coordinated['weight_sum']) >= minimum_effective_weight
    return {'relevant': len(relevant), 'organic_probability_weighted': organic, 'coordinated_probability_weighted': coordinated, 'divergence': raw if enough else None, 'divergence_state': 'EXPERIMENTAL' if enough else 'INSUFFICIENT_WEIGHT', 'raw_difference_diagnostic': raw, 'note': 'Choice masses are uncalibrated. Heuristic fusion score is separate and not a calibrated probability. No account authenticity or investment-return assertion.'}
