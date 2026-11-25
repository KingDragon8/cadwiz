# SPDX-License-Identifier: LGPL-2.1-or-later
"""A gradient or scene ray hit cannot stand in for painted model evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec=importlib.util.spec_from_file_location('viewport_check',Path(__file__).parents[1]/'scripts/ci/native_viewport_check.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Image:
    def __init__(self,paint=False,shift=False):self.paint=paint;self.shift=shift
    def size(self):return (100,100)
    def width(self):return 100
    def height(self):return 100
    def pixelColor(self,x,y):
        value=(0 if self.paint and 20<=x<=60 else y)+int(self.shift)*80
        return SimpleNamespace(getRgb=lambda:(value,value,value,255))

hits=[(x,40) for x in range(20,61,5)]
misses=[(x,40) for x in range(70,96,5)]

def test_unchanged_gradient_with_valid_scene_hits_cannot_pass():
    with pytest.raises(AssertionError,match='silhouette'):
        module.compare_paint(Image(),Image(),hits,misses,100,100)

def test_actual_silhouette_passes_and_changed_background_fails():
    assert module.compare_paint(Image(True),Image(),hits,misses,100,100)['painted_geometry_samples']==len(hits)
    with pytest.raises(AssertionError,match='Background'):
        module.compare_paint(Image(True,True),Image(),hits,misses,100,100)
