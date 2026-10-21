# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""FreeCAD-facing half of the AI-master architecture: reading facts from a real
document (`freecad_facts`), executing the coarse tools (`executor`). Allowed to
know about FreeCAD; the rules it applies live in `ai_freecad_core.ai_master`."""
