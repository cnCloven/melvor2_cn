# Melvor Idle 2 简体中文：背景、原理、方案 B

**结论：游戏包里本来就有 `Locale/zh_CN.po`，缺的是把它写进 `project.binary` 的 `internationalization/locale/translations`。方案 B 把这条路径从 `res://Locale/en_GB.po` 原地换成 `res://Locale/zh_CN.po` 之后，从 Steam 启动即可走中文。**

相关文件都在本目录：

| 路径 | 作用 |
|---|---|
| `tools/zh-CN-hanhua.md` | 本文 |
| `tools/patch_pck_translations.py` | 方案 B：改 `Melvor2.exe` 里的 `project.binary` |
| `tools/enable_zh_cn_locale.py` | 方案 A：抽 `.po`、写 `override.cfg`（默认不再注入） |
| `tools/extracted/Locale/zh_CN.po` | 从包里抽出的简中目录备份 |
| `tools/backups/project.binary.bak` | 方案 B 打补丁前的 `project.binary` |
| `tools/backups/project.binary.dirmeta.json` | 原 size / md5，供 `--revert` |

不改 `GamesByMalcs.Melvor2.dll`。不要对 Steam 使用「验证游戏文件完整性」，那会还原 `Melvor2.exe`。

---

## 1. 使用场景

需求：界面和数据说明显示简体中文。

环境：

- 游戏：`Melvor2.exe`（Godot 4.7.2 + .NET 10，版本日志里是 `0.11.6-alpha.1`）
- 资源在 exe 的 PE 节 `.pck` 里，不是旁边单独的 `.pck` 文件
- 系统区域是 `zh_CN` 时，Godot 的 `Project Locale` 会跟系统走
- 必须从 Steam 启动，不要双击 `Melvor2.exe`（否则会走 `Failed to initialize Steam` / `Please start the game through Steam.`）

用哪条命令（方案 B，当前生效的做法）：

```text
python tools/patch_pck_translations.py
python tools/patch_pck_translations.py --dry-run
python tools/patch_pck_translations.py --revert
```

默认是 `--replace`（原地换路径）。`--add` 会再塞一份目录，启动阶段会多解析约 2.5MB，容易再次卡 `SteamAPI_Init`。

---

## 2. 文本实际放在哪

安装目录里没有散开的中文 txt。玩家看到的字来自这几处：

| 位置 | 内容 |
|---|---|
| `Locale/zh_CN.po` | gettext 简中，约 10408 条 `msgid`，约 14.2 万汉字 |
| `Locale/en_GB.po` | 英文目录，约 11541 条 `msgid` |
| `Locale/fr.po` | 几乎空壳，仍是英文 |
| `Data/Packages/MelvorBase.json` | 英文底稿（物品名、词条模板等），再被抽进 `.po` |
| `Localization/*.cs` | 逻辑占位，导出后大小为 1 字节，真代码在 `GamesByMalcs.Melvor2.dll` |
| `GamesByMalcs.Melvor2.dll` | `SetLocale`、`PopulateLanguageOptions`、`GetLoadedLocales`、`TranslationServer` |

`zh_CN.po` 头信息：`Language: zh_CN`，`charset=UTF-8`。例如：

```
msgid "Options"
msgstr "选项"

msgid "Local Save"
msgstr "本地存档"
```

约 982 条 `msgstr` 仍是空的，那些会继续显示英文 `msgid`。

运行时链路：

1. Godot 启动时读 `project.binary` 的 `internationalization/locale/translations`
2. 把列出的 `.po` 交给 `TranslationServer`
3. 游戏 C# 用 `GetLoadedLocales` / `PopulateLanguageOptions` 填语言列表
4. `UserSettings.json` 的 `Language` 以及 `TranslationServer.SetLocale` 决定当前语言

打补丁之前，`project.binary` 只登记了：

```
res://Locale/en_GB.po
```

`zh_CN.po` 人在包里，但不在这个数组里，所以 `GetLoadedLocales` 看不到中文。

---

## 3. 包格式（读 `Melvor2.exe` 时用到的事实）

- `Melvor2.exe` 约 630MB，PE 节名 `pck`，起始偏移 `109411328`，约 496MB
- 魔数 `GDPC`，pack format **v4**（Godot 4.7.2）
- `PACK_REL_FILEBASE`：文件数据偏移 = `pck节起始 + file_base(112) + 条目offset`
- 目录在包尾，相对偏移 `519120160`，共 14741 个文件
- `project.binary` 是目录前最后一个文件：pack 内 offset `519036352`，size `83690`
- 它后面到目录之间有 **118 字节**空隙（方案 B 的 `--add` 只用 28 字节；`--replace` 不用空隙）

`project.binary` 是 Godot `ECFG`：键 `internationalization/locale/translations`，值类型 `PackedStringArray`（variant type `34`）。

打补丁前该数组只有 1 个元素：

```
res://Locale/en_GB.po\0
```

