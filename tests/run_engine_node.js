// Test helper: run the browser patch engine under Node for the parity test.
// Usage: node run_engine_node.js <fixture.bin> <patches.json> <mode> <fov|null> <cull|null> <bob|null> <out.bin> [bpsOut]
const fs = require("fs");
const path = require("path");
const { applyPatches, makeBps } = require(path.join(__dirname, "..", "docs", "engine.js"));

const [, , fixture, manifestPath, mode, fovArg, cullArg, bobArg, out, bpsOut] = process.argv;
const src = new Uint8Array(fs.readFileSync(fixture));
const buf = src.slice(0);                       // keep the source for the BPS
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const fov = fovArg === "null" ? null : parseFloat(fovArg);
const cull = cullArg === "null" ? null : cullArg === "true";
const bob = (bobArg === "null" || bobArg === undefined) ? "on" : bobArg;
applyPatches(manifest, buf, mode, { fov: fov, cull: cull, bob: bob });
fs.writeFileSync(out, Buffer.from(buf));
if (bpsOut) fs.writeFileSync(bpsOut, Buffer.from(makeBps(src, buf)));
