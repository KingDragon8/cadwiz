# Third-party notices

CADWiz's own code is licensed under LGPL-2.1-or-later ([LICENSE](LICENSE)). It
includes, uses or runs alongside the following. Each keeps its own licence.

## Included in this repository

| Component | Where | Licence | Notes |
|---|---|---|---|
| freecad-ai (vendored, unmodified) | `CADWiz/vendor/freecad-ai/freecad_ai` | LGPL-2.1 (`CADWiz/vendor/freecad-ai/LICENSE-CODE`) | Upstream commit `8542eae4ac1a83560d187c24f7972463b3363e83`. Its icons (CC0 1.0) are not included. |
| freecad-robust-mcp (vendored, unmodified) | `CADWiz/vendor/robust-mcp/src/freecad_mcp` | MIT (`CADWiz/vendor/robust-mcp/LICENSE-CODE`) | Upstream commit `d9a37118a8331e8739ad45fd97d027437984296f`. Its icons are licensed CC BY-NC-SA 4.0 and are **not** included. |
| CADWiz logo and Wiz character artwork | `CADWiz/src/integrations/freecad_native/resources/`, `CADWiz/src/integrations/cadwiz_plugin/resources/` | **Not licensed** -- trademarks of Steve Gregerson / WizLabs | Made for CADWiz. See [TRADEMARK.md](TRADEMARK.md). Forks must replace them. |
| Contributor Covenant 2.1 | `CODE_OF_CONDUCT.md` | CC BY 4.0 | contributor-covenant.org |

## Needed at run time, installed separately (not included)

| Component | Licence | How CADWiz uses it |
|---|---|---|
| FreeCAD 1.1 (with its Python, Qt/PySide6, OpenCascade, Pivy, NumPy) | LGPL-2.1+ (FreeCAD); see FreeCAD's own notices for the rest | CADWiz is a FreeCAD addon |
| `mcp` 1.27 (Model Context Protocol SDK) and its dependencies (pydantic, pydantic-settings, ...) | MIT | Installed into FreeCAD's Python; the connection to Claude Desktop |
| Claude Desktop | Anthropic's terms | The AI app the user talks to; not part of CADWiz |

## Optional, only if the user installs them

| Component | Licence | How CADWiz uses it |
|---|---|---|
| Blender | GPL-2.0-or-later | Run as a separate program, without a window, for some mesh jobs |
| PyMeshLab | **GPL-3.0** | Run in a separate Python process (`cadwiz_plugin/mesh_job.py`) to repair meshes. **Flagged for review:** that module imports PyMeshLab directly. It is not shipped with CADWiz and runs only if the user has installed PyMeshLab; whether this needs a different arrangement is a question for the maintainer before the public release. |
| OpenCV (`cv2`), SciPy, Matplotlib, python-dotenv | Apache-2.0, BSD-3-Clause, Matplotlib (PSF-style), BSD-3-Clause | Imported by a few optional code paths if present |

## Not known to be included

Nothing of unknown origin is included. If you find a file whose origin is not
stated here, please report it at [cadwiz.app/feedback](https://cadwiz.app/feedback).
