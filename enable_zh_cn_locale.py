#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enable the shipped Simplified Chinese catalog without patching Melvor2.exe.

Scheme A
--------
The Godot pack already contains res://Locale/zh_CN.po, but project.binary only
registers res://Locale/en_GB.po. This script does not touch the executable.
It:

  1. Parses the embedded Godot PCK inside Melvor2.exe (read-only).
  2. Extracts Locale/zh_CN.po to a local backup folder for inspection/editing.
  3. Merges translation keys into Godot's project-settings override file:
       %APPDATA%/Games By Malcs/Melvor Idle 2/device_settings/override.cfg
  4. Sets Language=zh_CN in each steam/*/userSettings.json found.

IMPORTANT
---------
Registering the .po files in override.cfg loads ~4.8 MB of gettext catalogs
during Godot engine setup, before Steamworks initializes. That delay can make
SteamAPI_Init fail (dialog: start via Steam / no license) and the process
exits within ~20 seconds. Default mode is therefore EXTRACT ONLY.

Use --inject-override only for experiments. Use --revert to undo it.

Does not modify Melvor2.exe, DLLs, or any other Steam install binary.

Usage
-----
  python enable_zh_cn_locale.py
  python enable_zh_cn_locale.py --revert
  python enable_zh_cn_locale.py --inject-override
  python enable_zh_cn_locale.py --dry-run
  python enable_zh_cn_locale.py --game-dir "C:\\SteamLibrary\\steamapps\\common\\Melvor Idle 2"
"""

from __future__ import print_function

import argparse
import datetime
import json
import os
import shutil
import struct
import sys

# Godot 4 pack magic "GDPC" (little-endian 0x43504447).
PACK_MAGIC = 0x43504447
PACK_REL_FILEBASE = 1 << 1

# Paths inside the pack / project settings.
PO_PACK_PATH = "Locale/zh_CN.po"
EN_PO_RES = "res://Locale/en_GB.po"
ZH_PO_RES = "res://Locale/zh_CN.po"
TARGET_LOCALE = "zh_CN"

# Marker so a later run can find the block we own without wiping [display].
OVERRIDE_COMMENT = (
    "; --- managed by enable_zh_cn_locale.py (Scheme A). "
    "Do not remove if you want zh_CN loaded. ---"
)


def eprint(*args):
    print(*args, file=sys.stderr)


def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def is_process_running(image_name):
    """Return True if a Windows process with this image name is running."""
    try:
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image_name, "/NH"],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        return image_name.lower() in out.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PE / Godot PCK (read-only)
# ---------------------------------------------------------------------------

def parse_pe_sections(exe_path):
    """Yield (name, raw_ptr, raw_size) for each PE section."""
    with open(exe_path, "rb") as f:
        mz = f.read(2)
        if mz != b"MZ":
            raise RuntimeError("Not a PE file: %s" % exe_path)
        f.seek(0x3C)
        pe_off = struct.unpack("<I", f.read(4))[0]
        f.seek(pe_off)
        if f.read(4) != b"PE\x00\x00":
            raise RuntimeError("Missing PE signature: %s" % exe_path)
        _machine, num_sections = struct.unpack("<HH", f.read(4))
        f.read(12)  # timestamp, pointers
        opt_size, _chars = struct.unpack("<HH", f.read(4))
        f.seek(pe_off + 24 + opt_size)
        sections = []
        for _ in range(num_sections):
            rec = f.read(40)
            name = rec[:8].split(b"\x00", 1)[0].decode("ascii", "replace")
            _vsize, _va, raw_size, raw_ptr = struct.unpack("<IIII", rec[8:24])
            sections.append((name, raw_ptr, raw_size))
        return sections


def find_pck_section(sections):
    for name, raw_ptr, raw_size in sections:
        if name == "pck":
            return raw_ptr, raw_size
    raise RuntimeError("No PE section named 'pck' (Godot embedded pack).")


def read_pack_header(f, pack_off):
    """
    Parse a Godot 4.x pack header at pack_off.

    Format v4 (Godot 4.7): directory lives at the end of the pack.
    After file_base (u64), the next u64 is the directory offset relative
    to the pack start. flags bit 1 = PACK_REL_FILEBASE.
    """
    f.seek(pack_off)
    magic, version, ver_maj, ver_min, ver_pat, flags = struct.unpack(
        "<IIIIII", f.read(24)
    )
    if magic != PACK_MAGIC:
        raise RuntimeError("GDPC magic not found at pack start (got 0x%08X)." % magic)
    file_base = struct.unpack("<Q", f.read(8))[0]
    dir_rel = struct.unpack("<Q", f.read(8))[0]
    return {
        "version": version,
        "godot": (ver_maj, ver_min, ver_pat),
        "flags": flags,
        "file_base": file_base,
        "dir_rel": dir_rel,
        "pack_off": pack_off,
    }


def iter_pack_files(f, header):
    """Yield dicts: path, offset, size, flags for each pack entry."""
    pack_off = header["pack_off"]
    f.seek(pack_off + header["dir_rel"])
    (file_count,) = struct.unpack("<I", f.read(4))
    if file_count <= 0 or file_count > 1_000_000:
        raise RuntimeError("Implausible pack file_count: %d" % file_count)
    for _ in range(file_count):
        (plen,) = struct.unpack("<I", f.read(4))
        if plen > 8192:
            raise RuntimeError("Implausible pack path length: %d" % plen)
        raw = f.read(plen)
        path = raw.decode("utf-8", "replace").rstrip("\x00")
        offs, size = struct.unpack("<QQ", f.read(16))
        f.read(16)  # md5
        (fflags,) = struct.unpack("<I", f.read(4))
        yield {"path": path, "offset": offs, "size": size, "flags": fflags}


def extract_pack_file(exe_path, entry, header, dest_path):
    """Copy one pack blob to dest_path. Does not modify the exe."""
    rel = header["file_base"] if (header["flags"] & PACK_REL_FILEBASE) else 0
    abs_off = header["pack_off"] + rel + entry["offset"]
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(exe_path, "rb") as f:
        f.seek(abs_off)
        data = f.read(entry["size"])
    if len(data) != entry["size"]:
        raise RuntimeError("Short read for %s" % entry["path"])
    with open(dest_path, "wb") as out:
        out.write(data)
    return data


# ---------------------------------------------------------------------------
# Godot override.cfg merge
# ---------------------------------------------------------------------------

def packed_string_array(paths):
    inner = ", ".join('"%s"' % p.replace("\\", "/") for p in paths)
    return "PackedStringArray(%s)" % inner


def merge_override_cfg(original_text, translation_paths, fallback_locale):
    """
    Keep every existing section (the game writes [display] here).
    Insert or replace [internationalization] locale/translations + fallback.
    """
    text = original_text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"

    # Drop a previous copy of our section so re-runs stay clean.
    lines = text.split("\n")
    out = []
    skipping = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("[internationalization]"):
            skipping = True
            i += 1
            continue
        if skipping:
            if line.startswith("[") and line.endswith("]"):
                skipping = False
                # fall through to keep this new section header
            else:
                i += 1
                continue
        if line.strip() == OVERRIDE_COMMENT.strip():
            i += 1
            continue
        out.append(line)
        i += 1

    # Trim trailing empty lines, then append our section.
    while out and out[-1] == "":
        out.pop()

    trans_value = packed_string_array(translation_paths)
    block = [
        "",
        OVERRIDE_COMMENT,
        "[internationalization]",
        "",
        "locale/translations=%s" % trans_value,
        'locale/fallback="%s"' % fallback_locale,
        "",
    ]
    merged = "\n".join(out) + "\n" + "\n".join(block)
    if not merged.startswith("config_version="):
        # Preserve Godot 4 header if the original had it; otherwise add it.
        if "config_version=" not in merged.split("\n", 3)[0]:
            merged = "config_version=5\n\n" + merged.lstrip("\n")
    return merged


def strip_override_translations(original_text):
    """Remove [internationalization] and our marker; keep [display] intact."""
    text = original_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out = []
    skipping = False
    for line in lines:
        if line.startswith("[internationalization]"):
            skipping = True
            continue
        if skipping:
            if line.startswith("[") and line.endswith("]"):
                skipping = False
            else:
                continue
        if line.strip() == OVERRIDE_COMMENT.strip():
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    out.append("")
    return "\n".join(out) + "\n"


def backup_file(path):
    bak = path + ".bak-" + timestamp()
    shutil.copy2(path, bak)
    return bak


# ---------------------------------------------------------------------------
# userSettings.json
# ---------------------------------------------------------------------------

def patch_user_settings(path, locale, dry_run):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig")
    data = json.loads(text)
    old = data.get("Language", "")
    if old == locale:
        print("  Language already %r in %s" % (locale, path))
        return False
    print("  Language %r -> %r in %s" % (old, locale, path))
    if dry_run:
        return True
    backup_file(path)
    data["Language"] = locale
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def default_game_dir():
    here = os.path.abspath(os.path.dirname(__file__))
    parent = os.path.dirname(here)
    if os.path.isfile(os.path.join(parent, "Melvor2.exe")):
        return parent
    return os.path.abspath(
        r"C:\SteamLibrary\steamapps\common\Melvor Idle 2"
    )


def default_user_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set.")
    return os.path.join(appdata, "Games By Malcs", "Melvor Idle 2")


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Enable Locale/zh_CN.po via Godot override.cfg (does not patch the exe)."
        )
    )
    p.add_argument(
        "--game-dir",
        default=default_game_dir(),
        help="Folder that contains Melvor2.exe",
    )
    p.add_argument(
        "--user-dir",
        default=None,
        help="Godot user:// root (default: %%APPDATA%%/Games By Malcs/Melvor Idle 2)",
    )
    p.add_argument(
        "--extract-dir",
        default=None,
        help="Where to write the extracted .po backup (default: <script>/extracted)",
    )
    p.add_argument(
        "--skip-extract",
        action="store_true",
        help="Do not dump Locale/zh_CN.po from the pack",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing user files",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Continue even if Melvor2.exe is running",
    )
    p.add_argument(
        "--inject-override",
        action="store_true",
        help=(
            "UNSAFE: register zh_CN.po in override.cfg. Can block Steam init. "
            "Prefer --revert if the game shows a license / Steam error."
        ),
    )
    p.add_argument(
        "--revert",
        action="store_true",
        help="Remove [internationalization] from override.cfg (keeps display settings)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    game_dir = os.path.abspath(args.game_dir)
    exe_path = os.path.join(game_dir, "Melvor2.exe")
    user_dir = os.path.abspath(args.user_dir or default_user_dir())
    extract_dir = args.extract_dir or os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "extracted"
    )

    print("Game dir :", game_dir)
    print("Exe      :", exe_path)
    print("User dir :", user_dir)
    print("Extract  :", extract_dir)
    print("Dry run  :", args.dry_run)

    if not os.path.isfile(exe_path):
        eprint("ERROR: Melvor2.exe not found.")
        return 1
    if not os.path.isdir(user_dir):
        eprint("ERROR: user dir not found (launch the game once first): %s" % user_dir)
        return 1

    game_running = is_process_running("Melvor2.exe")
    if game_running:
        eprint(
            "WARNING: Melvor2.exe is running. Pack extract and override.cfg "
            "will still run. userSettings.json is skipped unless --force "
            "(the live game would overwrite Language on save)."
        )
        if args.force:
            eprint("WARNING: --force set; writing userSettings.json anyway.")

    # --- 1. Read-only pack parse + optional extract ---
    sections = parse_pe_sections(exe_path)
    pack_off, pack_size = find_pck_section(sections)
    print("PCK section: offset=%d size=%d" % (pack_off, pack_size))

    po_entry = None
    header = None
    with open(exe_path, "rb") as f:
        header = read_pack_header(f, pack_off)
        print(
            "Pack format v%d Godot %d.%d.%d flags=0x%X"
            % (
                header["version"],
                header["godot"][0],
                header["godot"][1],
                header["godot"][2],
                header["flags"],
            )
        )
        for entry in iter_pack_files(f, header):
            if entry["path"] == PO_PACK_PATH:
                po_entry = entry
                break

    if po_entry is None:
        eprint("ERROR: %s not found inside the pack." % PO_PACK_PATH)
        return 1

    print(
        "Found %s size=%d flags=%d"
        % (po_entry["path"], po_entry["size"], po_entry["flags"])
    )

    if not args.skip_extract:
        dest_po = os.path.join(extract_dir, "Locale", "zh_CN.po")
        print("Extract ->", dest_po)
        if not args.dry_run:
            data = extract_pack_file(exe_path, po_entry, header, dest_po)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                eprint("WARNING: extracted file is not valid UTF-8.")
            else:
                cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
                print("  UTF-8 OK, CJK ideographs=%d, msgid=%d" % (cjk, text.count("msgid ")))
                if "Language: zh_CN" not in text:
                    eprint("WARNING: header does not contain 'Language: zh_CN'.")

    # --- 2. override.cfg ---
    override_path = os.path.join(user_dir, "device_settings", "override.cfg")
    print("Override :", override_path)
    if os.path.isfile(override_path):
        original = open(override_path, "r", encoding="utf-8-sig").read()
    else:
        original = "config_version=5\n"

    if args.revert:
        stripped = strip_override_translations(original)
        print("  Reverting [internationalization] from override.cfg")
        if not args.dry_run and stripped != original.replace("\r\n", "\n").replace("\r", "\n"):
            bak = backup_file(override_path) if os.path.isfile(override_path) else None
            if bak:
                print("  Backup:", bak)
            tmp = override_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(stripped)
            os.replace(tmp, override_path)
            print("  Wrote", override_path)
        print("Done. Launch the game FROM STEAM.")
        return 0

    if args.inject_override:
        merged = merge_override_cfg(
            original,
            translation_paths=[EN_PO_RES, ZH_PO_RES],
            fallback_locale="en_GB",
        )
        print("  WARNING: --inject-override can break SteamAPI_Init.")
        if not args.dry_run:
            os.makedirs(os.path.dirname(override_path), exist_ok=True)
            if os.path.isfile(override_path):
                bak = backup_file(override_path)
                print("  Backup:", bak)
            tmp = override_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(merged)
            os.replace(tmp, override_path)
            print("  Wrote", override_path)
    else:
        print("  Skipping override.cfg inject (default). Use --inject-override to try it.")
        print("  Use --revert if a previous inject blocked Steam.")

    # --- 3. Set Language in every Steam-account userSettings.json ---
    if not args.inject_override:
        print("")
        print("Extract finished. zh_CN.po is in the extract folder.")
        print("Do not inject override.cfg: it can abort Steam init.")
        print("Next step is Scheme B/C (load translations AFTER Steam is up).")
        if args.dry_run:
            print("(dry-run: no files were written)")
        return 0
    steam_root = os.path.join(user_dir, "steam")
    patched = 0
    skip_user_settings = game_running and not args.force
    if skip_user_settings:
        eprint(
            "Skipping userSettings.json while the game is running. "
            "Close Melvor2.exe and re-run this script to set Language=zh_CN."
        )
    elif os.path.isdir(steam_root):
        for account in os.listdir(steam_root):
            settings_path = os.path.join(steam_root, account, "userSettings.json")
            if os.path.isfile(settings_path):
                if patch_user_settings(settings_path, TARGET_LOCALE, args.dry_run):
                    patched += 1
    else:
        eprint("WARNING: no steam/ folder under user dir; Language was not set.")

    print("")
    print("Done. If Steam failed after inject, run: python enable_zh_cn_locale.py --revert")
    print("Always launch the game FROM STEAM, not by double-clicking Melvor2.exe.")
    if args.dry_run:
        print("(dry-run: no files were written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
