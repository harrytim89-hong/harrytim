import os
import subprocess
import sys
from mathbank.processes import external_run, external_environment, startup_failure


def test_external_tool_roundtrip():
    result=external_run([sys.executable,'-c','print("EXTERNAL_OK")'])
    assert result.returncode==0 and result.stdout.strip()=='EXTERNAL_OK'


def test_loader_exit_code_is_detected():
    assert startup_failure(0xC0000142)
    assert startup_failure(0xC0000142-2**32)
    assert not startup_failure(1)


def test_frozen_environment_cleans_only_bundled_paths(monkeypatch,tmp_path):
    root=tmp_path/'bundle'
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'_MEIPASS',str(root),raising=False)
    monkeypatch.setenv('PATH',os.pathsep.join([str(root),str(root/'bin'),str(tmp_path/'tools')]))
    monkeypatch.setenv('LD_LIBRARY_PATH','bundle-libs')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG','original-libs')
    env=external_environment()
    assert env['PATH']==str(tmp_path/'tools')
    if os.name!='nt': assert env['LD_LIBRARY_PATH']=='original-libs'
    assert 'bundle-libs'==os.environ['LD_LIBRARY_PATH']
