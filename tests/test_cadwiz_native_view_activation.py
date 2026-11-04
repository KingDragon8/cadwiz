"""A cached document view must never masquerade as the visible CAD window."""
from types import SimpleNamespace

from integrations.cadwiz_plugin import view_link


def test_cached_model_does_not_count_as_a_visible_native_model():
    model = SimpleNamespace(getCameraNode=lambda: None, saveImage=lambda *args: None)
    native = SimpleNamespace(current=SimpleNamespace())  # Start is actually visible
    native.getActiveWindow = lambda: native.current
    gui = SimpleNamespace(getMainWindow=lambda: native, ActiveDocument=SimpleNamespace(ActiveView=model))
    assert view_link.active_view(gui) is None
    native.current = model
    assert view_link.active_view(gui) is model


def test_present_forces_native_window_even_if_document_already_active():
    view = SimpleNamespace(getCameraNode=lambda: None, saveImage=lambda *args: None)
    native = SimpleNamespace(current=SimpleNamespace(), updates=0)
    native.getActiveWindow = lambda: native.current
    native.setActiveWindow = lambda chosen: setattr(native, "current", chosen)
    native.update = lambda: setattr(native, "updates", native.updates + 1)
    gui_doc = SimpleNamespace(ActiveView=view)
    gui = SimpleNamespace(getMainWindow=lambda: native, ActiveDocument=gui_doc,
                          setActiveDocument=lambda name: None, getDocument=lambda name: gui_doc)
    assert view_link.activate_document_view(gui, SimpleNamespace(Name="AlreadyActive")) is view
    assert native.current is view
    assert native.updates == 1


def test_a_spreadsheet_does_not_prevent_reusing_the_existing_3d_view():
    view = SimpleNamespace(getCameraNode=lambda: None, saveImage=lambda *args: None)
    chosen = []
    gui_doc = SimpleNamespace(ActiveView=SimpleNamespace(), mdiViewsOfType=lambda kind: [view])
    gui = SimpleNamespace(setActiveDocument=lambda name: None, getDocument=lambda name: gui_doc,
                          getMainWindow=lambda: SimpleNamespace(setActiveWindow=chosen.append, update=lambda: None))
    assert view_link.activate_document_view(gui, SimpleNamespace(Name="WithSpreadsheet")) is view
    assert chosen == [view]
