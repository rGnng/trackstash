# Apple Music / iTunes 命名与库结构分析

> **本文是最早的分析记录，部分结论已被后续实测修正。**
> 当前的权威记录请参阅：
> - `docs/MUSIC_ITUNES_BEHAVIOR.md` —— Music 的导入、改名、标签读取行为（含碟号矩阵、合辑读取、长度上限）。
> - `docs/FILENAME_COMPATIBILITY.md` —— NTFS/exFAT 兼容规则与现有库审计。
>
> 主要更正：合辑的 757 首"不一致"是 TrackStash 的读取 bug（文本 `'0'` 被 mutagen 当成真值），Music 和库都是正确的；最终匹配率为 17,918 / 20,829（86.0%），而不是下文早期数字。

| | |
|---|---|
| **状态** | 完成（库侧真值 + Music 实测 + TrackStash 对比） |
| **音频目录** | `/Volumes/New Volume/MusicLocal/Media.localized/Music`（exFAT） |
| **库** | `/Volumes/New Volume/MusicLocal/Music Library.musiclibrary` |
| **备份** | `backups/musiclibrary-20261110-213343`（写入前的完整副本） |
| **真值来源** | Music.app AppleScript 批量只读导出（`itunes_export.tsv`，20,829 行） |

## 0. 更正

- 早期的 20,806 首与"23 个库外文件"是**解析错误**。导出的标题以 `"` 开头时，csv 默认引号规则把后续行合并了。正确数字是 **20,829 首**，与磁盘上的音频文件一一对应（库外 0 个、磁盘缺失 0 个）。
- 早期基于错误解析的统计（合辑 870/1,627、82.7%、78% 等）已作废，以下数字全部基于修正后的解析。
- Music 启动时没有自动导入任何文件。

## 1. 数据概览

| 项目 | 数值 |
|---|---|
| 库内曲目 | 20,829（导出前快照） |
| 磁盘音频文件 | 20,829 |
| 库与磁盘 | 一一对应 |
| 类型 | Apple Lossless 14,396；MPEG audio 4,863；AAC 954；Purchased AAC 574；MPEG-4 video 19 |
| 扩展名 | `.m4a` 15,924，`.mp3` 4,863，`.mp4` 19（全部小写，来自原始文件） |
| 最长路径组件 | 139 字符 / 224 字节 |
| Unicode 形式 | 磁盘上 3,036 个名字为 NFD（分解形式） |

## 2. Music 的实测行为（实验，非推断）

所有实验都在 Music 的 MusicLocal 库里进行，用 ffmpeg 生成静音 m4a，用 TrackStash 的 `write_tags` 写入标签。

### 2.1 导入时的命名（20 个用例，与 TrackStash 规则逐条对比）

| 用例 | 标签 | Music 结果 | TrackStash（修正后） |
|---|---|---|---|
| 标题含点 | `O.O.H` | `16 O.O.H.m4a` | 一致 |
| 标题含点+文字 | `Mr. Hyde` | `01 Mr. Hyde.m4a` | 一致 |
| 标签含 `/` | `w/FullMoon` | `w_FullMoon` | 一致 |
| 艺术家含 `:`，专辑含 `*` `?` | `Glassy:oceaN` / `Star*Album?` | `Glassy_oceaN/Star_Album_` | 一致 |
| 艺术家末尾 `.` | `V.A.` | `V.A_` | 一致 |
| 艺术家末尾空格 | `Cosmo Burst ` | `Cosmo Burst` | 一致 |
| 标题末尾空格 | `Desire Drive ` | `03 Desire Drive.m4a` | 一致 |
| 弯引号 | `Shelter’s “X”` | `Shelter_s _X_` | 一致 |
| 方括号 | `31 days [MUSIC SELECT]` | 保留 `[ ]` | 一致 |
| 无曲目号 | `Otenba Sensation!!` | 无前缀 | 一致 |
| 曲目号 0 | `Zero` | 无前缀 | 一致 |
| 碟号 1/1 | `Neon` | 无前缀 | 一致 |
| 碟号 1，总数空 | `Memory` | `1-01 Memory.m4a` | 一致 |
| 碟号 2/2 | `Night` | `2-02 Night.m4a` | 一致 |
| 合辑 | `Comp Song` | `Compilations/…` | 一致 |
| NFD 标题与专辑 | `が`（NFD） | 保留 NFD 字节 | TrackStash 输出 NFC（见 2.4） |
| 专辑含零宽空格 | `A\u200bB` | 保留 `\u200b` | 一致 |
| 标题以两个点结尾 | `here..` | `here...m4a` | 一致 |
| 反斜杠 | `Edge\Artist` / `Back\slash` | `Edge_Artist` / `Back_slash` | 一致 |
| 专辑艺术家为空 | 艺术家 `Solo Artist` | 使用艺术家作为文件夹 | 一致 |
| 专辑为空 | — | `Unknown Album` | 一致 |
| 标题为空 | — | 使用源文件名（去掉扩展名）：`E25 source.m4a` | 修正后一致（之前为 `Unknown Title`） |
| 保留名 `CON` / `con` | — | `CO_` | 修正后一致（之前为 `_CON`） |
| 保留名 `AUX` `PRN` `NUL` `COM1` `LPT1` | — | `AU_` `PR_` `NU_` `COM_` `LPT_` | 修正后一致 |
| 扩展名大写 `.MP3` | — | 保留 `.MP3` | 修正后一致（之前转小写） |

