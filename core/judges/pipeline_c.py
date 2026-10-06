"""Evidence-validated atomic-unit direction gate; never promote board context."""
from .base import JudgeContext


def validate_unit(unit, comment_text, target_code):
    evidence = unit.get('evidence') or {}
    quote, start, end = evidence.get('quote'), evidence.get('start'), evidence.get('end')
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(comment_text) or comment_text[start:end] != quote:
        return 'REVIEW_INVALID_EVIDENCE'
    code = str(unit.get('subject_code', '')).split('.')[0]
    relation = unit.get('subject_relation', 'UNKNOWN')
    if relation == 'EXTERNAL' or code != str(target_code).split('.')[0]:
        return 'EXTERNAL_NO_TARGET_DIRECTION'
    if relation not in ('PRIMARY_SUBJECT', 'PRIMARY'):
        return 'REVIEW_SUBJECT_RELATION'
    return 'PASS'


async def judge_units(judge, record, context: JudgeContext):
    results = []
    for unit in record.get('atomic_units', []):
        gate = validate_unit(unit, record['text'], context.stock_code)
        row = {'unit_id': unit.get('unit_id'), 'gate': gate, 'subject_relation': unit.get('subject_relation'), 'direction': None}
        if gate == 'PASS':
            # Do not inject model-generated stance/action into the judge's evidence text.
            direction = await judge.judge_direction({'text': record['text'], 'evidence': unit['evidence'], 'granularity': 'VALIDATED_ATOMIC_UNIT', 'subject_relation': unit['subject_relation']}, context)
            row['direction'] = direction.model_dump()
        results.append(row)
    return results
