# SPDX-License-Identifier: LGPL-2.1-or-later
"""Read-only CI diagnostics for a rejected synthetic GUI-to-worker reference."""
import json
import os
from pathlib import Path
import sys

assert os.environ.get('CI') == 'true', 'Disposable CI fixtures only'
source=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
assert source.name=='Working.FCStd' and source.parent.name=='neil-gui'
assert output.parent==source.parent
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'CADWiz/src'))
import FreeCAD as App  # noqa: E402
from integrations.cadwiz_plugin.engineering_control import geometry_reference,document_revision  # noqa: E402

document=App.openDocument(str(source))
try:
    body=document.getObject('Pulley')
    result={'revision':document_revision(document),'faces':[
        geometry_reference(document,body,'Face'+str(i+1)) for i in range(len(body.Shape.Faces))]}
    output.write_text(json.dumps(result,indent=2),encoding='utf8')
finally:
    App.closeDocument(document.Name)
