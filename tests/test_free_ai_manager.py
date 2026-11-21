from dataclasses import replace
import json
import pytest
from integrations.cadwiz_plugin.free_ai_manager import (
    PROVIDERS,ProviderState,Route,SafeHandoff,RateLimited,NoFreeRoute,
)


def ready(provider='groq',pool='groq-account',**kw):
    return Route(provider,'test-model',pool,2,1000,True,True,True,True,True,True,**kw)


def test_seven_distinct_official_signup_guides():
    assert len(PROVIDERS)==7 and len({p.id for p in PROVIDERS})==7
    assert all(p.signup.startswith('https://') for p in PROVIDERS)


def test_signup_and_connection_are_separate_and_secrets_rejected(tmp_path):
    state=ProviderState(tmp_path/'providers.json')
    state.connected('groq',True)
    state.connected('groq',False)
    row=state.read()['providers']['groq']
    assert row['account_added'] and not row['connected']
    with pytest.raises(ValueError):state.update('groq',{'api_key':'secret'})
    with pytest.raises(ValueError):state.update('groq',{'benchmark':{'passed':True}})
    assert 'secret' not in state.path.read_text()


def test_corrupt_state_is_preserved(tmp_path):
    path=tmp_path/'providers.json';path.write_text('{bad')
    with pytest.raises(json.JSONDecodeError):ProviderState(path).connected('groq',True)
    assert path.read_text()=='{bad'


def test_queue_order_is_durable_and_cannot_inject_provider(tmp_path):
    state=ProviderState(tmp_path/'providers.json')
    order=[p.id for p in PROVIDERS][::-1]
    state.set_order(order)
    assert ProviderState(state.path).read()['queue']==order
    with pytest.raises(ValueError):state.set_order(order[:-1]+['paid-injected-provider'])
    assert state.read()['queue']==order


def test_usage_events_are_real_counters_without_content_or_secret_fields(tmp_path):
    state=ProviderState(tmp_path/'providers.json')
    state.record_event({'provider':'groq','event':'request','at':100.0})
    assert len(state.read()['events'])==1
    with pytest.raises(ValueError):state.record_event({'provider':'groq','event':'request','at':101,'prompt':'private'})
    assert len(state.read()['events'])==1


def test_cooldown_moves_to_next_independent_pool_and_preserves_revision():
    routes=(ready(),ready(pool='groq-account'),ready('openrouter','openrouter-account'))
    clock=[100.0];router=SafeHandoff(routes,clock=lambda:clock[0]);calls=[]
    def request(route):
        calls.append(route.provider)
        if route.provider=='groq':raise RateLimited(120)
        return {'parameter':'Width','value':45}
    result,route=router.propose(tier=1,revision='a',current_revision=lambda:'a',request=request,validate=lambda x:x)
    assert calls==['groq','openrouter'] and result['value']==45 and route.provider=='openrouter'
    assert not router.eligible(routes[0],1)
    clock[0]=221
    assert router.eligible(routes[0],1)


@pytest.mark.parametrize('field,value', [('free_verified',False),('billing_verified',False),('consent',False),
    ('credential_available',False),('benchmark_passed',False),('executor_passed',False),('evidence_expires',99),('tier',0)])
def test_no_fallback_can_relax_eligibility(field,value):
    router=SafeHandoff((replace(ready(),**{field:value}),),clock=lambda:100)
    with pytest.raises(NoFreeRoute):router.propose(tier=1,revision='a',current_revision=lambda:'a',
        request=lambda r:pytest.fail('must not call'),validate=lambda x:x)


def test_manual_edit_during_request_discards_late_result():
    revision=['a'];router=SafeHandoff((ready(),),clock=lambda:100)
    def request(route):revision[0]='b';return {'value':45}
    with pytest.raises(NoFreeRoute,match='late response'):
        router.propose(tier=1,revision='a',current_revision=lambda:revision[0],request=request,
                       validate=lambda x:pytest.fail('stale plan must not reach validation'))


def test_invalid_plan_is_not_retried_as_a_geometry_success():
    router=SafeHandoff((ready(),ready('openrouter','other')),clock=lambda:100)
    def validate(plan):raise ValueError('malicious code')
    with pytest.raises(ValueError):router.propose(tier=1,revision='a',current_revision=lambda:'a',request=lambda r:'exec(...)',validate=validate)
    assert [x['event']for x in router.events]==['request']
