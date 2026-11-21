from datetime import datetime, timezone
import pytest
from integrations.cadwiz_plugin.free_ai import capacity_label, qualification_blockers, GUIDES


@pytest.mark.parametrize('limit,used', [(None,None),(0,0),(100,-1),(float('nan'),2),(100,float('inf')),(True,0)])
def test_invalid_or_missing_capacity_is_unknown(limit,used):
    assert 'Unknown' in capacity_label(limit=limit,used=used,authoritative=True,externally_used=False)


def test_local_counts_cannot_claim_account_balance():
    assert 'Unknown' in capacity_label(limit=100,used=20)
    assert 'Unknown' in capacity_label(limit=100,used=20,authoritative=True)
    assert '(80%)' in capacity_label(limit=100,used=20,authoritative=True,externally_used=False)
    assert '(0%)' in capacity_label(limit=100,used=120,authoritative=True,externally_used=False)


def test_empty_evidence_fails_every_gate():
    blockers=qualification_blockers({})
    assert len(blockers)==10
    assert any('benchmark' in x for x in blockers)
    assert any('consent' in x for x in blockers)


def test_truthy_strings_do_not_authorize_and_expired_evidence_fails():
    now=datetime(2026,11,19,tzinfo=timezone.utc)
    assert 'Free endpoint not verified' in qualification_blockers({'free_endpoint_verified':'yes'},now=now)
    assert any('expired' in x for x in qualification_blockers({'expires_at':'2026-11-18T00:00:00Z'},now=now))


def test_guides_do_not_claim_live_models_or_free_entitlements():
    assert len(GUIDES)==4
    assert all(g.signup.startswith('https://') and g.policy.startswith('https://') for g in GUIDES)
