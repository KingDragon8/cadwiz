"""Saved panel geometry must not hide the native CAD viewport."""
from types import SimpleNamespace

from integrations.cadwiz_plugin.panel_host import PanelHost, usable_dock_width


def test_stale_wide_panel_is_bounded_and_normal_width_is_preserved():
    assert usable_dock_width(1426,1846) == 830
    assert usable_dock_width(600,1846) == 600
    assert usable_dock_width(100,1846) == 420


def make_host(view_width, dock_width):
    minima, resized, scheduled, saved = [], [], [], []
    mdi = SimpleNamespace(width=lambda: view_width, height=lambda: 800,
                          setMinimumSize=lambda w,h: minima.append((w,h)))
    host = PanelHost.__new__(PanelHost)
    host.window = SimpleNamespace(width=lambda: 1846, findChild=lambda cls: mdi)
    host.QtWidgets = SimpleNamespace(QMdiArea=object)
    host.QtCore = SimpleNamespace(QTimer=SimpleNamespace(singleShot=lambda delay, work: scheduled.append(work)))
    host.dock = SimpleNamespace(isFloating=lambda: False,width=lambda: dock_width)
    host.collapsed = False
    host.settings = {}
    host._save_timer = SimpleNamespace(start=lambda: saved.append(True))
    host._resize_docked = resized.append
    return host, minima, resized, scheduled, saved


def test_squeezed_view_gets_space_and_corrected_preference():
    host, minima, resized, scheduled, saved = make_host(196,1426)
    assert host.protect_viewport()
    assert minima == [(360,200)]
    assert resized == [830]
    assert host.settings['docked_width'] == 830
    assert scheduled and saved


def test_valid_manual_view_is_not_refitted_or_resized():
    host, minima, resized, scheduled, saved = make_host(800,600)
    assert not host.protect_viewport()
    assert not resized and not scheduled and not saved
