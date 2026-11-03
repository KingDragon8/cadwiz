// SPDX-License-Identifier: LGPL-2.1-or-later
// Node comes with Claude Desktop; all CAD operations stay in the existing Python connector.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const base = process.env.CADWIZ_SETUP_DIR || (process.platform === 'win32'
  ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'CADWiz')
  : path.join(os.homedir(), 'Library', 'Application Support', 'CADWiz'));
try {
  const runtime = JSON.parse(fs.readFileSync(path.join(base, 'runtime.json'), 'utf8'));
  const launcher = path.join(runtime.addon, 'src', 'integrations', 'cadwiz_plugin', 'offline_launcher.py');
  if (!fs.existsSync(runtime.python) || !fs.existsSync(launcher)) throw Error('FreeCAD has moved.');
  if (!/^0\.6\./.test(runtime.version)) throw Error('Update the CADWiz extension and FreeCAD add-on together.');
  const child = spawn(runtime.python, [launcher], {
    stdio: 'inherit', shell: false, windowsHide: true,
    env: {...process.env, CADWIZ_CLIENT_APP: 'claude'},
  });
  child.on('error', error => { console.error('CW-SETUP-LAUNCH: ' + error.message); process.exitCode = 1; });
  child.on('exit', code => { process.exitCode = code === null ? 1 : code; });
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
} catch (error) {
  console.error('CW-SETUP-RUNTIME: Open FreeCAD once, then enable CADWiz in Claude Extensions. ' + error.message);
  process.exitCode = 1;
}
