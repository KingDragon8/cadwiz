# SPDX-License-Identifier: LGPL-2.1-or-later
"""CI-only existing-window pointer/highlight -> measured edit acceptance."""
from pathlib import Path
import os
import json
import contextlib
import shutil


def check(app, gui, folder, panel):
    assert os.environ.get('CI') == 'true', 'Disposable CI desktop only'
    from native_neil_pulley_check import pulley, intent
    from integrations.cadwiz_plugin import view_link
    from integrations.cadwiz_plugin.engineering_control import mark_geometry, file_hash
    from ai_freecad_core.visual_communications.anchored import AnchoredMark
    from ai_freecad_core.visual_communications.contracts import VisualMarkKind
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    progress={}
    def stage(name, **details):
        progress.update(details);progress['stage']=name
        (folder/'progress.json').write_text(json.dumps(progress,indent=2))
    stage('creating-representative-variants')
    before_pid=os.getpid()
    a=pulley('GUI_Variant_A',folder/'Variant_A.FCStd')
    b=pulley('GUI_Variant_B',folder/'Variant_B.FCStd')
    for document in (a,b):
        for obj in document.Pulley.Group:
            obj.ViewObject.Visibility=obj==document.Pulley.Tip
        document.Pulley.ViewObject.Visibility=True
        document.save()
    hashes=[file_hash(a.FileName),file_hash(b.FileName)]
    app.setActiveDocument(b.Name)
    assert panel is not None, 'The actual CADWiz panel must be present'
    session=panel.session()
    assert session is not None and session.document_authority is None
    real_factory=session._factory
    def executor_factory(project, name, filename, **hooks):
        executor = real_factory(project, name, filename, **hooks)
        executor.time_limit_s = 45  # Small deterministic CI fixture; retain real worker discovery.
        stage('worker-selected', executable=str(executor.freecadcmd), resolved=str(executor.freecadcmd.resolve()))
        return executor
    session._factory=executor_factory
    result=session.call('document_operation',{'mode':'variant','source_path':a.FileName,'target_path':str(folder/'Working.FCStd')})
    assert result['ok'],result
    stage('working-variant-bound')
    target=session._document(result['document'])
    view=gui.getDocument(target.Name).activeView();view.viewTop();view.fitAll();gui.updateGui()
    camera=view_link.read_camera(view);width,height=view.getSize();aspect=width/height
    u,v=camera.project((22,0,8),aspect)
    panel.picture_camera=camera;panel.picture_aspect=aspect
    panel.click_select(u,v,False)
    anchor=view_link.pick(view,camera,u,v,aspect)  # Same face pick as the panel; no measurement corner snapping.
    stage('native-pointer-picked')
    assert anchor.on_model and anchor.obj=='Pulley' and abs(anchor.point[2]-8)<.001,anchor
    outline=view_link.face_outline(target,anchor)
    assert len(outline)>4
    before_marks=len(panel.book().marks)
    panel.highlight_face((u,v))
    assert len(panel.book().marks)==before_marks+1
    marks=[AnchoredMark('pointer',VisualMarkKind.POINT,(anchor,)),panel.book().marks[-1]]
    references=mark_geometry(target,marks)
    assert references and all('reference' in r for r in references),references
    selected=view_link.selection(gui)
    assert selected and selected[0]['geometry_references'],selected
    operation=intent(target);operation['reference']=references[0]['reference']
    stage('starting-protected-native-edit',intent=operation)
    target_file = str(Path(target.FileName).resolve()).casefold()
    result=session.call('annular_edit',{'document':target.Name,'intent':operation})
    with contextlib.suppress(OSError,AttributeError):
        executor=session._executors.get(target_file)
        if executor is not None:
            shutil.copy2(executor._latest_file(),folder/'WorkerSnapshot.FCStd')
    stage('native-edit-returned', result=result)
    assert result.get('ok') and result.get('verification_status')=='VERIFIED SUCCESS',result
    assert abs(result['dimensional_verification']['inner_radius_change_mm']+.8)<.001
    assert hashes==[file_hash(a.FileName),file_hash(b.FileName)] and before_pid==os.getpid()
    from native_viewport_check import verify
    native_viewport = verify(app,gui,session.document_authority,folder)
    stage('native-viewport-verified',native_viewport=native_viewport)
    screenshot=folder/'pointer-edit-verified.png'
    for document in list(app.listDocuments().values()):
        if document.FileName and Path(document.FileName).resolve().is_relative_to(folder.resolve()):app.closeDocument(document.Name)
    return {'status':'PASS','pointer_to_annular_floor':True,'highlight_geometry_resolved':True,
            'native_viewport':progress['native_viewport'],
            'measured_inner_radius_change_mm':-.8,'source_and_other_variant_unchanged':True,'same_gui_pid':before_pid,'screenshot':str(screenshot)}
