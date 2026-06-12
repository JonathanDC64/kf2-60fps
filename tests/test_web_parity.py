"""Parity test: the browser engine (web/engine.js, via the generated web/patches.json) must
produce byte-identical output to the Python apply_patches() on the synthetic fixture.

This is the guard that keeps the two patchers from drifting:
  * test_manifest_is_fresh -- the committed web/patches.json matches the current Python constants.
  * test_engine_parity     -- engine.js (Node) == apply_patches() for every option combo.
The Node tests skip automatically if `node` isn't installed.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zlib

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
    ("quarter", None, None, "on"),     # default 60 fps build (head-bob fixed)
    ("half", None, None, "on"),        # 30 fps
    ("quarter", 90.0, None, "on"),     # --fov 90 (cull auto-on)
    ("quarter", None, True, "on"),     # --cull on, stock FOV (the recommended widescreen build)
    ("quarter", 100.0, False, "on"),   # --fov 100 --cull off
    ("quarter", None, None, "off"),    # --bob off (head-bob disabled)
    ("half", None, None, "off"),       # --bob off, 30 fps
]


def test_manifest_is_fresh():
    """The committed manifest must match what export_manifest would generate now."""
    with open(MANIFEST) as f:
        committed = json.load(f)
    assert committed == export_manifest.build(), \
        "web/patches.json is stale -- run `python tools/export_manifest.py`"


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode,fov,cull,bob", CONFIGS)
def test_engine_parity(mode, fov, cull, bob, tmp_path):
    target = make_fixture()
    P.apply_patches(target, mode, fov, cull, bob)

    fixture = tmp_path / "fixture.bin"
    fixture.write_bytes(bytes(make_fixture()))
    out = tmp_path / "out.bin"
    subprocess.run(
        [NODE, DRIVER, str(fixture), MANIFEST, mode,
         "null" if fov is None else str(fov),
         "null" if cull is None else ("true" if cull else "false"),
         bob, str(out)],
        check=True, cwd=HERE)

    assert out.read_bytes() == bytes(target), \
        "engine.js output differs from apply_patches (%s fov=%s cull=%s bob=%s)" % (mode, fov, cull, bob)


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
    subprocess.run([NODE, DRIVER, str(fixture), MANIFEST, "quarter", "null", "null", "on",
                    str(out), str(bps)], check=True, cwd=HERE)
    assert bps.read_bytes() == py_bps, "engine.js makeBps differs from make_bps"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_hash_parity(tmp_path):
    """engine.js md5Hex/crc32Hex must match hashlib.md5 / zlib.crc32 (used to verify the dump)."""
    data = bytes(make_fixture())
    fx = tmp_path / "f.bin"
    fx.write_bytes(data)
    engine = os.path.join(ROOT, "docs", "engine.js").replace("\\", "/")
    code = ("const e=require(%r);const fs=require('fs');"
            "const b=new Uint8Array(fs.readFileSync(process.argv[1]));"
            "process.stdout.write(e.md5Hex(b)+' '+e.crc32Hex(b));") % engine
    r = subprocess.run([NODE, "-e", code, str(fx)], capture_output=True, text=True, check=True)
    md5, crc = r.stdout.split()
    assert md5 == hashlib.md5(data).hexdigest()
    assert crc == "%08X" % (zlib.crc32(data) & 0xffffffff)
    # the manifest's documented hashes are valid hex of the right length
    meta = json.load(open(MANIFEST))["meta"]
    assert len(meta["src_md5"]) == 32 and len(meta["src_sha1"]) == 40
    assert meta["serial"] == "SLUS-00255"
