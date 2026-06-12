"""Parity test: the browser engine (web/engine.js, via the generated web/patches.json) must
produce byte-identical output to the Python apply_patches() on the synthetic fixture.

This is the guard that keeps the two patchers from drifting:
  * test_manifest_is_fresh -- the committed web/patches.json matches the current Python constants.
  * test_engine_parity     -- engine.js (Node) == apply_patches() for every option combo.
The Node tests skip automatically if `node` isn't installed.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_60fps_patch as P            # noqa: E402
import export_manifest                   # noqa: E402
from test_patch import make_fixture      # noqa: E402

NODE = shutil.which("node")
MANIFEST = os.path.join(ROOT, "docs", "patches.json")
DRIVER = os.path.join(HERE, "run_engine_node.js")

CONFIGS = [
    ("quarter", None, None),     # default 60 fps build
    ("half", None, None),        # 30 fps
    ("quarter", 90.0, None),     # --fov 90 (cull auto-on)
    ("quarter", None, True),     # --cull on, stock FOV (the recommended widescreen build)
    ("quarter", 100.0, False),   # --fov 100 --cull off
]


def test_manifest_is_fresh():
    """The committed manifest must match what export_manifest would generate now."""
    with open(MANIFEST) as f:
        committed = json.load(f)
    assert committed == export_manifest.build(), \
        "web/patches.json is stale -- run `python tools/export_manifest.py`"


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode,fov,cull", CONFIGS)
def test_engine_parity(mode, fov, cull, tmp_path):
    target = make_fixture()
    P.apply_patches(target, mode, fov, cull)

    fixture = tmp_path / "fixture.bin"
    fixture.write_bytes(bytes(make_fixture()))
    out = tmp_path / "out.bin"
    subprocess.run(
        [NODE, DRIVER, str(fixture), MANIFEST, mode,
         "null" if fov is None else str(fov),
         "null" if cull is None else ("true" if cull else "false"),
         str(out)],
        check=True, cwd=HERE)

    assert out.read_bytes() == bytes(target), \
        "engine.js output differs from apply_patches (%s fov=%s cull=%s)" % (mode, fov, cull)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_bps_parity(tmp_path):
    """engine.js makeBps() must match Python make_bps() byte-for-byte."""
    source = make_fixture()
    target = bytearray(source)
    P.apply_patches(target, "quarter")
    py_bps = P.make_bps(bytes(source), bytes(target))

    fixture = tmp_path / "fixture.bin"
    fixture.write_bytes(bytes(make_fixture()))
    out = tmp_path / "out.bin"
    bps = tmp_path / "out.bps"
    subprocess.run([NODE, DRIVER, str(fixture), MANIFEST, "quarter", "null", "null",
                    str(out), str(bps)], check=True, cwd=HERE)
    assert bps.read_bytes() == py_bps, "engine.js makeBps differs from make_bps"
