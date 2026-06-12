// KF2 60fps patcher -- browser/Node patch engine.
// Mirrors src/build_60fps_patch.py apply_patches(), driven by the generated web/patches.json.
// A parity test (tests/test_web_parity.py) asserts byte-identical output to the Python patcher.
// Pure data-in/data-out: takes a Uint8Array of the .bin and edits it IN PLACE.
(function (root) {
  "use strict";

  function hexToBytes(h) {
    var n = h.length >> 1, a = new Uint8Array(n);
    for (var i = 0; i < n; i++) a[i] = parseInt(h.substr(i * 2, 2), 16);
    return a;
  }
  function fileOff(vaddr, textVaddr) { return (vaddr - textVaddr) + 0x800; }
  function binOff(f) { return f + Math.floor(f / 2048) * 304; }

  // Search `buf` for `pat` within [lo, hi). Returns index or -1.
  function search(buf, pat, lo, hi) {
    var n = pat.length, last = hi - n, b0 = pat[0];
    for (var i = lo; i <= last; i++) {
      if (buf[i] !== b0) continue;
      var k = 1;
      for (; k < n; k++) if (buf[i + k] !== pat[k]) break;
      if (k === n) return i;
    }
    return -1;
  }
  // Like Python find_once: exactly one occurrence in [lo, hi).
  function findOnce(buf, pat, lo, hi, name) {
    var i = search(buf, pat, lo, hi);
    if (i < 0) throw new Error("signature not found: " + name + " (is this the right KF2 (USA) dump?)");
    if (search(buf, pat, i + 1, hi) >= 0) throw new Error("signature not unique: " + name);
    return i;
  }
  function eq(buf, off, bytes) {
    for (var i = 0; i < bytes.length; i++) if (buf[off + i] !== bytes[i]) return false;
    return true;
  }
  function writeLE(buf, off, value, width) {
    for (var i = 0; i < width; i++) { buf[off + i] = value & 0xff; value >>>= 8; }
  }
  function readU16(buf, off) { return buf[off] | (buf[off + 1] << 8); }

  function fovToH(deg, ofx) {
    var h = Math.round(ofx / Math.tan((deg * Math.PI / 180) / 2));
    return Math.max(24, Math.min(0x3ff, h));
  }
  function fovToCullHalf(deg, limiter) {
    var halfDeg = (deg / 2) * (4 / 3) + 5;         // 4:3 -> 16:9 widen + ~5deg rotation margin
    var units = Math.round(halfDeg * 4096 / 360);
    return Math.max(limiter, Math.min(0x3a0, units));  // >= limiter (always cos-scaled, no flicker)
  }

  // Apply all patches to `buf` (Uint8Array, edited in place).
  //   manifest : parsed patches.json
  //   mode     : "quarter" | "half"
  //   opts     : { fov: number|null, cull: boolean|null }
  // Returns a short log array (strings). Throws on any signature/byte mismatch.
  function applyPatches(manifest, buf, mode, opts) {
    opts = opts || {};
    var fov = (opts.fov === undefined ? null : opts.fov);
    var cull = (opts.cull === undefined ? null : opts.cull);
    var meta = manifest.meta, log = [];

    // Anchor: locate GAME.EXE base via the (unique) enemy signature, then bound the search to it.
    var anchorSig = hexToBytes(manifest.anchor.sig);
    var je = search(buf, anchorSig, 0, buf.length);
    if (je < 0) throw new Error("GAME.EXE anchor signature not found");
    var base = je - binOff(fileOff(manifest.anchor.vaddr, meta.text_vaddr));
    var magic = manifest.anchor.magic;
    for (var mi = 0; mi < magic.length; mi++)
      if (buf[base + mi] !== magic.charCodeAt(mi)) throw new Error("GAME.EXE anchor mismatch @0x" + base.toString(16));
    // GAME.EXE spans ~text_size; bound generously (1 MB) so signature searches stay fast on a 571MB bin.
    var lo = base, hi = Math.min(buf.length, base + 0x100000);

    function caveBin(vaddr) { return base + binOff(fileOff(vaddr, meta.text_vaddr)); }

    // ---- signature-located edits (+ optional cave) ----
    manifest.edits.forEach(function (e) {
      var sig = hexToBytes(e.sig);
      var idx = (e.name === "enemy") ? je : findOnce(buf, sig, lo, hi, e.name);
      e.ops.forEach(function (op) {
        if (readField(buf, idx + op.off, op.w) !== op.old)
          throw new Error(e.name + " byte mismatch @+0x" + op.off.toString(16));
        writeLE(buf, idx + op.off, op.new[mode], op.w);
      });
      if (e.cave) {
        var c = e.cave, old = hexToBytes(c.old);
        if (!eq(buf, idx + c.patch_off, old))
          throw new Error(e.name + " cave redirect mismatch");
        var cbin = caveBin(c.vaddr), words = c.words[mode];
        for (var z = 0; z < words.length * 4; z++)
          if (buf[cbin + z] !== 0) throw new Error(e.name + " cave region not free @0x" + cbin.toString(16));
        writeLE(buf, idx + c.patch_off, parseInt(c.jmp, 16), 4);
        for (var w = 0; w < words.length; w++) writeLE(buf, cbin + w * 4, parseInt(words[w], 16), 4);
      }
      log.push(e.name);
    });

    // ---- MENU-CAP: patched at an absolute vaddr (verify the flush sig is there) ----
    var mc = manifest.menucap, mcbin = caveBin(mc.vaddr), mcsig = hexToBytes(mc.sig);
    if (!eq(buf, mcbin, mcsig)) throw new Error("menucap: flush not at its vaddr");
    if (readField(buf, mcbin + mc.off, 4) !== parseInt(mc.old, 16)) throw new Error("menucap byte mismatch");
    writeLE(buf, mcbin + mc.off, parseInt(mc.new, 16), 4);
    log.push("menucap");

    // ---- FOV (--fov): rewrite the GTE H immediate at every gte_ldH site + recalibrate fog H ----
    if (fov !== null) {
      var f = manifest.fov, idiom = hexToBytes(f.idiom), h = fovToH(fov, f.ofx);
      var nFov = 0, start = lo;
      for (;;) {
        var p = search(buf, idiom, start, hi);
        if (p < 0) break;
        if (readU16(buf, p) !== f.h_default) throw new Error("fov H imm mismatch");
        writeLE(buf, p, h, 2);
        nFov++; start = p + idiom.length;
      }
      if (nFov === 0) throw new Error("FOV H-load idiom not found");
      var fg = f.fogh, fi = findOnce(buf, hexToBytes(fg.sig), lo, hi, "fogh");
      if (readU16(buf, fi + fg.off) !== fg.stock) throw new Error("fogh imm mismatch");
      writeLE(buf, fi + fg.off, h, 2);
      log.push("fov(" + nFov + " sites, H=" + h + ")");
    }

    // ---- widescreen culling (--cull wins; else auto-on when --fov set) ----
    var doCull = (cull !== null) ? cull : (fov !== null);
    if (doCull) {
      var cu = manifest.cull, effFov = (fov !== null) ? fov : cu.stock_fov;
      var half = fovToCullHalf(effFov, cu.limiter);
      var co = cu.cone, ci = findOnce(buf, hexToBytes(co.sig), lo, hi, "cull");
      if (readU16(buf, ci + co.off) !== co.stock) throw new Error("cull imm mismatch");
      writeLE(buf, ci + co.off, half, 2);
      var nb = cu.nearband, ni = findOnce(buf, hexToBytes(nb.sig), lo, hi, "nearband");
      if (buf[ni + nb.thresh_off] !== 0x05) throw new Error("nearband thresh mismatch");
      writeLE(buf, ni + nb.thresh_off, nb.thresh_new, 2);
      writeLE(buf, ni + nb.nop1, 0, 4);
      writeLE(buf, ni + nb.nop2, 0, 4);
      log.push("cull(half=0x" + half.toString(16) + ")");
    }
    return log;
  }

  function readField(buf, off, w) {
    if (w === 1) return buf[off];
    if (w === 2) return readU16(buf, off);
    return (buf[off] | (buf[off + 1] << 8) | (buf[off + 2] << 16) | (buf[off + 3] << 24)) >>> 0;
  }

  // ---- CRC32 (matches Python zlib.crc32) ----
  var CRC = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) { var c = n; for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); t[n] = c >>> 0; }
    return t;
  })();
  function crc32(buf) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  // ---- BPS patch (byte-identical to make_bps in build_60fps_patch.py) ----
  function makeBps(source, target) {
    var out = [];
    function varint(nn) { for (;;) { var x = nn % 128; nn = Math.floor(nn / 128); if (nn === 0) { out.push(0x80 | x); return; } out.push(x); nn -= 1; } }
    function u32(v) { out.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff); }
    out.push(66, 80, 83, 49); // "BPS1"
    varint(source.length); varint(target.length); varint(0);
    var i = 0, n = target.length;
    while (i < n) {
      var same = source[i] === target[i], j = i + 1;
      while (j < n && (source[j] === target[j]) === same) j++;
      varint((j - i - 1) * 4 + (same ? 0 : 1));
      if (!same) for (var k = i; k < j; k++) out.push(target[k]);
      i = j;
    }
    u32(crc32(source)); u32(crc32(target));
    u32(crc32(Uint8Array.from(out)));
    return Uint8Array.from(out);
  }

  // ---- streaming MD5 (matches Python hashlib.md5) -- for chunked, non-blocking hashing ----
  var MD5_S = [7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
               5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
               4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
               6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21];
  var MD5_K = (function () { var k = new Int32Array(64); for (var i = 0; i < 64; i++) k[i] = (Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296)) | 0; return k; })();
  function MD5() { this.h = new Int32Array([0x67452301, 0xefcdab89 | 0, 0x98badcfe | 0, 0x10325476]); this.block = new Uint8Array(64); this.blockLen = 0; this.total = 0; this.M = new Int32Array(16); }
  MD5.prototype._proc = function (buf, off) {
    var M = this.M, j;
    for (j = 0; j < 16; j++) M[j] = (buf[off + j * 4]) | (buf[off + j * 4 + 1] << 8) | (buf[off + j * 4 + 2] << 16) | (buf[off + j * 4 + 3] << 24);
    var a = this.h[0], b = this.h[1], c = this.h[2], d = this.h[3], f, g, i, s;
    for (i = 0; i < 64; i++) {
      if (i < 16) { f = (b & c) | (~b & d); g = i; }
      else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
      else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
      else { f = c ^ (b | ~d); g = (7 * i) & 15; }
      f = (f + a + MD5_K[i] + M[g]) | 0; a = d; d = c; c = b; s = MD5_S[i];
      b = (b + ((f << s) | (f >>> (32 - s)))) | 0;
    }
    this.h[0] = (this.h[0] + a) | 0; this.h[1] = (this.h[1] + b) | 0; this.h[2] = (this.h[2] + c) | 0; this.h[3] = (this.h[3] + d) | 0;
  };
  MD5.prototype.update = function (bytes) {
    this.total += bytes.length; var i = 0, n = bytes.length;
    if (this.blockLen) { while (i < n && this.blockLen < 64) this.block[this.blockLen++] = bytes[i++]; if (this.blockLen === 64) { this._proc(this.block, 0); this.blockLen = 0; } }
    while (i + 64 <= n) { this._proc(bytes, i); i += 64; }
    while (i < n) this.block[this.blockLen++] = bytes[i++];
    return this;
  };
  MD5.prototype.hex = function () {
    var total = this.total, pad = [0x80], z;
    var rem = (this.blockLen + 1) % 64, zeros = (rem <= 56) ? (56 - rem) : (120 - rem);
    for (z = 0; z < zeros; z++) pad.push(0);
    var bl = total * 8, lo = bl % 4294967296, hi = Math.floor(bl / 4294967296);
    pad.push(lo & 0xff, (lo >>> 8) & 0xff, (lo >>> 16) & 0xff, (lo >>> 24) & 0xff, hi & 0xff, (hi >>> 8) & 0xff, (hi >>> 16) & 0xff, (hi >>> 24) & 0xff);
    this.update(Uint8Array.from(pad));
    var out = "", v, b2, byte;
    for (var i = 0; i < 4; i++) { v = this.h[i] >>> 0; for (b2 = 0; b2 < 4; b2++) { byte = (v >>> (b2 * 8)) & 0xff; out += (byte < 16 ? "0" : "") + byte.toString(16); } }
    return out;
  };
  function md5Hex(bytes) { return new MD5().update(bytes).hex(); }
  function crc32Hex(buf) { return ("0000000" + crc32(buf).toString(16)).slice(-8).toUpperCase(); }

  // Incremental crc32 + md5 for chunked (non-blocking) hashing of a large buffer.
  function newHasher() {
    var c = 0xFFFFFFFF, md = new MD5();
    return {
      update: function (b) { md.update(b); for (var i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8); },
      crc32Hex: function () { return ("0000000" + ((c ^ 0xFFFFFFFF) >>> 0).toString(16)).slice(-8).toUpperCase(); },
      md5Hex: function () { return md.hex(); }
    };
  }

  var api = { applyPatches: applyPatches, fovToH: fovToH, fovToCullHalf: fovToCullHalf,
              crc32: crc32, crc32Hex: crc32Hex, md5Hex: md5Hex, makeBps: makeBps,
              newHasher: newHasher, _binOff: binOff, _fileOff: fileOff };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KF2Patcher = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
