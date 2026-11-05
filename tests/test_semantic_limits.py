from studio.fixtures import make_fixture
from studio.storage import Store
from studio.importers import import_document
from studio.formula import equation
from studio.reasoning import check_question
from studio.model import body_fingerprint

def test_unconsumed_domain_relation_is_held(tmp_path):
    source=make_fixture(tmp_path/'q.hwpx',notes=True);s=Store(tmp_path/'db');import_document(s,source);q=s.questions()[0]
    q['body']['blocks'].insert(0,{'kind':'paragraph','blocks':[equation('x>0')]});q['fingerprint']=body_fingerprint(q['body'])
    assert check_question(q)['verification']=='held'
