import pytest
from integrations.cadwiz_plugin.diagnostics import status_intent, status_report


@pytest.mark.parametrize('question',['Am I connected?','What is my AI status?','Is FreeCAD connected?','connection status'])
def test_connection_phrases(question):assert status_intent(question)=='connection'


@pytest.mark.parametrize('question',['Is my account working?','Tell me about my login/status','Am I logged in?','What is my plan?'])
def test_account_phrases(question):assert status_intent(question)=='account'


def test_native_login_probe_is_used_without_exposing_raw_output():
    seen=[]
    def native():
        seen.append(True)
        return {'state':'Authenticated','authenticated':True,'command':['private-path'],'raw':'secret'}
    r=status_report('Is my account working?',lambda:{'state':'connected'},selected='codex_cli',probe=native)
    assert seen and r['account']['authenticated']
    assert 'private-path' not in str(r) and 'secret' not in str(r)
    assert r['account']['plan']=='not_available'


def test_heartbeat_does_not_imply_authentication():
    r=status_report('Am I connected?',lambda:{'state':'connected'},selected='claude')
    assert r['account']['state']=='unknown'
    assert 'authenticated' not in r['account']
