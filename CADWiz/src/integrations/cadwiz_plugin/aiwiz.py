# SPDX-License-Identifier: LGPL-2.1-or-later
"""First-run navigation and explicit AI setup. Never activates a provider route."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from .install_setup import atomic_write


def desktop_route(app, platform=None):
    platform = platform or sys.platform
    if app == 'claude':
        return ('Claude Desktop', 'https://claude.ai/download', platform != 'linux')
    if app == 'codex_cli' or platform == 'linux':
        return ('Codex CLI', 'https://developers.openai.com/codex/cli/', True)
    return ('Codex', 'https://developers.openai.com/codex/app/', True)


def connected_apps(bridge):
    if bridge is None or not hasattr(bridge, 'connected_to'):
        return []
    return [name for key, name in (('claude', 'Claude Desktop'), ('chatgpt', 'OpenAI / Codex'), ('codex_cli', 'Codex CLI'))
            if bridge.connected_to(key)]


def landing_tab(path: Path, bridge=None):
    """A saved successful handshake affects navigation, never grants tool access."""
    if connected_apps(bridge):
        return 1
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        return 1 if record.get('schema') == 1 and record.get('connection_seen') is True else 0
    except (OSError, ValueError, AttributeError):
        return 0


class AIWizPage:
    def __init__(self, panel):
        from .free_ai import FreeAIPage
        from .session import plugin_data_dir
        self.panel = panel
        self.record = plugin_data_dir() / 'aiwiz-onboarding.json'
        self.recorded = landing_tab(self.record) == 1
        qt = panel.QtWidgets
        self.page = qt.QTabWidget(panel.full)
        self.page.setObjectName('CADWiz_AIWiz')
        self.page.setStyleSheet('QTabBar::tab {padding: 10px 12px;} '
                                'QTabBar::tab:selected {color: #175fa8; font-weight: bold;} '
                                'QGroupBox {background: #ffffff; border: 1px solid #cbd9e8; '
                                'border-radius: 10px; margin-top: 12px; padding: 16px 10px 10px; font-weight: bold;} '
                                'QGroupBox::title {subcontrol-origin: margin; left: 12px; color: #174a78;} '
                                'QPushButton {padding: 9px 12px; min-height: 24px; border-radius: 7px; '
                                'border: 1px solid #a8bfd8; background: #edf4fc; color: #174a78;} '
                                'QPushButton:hover {background: #dceaf9;} '
                                'QPushButton:focus {border: 2px solid #175fa8;}')
        scroll = qt.QScrollArea(self.page)
        scroll.setWidgetResizable(True)
        inner = qt.QWidget(scroll)
        column = qt.QVBoxLayout(inner)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(12)
        scroll.setWidget(inner)
        self.page.addTab(scroll, 'AI Wiz Setup')
        self.status = self.label(column, 'Choose your AI. We’ll guide you through the rest.', heading=True)
        self.stack = qt.QStackedWidget(inner)
        column.addWidget(self.stack)
        choices = qt.QWidget(self.stack)
        rows = qt.QVBoxLayout(choices)
        self.stack.addWidget(choices)
        for key, title, description, button in (
            ('claude', 'Claude', 'Use Claude Desktop with your account.', 'Set up Claude'),
            ('chatgpt', 'OpenAI', 'Use Codex with your OpenAI account.', 'Set up Codex'),
            ('codex_cli', 'Codex CLI', 'Use the installed command-line agent. No ChatGPT Desktop required.', 'Set up Codex CLI'),
            ('free', 'Free AIWiz', 'Explore providers and check API access. Direct CAD requests are not enabled yet.', 'Explore free AI'),
            ('other', 'Other AI', 'Gemini, Grok or another AI: check current support before connecting.', 'Choose my AI'),
        ):
            group = qt.QGroupBox(title, choices)
            layout = qt.QVBoxLayout(group)
            self.label(layout, description)
            action = qt.QPushButton(button, group)
            action.setMinimumHeight(40)
            action.setObjectName('CADWiz_AIWiz_Choose_' + key)
            action.clicked.connect(lambda _checked=False, route=key: self.choose(route))
            layout.addWidget(action)
            rows.addWidget(group)
        detail = qt.QWidget(self.stack)
        self.details = qt.QVBoxLayout(detail)
        self.stack.addWidget(detail)
        back = qt.QPushButton('Back to AI choices', detail)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.details.addWidget(back)
        self.detail_title = self.label(self.details, '', heading=True)
        self.detail_text = self.label(self.details, '')
        self.download = qt.QPushButton('Get the desktop app', detail)
        self.download.clicked.connect(self.open_download)
        self.details.addWidget(self.download)
        self.connect = qt.QPushButton('Connect', detail)
        self.connect.clicked.connect(self.connect_chosen)
        self.details.addWidget(self.connect)
        self.other = qt.QComboBox(detail)
        self.other.addItems(['Gemini', 'Grok', 'DeepSeek', 'Qwen', 'Mistral', 'Another AI'])
        self.other.currentTextChanged.connect(self.explain_other)
        self.details.addWidget(self.other)
        self.support = self.label(self.details, '')
        self.label(column, 'Your project stays open. Sign-in and account permissions are yours to approve. '
                   'Files and Cura require separate tools; an AI connection alone does not control them.')
        later = qt.QPushButton('Set up later — return to my model', inner)
        later.clicked.connect(lambda: panel.open_page(0))
        column.addWidget(later)
        column.addStretch(1)
        self.management = FreeAIPage(panel)
        self.page.addTab(self.management.page, 'AI Wiz Management')
        self.page.setCurrentIndex(landing_tab(self.record, panel.bridge()))
        self.route = getattr(panel.prefs, 'ai_setup_route', '') or getattr(panel.prefs, 'ai_app', 'claude')
        self.cli_result = None
        self.cli_checked = 0.0
        if self.route in ('claude', 'chatgpt', 'codex_cli', 'free', 'other'):
            self.choose(self.route)

    def label(self, layout, text, heading=False):
        label = self.panel.QtWidgets.QLabel(text)
        label.setWordWrap(True)
        if heading:
            label.setStyleSheet('font-size: 21px; font-weight: 700; color: #174a78;')
        layout.addWidget(label)
        return label

    def choose(self, route):
        self.panel.prefs.ai_setup_route = route
        self.panel.save_preferences()
        if route == 'free':
            self.page.setCurrentIndex(1)
            self.management.refresh()
            return
        self.route = route
        if route in ('claude', 'chatgpt', 'codex_cli'):
            self.panel.prefs.ai_app = route
            self.panel.save_preferences()
        self.stack.setCurrentIndex(1)
        desktop = route in ('claude', 'chatgpt', 'codex_cli')
        self.download.setVisible(desktop)
        self.connect.setVisible(desktop)
        self.other.setVisible(not desktop)
        self.support.setVisible(not desktop)
        if desktop:
            if route == 'codex_cli':
                self.check_cli()
            name, _url, supported = desktop_route(route)
            if not supported:
                self.detail_title.setText('Claude Desktop is not a Linux route')
                self.detail_text.setText('Choose OpenAI / Codex to set up the supported local Codex CLI route on Linux. '
                                         'A Claude website account alone does not connect to this computer.')
                self.download.hide()
                self.connect.hide()
                return
            self.detail_title.setText('Let’s set up ' + name)
            self.detail_text.setText('1. If needed, get ' + name + ' from the official page below.\n'
                                     '2. Open it and sign in to your own account.\n'
                                     '3. Press Connect below and approve the setup.\n'
                                     '4. Ask your assistant: “What’s open in FreeCAD?”\n\n'
                                     'The connection status updates only after the assistant checks in. '
                                     'No AI account is assigned by CADWiz.' +
                                     (' ChatGPT and Codex are different apps; this route configures Codex.'
                                      if route == 'chatgpt' else ''))
            if route == 'codex_cli':
                self.detail_text.setText('1. Install Codex CLI using the official instructions below.\n'
                    '2. In your terminal, run codex login and approve sign-in yourself.\n'
                    '3. Press Connect to add the existing CADWiz MCP adapter, with backup and Undo.\n'
                    '4. Start or restart Codex CLI, then ask: What is open in FreeCAD?\n\n'
                    'No desktop app is required. Authentication does not prove CAD readiness. '
                    'CADWiz does not run paid inference during discovery or setup.')
            self.download.setText('Get ' + name)
            self.connect.setText('Connect ' + name)
        else:
            self.detail_title.setText('Which AI do you use?')
            self.detail_text.setText('Choose your AI to see what this release supports.')
            self.explain_other(self.other.currentText())

    def explain_other(self, name):
        self.support.setText(name + ': no guided, CAD-qualified connection is available in this release. '
                             'A website account alone does not connect it to FreeCAD. '
                             'Gemini API and Mistral API enrollment are available in AI Wiz Management, '
                             'but enrollment does not enable model creation or automatic switching. '
                             'Use Claude Desktop or Codex for the existing assistant connection routes.')

    def open_download(self):
        _name, url, supported = desktop_route(self.route)
        if not supported:
            return
        self.panel.QtGui.QDesktopServices.openUrl(self.panel.QtCore.QUrl(url))

    def connect_chosen(self):
        from .setup_panel import connect
        self.panel.prefs.ai_app = self.route
        self.panel.save_preferences()
        connect(self.panel)
        self.refresh()

    def check_cli(self):
        if time.monotonic() - self.cli_checked < 30:
            return
        self.cli_checked = time.monotonic()
        def work():
            from .codex_cli import probe
            self.cli_result = probe()
        threading.Thread(target=work, name='CADWizCodexDiscovery', daemon=True).start()

    def refresh(self):
        apps = connected_apps(self.panel.bridge())
        self.status.setText(('Connection verified: ' + ', '.join(apps) +
                             '. Ask your assistant to inspect the open model.') if apps else
                            'Choose your AI. No desktop assistant is connected right now.')
        if getattr(self, 'route', '') == 'codex_cli':
            from .codex_cli import connection_status
            self.check_cli()
            result = connection_status(self.cli_result, self.panel.bridge()) if self.cli_result else None
            self.status.setText(('Codex CLI: ' + result['state'] + '. ' + result['guidance'])
                                if result else 'Checking installed Codex CLI and authentication…')
        if apps and not self.recorded:
            try:
                atomic_write(self.record, json.dumps({'schema': 1, 'connection_seen': True}))
                self.recorded = True
            except (OSError, ValueError):
                pass  # A status-cache failure must never prevent CAD work.
        self.management.refresh()
