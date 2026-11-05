from pathlib import Path
from studio.selftest import exercise

def test_entire_new_application_pipeline(tmp_path):
    store,result=exercise(tmp_path)
    assert result['score']==62.5 and result['backup_restored']
    store.db.close()
