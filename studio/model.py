"""Document-independent question model and version fingerprints."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


class CheckState(StrEnum):
    UNTESTED = 'untested'
    RUNNING = 'running'
    PASSED = 'passed'
    HELD = 'held'
    FAILED = 'failed'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identity():
    return uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def checksum(value):
    data = value if isinstance(value, bytes) else encode(value).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def body_fingerprint(body):
    return checksum({key:body.get(key) for key in ('blocks','choices','answer_format')})


def paragraphs(blocks):
    for item in blocks:
        yield item
        for child in paragraphs(item.get('blocks', [])):
            yield child
        for row in item.get('rows', []):
            for cell in row:
                yield from paragraphs(cell.get('blocks', []))


def plain_text(blocks):
    pieces = []
    for b in blocks:
        match b['kind']:
            case 'text': pieces.append(b['value'])
            case 'math': pieces.append('$'+b['latex']+'$')
            case 'paragraph': pieces.append(plain_text(b['blocks'])+'\n')
            case 'table': pieces.append('\n'.join(' | '.join(plain_text(c['blocks']) for c in row) for row in b['rows'])+'\n')
            case 'box' | 'note': pieces.append(plain_text(b['blocks'])+'\n')
    return ''.join(pieces)


def available(question):
    answer = question.get('answer') or {}
    proof = answer.get('proof') or {}
    return (question['input_state']=='complete' and not question.get('text_review',{}).get('blocking') and not question.get('source',{}).get('answer_ambiguity') and answer.get('verification')=='passed'
            and proof.get('body_fingerprint')==question['fingerprint']
            and bool(answer.get('final_answer')) and bool(answer.get('steps')))


def difficulty_band(value):
    return '하' if value <= 4 else '중' if value <= 7 else '상'


def question_difficulty(question):
    c=question.get('classification',{});a=c.get('difficulty_assessment',{})
    if question.get('source',{}).get('boundary_review'):return None
    if c.get('certainty')!='user_confirmed' and a.get('state') in ('unknown','pending_boundary'):return None
    return question['difficulty']


def difficulty_label(question):
    value=question_difficulty(question)
    if value is None:return '난이도 미분류'
    origin='교사 지정' if question['classification'].get('certainty')=='user_confirmed' else '추정'
    return f'{difficulty_band(value)} · {value}/10 · {origin}'


def difficulty_counts(questions):
    counts={key:0 for key in ('하','중','상','미분류')}
    for q in questions:
        score=question_difficulty(q)
        counts['미분류' if score is None else difficulty_band(score)]+=1
    return counts