20 个用例全部一致（修正前 16 个）。

### 2.2 改标签后，Music 立即移动或改名

这是迁移风险最大的一点：**Music 默认"保持 Music 媒体文件夹有序"，改标签就会立即改路径。** TrackStash 默认只在 Organize 时改名。

| 修改 | 修改前 | 修改后（Music 实测） |
|---|---|---|
| disc_count 空 → 1（碟号 1） | `1-01 Memory.m4a` | `01 Memory.m4a` |
| 碟号 1 → 6（总数空） | `01 Memory.m4a` | `6-01 Memory.m4a` |
| 曲目号 7 → 9 | `07 Neon.m4a` | `09 Neon.m4a` |
| 标题 `Desire Drive` → `Desire Drive X` | `03 Desire Drive.m4a` | `03 Desire Drive X.m4a` |
| 合辑标志 false → true | `Edge Artist/EDGE 01…/16 O.O.H.m4a` | `Compilations/EDGE 01…/16 O.O.H.m4a` |
| 专辑艺术家 `V.A.` → `Edge Artist` | `V.A_/EDGE 05…/01 Plain.m4a` | `Edge Artist/EDGE 05…/01 Plain.m4a` |

### 2.3 加入碟号 5 不会改已有文件

- 在 `EDGE 13`（已有 disc 6 的 `6-01 Memory.m4a`）中加入 disc 5 的 `Five Two`：`6-01 Memory.m4a` **未改名**，新文件为 `5-02 Five Two.m4a`。
- 结论：Music 与 TrackStash 的碟号规则都是逐曲目的，加入新碟不会触发已有文件改名。

### 2.4 Unicode 与长度

- **NFD 原样保存**：Music 对 NFD 输入保留 NFD 字节（目录与文件）。TrackStash 输出 NFC。迁移时需要决定统一方式（见第 5 节）。
- **exFAT 上的查找**：`exists()` 与 `create` 对 NFC/NFD 基本等价，但 `listdir` 返回的是**首次写入的字节形式**；NFD 字节有时无法用于 `unlink`。**所有操作都应使用 NFC 路径，并通过逐级解析真实目录项（不直接拼接）访问。**
- **大小写不敏感**：`CaseTest` 与 `casetest` 指向同一文件。
- **字节上限 253**：ASCII 文件名超过 253 字节时被截到 253 字节，**扩展名保留**（`…AAAA.m4a`，253 字节）。目录名超过时也截到 253 字节。
- **多字节截断丢扩展名（Music bug）**：标题为 84 个 `あ`（252 字节）时，文件名总长超限，Music 截断后**文件没有扩展名**（`…ああああああ`，252 字节，无 `.m4a`）。70 个 `あ`（210 字节）正常保留 `.m4a`。这种文件 Music 仍在库中，但无法按扩展名识别。

### 2.5 其他 Music 行为

- **重复内容**：两个内容相似的文件（E20/E21，标签完全相同）只加入了一首，第二首被 Music 静默跳过。
- **自动维护**：Music 在改标签后会自动重命名（见 2.2）。但 iTunes 库里的文件名（见第 3 节）是某个时刻的快照，与当前标签经常不一致，说明它并非对所有历史修改都做了整理。

## 3. iTunes 数据库里的历史快照（20,829 首）

### 3.1 碟号前缀

iTunes 对碟号前缀是**逐曲目**决定的，以 `disc_count` 为主要依据：

| 情况 | 结果 |
|---|---|
| 单碟专辑，disc_count = 1 | 8,629 首，**全部无前缀** |
| 单碟专辑，disc_count = 2 或以上 | 83 首，全部有前缀 |
| 单碟专辑，disc_count 为空 | 1,887 首有前缀，332 首无前缀（多数有前缀） |
| 多碟专辑，disc_count = 1 | 78 首无前缀（与规则一致） |
| 多碟专辑，disc_count ≥ 2 | 约 90% 有前缀；约 10% 无前缀（历史快照） |

iTunes 不看专辑的碟数，只看曲目自己的 disc_count。这与 TrackStash 的规则（`disc_total != 1` 时加前缀）一致。

