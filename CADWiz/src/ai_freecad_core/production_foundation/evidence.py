# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Append-only JSONL evidence ledger."""
from __future__ import annotations
import json,os
from pathlib import Path
from typing import Mapping

class AppendOnlyEvidenceLedger:
    def __init__(self,path:Path):self.path=path
    def append(self,event:Mapping[str,object])->None:
        self.path.parent.mkdir(parents=True,exist_ok=True)
        payload=(json.dumps(dict(event),sort_keys=True,separators=(",",":"))+"\n").encode()
        fd=os.open(self.path,os.O_APPEND|os.O_CREAT|os.O_WRONLY,0o600)
        try:os.write(fd,payload);os.fsync(fd)
        finally:os.close(fd)

