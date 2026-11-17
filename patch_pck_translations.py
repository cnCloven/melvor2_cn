#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheme B: register Locale/zh_CN.po inside the embedded PCK's project.binary.

Unlike Scheme A (override.cfg), this edits Melvor2.exe. Always keep a backup
under tools/backups/ and pass --revert to restore.

Two patch modes
---------------
  --replace  (default, safer)
      In-place swap res://Locale/en_GB.po -> res://Locale/zh_CN.po.
      Same string length (21 chars + NUL), so the file does not grow.
      Startup still loads ONE catalog (~2.2 MB), similar to stock (~2.6 MB).
      Language list will likely show Chinese only; English msgids remain as
      fallback for empty msgstr entries.

  --add
      Insert zh_CN.po as a second PackedStringArray element (28 extra bytes
      into the 118-byte slack after project.binary). Loads BOTH catalogs at
      engine setup, which is what broke SteamAPI_Init in Scheme A.

Does not change pack file offsets of any other resource.

Usage
-----
  python patch_pck_translations.py --dry-run
  python patch_pck_translations.py
  python patch_pck_translations.py --add
  python patch_pck_translations.py --revert
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enable_zh_cn_locale import (
    PACK_REL_FILEBASE,
    default_game_dir,
    find_pck_section,
    is_process_running,
    iter_pack_files,
    parse_pe_sections,
    read_pack_header,
    timestamp,
)

EN_PATH = b"res://Locale/en_GB.po\x00"
ZH_PATH = b"res://Locale/zh_CN.po\x00"
assert len(EN_PATH) == len(ZH_PATH) == 22

VARIANT_PACKED_STRING_ARRAY = 34
TRANSLATIONS_KEY = b"internationalization/locale/translations"


def eprint(*args):
    print(*args, file=sys.stderr)


def backup_dir():
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), "backups")


def find_project_binary(f, header):
    """Return pack entry plus byte positions of size and md5 in the directory."""
    pack_off = header["pack_off"]
    dir_off = pack_off + header["dir_rel"]
    f.seek(dir_off)
    (file_count,) = struct.unpack("<I", f.read(4))
    for _ in range(file_count):
        (plen,) = struct.unpack("<I", f.read(4))
        raw = f.read(plen)
        path = raw.decode("utf-8", "replace").rstrip("\x00")
        offset_pos = f.tell()
        offs, size = struct.unpack("<QQ", f.read(16))
        md5_pos = f.tell()
        md5 = f.read(16)
        flags_pos = f.tell()
        (flags,) = struct.unpack("<I", f.read(4))
        if path == "project.binary":
            return {
                "path": path,
                "offset": offs,
                "size": size,
                "flags": flags,
                "md5": md5,
                "offset_pos": offset_pos,
                "md5_pos": md5_pos,
                "size_pos": offset_pos + 8,
                "flags_pos": flags_pos,
            }
    raise RuntimeError("project.binary not found in pack directory")


def read_abs(exe, abs_off, size):
    with open(exe, "rb") as f:
        f.seek(abs_off)
        data = f.read(size)
    if len(data) != size:
        raise RuntimeError("short read at %d" % abs_off)
    return data


def write_abs(exe, abs_off, data):
    with open(exe, "r+b") as f:
        f.seek(abs_off)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def parse_translations_field(blob):
    """Return offsets inside project.binary for the translations variant."""
    idx = blob.find(TRANSLATIONS_KEY)
    if idx < 0:
        raise RuntimeError("translations key not found in project.binary")
    key_len = struct.unpack_from("<I", blob, idx - 4)[0]
    if key_len != len(TRANSLATIONS_KEY):
        raise RuntimeError("unexpected translations key length %d" % key_len)
    var_off = idx + key_len
    size, typ, count, slen = struct.unpack_from("<IIII", blob, var_off)
    if typ != VARIANT_PACKED_STRING_ARRAY:
        raise RuntimeError("translations variant type %d, expected 34" % typ)
    str_off = var_off + 16
    first = blob[str_off : str_off + slen]
    pad = (4 - (slen % 4)) % 4
    first_end = str_off + slen + pad
    expected_size = 4 + 4 + 4 + slen + pad  # type + count + (len+data+pad) for 1 elem
    # size field covers type through last string padding (not including size itself)
    return {
        "var_off": var_off,
        "size": size,
        "type": typ,
        "count": count,
        "slen": slen,
        "str_off": str_off,
        "first": first,
        "pad": pad,
        "first_end": first_end,
        "expected_min_size": expected_size,
    }


