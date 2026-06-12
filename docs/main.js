// King's Field II 60 FPS patcher -- browser UI glue.
// Loads the generated manifest, drives web/engine.js, and produces the patched .bin/.cue (+ .bps),
// all client-side. The .bin is never uploaded.
(function () {
  "use strict";
  var P = window.KF2Patcher;
  var manifest = null;

  var $ = function (id) { return document.getElementById(id); };
  var fileInput = $("fileInput"), drop = $("drop"), forge = $("forge"), status = $("status");
  var downloads = $("downloads"), cull = $("cull"), fovEnable = $("fovEnable");
  var fov = $("fov"), fovVal = $("fovVal"), fovRow = $("fovRow"), wantBps = $("wantBps");

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
      $("dropSmall").textContent = fmtSize(file.size) + " loaded — ready to forge";
      if (manifest && file.size !== manifest.meta.src_size) {
        setStatus("Warning: size isn't the known KF2 (USA) dump (" + fmtSize(manifest.meta.src_size) + "). You can still try.", "err");
      } else {
        setStatus("Loaded. Choose options and forge your patch.", "ok");
      }
      forge.disabled = !manifest;
      forge.textContent = "Forge patched .bin";
    };
    r.onerror = function () { setStatus("Could not read that file.", "err"); };
    r.readAsArrayBuffer(file);
  }

  function doForge() {
    if (!srcBytes || !manifest) return;
    var mode = document.querySelector('input[name=mode]:checked').value;
    var opts = { cull: cull.checked ? true : null, fov: fovEnable.checked ? parseFloat(fov.value) : null };
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
        forge.disabled = false;
        // srcBytes was edited in place; force a re-load before another forge to avoid double-patching.
        srcBytes = null; drop.classList.remove("loaded");
        $("dropBig").textContent = "Choose your King's Field II (USA) .bin";
        $("dropSmall").textContent = "(re-select the original .bin to forge again)";
        forge.textContent = "Load a .bin first"; forge.disabled = true;
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
  forge.addEventListener("click", doForge);

  // ---- load the manifest ----
  fetch("patches.json").then(function (r) { return r.json(); }).then(function (m) {
    manifest = m;
    if (srcBytes) { forge.disabled = false; forge.textContent = "Forge patched .bin"; }
  }).catch(function () {
    setStatus("Could not load patches.json (serve this folder over http, not file://).", "err");
  });
})();
