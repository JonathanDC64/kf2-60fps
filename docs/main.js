// King's Field II 60 FPS patcher -- browser UI glue.
// Loads the generated manifest, drives web/engine.js, and produces the patched .bin/.cue (+ .bps),
// all client-side. The .bin is never uploaded.
(function () {
  "use strict";
  var P = window.KF2Patcher;
  var manifest = null;

  var $ = function (id) { return document.getElementById(id); };
  var fileInput = $("fileInput"), drop = $("drop"), forge = $("forge"), status = $("status");
  var downloads = $("downloads"), cull = $("cull"), fovEnable = $("fovEnable"), bobOff = $("bobOff");
  var fov = $("fov"), fovVal = $("fovVal"), fovRow = $("fovRow"), wantBps = $("wantBps");
  var fovReset = $("fovReset");
  var FOV_DEFAULT = 77;            // the game's stock horizontal FOV (shown for reference)

  var srcBytes = null, srcName = "", urls = [];

  function setStatus(msg, cls) { status.textContent = msg; status.className = cls || ""; }
  function fmtSize(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(0) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
    return bytes + " B";
  }
  function clearUrls() { urls.forEach(function (u) { URL.revokeObjectURL(u); }); urls = []; }
  function addDownload(blob, name, label) {
    var u = URL.createObjectURL(blob); urls.push(u);
    var a = document.createElement("a");
    a.href = u; a.download = name;
    a.innerHTML = label + ' <span class="sz">(' + fmtSize(blob.size) + ')</span>';
    downloads.appendChild(a);
  }

  function baseName() {
    var n = srcName.replace(/\.[^.]+$/, "");
    return n + " [60fps]";
  }

  function loadFile(file) {
    srcName = file.name;
    setStatus("Reading " + file.name + " (" + fmtSize(file.size) + ")…");
    forge.disabled = true;
    var r = new FileReader();
    r.onload = function () {
      srcBytes = new Uint8Array(r.result);
      drop.classList.add("loaded");
      $("dropBig").textContent = file.name;
      $("dropSmall").textContent = fmtSize(file.size) + " loaded";
      forge.textContent = "Forge patched .bin";
      verify();
    };
    r.onerror = function () { setStatus("Could not read that file.", "err"); };
    r.readAsArrayBuffer(file);
  }

  function setChk(id, state) { $(id).className = "chk" + (state ? " " + state : ""); }

  function hex2(buf) {
    var b = new Uint8Array(buf), s = "";
    for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
  }

  // Verify the loaded file against the manifest fingerprints (size + crc32 + md5 + sha1),
  // hashing the big buffer in chunks so the UI stays responsive. Forge stays allowed either way.
  function verify() {
    if (!manifest || !srcBytes) return;
    var m = manifest.meta, vs = $("verifyStatus");
    forge.disabled = true;
    ["c-size", "c-crc", "c-md5", "c-sha1"].forEach(function (id) { setChk(id, "run"); });
    var sizeOk = srcBytes.length === m.src_size;
    setChk("c-size", sizeOk ? "ok" : "bad");
    $("x-size").innerHTML = m.src_size.toLocaleString() + " B" +
      (sizeOk ? "" : ' <span style="color:#e08a7a">(yours: ' + srcBytes.length.toLocaleString() + ')</span>');

    vs.textContent = "Verifying…"; vs.className = "note run";

    // SHA-1 via SubtleCrypto (native, off-thread); crc32+md5 via chunked incremental hashing.
    var sha1p = (window.crypto && crypto.subtle)
      ? crypto.subtle.digest("SHA-1", srcBytes).then(hex2) : Promise.resolve(null);

    var h = P.newHasher(), off = 0, CH = 8 * 1024 * 1024;
    function step() {
      var end = Math.min(srcBytes.length, off + CH);
      h.update(srcBytes.subarray(off, end));
      off = end;
      if (off < srcBytes.length) { vs.textContent = "Verifying… " + Math.floor(off * 100 / srcBytes.length) + "%"; setTimeout(step, 0); }
      else finish();
    }
    function finish() {
      var crc = h.crc32Hex(), md5 = h.md5Hex();
      var crcOk = crc === m.src_crc32.toUpperCase(), md5Ok = md5 === m.src_md5.toLowerCase();
      setChk("c-crc", crcOk ? "ok" : "bad"); setChk("c-md5", md5Ok ? "ok" : "bad");
      if (!crcOk) $("x-crc").innerHTML = m.src_crc32 + ' <span style="color:#e08a7a">(yours: ' + crc + ')</span>';
      if (!md5Ok) $("x-md5").innerHTML = m.src_md5 + ' <span style="color:#e08a7a">(yours: ' + md5 + ')</span>';
      sha1p.then(function (sha1) {
        var sha1Ok = sha1 ? (sha1 === m.src_sha1.toLowerCase()) : null;
        setChk("c-sha1", sha1Ok === null ? "" : (sha1Ok ? "ok" : "bad"));
        if (sha1Ok === false) $("x-sha1").innerHTML = m.src_sha1 + ' <span style="color:#e08a7a">(yours: ' + sha1 + ')</span>';
        var allOk = sizeOk && crcOk && md5Ok && sha1Ok !== false;
        if (allOk) { vs.textContent = "✔ Verified — this is the correct " + m.serial + " dump."; vs.className = "note ok"; }
        else { vs.textContent = "✘ This file does NOT match the known " + m.serial + " dump. Patching may fail — proceed only if you know what you're doing."; vs.className = "note err"; }
        forge.disabled = false;
      });
    }
    setTimeout(step, 0);
  }

  function doForge() {
    if (!srcBytes || !manifest) return;
    var mode = document.querySelector('input[name=mode]:checked').value;
    var opts = { cull: cull.checked ? true : null, fov: fovEnable.checked ? parseFloat(fov.value) : null,
                 bob: bobOff.checked ? "off" : "on" };
    forge.disabled = true; clearUrls(); downloads.innerHTML = ""; downloads.classList.remove("show");
    setStatus("Forging… (large file — this can take a few seconds)");

    // Defer so the status paints before the heavy work blocks the thread.
    setTimeout(function () {
      try {
        var needSrcCopy = wantBps.checked;
        var srcCopy = needSrcCopy ? srcBytes.slice(0) : null;   // BPS needs the unmodified source
        var work = needSrcCopy ? srcBytes : srcBytes;            // edit in place
        P.applyPatches(manifest, work, mode, opts);

        var binName = baseName() + ".bin";
        addDownload(new Blob([work], { type: "application/octet-stream" }), binName, "Patched .bin");

        var cue = 'FILE "' + binName + '" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n';
        addDownload(new Blob([cue], { type: "text/plain" }), baseName() + ".cue", ".cue");

        if (needSrcCopy) {
          setStatus("Building .bps patch…");
          var bps = P.makeBps(srcCopy, work);
          addDownload(new Blob([bps], { type: "application/octet-stream" }), baseName() + ".bps", "Shareable .bps");
        }

        downloads.classList.add("show");
        setStatus("Done — download your files below.", "ok");
      } catch (e) {
        setStatus("Patch failed: " + e.message, "err");
      } finally {
        // srcBytes was edited in place; force a re-load before another forge to avoid double-patching.
        srcBytes = null; drop.classList.remove("loaded");
        $("dropBig").textContent = "Choose your King's Field II (USA) .bin";
        $("dropSmall").textContent = "(re-select the original .bin to forge again)";
        forge.textContent = "Load a .bin first"; forge.disabled = true;
        ["c-size", "c-crc", "c-md5", "c-sha1"].forEach(function (id) { setChk(id, ""); });
        $("verifyStatus").textContent = "Load your .bin above to verify it."; $("verifyStatus").className = "note";
      }
    }, 30);
  }

  // ---- wiring ----
  fileInput.addEventListener("change", function (e) { if (e.target.files[0]) loadFile(e.target.files[0]); });
  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("drag"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("drag"); });
  });
  drop.addEventListener("drop", function (e) { if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });

  fovEnable.addEventListener("change", function () {
    fovRow.classList.toggle("on", fovEnable.checked);
    if (fovEnable.checked) cull.checked = true;   // FOV auto-enables culling (mirrors the CLI)
  });
  fov.addEventListener("input", function () { fovVal.textContent = fov.value + "°"; });
  fovReset.addEventListener("click", function () {
    fov.value = FOV_DEFAULT; fovVal.textContent = FOV_DEFAULT + "°";
  });
  forge.addEventListener("click", doForge);

  // ---- load the manifest ----
  fetch("patches.json").then(function (r) { return r.json(); }).then(function (m) {
    manifest = m;
    if (m.meta.version) $("version").textContent = "v" + m.meta.version;
    $("serial").textContent = m.meta.serial;
    $("x-size").textContent = m.meta.src_size.toLocaleString() + " B";
    $("x-crc").textContent = m.meta.src_crc32;
    $("x-md5").textContent = m.meta.src_md5;
    $("x-sha1").textContent = m.meta.src_sha1;
    if (srcBytes) verify();
  }).catch(function () {
    setStatus("Could not load patches.json (serve this folder over http, not file://).", "err");
  });
})();