### 3.2 合辑

- compilation 标志为真的曲目，iTunes 中 870 首，其中 869 首在 `Compilations/` 下。
- **已更正**：757 首的 cpil 存的是文本 `'0'`（0x30，意为 false），mutagen 把任何非零整数当成 True，导致 TrackStash 误读。Music 与库都是正确的。修复后这类不一致为 0。

### 3.3 历史快照导致的残余差异

完整路径与 TrackStash 修正后规则的对比（20,829 首）：

| 类别 | 数量 | 说明 |
|---|---|---|
| 完全一致 | 17,918（86.0%） | 最终规则，见 `MUSIC_ITUNES_BEHAVIOR.md` 第 8.1 节 |
| 文件名：源文件名未被 iTunes 重命名 | 1,025 | 如 `4.GROOVE IN LUCKY.m4a`、`N. Title` |
| 其他（碟号 1 且碟数空的少数专辑、源文件名等） | 993 | 历史快照 |
| 文件夹：大小写差异 | 357 | 历史快照 |
| 文件名：标题与当前标签不同 | 340 | 改标签后 iTunes 未重命名 |
| 文件名：源文件名含"艺术家 - 标题"或 `×` | 196 | 从未被 iTunes 整理 |

## 4. TrackStash 修正（本次改动）

- 标题为空：使用源文件名（去掉扩展名）。
- 保留名（`CON` `PRN` `AUX` `NUL` `COM1–9` `LPT1–9`，不分大小写）：转为大写，最后一个字符替换为 `_`。
- 扩展名保留原始大小写。
- 路径组件上限 253 个 UTF-16 码元，截断主体，**扩展名永远保留**（Music 在多字节超长时会丢扩展名，不复制该 bug）。
- 碟号前缀：`disc_number > 0` 且 `disc_total != 1` 时输出 `N-`；`disc_total` 支持 `1/1` 这类 `N/M` 写法。
- 目录名以 `.` 或空白开头时，首个字符替换为 `_`。
- 合辑：`compilation` 为真时使用 `Compilations`。
- 字符替换、末尾点/空格、弯引号等规则与第 2.1 节一致。

测试：151 个通过。新增 `tests/test_template_itunes.py` 覆盖上述规则（空标题、保留名、大写扩展名、253 字节上限）。

已知的既有失败：`tests/test_library.py::test_import_copies_and_computes_uuid` 在 HEAD 上同样失败（单独文件运行时），是测试之间的隔离问题，与本次改动无关，待单独修复。

## 5. 待你决定

1. **合辑的来源**：文件标签（757 首与 iTunes 不一致）还是 iTunes 库？迁移时如果以文件为准，这些曲目会移到 `Compilations/`。
2. **Unicode 统一策略**：Music 原样保存 NFD。是否在迁移时把所有名字统一为 NFC（需要重命名约 3,036 处）？
3. **多字节超长文件名**：Music 会丢扩展名（见 2.4）。TrackStash 已保证扩展名保留；对于迁移后仍残留的此类文件，是否需要单独列出？
4. **非 ASCII 空白**：`_pomme'tto` 的差异提示，iTunes 可能不去掉非 ASCII 空白字符（如全角空格），而是替换为 `_`。需要进一步确认。

## 6. 清理记录

- 边缘测试曲目（54 首）已从 Music 库中删除，文件移到 `~/.Trash/trackstash-edge-test-20261110-231706`。
- 因此变空的 55 个目录已删除（都是测试生成的专辑/艺术家目录）。
- 库回到 **20,829 首**，与磁盘音频文件一致。
- 删除时 Music 弹出"移到废纸篓还是保留？"的确认框，已选择 **Keep File**（从库删除，文件保留在原位），之后由脚本移到废纸篓。

## 7. 数据库侧的隐藏问题

1. **两个库并存**：`~/Music/Music` 的默认库仅 21 首；MusicLocal 库 20,829 首。切换只能通过"按住 Option 启动"完成。
2. **历史快照与回收站副本**：`Previous Libraries.localized` 的两份快照和 `.Trashes` 中的 `Library.musicdb` 副本不应误用。
3. **数据库加密**：`Library.musicdb` 只能通过 Music.app 读取。
4. **Music 退出时写入数据库**：退出时 `Library.musicdb` 等文件被 Music 保存（大小变化），备份仍保留写入前的状态。
5. **AppleDouble 文件**：23,979 个 `._*`，扫描必须跳过。
6. **文件标签与库不同步**：合辑标志相差 757 首（见 3.2）。
7. **改标签即移动**：Music 的自动维护会移动文件，TrackStash 不会。两者混用会造成路径冲突。
8. **多字节超长名丢扩展名**：Music bug（见 2.4）。
