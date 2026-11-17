#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dump ECFG keys around internationalization/locale/translations (read-only)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enable_zh_cn_locale import (
    default_game_dir,
    find_pck_section,
    iter_pack_files,
    parse_pe_sections,
    read_pack_header,
    PACK_REL_FILEBASE,
)

exe = os.path.join(default_game_dir(), "Melvor2.exe")
sections = parse_pe_sections(exe)
pack_off, _ = find_pck_section(sections)
with open(exe, "rb") as f:
    header = read_pack_header(f, pack_off)
    rel = header["file_base"] if (header["flags"] & PACK_REL_FILEBASE) else 0
    entry = None
    for e in iter_pack_files(f, header):
        if e["path"] == "project.binary":
            entry = e
            break
    assert entry, "project.binary missing"
    abs_off = pack_off + rel + entry["offset"]
    f.seek(abs_off)
    blob = f.read(entry["size"])

print("project.binary offset", entry["offset"], "size", entry["size"], "abs", abs_off)
print("magic", blob[:4], "file_end_rel", entry["offset"] + entry["size"], "dir_rel", header["dir_rel"])
print("slack", header["dir_rel"] - (entry["offset"] + entry["size"]))

# Walk ECFG: "ECFG" + repeated (u32 key_len, key bytes, encoded variant)
assert blob[:4] == b"ECFG"
pos = 4
# some versions store leftover/custom feature count
print("after magic u32s", struct.unpack_from("<II", blob, 4))

# Try: ECFG, then u32 count of properties
count = struct.unpack_from("<I", blob, 4)[0]
print("possible prop count", count)
pos = 8


def read_pascal(buf, i):
    n = struct.unpack_from("<I", buf, i)[0]
    i += 4
    s = buf[i : i + n]
    i += n
    pad = (4 - (n % 4)) % 4
    i += pad
    return s, i, n, pad


# Dump first few and the translations key
shown = 0
i = pos
keys = []
while i + 4 <= len(blob) and shown < 8:
    try:
        key, j, n, pad = read_pascal(blob, i)
        key_s = key.decode("utf-8")
    except Exception as ex:
        print("fail at", i, ex)
        break
    print("KEY @%d len=%d pad=%d %r next4=%s" % (i, n, pad, key_s[:80], blob[j : j + 16].hex()))
    keys.append((i, key_s, j))
    # skip variant: first u32 might be length
    # print more
    shown += 1
    # naive skip: we don't know variant size yet
    break

# Find translations key by bytes
needle = b"internationalization/locale/translations"
idx = blob.find(needle)
print("needle idx", idx)
print("bytes before key (8):", blob[idx - 8 : idx].hex())
print("bytes after key (64):", blob[idx + len(needle) : idx + len(needle) + 64].hex())
print("ascii after:", "".join(chr(b) if 32 <= b < 127 else "." for b in blob[idx - 4 : idx + 80]))
