# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pick against private geometry copies; never access a live document in a worker."""
from __future__ import annotations
import queue
import threading
import time
from types import SimpleNamespace
from . import view_link
from ai_freecad_core.visual_communications.anchored import ModelAnchor


def snapshot():
    objects = view_link._visible_objects()
    # App::Part aggregates and visible Body Tips repeat the same geometry.
    names = {obj.Name for obj in objects}
    result = []
    for obj in objects:
        if getattr(obj, "TypeId", "") == "App::Part":
            continue
        if any(getattr(parent, "TypeId", "") == "PartDesign::Body" and parent.Name in names
               for parent in getattr(obj, "InList", [])):
            continue
        item = SimpleNamespace(Name=obj.Name, TypeId=getattr(obj, "TypeId", ""), Shape=obj.Shape.copy())
        if item.TypeId == "Mesh::Feature":
            item.Mesh = obj.Mesh.copy()
            item.Placement = obj.Placement.copy()
        result.append(item)
    return result


class Job:
    def __init__(self, camera, points, aspect, pixels, objects):
        self.cancelled = threading.Event()
        self.result = queue.Queue(maxsize=1)
        self.started = time.monotonic()
        def worker():
            try:
                anchors = []
                for u, v in points:
                    if self.cancelled.is_set():
                        return
                    hit = view_link.ray_hit(camera, u, v, aspect, objects)
                    nearby = [o for o in objects if hit is None or o.Name == hit.obj]
                    corner = view_link._nearest_corner(nearby, camera, u, v, aspect, pixels,
                              no_deeper_than=view_link._depth(camera, hit.point) + 1 if hit else None)
                    anchors.append(corner or hit or ModelAnchor(camera.point_at_focus(u, v, aspect)))
                self.result.put((anchors, time.monotonic() - self.started, ""))
            except Exception as error:
                self.result.put(([], time.monotonic() - self.started, str(error)))
        threading.Thread(target=worker, name="cadwiz-mark-pick", daemon=True).start()

    def poll(self):
        try:
            return self.result.get_nowait()
        except queue.Empty:
            return None