def save_backup(meta, blob):
    os.makedirs(backup_dir(), exist_ok=True)
    blob_path = os.path.join(backup_dir(), "project.binary.bak")
    meta_path = os.path.join(backup_dir(), "project.binary.dirmeta.json")
    with open(blob_path, "wb") as f:
        f.write(blob)
    # md5 is bytes -> hex
    dump = dict(meta)
    dump["md5_hex"] = meta["md5"].hex()
    dump.pop("md5", None)
    dump["blob_sha256"] = hashlib.sha256(blob).hexdigest()
    dump["saved_at"] = timestamp()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2)
        f.write("\n")
    return blob_path, meta_path


def load_backup():
    blob_path = os.path.join(backup_dir(), "project.binary.bak")
    meta_path = os.path.join(backup_dir(), "project.binary.dirmeta.json")
    if not os.path.isfile(blob_path) or not os.path.isfile(meta_path):
        raise RuntimeError("no backup at %s" % backup_dir())
    blob = open(blob_path, "rb").read()
    meta = json.load(open(meta_path, encoding="utf-8"))
    meta["md5"] = bytes.fromhex(meta["md5_hex"])
    return blob, meta


def patch_replace(blob, info):
    if info["first"] != EN_PATH:
        if info["first"] == ZH_PATH:
            return blob, False, "already replaced with zh_CN.po"
        raise RuntimeError("first translation path is %r, not en_GB.po" % info["first"])
    out = bytearray(blob)
    out[info["str_off"] : info["str_off"] + len(ZH_PATH)] = ZH_PATH
    return bytes(out), True, "replaced en_GB.po with zh_CN.po (in-place)"


def patch_add(blob, info):
    if info["count"] != 1:
        if info["count"] >= 2 and ZH_PATH in blob[info["str_off"] : info["first_end"] + 40]:
            return blob, False, "zh_CN.po already present"
        raise RuntimeError("translations count is %d, expected 1" % info["count"])
    if info["first"] not in (EN_PATH, ZH_PATH):
        raise RuntimeError("unexpected first path %r" % info["first"])
    extra = struct.pack("<I", len(ZH_PATH)) + ZH_PATH + (b"\x00" * info["pad"])
    if len(extra) != 28:
        raise RuntimeError("extra record size %d, expected 28" % len(extra))
    new_size = info["size"] + len(extra)
    new_count = info["count"] + 1
    out = bytearray(blob)
    struct.pack_into("<I", out, info["var_off"], new_size)
    struct.pack_into("<I", out, info["var_off"] + 8, new_count)
    insert_at = info["first_end"]
    out[insert_at:insert_at] = extra
    return bytes(out), True, "added zh_CN.po (%d extra bytes)" % len(extra)


def write_dir_size_md5(exe, entry, new_size, new_md5):
    with open(exe, "r+b") as f:
        f.seek(entry["size_pos"])
        f.write(struct.pack("<Q", new_size))
        f.seek(entry["md5_pos"])
        f.write(new_md5)
        f.flush()
        os.fsync(f.fileno())


