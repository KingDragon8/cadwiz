# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native status intent routing; no model request, login, secret reading or inference."""
import re


def status_intent(question):
    if re.search(r'\b(login|log\s*in|logged|sign.?in|account|authenticat\w*|subscription|quota|plan|billing)\b', str(question).casefold()):
        return 'account'
    return 'connection'


def status_report(question, connection, *, selected=None, probe=None):
    if selected is None:
        from integrations.cadwiz_plugin.preferences_store import load
        selected = load().ai_app
    result = {'intent': status_intent(question), 'assistant': selected, 'bridge': connection(),
              'account': {'state': 'unknown', 'plan': 'not_available', 'quota': 'not_available'}}
    if result['intent'] == 'account' and selected == 'codex_cli':
        if probe is None:
            from integrations.cadwiz_plugin.codex_cli import probe
        native = probe()
        result['account'] = {k:v for k,v in native.items() if k in
                             ('installed','authenticated','auth_mode','state','guidance')}
        result['account'].update(plan='not_available', quota='not_available')
    else:
        result['account']['guidance'] = ('Account authentication is not verified by the FreeCAD heartbeat. '
            'Use your selected assistant’s built-in status/account view for its account details.')
    return result
