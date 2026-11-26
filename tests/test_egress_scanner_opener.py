import ast
import importlib.util
from pathlib import Path


def test_opener_construction_is_recorded_as_network_capability():
    path=Path(__file__).resolve().parents[1]/'scripts/ci/check_egress_allowlist.py'
    spec=importlib.util.spec_from_file_location('egress_check',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    scanner=module._Scanner(Path('candidate.py'))
    scanner.visit(ast.parse('import urllib.request\nclient = urllib.request.build_opener()\n'))
    assert scanner.findings, 'A private opener must not disappear from the egress capability review'
