import io
import json
import sys
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from integrations.cadwiz_plugin.free_ai_connection import (
    ConnectionFailure, WindowsCredentialStore, check_groq_key, check_provider_key, validate_key, _NoRedirect,
)

KEY = 'test-key-no-real-account-123456789'


class Opener:
    def __init__(self, result=None, error=None):
        self.result = result or {'data': [{'id': 'example'}]}
        self.error = error
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.result).encode())


def test_no_consent_means_no_transmission():
    op = Opener()
    with pytest.raises(ConnectionFailure):
        check_groq_key(KEY, opener=op)
    assert not op.calls


def test_connection_check_is_fixed_get_and_does_not_qualify_cad_or_billing():
    op = Opener()
    result = check_groq_key(KEY, consent=True, opener=op)
    req, timeout = op.calls[0]
    assert req.full_url == 'https://api.groq.com/openai/v1/models'
    assert req.method == 'GET' and req.data is None and timeout == 15
    assert not result['cad_qualified'] and not result['billing_verified']
    assert result['remaining_capacity'] == 'Unknown'
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize('status', [301,302,307,401,403,429,500])
def test_provider_errors_do_not_expose_body_or_secret_or_retry(status):
    op = Opener(error=HTTPError('https://api.groq.com/openai/v1/models', status, KEY, {}, io.BytesIO(KEY.encode())))
    with pytest.raises(ConnectionFailure) as err:
        check_groq_key(KEY, consent=True, opener=op)
    assert KEY not in str(err.value) and len(op.calls) == 1


def test_redirect_never_receives_key():
    assert _NoRedirect().redirect_request(None,None,302,'',{},'https://evil.invalid') is None


@pytest.mark.parametrize('value', ['', 'short', 'abc\nAuthorization: injected', 'X'*513, None])
def test_key_header_injection_and_invalid_input_rejected(value):
    with pytest.raises(ConnectionFailure):
        validate_key(value)


def test_network_error_is_sanitized():
    with pytest.raises(ConnectionFailure) as err:
        check_groq_key(KEY,consent=True,opener=Opener(error=URLError(KEY)))
    assert KEY not in str(err.value)


@pytest.mark.parametrize('provider,result,host',[
    ('groq',{'data':[{'id':'test'}]},'api.groq.com'),
    ('openrouter',{'data':{'label':'ignored'}},'openrouter.ai'),
    ('cloudflare',{'success':True,'result':{'status':'active'}},'api.cloudflare.com'),
    ('gemini',{'models':[{'name':'models/test'}]},'generativelanguage.googleapis.com'),
    ('cerebras',{'data':[{'id':'test'}]},'api.cerebras.ai'),
    ('mistral',{'data':[{'id':'test'}]},'api.mistral.ai'),
    ('github',{'id':123},'api.github.com'),
])
def test_all_seven_provider_checks_use_fixed_host_read_only(provider,result,host):
    op=Opener(result=result)
    checked=check_provider_key(provider,KEY,consent=True,opener=op)
    from urllib.parse import urlsplit
    assert urlsplit(op.calls[0][0].full_url).hostname==host
    assert op.calls[0][0].method=='GET' and op.calls[0][0].data is None
    assert checked['provider_id']==provider and checked['connection_verified']
    assert not checked['cad_qualified'] and not checked['billing_verified']


def test_arbitrary_provider_url_cannot_receive_key():
    op=Opener()
    with pytest.raises(ConnectionFailure):check_provider_key('https://evil.invalid',KEY,consent=True,opener=op)
    assert not op.calls


@pytest.mark.skipif(sys.platform != 'win32',reason='Windows OS vault witness')
def test_windows_vault_roundtrip_and_remove_own_disposable_key():
    store=WindowsCredentialStore('CADWiz/FreeAI/Test/'+uuid4().hex)
    assert store.get() is None
    try:
        store.set(KEY)
        assert store.get() == KEY
    finally:
        store.remove()
    assert store.get() is None
