# SPDX-License-Identifier: LGPL-2.1-or-later
import json
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET
import zipfile

from integrations.cadwiz_plugin import CADWIZ_VERSION
from integrations.cadwiz_plugin import install_setup

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_extension_agree():
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    package = ET.parse(ROOT/'package.xml').getroot()
    assert package.find('{*}version').text == version == CADWIZ_VERSION == install_setup.VERSION
    assert package.find('{*}content/{*}workbench/{*}subdirectory').text == 'CADWiz'
    manifest = json.loads((ROOT/'CADWiz/Resources/claude-extension/manifest.json').read_text())
    with zipfile.ZipFile(ROOT/'CADWiz/Resources/CADWiz.mcpb') as archive:
        assert json.loads(archive.read('manifest.json')) == manifest
    assert manifest['version'] == version
    assert (ROOT/'Install-CADWiz.command').is_file()


def test_default_install_has_no_assistant_or_network_side_effects():
    script = (ROOT/'scripts/install.sh').read_text()
    assert 'pip install' not in script and 'claude_desktop_config' not in script
    assert 'git clone' not in script
