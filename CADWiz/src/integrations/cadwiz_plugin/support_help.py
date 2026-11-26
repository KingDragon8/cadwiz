"""Visible help choices; opening an assistant never silently submits a prompt."""
from __future__ import annotations

HELP_PROMPT = "CADWiz, help me."
IDEA_PROMPT = "CADWiz, I've got an idea."

SUPPORT_URL = "https://cadwiz.app/support"


def show_help(panel):
    """Use the existing Qt instance, selected assistant and owner window."""
    widgets = panel.QtWidgets
    dialog = widgets.QDialog(panel.content)
    dialog.setWindowTitle("CADWiz Help & Support")
    dialog.resize(600, 620)
    layout = widgets.QVBoxLayout(dialog)

    def section(title, text, button_text, callback):
        box = widgets.QGroupBox(title, dialog)
        column = widgets.QVBoxLayout(box)
        words = widgets.QLabel(text, box)
        words.setWordWrap(True)
        column.addWidget(words)
        button = widgets.QPushButton(button_text, box)
        button.clicked.connect(lambda _checked=False: callback())
        column.addWidget(button)
        layout.addWidget(box)

    def assistant(prompt):
        widgets.QApplication.clipboard().setText(prompt)
        panel.connect_claude()
        panel.flash("Copied. Paste into your connected assistant and leave your message.", panel.FOUNDER_BLUE, seconds=8.0)

    import webbrowser
    section("Ask your assistant — fully integrated with CADWiz",
            "Already connected to CADWiz? Say: CADWiz, help me.\n"
            "Explain what you want to do or the problem you are having.",
            "Copy: CADWiz, help me", lambda: assistant(HELP_PROMPT))
    section("Got a suggestion for CADWiz — tell your assistant",
            "Say: CADWiz, I've got an idea.\nLeave your message, then say: Send this to the CADWiz team. "
            "Your assistant prepares the report for you to confirm.",
            "Copy: CADWiz, I've got an idea", lambda: assistant(IDEA_PROMPT))
    section("Can't connect or install? Email the CADWiz team",
            "support@cadwiz.app\nNo CADWiz connector is needed. Include the error message and "
            "your operating system, FreeCAD version and assistant name if known. "
            "Automatic support tries to reply promptly. Reply to continue. "
            "No FreeCAD model file is required.",
            "Email support@cadwiz.app", lambda: webbrowser.open("mailto:support@cadwiz.app?subject=CADWiz%20help"))
    note = widgets.QLabel("Report a problem in Help & Support to prepare a private screenshot preview. "
                         "Titles and private panels are excluded automatically; unsafe views use text alone.", dialog)
    note.setWordWrap(True)
    layout.addWidget(note)
    website = widgets.QPushButton("cadwiz.app/support", dialog)
    website.clicked.connect(lambda _checked=False: webbrowser.open(SUPPORT_URL))
    layout.addWidget(website)
    close = widgets.QPushButton("Close", dialog)
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    dialog.exec_()
