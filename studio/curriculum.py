"""Broad curriculum scope, including explicitly shared middle/high-school content."""
import re
from .model import plain_text


def scope(body, classification):
    level = classification.get('school_level')
    if level in ('중등', '고등', '중·고 공통', '미분류') and classification.get('certainty') == 'user_confirmed':
        return level
    course = classification.get('course', '')
    if re.search(r'중[학교등123]|중\s*[123]', course):
        return '중등'
    if re.search(r'고[등교123]|고\s*[123]|공통수학|미적분|대수|확률과 통계|수학[ⅠⅡ12]|기하', course):
        return '고등'
    text = plain_text(body['blocks'])
    if any(w in text for w in ('도함수', '미분', '적분', '극한', '복소수', '허수', '나머지정리', '인수정리', '순열', '조합', '행렬', '로그', '수열', '정규분포', '조건부확률', '원의 방정식', '삼차방정식', '사차방정식', '명제', '판별식')):
        return '고등'
    if any(w in text for w in ('소인수분해', '최대공약수', '최소공배수', '정비례', '반비례', '일차방정식', '일차함수', '피타고라스', '삼각비', '원주각', '줄기와 잎', '도수분포')):
        return '중등'
    if classification.get('unit', '미분류') != '미분류':
        return '중·고 공통'
    return '미분류'
