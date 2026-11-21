# SPDX-License-Identifier: LGPL-2.1-or-later
"""Free AI management and explicit provider enrollment. No automatic inference.

Provider policy links are informational, never proof of account entitlement or
CAD capability. Direct calls stay disabled until the v2.1 qualification gates
are satisfied. Existing assistant connections remain user initiated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from .free_ai_manager import PROVIDERS, ProviderState


@dataclass(frozen=True)
class ProviderGuide:
    name: str
    signup: str
    policy: str
    caution: str


GUIDES = (
    ProviderGuide("Gemini API", "https://aistudio.google.com/apikey",
                  "https://ai.google.dev/gemini-api/docs/pricing",
                  "Free eligibility varies by model and account. Free-tier inputs may be used to improve products."),
    ProviderGuide("Groq", "https://console.groq.com/keys",
                  "https://console.groq.com/docs/rate-limits",
                  "Account and model limits apply. A consumer subscription is not API credit."),
    ProviderGuide("Cloudflare Workers AI", "https://dash.cloudflare.com/",
                  "https://developers.cloudflare.com/workers-ai/platform/pricing/",
                  "Paid plans can bill above the free allocation. Confirm the account plan first."),
    ProviderGuide("OpenRouter", "https://openrouter.ai/settings/keys",
                  "https://openrouter.ai/docs/api-reference/limits",
                  "Free routes can share limits. Provider privacy policies differ; never assume automatic routing is free."),
)


def capacity_label(*, limit: float | None = None, used: float | None = None,
                   authoritative: bool = False, externally_used: bool = True,
                   unit: str = "requests") -> str:
    """Never invent a remaining percentage from local-only or invalid counters."""
    if (not authoritative or externally_used or limit is None or used is None
            or isinstance(limit, bool) or isinstance(used, bool)
            or not isfinite(limit) or not isfinite(used) or limit <= 0 or used < 0):
        return "Remaining capacity: Unknown — this service does not provide a verified account-wide balance."
    remaining = max(0, limit - used)
    return f"Provider-reported remaining: {remaining:g} / {limit:g} {unit} ({100 * remaining / limit:.0f}%)."


def qualification_blockers(evidence: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """Offline review checklist only, not an authorization token or callable route.

