# melvo2_cn

Melvor Idle 2 简体中文补丁工具（方案 B：改 `project.binary` 里的 `internationalization/locale/translations`）。

说明见 [zh-CN-hanhua.md](zh-CN-hanhua.md)。

## 没有 Python 的电脑

下载 Release 里的 `Melvo2CN.exe`，双击：

1. 打中文补丁
2. 还原英文

从 Steam 启动游戏。不要验证游戏完整性。Windows 可能对 PyInstaller 报毒，选仍要运行。

## 有 Python 时

```text
python patch_pck_translations.py --dry-run
python patch_pck_translations.py
python patch_pck_translations.py --revert
```

打包 exe（仅构建机需要 Python）：

```text
powershell -File build_exe.ps1
```
