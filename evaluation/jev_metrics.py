"""Closed-set confusion, class support, multiclass Brier and top-label ECE."""
import math
import random


def metrics(pairs, labels, bins=10):
    if not pairs:
        return {'state': 'PENDING_HUMAN_GOLD', 'n': 0, 'macro_f1': None, 'brier': None, 'ece': None, 'per_class': {k: {'support': 0, 'precision': None, 'recall': None, 'f1': None} for k in labels}, 'confusion': None}
    confusion = {a: {b: 0 for b in labels} for a in labels}
    buckets = [[] for _ in range(bins)]; brier = 0
    for gold, predicted, probabilities in pairs:
        if gold not in labels or predicted not in labels or set(probabilities) != set(labels): raise ValueError('Unknown evaluation label')
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities.values()) or abs(sum(probabilities.values())-1)>.02: raise ValueError('Invalid evaluation probabilities')
        confusion[gold][predicted] += 1
        confidence = probabilities[predicted]
        buckets[min(bins-1, int(confidence*bins))].append((confidence, gold == predicted))
        brier += sum((probabilities[k] - int(k == gold))**2 for k in labels)
    classes = {}
    for k in labels:
        tp = confusion[k][k]; support = sum(confusion[k].values()); predicted_n = sum(confusion[g][k] for g in labels)
        precision = tp/predicted_n if predicted_n else None
        recall = tp/support if support else None
        f1 = 2*tp/(support+predicted_n) if support+predicted_n else None
        classes[k] = {'support': support, 'predicted': predicted_n, 'precision': precision, 'recall': recall, 'f1': f1}
    ece = sum(len(b)/len(pairs)*abs(sum(x[0] for x in b)/len(b)-sum(x[1] for x in b)/len(b)) for b in buckets if b)
    supported = [v['f1'] or 0 for v in classes.values() if v['support']]
    return {'state': 'PARTIAL_GOLD' if any(not v['support'] for v in classes.values()) else 'MEASURED', 'n': len(pairs), 'macro_f1': sum(supported)/len(supported), 'macro_f1_denominator': 'classes with human support', 'brier': brier/len(pairs), 'brier_definition': 'mean sum squared error over all classes (0..2)', 'ece': ece, 'ece_definition': '10 equal-width bins; provider winner-label confidence', 'per_class': classes, 'confusion': confusion}


def bootstrap95(pairs, labels, iterations=1000, seed=42):
    if len(pairs) < 2:
        return {'state': 'INSUFFICIENT_HUMAN_GOLD', 'macro_f1': None, 'brier': None, 'ece': None}
    rng = random.Random(seed)
    strata = {label: [p for p in pairs if p[0] == label] for label in labels}
    samples = {k: [] for k in ('macro_f1', 'brier', 'ece')}
    for _ in range(iterations):
        resampled = [rng.choice(group) for group in strata.values() for _ in range(len(group))]
        result = metrics(resampled, labels)
        for k in samples:
            samples[k].append(result[k])
    intervals = {}
    for k, values in samples.items():
        values.sort()
        intervals[k] = [values[int((iterations-1)*.025)], values[int((iterations-1)*.975)]]
    return {'state': 'EXPERIMENTAL_INTERVAL', 'iterations': iterations, 'seed': seed, 'method': 'human-class-stratified percentile bootstrap; conditional on observed class supports', **intervals}
