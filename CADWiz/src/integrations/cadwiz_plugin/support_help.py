"""Visible help choices; opening an assistant never silently submits a prompt."""
from __future__ import annotations

HELP_PROMPT = (
    "Help me with a CADWiz problem. Ask what happened, then inspect the relevant "
    "diagnostics and known issues. Explain a safe next step. Ask before changing "
    "my model or sharing information. If needed, show me a report to send to the CADWiz team."
)
SUPPORT_URL = "https://cadwiz.app/support"


def show_help(panel):
    """Use the existing Qt instance, selected assistant and owner window."""
    widgets = panel.QtWidgets
    box = widgets.QMessageBox(panel.content)
    box.setWindowTitle("Get help with CADWiz")
    box.setText("Get help from your connected assistant or contact CADWiz support.")
    box.setInformativeText(
        "Ask my assistant: copies a help request and opens your selected assistant. "
        "Paste it into the conversation and describe your problem.\n\n"
        "Email CADWiz support: opens the support page with the available contact options. "
        "It explains whether automatic email replies are currently available.\n\n"
        "Your model and diagnostics are never attached automatically."
    )
    assistant = box.addButton("Ask my assistant", widgets.QMessageBox.ActionRole)
    email = box.addButton("Email CADWiz support", widgets.QMessageBox.ActionRole)
    box.addButton(widgets.QMessageBox.Close)
    box.exec_()
    if box.clickedButton() is assistant:
        widgets.QApplication.clipboard().setText(HELP_PROMPT)
        panel.connect_claude()
        panel.flash("Help request copied. Paste it into your assistant and describe the problem.", panel.FOUNDER_BLUE, seconds=8.0)
    elif box.clickedButton() is email:
        import webbrowser
        webbrowser.open(SUPPORT_URL)
