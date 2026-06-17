#!/usr/bin/env python3
"""Generate docs/patches.json from the authoritative Python patcher constants.

The Python patcher (src/build_60fps_patch.py) stays the single source of truth: this script
imports its constants and serialises them into a declarative manifest the browser patcher
(docs/engine.js) consumes. Run it whenever the patcher's patch data changes:

    python tools/export_manifest.py

A parity test (tests/test_web_parity.py) then asserts the JS engine, driven by this manifest,
produces byte-identical output to apply_patches() on the synthetic fixture -- so any drift in
the manifest *or* the JS apply-logic fails loudly.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import build_60fps_patch as P  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "patches.json")


def hx(b):
    return b.hex()


def cave(vaddr, words):
    return {"vaddr": vaddr, "words": {m: ["%08x" % w for w in words[m]] for m in ("quarter", "half")}}


def per_mode(d):
    return {"quarter": d["quarter"], "half": d["half"]}


def build():
    m = {
        "meta": {
            "version": P.VERSION,               # patcher version (shown in the web UI)
            "serial": P.SRC_SERIAL,             # SLUS-00255 (King's Field II, USA)
            "src_size": P.SRC_SIZE,
            "src_crc32": "%08X" % P.SRC_CRC32,
            "src_md5": P.SRC_MD5,
            "src_sha1": P.SRC_SHA1,
            "text_vaddr": P.TEXT_VADDR,         # for vaddr -> file-offset
            "sector_data": 2048,                # MODE2/2352 user bytes per sector
            "sector_overhead": 304,             # ... and the non-data bytes
        },
        # ENEMY_JSIG doubles as the GAME.EXE anchor: base = found - bin_off(file_off(vaddr)).
        "anchor": {"sig": hx(P.ENEMY_JSIG), "vaddr": P.ENEMY_JSIG_VADDR, "magic": "PS-X EXE"},
        "edits": [],
        "fov": {},
        "cull": {},
    }

    def edit(name, sig, ops, cave_obj=None):
        e = {"name": name, "sig": hx(sig), "ops": ops}
        if cave_obj:
            e["cave"] = cave_obj
        m["edits"].append(e)

    # ---- same-size byte / word / u16 edits ----
    edit("cap", P.CAP_SIG, [{"off": o, "w": 1, "old": 0x04, "new": per_mode(P.CAP_NEW)}
                            for o in P.CAP_OFF])
    edit("walk", P.WALK_SIG, [{"off": o, "w": 1, "old": 0x03, "new": per_mode(P.WALK_NEW)}
                              for o in P.WALK_OFF])
    edit("turn", P.TURN_SIG, [
        {"off": P.TURN_OFF20, "w": 1, "old": 0x20, "new": per_mode(P.TURN_NEW20)},
        {"off": P.TURN_OFF28, "w": 1, "old": 0x28, "new": per_mode(P.TURN_NEW28)}])
    # LOOK (vertical camera / pitch): both apply sites, addu v1,v0,zero -> sra v1,v0,N
    edit("look_up", P.LOOK_UP_SIG, [{"off": P.LOOK_OFF, "w": 4, "old": P.LOOK_OLD,
                                     "new": per_mode(P.LOOK_NEW)}])
    edit("look_dn", P.LOOK_DN_SIG, [{"off": P.LOOK_OFF, "w": 4, "old": P.LOOK_OLD,
                                     "new": per_mode(P.LOOK_NEW)}])
    edit("magdelay", P.MAGDELAY_SIG, [{"off": P.MAGDELAY_OFF, "w": 1, "old": 0x3c,
                                       "new": per_mode(P.MAGDELAY_NEW)}])
    edit("enemyanim", P.ENEMYANIM_SIG, [{"off": P.ENEMYANIM_OFF, "w": 4, "old": 0,
                                         "new": per_mode(P.ENEMYANIM_NEW)}])
    edit("enemyanim_far", P.ENEMYANIM_FAR_SIG, [{"off": P.ENEMYANIM_FAR_OFF, "w": 4, "old": 0,
                                                 "new": per_mode(P.ENEMYANIM_FAR_NEW)}])
    edit("door_open", P.DOOR_OPEN_SIG, [
        {"off": P.DOOR_OPEN_RAMP_OFF, "w": 1, "old": 0x20, "new": per_mode(P.DOOR_OPEN_RAMP)},
        {"off": P.DOOR_OPEN_TRIG_OFF, "w": 1, "old": 0x1f, "new": per_mode(P.DOOR_OPEN_TRIG)}])
    edit("door_openwin", P.DOOR_OPENWIN_SIG, [{"off": P.DOOR_OPENWIN_OFF, "w": 1, "old": 0x20,
                                               "new": per_mode(P.DOOR_OPENWIN)}])
    edit("door_closewin", P.DOOR_CLOSEWIN_SIG, [{"off": P.DOOR_CLOSEWIN_OFF, "w": 1, "old": 0x4c,
                                                 "new": per_mode(P.DOOR_CLOSEWIN)}])
    edit("door_closeramp", P.DOOR_CLOSERAMP_SIG, [{"off": P.DOOR_CLOSERAMP_OFF, "w": 1, "old": 0xe0,
                                                   "new": per_mode(P.DOOR_CLOSERAMP)}])
    # MENU: a byte (repeat count) + a 4-byte word (vsync -> deterministic wait).
    edit("menu", P.MENU_SIG, [
        {"off": P.MENU_OFF, "w": 1, "old": 0x08, "new": per_mode(P.MENU_NEW)},
        {"off": P.MENU_VSYNC_OFF, "w": 4, "old": P.MENU_VSYNC_OLD,
         "new": {"quarter": P.MENU_VSYNC_NEW, "half": P.MENU_VSYNC_NEW}}])
    # notification text speed (3 single-byte edits)
    edit("msg_hold", P.MSG_HOLD_SIG, [{"off": P.MSG_HOLD_OFF, "w": 1, "old": P.MSG_HOLD_OLD,
                                       "new": per_mode(P.MSG_HOLD_NEW)}])
    edit("msg_appear", P.MSG_APPEAR_SIG, [{"off": P.MSG_APPEAR_OFF, "w": 1, "old": P.MSG_APPEAR_OLD,
                                           "new": per_mode(P.MSG_APPEAR_NEW)}])
    edit("msg_disappear", P.MSG_DISAPPEAR_SIG, [{"off": P.MSG_DISAPPEAR_OFF, "w": 1,
                                                 "old": P.MSG_DISAPPEAR_OLD,
                                                 "new": per_mode(P.MSG_DISAPPEAR_NEW)}])
    # item pickup spin (1 byte) + 3 u16 immediates
    edit("itemspin", P.ITEMSPIN_SIG, [{"off": P.ITEMSPIN_OFF, "w": 1, "old": P.ITEMSPIN_OLD,
                                       "new": per_mode(P.ITEMSPIN_NEW)}])
    for name, sig, off, old_u16, new in P.ITEM_IMM_EDITS:
        edit(name, sig, [{"off": off, "w": 2, "old": old_u16, "new": per_mode(new)}])

    # ---- code-cave injections (redirect + cave words) ----
    edit("enemy", P.ENEMY_JSIG, [], cave_obj={
        "patch_off": P.ENEMY_MOVE_OFF, "old": "21b86002", "jmp": "%08x" % P.ENEMY_JMP,
        **cave(P.CAVE_VADDR, P.ENEMY_CAVE)})
    edit("attack", P.ATTACK_SIG, [], cave_obj={
        "patch_off": P.ATTACK_PATCH_OFF, "old": "70186394", "jmp": "%08x" % P.ATTACK_JMP,
        **cave(P.ATK_CAVE_VADDR, P.ATTACK_CAVE)})
    edit("magic", P.MAGIC_SIG, [], cave_obj={
        "patch_off": P.MAGIC_PATCH_OFF, "old": "21186200", "jmp": "%08x" % P.MAGIC_JMP,
        **cave(P.MAG_CAVE_VADDR, P.MAGIC_CAVE)})
    edit("swing", P.SWING_SIG, [], cave_obj={
        "patch_off": P.SWING_PATCH_OFF, "old": "00000296", "jmp": "%08x" % P.SWING_JMP,
        **cave(P.SWING_CAVE_VADDR, P.SWING_CAVE)})
    edit("turnface", P.TURNFACE_SIG, [], cave_obj={
        "patch_off": P.TURNFACE_PATCH_OFF, "old": "58000296", "jmp": "%08x" % P.TURNFACE_JMP,
        **cave(P.TURNFACE_CAVE_VADDR, P.TURNFACE_CAVE)})
    edit("fireanim", P.FIREANIM_SIG, [], cave_obj={
        "patch_off": P.FIREANIM_REDIR_OFF, "old": P.FIREANIM_REDIR_OLD, "jmp": "%08x" % P.FIREANIM_JMP,
        **cave(P.FIREANIM_CAVE_VADDR, P.FIREANIM_CAVE)})
    edit("waterscroll", P.WATERSCROLL_SIG, [], cave_obj={
        "patch_off": P.WATERSCROLL_REDIR_OFF, "old": P.WATERSCROLL_REDIR_OLD,
        "jmp": "%08x" % P.WATERSCROLL_JMP, **cave(P.WATERSCROLL_CAVE_VADDR, P.WATERSCROLL_CAVE)})
    edit("dropedge", P.DROPEDGE_SIG, [], cave_obj={
        "patch_off": P.DROPEDGE_OFF, "old": P.DROPEDGE_OLD, "jmp": "%08x" % P.DROPEDGE_JMP,
        **cave(P.DROPEDGE_CAVE_VADDR, P.DROPEDGE_CAVE)})
    # ENEMYDMG: ÷N frequency gate on the take-a-hit resolver entry (FUN_8002ab18) -- RESEARCH §18.
    edit("enemydmg", P.ENEMYDMG_SIG, [], cave_obj={
        "patch_off": P.ENEMYDMG_PATCH_OFF, "old": P.ENEMYDMG_OLD, "jmp": "%08x" % P.ENEMYDMG_JMP,
        **cave(P.ENEMYDMG_CAVE_VADDR, P.ENEMYDMG_CAVE)})
    # GRAVITY: accel byte edit + redirect-to-cave (one signature).
    edit("gravity", P.GRAV_SIG,
         [{"off": P.GRAV_INC_OFF, "w": 1, "old": 0x28, "new": per_mode(P.GRAV_INC_NEW)}],
         cave_obj={"patch_off": P.GRAV_REDIR_OFF, "old": P.GRAV_REDIR_OLD, "jmp": "%08x" % P.GRAV_JMP,
                   **cave(P.GRAV_CAVE_VADDR, P.GRAV_CAVE)})
    # POISON / MIST: nop the in-line flash store (op) + redirect the tick body to the ÷N gate cave.
    _poison_flash_old = int.from_bytes(bytes.fromhex(P.POISON_FLASH_OLD), "little")
    edit("poison", P.POISON_SIG,
         [{"off": P.POISON_FLASH_OFF, "w": 4, "old": _poison_flash_old,
           "new": {"quarter": 0, "half": 0}}],
         cave_obj={"patch_off": P.POISON_REDIR_OFF, "old": P.POISON_REDIR_OLD,
                   "jmp": "%08x" % P.POISON_JMP, **cave(P.POISON_CAVE_VADDR, P.POISON_CAVE)})

    # ---- patched by absolute vaddr, not signature search (the menu flush copy) ----
    m["menucap"] = {"vaddr": P.MENUCAP_VADDR, "sig": hx(P.MENUCAP_SIG), "off": P.MENUCAP_OFF,
                    "old": "%08x" % P.MENUCAP_OLD, "new": "%08x" % P.MENUCAP_NEW}

    # ---- parameterised: head-bob (--bob on=fix / off=disable) ----
    m["bob"] = {
        "fix": {"sig": hx(P.BOBFIX_SIG),
                "new": {"quarter": hx(P.BOBFIX_NEW["quarter"]), "half": hx(P.BOBFIX_NEW["half"])}},
        "off": {"sig": hx(P.BOB_SIG), "off": P.BOB_OFF},
    }

    # ---- parameterised: FOV (--fov) and widescreen culling (--cull) ----
    m["fov"] = {
        "idiom": hx(P.FOV_IDIOM), "h_default": P.FOV_H_DEFAULT, "ofx": P.FOV_OFX,
        "fogh": {"sig": hx(P.FOGH_SIG), "off": P.FOGH_OFF, "stock": P.FOGH_STOCK},
    }
    m["cull"] = {
        "stock_fov": P.CULL_STOCK_FOV,
        "limiter": P.CULL_LIMITER,          # clamp floor: keep the cone >= this (always cos-scaled)
        "cone": {"sig": hx(P.CULL_SIG), "off": P.CULL_OFF, "stock": P.CULL_STOCK},
        "nearband": {"sig": hx(P.NEARBAND_SIG), "thresh_off": P.NEARBAND_THRESH_OFF,
                     "thresh_new": P.NEARBAND_THRESH_NEW,
                     "nop1": P.NEARBAND_NOP1_OFF, "nop2": P.NEARBAND_NOP2_OFF},
    }
    return m


def main():
    m = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="\n") as f:
        json.dump(m, f, indent=1, sort_keys=False)
        f.write("\n")
    print("wrote %s (%d edits)" % (OUT, len(m["edits"])))


if __name__ == "__main__":
    main()
