from pathlib import Path
from types import SimpleNamespace

from integrations.cadwiz_plugin.support_screenshot import capture
from integrations.cadwiz_plugin.feedback import HelpDesk
from integrations.cadwiz_plugin.error_report import write_report


def test_viewport_capture_never_reads_desktop_or_window(tmp_path):
    target = tmp_path / "safe.png"
    calls = []

    def save_image(path, width, height, background):
        calls.append((width, height, background))
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    app = SimpleNamespace(ActiveDocument=SimpleNamespace(Objects=[]))
    gui_document = SimpleNamespace(Document=app.ActiveDocument, activeView=lambda: SimpleNamespace(saveImage=save_image))
    gui = SimpleNamespace(activeDocument=lambda: gui_document)
    assert capture(gui, app, target)
    assert calls == [(960, 720, "Current")]


def test_annotation_and_unknown_capture_fail_closed_without_stale_file(tmp_path):
    target = tmp_path / "safe.png"
    target.write_bytes(b"previous private pixels")
    app = SimpleNamespace(ActiveDocument=SimpleNamespace(Objects=[SimpleNamespace(TypeId="App::Annotation", PropertiesList=[])]))
    gui_document = SimpleNamespace(Document=app.ActiveDocument)
    gui = SimpleNamespace(activeDocument=lambda: gui_document)
    assert not capture(gui, app, target)
    assert not target.exists()
    assert not capture(None, None, target)


def test_linked_external_content_and_wrong_gui_document_are_not_captured(tmp_path):
    target = tmp_path / "safe.png"
    external = SimpleNamespace(TypeId="App::Annotation", Text="private linked text")
    link = SimpleNamespace(TypeId="App::Link", PropertiesList=["LinkedObject"], LinkedObject=external)
    document = SimpleNamespace(Objects=[link])
    app = SimpleNamespace(ActiveDocument=document)
    gui_document = SimpleNamespace(Document=document)
    gui = SimpleNamespace(activeDocument=lambda: gui_document)
    assert not capture(gui, app, target)
    document.Objects = []
    gui_document.Document = SimpleNamespace(Objects=[])
    assert not capture(gui, app, target)
    assert not target.exists()


def test_legacy_unmasked_screenshot_cannot_be_sent(tmp_path):
    def unmasked(path):
        path.write_bytes(b"private desktop")
        return True

    report = write_report(tmp_path, error_code="TEST", message="Test failure", tool="test", log_path=tmp_path / "missing", grab_window=unmasked)
    desk = HelpDesk(tmp_path, http=lambda *args: (_ for _ in ()).throw(AssertionError("No network during preview")))
    preview = desk.send_feedback("bug", "Legacy capture test", "The report must omit unmasked pixels.", report_id=report)["preview"]
    assert not preview["attached"]
