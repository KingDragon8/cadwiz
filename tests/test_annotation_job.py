# SPDX-License-Identifier: LGPL-2.1-or-later
import threading
import time
from types import SimpleNamespace as NS
from integrations.cadwiz_plugin import annotation_job as jobs
from ai_freecad_core.visual_communications.anchored import ModelAnchor


def test_slow_geometry_does_not_block_constructor_or_access_live_document(monkeypatch):
    released = threading.Event()
    threads = []
    def pick(camera, u, v, aspect, objects):
        threads.append(threading.current_thread())
        assert objects[0].Name == "Box"
        released.wait(2)
        return ModelAnchor((1, 2, 3), "Box", "Face1", True)
    monkeypatch.setattr(jobs.view_link, "ray_hit", pick)
    monkeypatch.setattr(jobs.view_link, "_nearest_corner", lambda *a, **k: None)
    monkeypatch.setattr(jobs.view_link, "_depth", lambda *a: 0)
    started = time.monotonic()
    job = jobs.Job(NS(), [(0.5, 0.5)], 1, (100, 100), [NS(Name="Box")])
    assert time.monotonic() - started < .1
    assert job.poll() is None
    released.set()
    result = None
    for _ in range(200):
        result = job.poll()
        if result is not None: break
        time.sleep(.005)
    assert result[0][0].element == "Face1"
    assert threads[0] is not threading.current_thread()


def test_cancelled_job_does_not_continue_to_next_point(monkeypatch):
    held = threading.Event();release = threading.Event();seen=[]
    def pick(*args):
        seen.append(1);held.set();release.wait(2)
        return None
    monkeypatch.setattr(jobs.view_link, "ray_hit", pick)
    monkeypatch.setattr(jobs.view_link, "_nearest_corner", lambda *a, **k: None)
    job = jobs.Job(NS(point_at_focus=lambda *args: (0,0,0)), [(0,0)]*60, 1, (100,100), [])
    assert held.wait(1)
    job.cancelled.set();release.set();time.sleep(.03)
    assert len(seen) == 1
