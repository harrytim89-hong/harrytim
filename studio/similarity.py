"""Explainable local retrieval. Scores rank candidates, not mathematical equivalence."""
from __future__ import annotations
import json
import re
import unicodedata
from threading import RLock
from collections import Counter
from .model import checksum, plain_text


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(value))).strip()


def canonical(blocks, store):
    result = []
    for block in blocks:
        kind = block['kind']
        if kind == 'text':
            value = normalized(block['value'])
            if not value:
                continue
            # Run boundaries reflect formatting, not question content.
            if result and result[-1][0] == 'text':
                result[-1][1] = normalized(result[-1][1] + ' ' + value)
                continue
            item = [kind, value]
        elif kind == 'math':
            item = [kind, block['ast']]
        elif kind == 'image':
            try:
                digest = checksum(store.path(block['path']).read_bytes())
            except (OSError, ValueError, KeyError):
                # Unreadable pictures must never establish an exact match.
                raise ValueError('그림 원본을 읽을 수 없습니다.')
            item = [kind, digest]
        elif kind == 'table':
            item = [kind, [[[
                cell.get('rowspan', 1), cell.get('colspan', 1),
                canonical(cell.get('blocks', []), store)
            ] for cell in row] for row in block['rows']]]
        elif 'blocks' in block:
            item = [kind, canonical(block['blocks'], store)]
        else:
            item = [kind, block]
        result.append(item)
    return result


def features(q, store):
    body = q['body']
    text = normalized(plain_text(body['blocks']) + '\n' + '\n'.join(
        plain_text(c) for c in body.get('choices', [])))
    # Retain operators and variable names. Only numeric values are masked.
    shape = re.sub(r'\d+(?:\.\d+)?', '#', text)
    grams = Counter(shape[i:i+3] for i in range(max(0, len(shape)-2)))
    stem = re.sub(r'\d+(?:\.\d+)?', '#', plain_text(body['blocks']))
    stem = re.sub(r'[\s{}]', '', stem)
    stem_grams = Counter(stem[i:i+3] for i in range(max(0,len(stem)-2)))
    try:
        signature = checksum([body.get('answer_format'), canonical(body['blocks'], store),
                              [canonical(c, store) for c in body.get('choices', [])]])
    except ValueError:
        signature = None
    return {'signature': signature, 'text': text, 'shape': shape, 'grams': grams, 'stem_grams':stem_grams}


class SimilarityIndex:
    def __init__(self, store):
        self.store = store
        self.cache = {}
        self.lock = RLock()

    def search(self, question_id, limit=30):
        with self.lock:
            return self._search(question_id, limit)

    def _search(self, question_id, limit):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('검색 결과 수는 1~100이어야 합니다.')
        rows = self.store.rows('''SELECT q.id,q.revision,v.fingerprint,v.body,v.classification,v.source,l.parent_id
            FROM questions q JOIN versions v ON v.question_id=q.id AND v.revision=q.revision
            LEFT JOIN documents d ON q.document_id=d.id
            LEFT JOIN lineage l ON q.id=l.child_id
            WHERE q.trashed=0 AND (d.id IS NULL OR d.trashed=0) ORDER BY q.created,q.rowid''')
        active = {q['id'] for q in rows}
        self.cache = {key: value for key, value in self.cache.items() if key in active}
        questions = {}
        for row in rows:
            if json.loads(row['source']).get('boundary_review'):
                self.cache.pop(row['id'], None)
                continue
            cached = self.cache.get(row['id'])
            if not cached or cached['revision'] != row['revision']:
                q = {**row, 'body': json.loads(row['body']),
                     'classification': json.loads(row['classification'])}
                cached = {**features(q, self.store), 'revision': row['revision'],
                          'classification': q['classification'], 'parent_id':row['parent_id']}
                self.cache[row['id']] = cached
            questions[row['id']] = cached
        if question_id not in questions:
            raise ValueError('검색할 문항이 없거나 분리 대기 중입니다.')
        source = questions[question_id]
        matches = []
        for qid, other in questions.items():
            if qid == question_id:
                continue
            intersection = sum((source['grams'] & other['grams']).values())
            union = sum((source['grams'] | other['grams']).values())
            overlap = intersection / union if union else 0
            stem_intersection=sum((source['stem_grams'] & other['stem_grams']).values())
            stem_union=sum((source['stem_grams'] | other['stem_grams']).values())
            overlap=max(overlap,stem_intersection/stem_union if stem_union else 0)
            linked=(other['parent_id']==question_id or source['parent_id']==qid or
                    bool(source['parent_id'] and source['parent_id']==other['parent_id']))
            reasons = []
            if source['signature'] and source['signature'] == other['signature']:
                kind, score = 'exact', 100
                reasons = ['본문·수식 구조·보기 순서·그림 내용 일치']
            else:
                if overlap < .24 and not linked:
                    continue
                score = overlap * 70
                for key, label, weight in [('unit', '단원', 10), ('subunit', '세부단원', 8), ('type', '유형', 7)]:
                    a, b = source['classification'].get(key), other['classification'].get(key)
                    if a and a not in ('미분류', '미상') and a == b:
                        score += weight
                        reasons.append(label + ' 일치')
                kind = 'template' if source['shape'] == other['shape'] and len(source['shape']) >= 12 else 'related'
                reasons.insert(0, '수치를 제외한 본문·수식 표현 일치' if kind == 'template' else '본문·수식 표현 유사')
                if kind == 'template':
                    score = max(score, 90)
                if linked:
                    score = max(score,80)
                    reasons.append('같은 원본에서 연결된 변형 문항')
                if score < 35:
                    continue
                score = min(99, round(score))
            matches.append({'id': qid, 'revision': other['revision'], 'kind': kind,
                            'score': score, 'reasons': reasons})
        matches.sort(key=lambda m: (m['kind'] != 'exact', -m['score'], m['id']))
        return {'question_id': question_id, 'revision': source['revision'],
                'total': len(matches), 'exact_count': sum(m['kind'] == 'exact' for m in matches),
                'matches': matches[:limit],
                'method': '본문·수식 표현과 분류를 비교한 로컬 검색입니다. 점수는 검색 순위 지표이며 풀이의 동등성이나 정답 일치를 보장하지 않습니다.'}
