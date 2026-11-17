#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-click launcher for Scheme B. No Python/Node required after PyInstaller build.

Double-click Melvo2CN.exe, pick Apply or Revert. Finds Melvor2.exe via Steam
libraries. Bundles the stock project.binary backup for revert.
"""

from __future__ import print_function

import os
import sys


def _enable_utf8_console():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def pause():
    try:
        input("\nPress Enter to exit / 按回车退出...")
    except EOFError:
        pass


def print_banner(game_dir):
    print("=" * 60)
    print("  Melvo2CN  -  Melvor Idle 2  Simplified Chinese patch")
    print("  Scheme B: project.binary  internationalization/locale/translations")
    print("=" * 60)
    print("Game dir:", game_dir)
    exe = os.path.join(game_dir, "Melvor2.exe")
    print("Melvor2.exe:", "OK" if os.path.isfile(exe) else "NOT FOUND")
    print("")
    print("  [1] Apply Chinese patch  (en_GB.po -> zh_CN.po)")
    print("  [2] Revert to English    (restore project.binary.bak)")
    print("  [3] Exit")
    print("")
    print("Always launch the game FROM STEAM after patching.")
    print("Do not use Steam 'Verify integrity of game files'.")
    print("=" * 60)


def ask_game_dir(current):
    exe = os.path.join(current, "Melvor2.exe")
    if os.path.isfile(exe):
        return current
    print("Could not find Melvor2.exe.")
    print("Paste the folder that contains Melvor2.exe, then Enter.")
    try:
        typed = input("> ").strip().strip('"')
    except EOFError:
        return current
    return typed or current


def main():
    _enable_utf8_console()
    # Allow the same CLI flags as patch_pck_translations.py
    if any(a in sys.argv[1:] for a in ("-h", "--help", "--revert", "--add", "--replace", "--dry-run")):
        from patch_pck_translations import main as patch_main

        return patch_main()

    from enable_zh_cn_locale import find_melvor2_dir
    from patch_pck_translations import run_patch

    game_dir = find_melvor2_dir()
    print_banner(game_dir)
    game_dir = ask_game_dir(game_dir)
    if not os.path.isfile(os.path.join(game_dir, "Melvor2.exe")):
        print("ERROR: Melvor2.exe not found in:", game_dir)
        return 1

    try:
        choice = input("Select 1/2/3: ").strip()
    except EOFError:
        choice = "3"

    if choice == "1":
        rc = run_patch(game_dir, revert=False, mode="replace")
    elif choice == "2":
        rc = run_patch(game_dir, revert=True)
    else:
        print("Bye.")
        return 0
    return rc


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except Exception as ex:
        print("ERROR:", ex)
        code = 1
    if getattr(sys, "frozen", False) or os.environ.get("MELVO2CN_PAUSE"):
        pause()
    sys.exit(code)