def parse_args():
    p = argparse.ArgumentParser(description="Scheme B: patch project.binary translations")
    p.add_argument("--game-dir", default=default_game_dir())
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--add",
        action="store_true",
        help="Insert zh_CN as a second catalog (Steam-init risk, same as Scheme A)",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="In-place swap en_GB -> zh_CN (default if neither --add nor --replace)",
    )
    p.add_argument("--revert", action="store_true")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.add and args.replace:
        eprint("ERROR: use only one of --add / --replace")
        return 1
    mode = "add" if args.add else "replace"

    exe = os.path.join(os.path.abspath(args.game_dir), "Melvor2.exe")
    print("Exe :", exe)
    print("Mode:", "revert" if args.revert else mode)
    if not os.path.isfile(exe):
        eprint("ERROR: Melvor2.exe not found")
        return 1
    if is_process_running("Melvor2.exe") and not args.force:
        eprint("ERROR: Melvor2.exe is running. Close it, or pass --force.")
        return 1

    sections = parse_pe_sections(exe)
    pack_off, pack_size = find_pck_section(sections)
    with open(exe, "rb") as f:
        header = read_pack_header(f, pack_off)
        entry = find_project_binary(f, header)
    rel = header["file_base"] if (header["flags"] & PACK_REL_FILEBASE) else 0
    abs_off = pack_off + rel + entry["offset"]
    print(
        "PCK off=%d file_base=%d project.binary pack_off=%d size=%d abs=%d md5=%s"
        % (pack_off, rel, entry["offset"], entry["size"], abs_off, entry["md5"].hex())
    )
    slack = header["dir_rel"] - (entry["offset"] + entry["size"])
    print("Slack before directory:", slack)

    if args.revert:
        blob, meta = load_backup()
        print("Restoring %d bytes from backup (sha256 %s)" % (len(blob), meta["blob_sha256"]))
        if args.dry_run:
            print("dry-run: skip write")
            return 0
        write_abs(exe, abs_off, blob)
        # if we previously grew the file, also restore size; extra slack bytes can stay
        write_dir_size_md5(exe, entry, meta["size"], meta["md5"])
        print("Reverted. Launch from Steam.")
        return 0

    blob = read_abs(exe, abs_off, entry["size"])
    digest = hashlib.md5(blob).digest()
    if digest != entry["md5"]:
        eprint(
            "WARNING: pack MD5 %s != computed %s (Godot may not verify this)"
            % (entry["md5"].hex(), digest.hex())
        )
    info = parse_translations_field(blob)
    print(
        "translations count=%d first=%r variant_size=%d"
        % (info["count"], info["first"], info["size"])
    )

    if mode == "replace":
        new_blob, changed, msg = patch_replace(blob, info)
    else:
        new_blob, changed, msg = patch_add(blob, info)
        extra = len(new_blob) - len(blob)
        if extra > slack:
            raise RuntimeError("need %d slack bytes, only %d available" % (extra, slack))
    print("Patch:", msg, "changed=", changed, "new_size=", len(new_blob))

    if not changed:
        print("Nothing to do.")
        return 0
    if args.dry_run:
        print("dry-run: skip write. Backup would go to", backup_dir())
        return 0

    b1, b2 = save_backup(entry, blob)
    print("Backup:", b1)
    print("Meta  :", b2)

    # For --add the on-disk region is larger than the old size field.
    write_abs(exe, abs_off, new_blob)
    new_md5 = hashlib.md5(new_blob).digest()
    write_dir_size_md5(exe, entry, len(new_blob), new_md5)
    print("Wrote project.binary size=%d md5=%s" % (len(new_blob), new_md5.hex()))

    # Verify
    with open(exe, "rb") as f:
        header2 = read_pack_header(f, pack_off)
        entry2 = find_project_binary(f, header2)
    blob2 = read_abs(exe, abs_off, entry2["size"])
    info2 = parse_translations_field(blob2)
    print(
        "Verify count=%d first=%r size=%d md5_ok=%s"
        % (
            info2["count"],
            info2["first"],
            entry2["size"],
            entry2["md5"] == hashlib.md5(blob2).digest(),
        )
    )
    print("")
    print("Launch the game FROM STEAM (not Melvor2.exe).")
    print("If Steam/license error: python patch_pck_translations.py --revert")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        eprint("ERROR:", ex)
        sys.exit(1)
