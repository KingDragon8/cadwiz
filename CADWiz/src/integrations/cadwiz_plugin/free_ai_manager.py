# SPDX-License-Identifier: LGPL-2.1-or-later
"""Provider catalog, durable non-secret status and capability-gated handoff.

The router accepts only reviewed route records and trusted transport/executor
adapters. Model text cannot register a route or authorize CAD mutations.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time
import tempfile
from typing import Callable

def atomic_write(path: Path, text: str):
    """Self-contained metadata writer, including older installed add-on trees."""
    if path.is_symlink():
        raise ValueError('Provider state must be a regular file.')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8')as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    signup: str
    policy: str
    models_url: str
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    response_list: str = "data"


PROVIDERS = (
    Provider('groq','Groq','https://console.groq.com/keys','https://console.groq.com/docs/rate-limits','https://api.groq.com/openai/v1/models'),
    Provider('openrouter','OpenRouter','https://openrouter.ai/settings/keys','https://openrouter.ai/docs/api-reference/limits','https://openrouter.ai/api/v1/key',response_list='key'),
    Provider('cloudflare','Cloudflare Workers AI','https://dash.cloudflare.com/','https://developers.cloudflare.com/workers-ai/platform/pricing/','https://api.cloudflare.com/client/v4/user/tokens/verify',response_list='token'),
    Provider('gemini','Google Gemini API','https://aistudio.google.com/apikey','https://ai.google.dev/gemini-api/terms','https://generativelanguage.googleapis.com/v1beta/models','x-goog-api-key','', 'models'),
    Provider('cerebras','Cerebras','https://cloud.cerebras.ai/','https://inference-docs.cerebras.ai/support/rate-limits','https://api.cerebras.ai/v1/models'),
    Provider('mistral','Mistral','https://console.mistral.ai/','https://docs.mistral.ai/admin/billing-usage/usage-limits','https://api.mistral.ai/v1/models'),
    Provider('github','GitHub Models','https://github.com/settings/personal-access-tokens','https://docs.github.com/en/github-models/prototyping-with-ai-models','https://api.github.com/user',response_list='github'),
)
CATALOG = {p.id:p for p in PROVIDERS}


def utc():
    return datetime.now(timezone.utc).isoformat()


class ProviderState:
    """No credentials, prompts, project names or geometry may enter this store."""
    def __init__(self, path: Path):
        self.path=Path(path)
        self.lock=threading.RLock()

    def read(self):
        if not self.path.exists():
            return {'schema':1,'revision':0,'providers':{},'events':[],'queue':[p.id for p in PROVIDERS]}
        value=json.loads(self.path.read_text(encoding='utf-8'))
        if value.get('schema')!=1 or not isinstance(value.get('providers'),dict) or not isinstance(value.get('events'),list):
            raise ValueError('Provider status file needs recovery; it was not overwritten.')
        return value

    def set_order(self, order):
        if not isinstance(order,list)or len(order)!=len(CATALOG)or set(order)!=set(CATALOG):
            raise ValueError('Provider queue must contain each supported provider once')
        lockfile=self.path.with_suffix('.lock')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.lock:
            try:descriptor=lockfile.open('x')
            except FileExistsError:raise ValueError('Another window is updating the provider queue.')from None
            try:
                state=self.read();state['queue']=order;state['revision']+=1
                atomic_write(self.path,json.dumps(state,indent=2))
            finally:
                descriptor.close();lockfile.unlink()

    def update(self, provider, fields):
        if provider not in CATALOG:
            raise ValueError('Unknown provider')
        allowed={'account_added','connected','checked_at','last_result','usage','cooldown_until','benchmark','free_evidence'}
        if set(fields)-allowed:
            raise ValueError('Unsupported or sensitive state field')
        # Top-level key filtering is not a license to persist arbitrary strings.
        if 'last_result' in fields and fields['last_result'] not in ('connected','disconnected','rate_limited','error'):
            raise ValueError('Status must be a fixed enum')
        for name in ('usage','benchmark','free_evidence'):
            if name in fields:
                raise ValueError('Measured evidence must use its dedicated validated recorder')
        lockfile=self.path.with_suffix('.lock')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.lock:
            try:
                descriptor=lockfile.open('x')
            except FileExistsError:
                raise ValueError('Another CADWiz window is updating provider status. Try again.') from None
            try:
                state=self.read()
                row=state['providers'].setdefault(provider,{})
                row.update(fields)
                state['revision']+=1
                atomic_write(self.path,json.dumps(state,indent=2))
            finally:
                descriptor.close()
                lockfile.unlink()

    def connected(self, provider, connected):
        fields={'connected':bool(connected),'checked_at':utc(),
                'last_result':'connected'if connected else 'disconnected'}
        if connected:
            fields['account_added']=True
        self.update(provider,fields)

    def record_event(self, event):
        if set(event)!={'provider','event','at'} or event['provider']not in CATALOG:
            raise ValueError('Invalid routing event')
        if event['event']not in ('request','rate_limited','unavailable','plan_validated'):
            raise ValueError('Unsupported event type')
        if type(event['at'])not in (int,float)or not math.isfinite(event['at']):
            raise ValueError('Invalid event timestamp')
        lockfile=self.path.with_suffix('.lock')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.lock:
            try:descriptor=lockfile.open('x')
            except FileExistsError:raise ValueError('Provider usage is being updated by another window.')from None
            try:
                state=self.read()
                state['events']=(state['events']+[event])[-1000:]
                state['revision']+=1
                atomic_write(self.path,json.dumps(state,indent=2))
            finally:
                descriptor.close()
                lockfile.unlink()


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    pool: str
    tier: int
    evidence_expires: float
    free_verified: bool=False
    billing_verified: bool=False
    consent: bool=False
    credential_available: bool=False
    benchmark_passed: bool=False
    executor_passed: bool=False


class RateLimited(RuntimeError):
    def __init__(self, retry_after: float=60):
        if type(retry_after)not in (int,float)or not math.isfinite(retry_after) or retry_after<0:
            retry_after=60
        self.retry_after=min(retry_after,86400)


class NoFreeRoute(RuntimeError):
    pass


class SafeHandoff:
    """Bounded provider handoff BEFORE mutation; one checked plan returned once.

