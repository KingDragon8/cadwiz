"""Verify the detector against retained actual positive and negative CI captures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tool',type=Path,required=True)
args=parser.parse_args()
assert os.environ.get('CI')=='true' and sys.platform=='darwin'
root=Path(__file__).resolve().parents[2]
for name,expected in [('mac-local-network-prompt.png',True),('mac-no-permission-prompt.png',False)]:
    result=subprocess.run([str(args.tool),str(root/'tests/fixtures'/name)],capture_output=True,text=True,timeout=60,check=True)
    record=json.loads(result.stdout)
    assert record['permission_prompt_detected'] is expected,(name,record)
    print(json.dumps({'fixture':name,'expected_permission_prompt':expected,'passed':True}))