Evidence must come from a reviewed maintainer record, never a model response.
Even an empty result does not enable inference in this release.
"""
    now = now or datetime.now(timezone.utc)
    blockers = []
    required = {
        "free_endpoint_verified": "Free endpoint not verified",
        "billing_boundary_verified": "Account billing boundary not verified",
        "privacy_consent": "Cloud-data consent missing",
        "credential_secured": "Secure credential storage not verified",
        "cad_benchmark_passed": "FreeCAD task benchmark missing",
        "executor_security_passed": "Declarative executor security gate incomplete",
        "recovery_passed": "Disk recovery gate incomplete",
        "policy_verified": "Permitted automation not verified",
    }
    for key, reason in required.items():
        if evidence.get(key) is not True:
            blockers.append(reason)
    try:
        expiry = datetime.fromisoformat(str(evidence.get("expires_at", "")).replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= now:
            blockers.append("Provider evidence expired or timezone missing")
    except (ValueError, TypeError):
        blockers.append("Provider evidence expiry unknown")
    if not evidence.get("source_urls"):
        blockers.append("Provider evidence sources missing")
    return blockers


class FreeAIPage:
    def __init__(self, panel: Any) -> None:
        self.panel = panel
        from .session import plugin_data_dir
        self.provider_state = ProviderState(plugin_data_dir() / 'free-ai-status.json')
        self.cards = {}
        self.card_frames = {}
        self.rendered_queue = None
        qt = panel.QtWidgets
        self.page = qt.QScrollArea(panel.full)
        self.page.setObjectName("CADWiz_Free_AI_Page")
        self.page.setWidgetResizable(True)
        inner = qt.QWidget(self.page)
        inner.setObjectName("CADWiz_Free_AI_Inner")
        column = qt.QVBoxLayout(inner)
        column.setContentsMargins(18, 20, 18, 18)
        column.setSpacing(12)
        self.page.setWidget(inner)
        self.page.setStyleSheet("""
            QWidget#CADWiz_Free_AI_Inner { background: #f4f7fb; color: #20354d; }
            QWidget#CADWiz_Free_AI_Inner QLabel { background: transparent; color: #20354d; }
            QWidget#CADWiz_Free_AI_Inner QPushButton {
                background: #ffffff; color: #174a78; border: 1px solid #b7c9dc;
                border-radius: 8px; padding: 11px 14px; font-weight: 600; min-height: 24px;
            }
            QWidget#CADWiz_Free_AI_Inner QPushButton:hover { background: #e9f1fa; border-color: #4077ac; }
            QWidget#CADWiz_Free_AI_Inner QPushButton:pressed { background: #d9e8f7; }
            QWidget#CADWiz_Free_AI_Inner QPushButton:focus { border: 2px solid #2d70b5; }
            QWidget#CADWiz_Free_AI_Inner QPushButton#CADWiz_Free_AI_Setup {
                background: #205f9b; color: #ffffff; border-color: #205f9b;
            }
            QWidget#CADWiz_Free_AI_Inner QPushButton#CADWiz_Free_AI_Setup:hover { background: #174c80; }
            QWidget#CADWiz_Free_AI_Inner QPushButton#CADWiz_Free_AI_Create {
                background: #e4f3ed; color: #165d47; border-color: #9cccb9;
            }
            QWidget#CADWiz_Free_AI_Inner QCheckBox { color: #355875; padding: 6px 0px; }
        """)

        def label(text: str) -> Any:
            item = qt.QLabel(text, inner)
            item.setWordWrap(True)
            column.addWidget(item)
            return item

        cap = label("CADWIZ  /  AIWiz")
        cap.setStyleSheet("color: #426a91; font-size: 12px; font-weight: 700;")
        title = label("AI Wiz Management")
        title.setProperty("role", "heading")
        title.setStyleSheet("color: #174a78; font-size: 27px; font-weight: 700;")
        label("Desktop connections and provider accounts")
        label("Manage your accounts and preferred order. API enrollment checks access only; direct CAD requests and automatic switching are not enabled in this release.")
        self.overview = label("")
        status = self.overview
        status.setStyleSheet("background: #e5eef9; color: #234d77; border-radius: 8px; padding: 12px;")
        self.apps = label("")
        self.capacity = label(capacity_label())
        self.direct = label("Direct provider: not connected. Start with one free account.")
        # Keep detailed diagnostics available to support/tests, off the basic page.
        self.apps.show()
        self.capacity.hide()
        self.direct.hide()
        action_holder=qt.QWidget(inner)
        from .slim_panel import _make_flow_layout
        action_layout=_make_flow_layout(panel.QtCore,qt)(action_holder,8)
        column.addWidget(action_holder)
        enroll = qt.QPushButton("Set up my free AI", inner)
        enroll.setObjectName("CADWiz_Free_AI_Setup")
        enroll.clicked.connect(self.enroll)
        action_layout.addWidget(enroll)
        connect = qt.QPushButton("Connect assistant", inner)
        connect.setObjectName("CADWiz_Free_AI_Connect")
        connect.clicked.connect(lambda: (panel.open_page(3), panel.free_ai.page.setCurrentIndex(0)))
        action_layout.addWidget(connect)
        create = qt.QPushButton("Start creating", inner)
        create.setObjectName("CADWiz_Free_AI_Create")
        create.clicked.connect(lambda: panel.open_page(0))
        action_layout.addWidget(create)
        heading=label("YOUR FREE AI PROVIDERS")
        heading.setStyleSheet("color: #426a91; font-size: 13px; font-weight: 700;")
        queue_holder=qt.QWidget(inner)
        self.queue_layout=qt.QGridLayout(queue_holder)
        self.queue_layout.setContentsMargins(0,0,0,0)
        self.queue_layout.setSpacing(10)
        column.addWidget(queue_holder)
        for provider in PROVIDERS:
            card=qt.QFrame(inner)
            card.setStyleSheet("QFrame {background: #ffffff; border: 1px solid #d9e3ee; border-radius: 8px;} "
                              "QLabel {border: none;} QCheckBox {border: none;}")
            box=qt.QVBoxLayout(card)
            box.setContentsMargins(12,12,12,12)
            box.setSpacing(7)
            header=qt.QHBoxLayout()
            name=qt.QLabel(provider.name,card)
            name.setWordWrap(True)
            name.setStyleSheet("font-weight: 700; color: #174a78; border: none;")
            header.addWidget(name,1)
            up=qt.QPushButton("↑",card)
            down=qt.QPushButton("↓",card)
            up.setFixedSize(28,28);down.setFixedSize(28,28)
            up.setStyleSheet('padding: 0px; min-height: 0px;')
            down.setStyleSheet('padding: 0px; min-height: 0px;')
            up.setAccessibleName('Move '+provider.name+' up')
            down.setAccessibleName('Move '+provider.name+' down')
            up.clicked.connect(lambda _checked=False,p=provider.id:self.move_provider(p,-1))
            down.clicked.connect(lambda _checked=False,p=provider.id:self.move_provider(p,1))
            header.addWidget(up);header.addWidget(down)
            box.addLayout(header)
            account=qt.QCheckBox("I already have an account",card)
            account.setObjectName('CADWiz_Free_AI_Account_'+provider.id)
            account.toggled.connect(lambda checked,p=provider.id:self.mark_account(p,checked))
            account.setText('Have an account')
            account_row=qt.QHBoxLayout()
            account_row.addWidget(account)
            connection=qt.QLabel("",card)
            connection.setWordWrap(True)
            box.addWidget(connection)
            connection.hide()
            indicator=qt.QCheckBox("API access checked",card)
            indicator.setEnabled(False)
            indicator.setObjectName('CADWiz_Free_AI_Connected_'+provider.id)
            account_row.addWidget(indicator)
            box.addLayout(account_row)
            usage=qt.QLabel("",card)
            usage.setWordWrap(True)
            box.addWidget(usage)
            bar=qt.QProgressBar(card)
            bar.setRange(0,100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setMaximumHeight(7)
            bar.setStyleSheet("QProgressBar {background: #e8eef5; border: none; border-radius: 3px;} "
                             "QProgressBar::chunk {background: #2c81c5; border-radius: 3px;}")
            box.addWidget(bar)
            actions=qt.QHBoxLayout()
            signup=qt.QLabel(f'<a href="{provider.signup}">Sign up / account</a>',card)
            signup.setOpenExternalLinks(True)
            actions.addWidget(signup)
            add=qt.QPushButton("Let’s set it up",card)
            add.setObjectName('CADWiz_Free_AI_Provider_'+provider.id)
            add.clicked.connect(lambda _checked=False,p=provider.id:self.enroll_provider(p))
            actions.addWidget(add)
            box.addLayout(actions)
            self.queue_layout.addWidget(card,len(self.card_frames),0)
            self.card_frames[provider.id]=card
            self.cards[provider.id]=(account,connection,usage,bar,indicator,add)
        advanced = qt.QCheckBox("Provider details", inner)
        column.addWidget(advanced)
        details = qt.QWidget(inner)
        layout = qt.QVBoxLayout(details)
        for guide in GUIDES:
            line = qt.QLabel(f"{guide.name}: Unverified — automatic CAD calls disabled. {guide.caution}", details)
            line.setWordWrap(True)
            layout.addWidget(line)
            links = qt.QLabel(f'<a href="{guide.signup}">Official setup</a> · '
                             f'<a href="{guide.policy}">Limits and policy</a>', details)
            links.setOpenExternalLinks(True)
            layout.addWidget(links)
        note = qt.QLabel("Required before activation: current free-endpoint and billing evidence, secure credentials, "
                        "revocable project-data consent, task-specific FreeCAD benchmarks, a constrained declarative "
                        "executor and tested disk recovery. Consumer apps are not pooled API quotas. "
                        "Keys are stored only in your OS credential vault after an explicit connection check. "
                        "CADWiz does not scan installed apps or assume it can read account balances.", details)
        note.setWordWrap(True)
        layout.addWidget(note)
        column.addWidget(details)
        details.hide()
        advanced.toggled.connect(details.setVisible)
        column.addStretch(1)
        from importlib import import_module
        gui=import_module('PySide.QtGui')
        shortcut_class=getattr(qt,'QShortcut',None) or gui.QShortcut
        self.shortcut=shortcut_class(gui.QKeySequence('Ctrl+Alt+I'),panel.full)
        self.shortcut.activated.connect(lambda:panel.open_page(3))
        self.refresh()

    def enroll(self) -> None:
        self.enroll_provider('groq')

    def enroll_provider(self, provider_id) -> None:
        from .free_ai_enrollment import show_enrollment
        show_enrollment(self.panel, self.verified, provider_id)

    def mark_account(self, provider, added):
        try:
            self.provider_state.update(provider,{'account_added':bool(added)})
        except (ValueError,OSError):
            self.overview.setText("Account status could not be saved. Your previous settings were preserved.")

    def move_provider(self, provider, step):
        try:
            state=self.provider_state.read()
            order=state.get('queue',[p.id for p in PROVIDERS])
            index=order.index(provider)
            other=index+step
            if not 0<=other<len(order):return
            order[index],order[other]=order[other],order[index]
            self.provider_state.set_order(order)
            self.refresh()
        except (ValueError,OSError):
            self.overview.setText("The provider queue could not be saved; previous order preserved.")

    def verified(self, result: dict[str, Any]) -> None:
        provider=result.get('provider_id','groq')
        if 'connection_verified' in result:
            try:
                self.provider_state.connected(provider,result['connection_verified'])
            except (ValueError,OSError):
                self.overview.setText("Connection checked; account status could not be saved.")
        if result.get("connection_verified") is False:
            self.direct.setText("Direct provider: not connected. Saved key removed.")
            self.refresh()
            return
        name=next((p.name for p in PROVIDERS if p.id==provider),provider)
        self.direct.setText(name + " API connected — CAD qualification pending. "
                            "Billing protections and remaining capacity are not verified.")
        self.refresh()

    def refresh(self) -> None:
        bridge = self.panel.bridge()
        lines = []
        for app, name in (("claude", "Claude"), ("chatgpt", "OpenAI / Codex")):
            connected = bool(bridge is not None and hasattr(bridge, "connected_to") and bridge.connected_to(app))
            lines.append(f"{name}: " + ("Ready — app assisted" if connected else "Not connected"))
        self.apps.setText("\n".join(lines) + "\nUsage and eligibility depend on your account. "
                          "No automatic switching between consumer accounts is performed.")
        try:
            state=self.provider_state.read()
        except (ValueError,OSError):
            self.overview.setText("Provider status needs recovery. Existing account settings were preserved.")
            return
        connected=sum(row.get('connected')is True for row in state['providers'].values())
        self.overview.setText(f"{len(PROVIDERS)} providers  ·  {connected} API credentials checked\nPreferred order saved below. Automatic switching: unavailable.")
        order=state.get('queue',[p.id for p in PROVIDERS])
        columns=2 if self.page.viewport().width()>=720 else 1
        key=(tuple(order),columns)
        if key!=self.rendered_queue:
            for frame in self.card_frames.values():self.queue_layout.removeWidget(frame)
            for index,provider_id in enumerate(order):
                if provider_id in self.card_frames:
                    self.queue_layout.addWidget(self.card_frames[provider_id],index//columns,index%columns)
            self.rendered_queue=key
        for provider in PROVIDERS:
            row=state['providers'].get(provider.id,{})
            account,connection,usage,bar,indicator,add=self.cards[provider.id]
            account.blockSignals(True)
            account.setChecked(bool(row.get('account_added')))
            account.blockSignals(False)
            indicator.setChecked(bool(row.get('connected')))
            connection.setText("API access checked"if row.get('connected')else "Connect this provider to add it to your list")
            add.setText("Manage connection"if row.get('connected')else "Connect my account"if row.get('account_added')else "Let’s set it up")
            # No inference telemetry exists until a qualified route actually runs.
            # An empty rail means no measurable balance, never 0% remaining.
            events=[e for e in state['events']if e.get('provider')==provider.id and e.get('event')=='request']
            today=__import__('time').time()-86400
            recent=sum(e.get('at',0)>=today for e in events)
            usage.setText(f"{recent} AI requests from CADWiz in the last 24 hours"if recent else "Remaining allowance: not reported. Direct CAD requests are disabled.")
            max_count=max(1,max((sum(e.get('provider')==p.id and e.get('event')=='request'and e.get('at',0)>=today
                                    for e in state['events'])for p in PROVIDERS),default=1))
            bar.setRange(0,max_count)
            bar.setValue(recent)
            bar.setToolTip("Measured requests from CADWiz in the last 24 hours, relative to the busiest provider. Not remaining credit.")