`res://Locale/en_GB.po` 和 `res://Locale/zh_CN.po` 都是 21 个字符 + `\0` = 22 字节，所以可以原地改字母，不必移动后面的键。

---

## 4. 试过的方案

### 方案 A：`override.cfg`（失败，已撤回）

写：

`%APPDATA%\Games By Malcs\Melvor Idle 2\device_settings\override.cfg`

```
[internationalization]
locale/translations=PackedStringArray("res://Locale/en_GB.po", "res://Locale/zh_CN.po")
```

这会在 **Godot 引擎 setup、Steamworks 尚未 Init** 时解析两份目录（约 4.8MB）。日志表现为：打出 `Project Locale: zh_CN` 后约 18 秒退出，没有 `Steam account linked`，没有主菜单。界面上容易看成「无许可」。游戏内对应英文是 `Error Initializing Steam` / `Please start the game through Steam.`。

`enable_zh_cn_locale.py` 默认改为只抽取 `.po`。若误注入了：

```text
python tools/enable_zh_cn_locale.py --revert
```

### 方案 B：改 `project.binary`（当前在用，成功）

见下一节。

### 方案 C：未做

等 `SteamAPI_Init` 成功后再 `TranslationServer.AddTranslation`。要改 `GamesByMalcs.Melvor2.dll` 或打 Harmony，才能双语列表且不拖启动。

---

## 5. 方案 B 原理

官方加载路径就是 `project.binary` → `internationalization/locale/translations`。把这里的路径改成 `res://Locale/zh_CN.po` 之后：

- 启动仍只加载 **一份** 目录（约 2.2MB），体量和原来的 `en_GB.po`（约 2.6MB）接近，不再拖死 Steam
- 系统区域 `zh_CN` 时，`TranslationServer` 直接用简中
- `GetLoadedLocales` 里主要是 `zh_CN`，设置里的语言列表可能只剩中文
- 空 `msgstr` 继续显示英文 `msgid`

`--replace`（已执行）：只改那 5 个字符（`en_GB` → `zh_CN`），`project.binary` 长度仍是 `83690`，更新 PCK 目录里该文件的 MD5。

`--add`（未执行）：在 `PackedStringArray` 里再插入 `res://Locale/zh_CN.po`（28 字节），启动加载两份目录，和方案 A 同一类风险。

---

## 6. 方案 B 执行方式

前提：完全退出 `Melvor2.exe`。

```text
python tools/patch_pck_translations.py --dry-run
python tools/patch_pck_translations.py
```

脚本会：

1. 只读解析 PE 节 `.pck` 和 pack v4 目录，定位 `project.binary`
2. 解析 `ECFG` 里 `internationalization/locale/translations`
3. 把 `tools/backups/project.binary.bak` 和 `project.binary.dirmeta.json` 写好
4. 原地把 `res://Locale/en_GB.po` 换成 `res://Locale/zh_CN.po`
5. 回写文件字节，并更新目录中的 size、md5
6. 再读一遍做校验

本次实际结果：

```
Verify count=1 first=b'res://Locale/zh_CN.po\x00' size=83690 md5_ok=True
```

然后 **从 Steam 启动**。不要验证游戏完整性。

还原：

```text
python tools/patch_pck_translations.py --revert
```

`--revert` 用备份把 `project.binary` 整段和目录里的 size/md5 写回去。

---

## 7. 正反例子

| | 命令 | 结果 |
|---|---|---|
| 正 | `python tools/patch_pck_translations.py` 后从 Steam 启动 | `translations` 只有 `res://Locale/zh_CN.po`，界面中文 |
| 反 | 同一补丁后双击 `Melvor2.exe` | 走 `Please start the game through Steam.`，不像汉化失败 |
| 反 | `python tools/enable_zh_cn_locale.py --inject-override` | `override.cfg` 在 Steam Init 前加载两份 `.po`，约 18 秒退出 |
| 反 | Steam「验证游戏文件完整性」 | `Melvor2.exe` 回到只有 `en_GB.po` 的官方字节 |
| 反 | `python tools/patch_pck_translations.py --add` | 数组变成两条，启动体积回到方案 A 那档 |

改回英文界面：`--revert`，不要手改 `override.cfg` 里的 `locale/translations` 来「临时切语言」。

---

## 8. 没有的能力

- 没有把 `zh_CN.po` 再打进包里的步骤：文件本来就在 `res://Locale/zh_CN.po`
- `enable_zh_cn_locale.py` 默认不会写 `override.cfg`；没有「注入即官方加载」这回事
- `patch_pck_translations.py --replace` 不会保留 `en_GB.po` 在 `GetLoadedLocales` 里
- 没有自动补全那 982 条空 `msgstr`
- 没有改 `GamesByMalcs.Melvor2.dll`，也没有 Harmony
- 没有独立 `.pck` 热更新；用户目录里的抽出文件不会被游戏自动读
- Steam 验证会覆盖补丁；脚本不会对抗校验