Adapters return untrusted declarative plans. Validation precedes the caller's
single transactional commit; a failed stream is never committed. This does not
make an unqualified provider or a legacy Python executor safe.
"""
    def __init__(self, routes: tuple[Route,...], *, clock: Callable= time.time, observe: Callable|None=None):
        self.routes=routes
        self.clock=clock
        self.cooldowns={}
        self.events=[]
        self.lock=threading.Lock()
        self.observe=observe

    def emit(self,provider,event):
        item={'provider':provider,'event':event,'at':self.clock()}
        if self.observe is not None:
            self.observe(item)
        self.events.append(item)

    def eligible(self, route, tier):
        return (route.provider in CATALOG and bool(route.model) and bool(route.pool)
                and route.tier>=tier and route.evidence_expires>self.clock()
                and all(x is True for x in [route.free_verified,route.billing_verified,route.consent,
                    route.credential_available,route.benchmark_passed,route.executor_passed])
                and self.cooldowns.get(route.pool,0)<=self.clock())

    def propose(self, *, tier, revision, current_revision, request, validate):
        with self.lock:
            if revision!=current_revision():
                raise NoFreeRoute('The document changed; no request was sent.')
            tried=set()
            for route in self.routes[:10]:
                if route.pool in tried or not self.eligible(route,tier):
                    continue
                tried.add(route.pool)
                self.emit(route.provider,'request')
                try:
                    plan=request(route)
                except RateLimited as error:
                    self.cooldowns[route.pool]=self.clock()+error.retry_after
                    self.emit(route.provider,'rate_limited')
                    continue
                except (TimeoutError,ConnectionError):
                    self.emit(route.provider,'unavailable')
                    continue
                if revision!=current_revision():
                    raise NoFreeRoute('A late response was discarded because the document changed.')
                validated=validate(plan)
                self.emit(route.provider,'plan_validated')
                return validated,route
            raise NoFreeRoute('No eligible free route is available. No CAD changes were committed.')
