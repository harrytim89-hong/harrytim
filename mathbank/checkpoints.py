"""Exact-input, role-separated checkpoints for interrupted question processing."""
import hashlib
import json
import time


class Checkpoints:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        with store.connect() as db:
            db.execute("DELETE FROM records WHERE kind='ai_checkpoint' AND "
                       "json_extract(body,'$.time') < ?", (time.time() - 86400,))

    def clear(self, question_id):
        with self.store.connect() as db:
            db.execute("DELETE FROM records WHERE kind='ai_checkpoint' AND "
                       "json_extract(body, '$.question_id')=?", (question_id,))

    def call(self, q, role, prompt, images, cancel, validate):
        if cancel.is_set():
            from .provider import Cancelled
            raise Cancelled("사용자가 작업을 취소했습니다.")
        provider = self.provider
        identity = dict(revision=1, question=q['id'], version=q['version'],
                        role=role, prompt=prompt,
                        images=[hashlib.sha256(p.read_bytes()).hexdigest() for p in images],
                        model=getattr(provider, 'model', '') or getattr(provider, 'observed_model', ''),
                        effort=getattr(provider, 'effort', ''),
                        reading_effort=getattr(provider, 'reading_effort', ''))
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        key = 'ai-checkpoint-' + q['id'] + '-' + role
        try:
            saved = self.store.record(key)
        except ValueError:
            saved = None
        if saved and saved.get('fingerprint') == fingerprint and 0 <= time.time() - saved.get('time', 0) < 86400:
            try:
                validate(saved['result'])
            except (ValueError, KeyError, TypeError):
                pass
            else:
                self.store.put_record('ai_cache_metric', {'role': role, 'calls_saved': 1})
                return saved['result']
        call = getattr(provider, 'read', provider.call) if role == 'reading' else provider.call
        result = call(prompt, images, cancel)
        validate(result)
        identity['model'] = getattr(provider, 'model', '') or getattr(provider, 'observed_model', '')
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.store.put_record('ai_checkpoint', dict(question_id=q['id'], fingerprint=fingerprint,
                                                   time=time.time(), result=result), key)
        return result
