# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Optional, contextual learning through the existing assistant connection.

Learning requests are frozen beside the model like other founder requests. They
never change the model or silently revive the retired classic execution path.
"""
from __future__ import annotations

STYLES = {
    "Show me": "Demonstrate one step at a time on a separate practice copy or new practice document. Preserve my original model. Explain each action and its purpose, show the result, and wait for me before the next step.",
    "Guide me": "Let me do the work. Give one concrete FreeCAD action at a time, explain why, then inspect my result before proceeding. Do not modify the model for me unless I explicitly ask. Offer a hint or repeat when needed.",
    "Explain this": "Explain the selected feature, numbered mark, or current model in plain language. Describe its purpose, how it was made, and relevant printing considerations. Do not modify the model.",
}


def lesson_request(style: str, topic: str) -> dict:
    instruction = STYLES[style]
    return {"ask": f"Learning: {style}. Topic: {topic.strip() or 'the current model'}. {instruction}",
            "learning_style": style, "topic": topic.strip() or "the current model"}


class LearningPanel:
    def __init__(self, panel):
        self.panel = panel
        QtWidgets = panel.QtWidgets
        self.dialog = QtWidgets.QDialog(panel.content)
        self.dialog.setObjectName("CADWiz_Learning")
        self.dialog.setWindowTitle("Learn with CADWiz")
        self.dialog.setModal(False)
        self.dialog.resize(460, 330)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        intro = QtWidgets.QLabel("Choose how to learn. Your assistant teaches in its chat, using the model and selection you share here.", self.dialog)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.topic = QtWidgets.QComboBox(self.dialog)
        self.topic.setObjectName("CADWiz_Learning_Topic")
        self.topic.setEditable(True)
        self.topic.addItems(["The current model or selected feature", "Create a printable bracket: sketch, dimensions, extrusion, rounded edges, print preparation", "Understand an assembly and its moving parts", "Improve first-layer bed adhesion"])
        layout.addWidget(self.topic)
        for style in STYLES:
            button = QtWidgets.QPushButton(style, self.dialog)
            button.setToolTip(STYLES[style])
            button.clicked.connect(lambda _checked=False, chosen=style: self.request(chosen))
            layout.addWidget(button)
        self.status = QtWidgets.QLabel("You can ask to pause, repeat, resume, or exit at any time. Nothing starts automatically.", self.dialog)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QtWidgets.QPushButton("Close", self.dialog)
        close.clicked.connect(self.dialog.hide)
        layout.addWidget(close)

    def request(self, style):
        request = lesson_request(style, self.topic.currentText())
        self.panel.freeze_for_claude(request=request)
        self.panel.QtWidgets.QApplication.clipboard().setText(request["ask"])
        self.status.setText("Lesson request prepared and copied. In your assistant chat, paste it or say ‘start my lesson’. Your original model has not changed.")
