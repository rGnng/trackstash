# TrackStash 代码评审报告

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-01 |
| 评审范围 | `src/trackstash` 全部模块、`tests`、构建配置与近期提交历史 |
| 结论 | 存在明显的“补丁上补丁”和“功能只做了一半”的痕迹；性能上发现并修复了一个 O(N²) 的 FTS 维护瓶颈，以及多处 N+1 查询。 |

---

## 1. 结论摘要

1. **补丁上补丁确实存在**，主要集中在三个地方：
   - 专辑网格的间距/选中样式：连续多个 style/fix/revert 提交，最后用自绘 delegate 和调色板兜底逻辑收场。**本次已重构掉调色板平均和硬编码颜色，改用 `QStyle` 绘制选中/焦点背景。**
   - 设置迁移：旧模板、旧封面裁剪字段、列配置版本迁移全部散落在 `MainWindow.__init__` 和 `_load_column_config` 中（未改）。
   - 初始化与刷新链：大量 `hasattr` 守卫、`refresh_libraries()` 后再次 `refresh_tracks()`、`_tab_changed` 与显式 `refresh_albums()` 重复调用。**重复刷新已移除；`hasattr` 结构仍在。**
2. **最大的性能问题已经修复**：FTS5 的 `song_id` 是 `UNINDEXED` 列，原先按 `song_id` 删除 FTS 行会全表扫描，导入 2 万首时形成 O(N²)，耗时 49.7s；改为稳定 rowid 后降到 3.2s（约 15.7 倍）。
3. **仍有架构级性能问题**：`list_tracks` 仍把整库加载进 Python/Qt 模型，2 万首约 250ms，10 万首会超过 1s，与需求中的 “SQL-backed virtualized model / 100k 首 p95 < 100ms” 不一致。这是下一步最值得做的改造。
4. 顺带修复了几处正确性问题：跨库封面串用、重复检测未按库隔离、`_remap_song_id` 防御分支的主键冲突、SQL 侧格式/缺封面过滤、标签编辑器把文本音轨号解析成 0 等。

---

## 2. “补丁上补丁”的具体位置

### 2.1 专辑网格样式：样式表 → 自绘 delegate → 调色板兜底（已修复）

相关提交：

```text
d683ddc style: apply album grid spacing per item
2957708 style: make the album top padding use the grid background
55c3a40 style: pad the album grid inside the viewport
4931b76 Revert "style: restore the 22 px album grid top inset"
cca7142 style: restore the 22 px album grid top inset
90db5e1 style: align the album grid outer edge with the Tracks view
8b61d06 Revert "style: tighten the album grid top inset"
6b2df1e style: tighten the album grid top inset
ffc619f style: match the Tracks album grid spacing
021040e fix: unify album grid selection styling
```

修复前：

- `_solid_palette_color()` 会对渐变 palette brush 的 stop 求平均，并写死 `#314f78`、`#ffffff`、`#e8e8e8` 等兜底颜色；
- `AlbumItemDelegate.paint()` 完全接管绘制，没有调用 `QStyle::drawControl`，hover/focus/disabled/键盘导航/高对比度主题都没有标准样式处理；
- 测试直接断言了 delegate 内部绘制结果，把实现细节固化成了契约。

本次修复：

- 删除 `_solid_palette_color()` 及所有硬编码颜色；
- `AlbumItemDelegate.paint()` 先构造 `QStyleOptionViewItem`，调用 `initStyleOption()`，保留真实 `state/palette/rect`，再用 `QStyle.CE_ItemViewItem` 绘制背景、选中态和焦点；
- 通过清除 `HasDecoration` 并写入一个不可见空格，避免标准样式重复绘制图标/文字；
- 图标和两行文字仍按固定 padding 绘制，但颜色来自 `option.palette` 的 `HighlightedText` / `Text`，不再自算颜色；
- 测试改为断言“选中背景等于 `palette(highlight)`”，不再依赖内部颜色函数。

保留的常量 `ALBUM_SPACING / ALBUM_ITEM_PADDING / ALBUM_ITEM_MARGIN` 属于布局参数，不是补丁兜底逻辑。

### 2.2 设置迁移散落在 UI 构造函数里

`src/trackstash/ui/main_window.py:252-270`：

```python
template = db.get_setting("default_template", DEFAULT_TEMPLATE)
if template == LEGACY_DEFAULT_TEMPLATE:
    ...
artwork_aspect = db.get_setting("artwork_aspect", "")
if artwork_aspect not in {"crop", "fit", "original"}:
    legacy = db.get_setting("artwork_crop_square", "1")
    ...
```

`_load_column_config()`（`main_window.py:1445`）又手工把新列 `added` 插入 `visible / order / widths` 三个结构，版本号 `COLUMN_CONFIG_VERSION = 2` 只处理这一种情况。

**问题**：
- 迁移逻辑和 UI 初始化耦合，新增设置项就要继续往构造函数里加 `if`；
- 没有统一的 setting schema、默认值和迁移测试；
- `artwork_max_size` / `artwork_quality` 的 `try/except ValueError` 也是一次性的兜底。

**建议**：增加一个 `Settings` 数据类 + `migrate_settings(raw) -> Settings`，集中处理默认值、类型转换、旧键迁移；`MainWindow` 只接收一个配置对象。列配置也可以复用同一套版本化迁移。

### 2.3 初始化顺序靠 `hasattr` 兜底，刷新链重复

`main_window.py` 中有 15 处 `hasattr(self, ...)`：

```text
status_summary / table / search_edit / album_model / album_view /
tracks_view_action / albums_view_button / album_filter_label / tabs / ...
```

这些守卫本质上是在掩盖“构造函数里先创建 action、再创建 widget、再 refresh”的顺序问题。

重复刷新也已修复了一部分：

- `save_inline_edits`、`edit_tags`、`auto_number_tracks`、`organize`、`delete_tracks`、`find_duplicates` 原先在 `refresh_libraries()` 之后又调用 `refresh_tracks()`；而 `refresh_libraries()` 内部已经刷新 tracks。
- `clear_album_filter()` / `go_to_album()` 在切换 tab 后再次调用 `refresh_albums()`，而 `_tab_changed()` 已经会刷新。
- `_tab_changed()` 原先无条件刷新专辑；现在只在 `_albums_dirty` 为真时刷新。

**建议**：把窗口生命周期拆成 `build_ui()`、`load_state()`、`refresh()` 三个阶段，去掉 `hasattr` 守卫；把“数据变更 → 标记 dirty → 当前视图刷新”做成单一入口。

### 2.4 FTS 是“只写不读”的半成品

修复前：

- schema 创建了 `ts_track_fts`；
- `upsert_tracks` 每条都维护 FTS；
- 但 `list_tracks(query=...)` 使用的是 7 个 `LIKE '%...%'`，从未查询 FTS；
- 同时 `_update_fts()` 用 `WHERE song_id = ?` 删除，而 `song_id` 是 `UNINDEXED`，导致每次删除都扫描整个 FTS 表，导入复杂度 O(N²)。

这是一个典型的“功能已经写进去了，但没有接线、也没有基准测试”的补丁式实现。本次已修复：

- `list_tracks` 在 query 非空时走 FTS5 `MATCH`（`db.py:1197`）；
- `_fts_match_query()` 对用户输入做安全 token 化，避免 FTS 运算符注入/语法错误；
- `_fts_rowid()` 为每个 song ID 生成稳定 63-bit rowid，`_update_fts` / remap / delete 都按 rowid 操作；
- `SCHEMA_VERSION = 4` 时重建 FTS 索引，旧库自动迁移（`_rebuild_fts`）。

**注意**：搜索语义从“任意子串 LIKE”变成了“FTS token 前缀匹配”。例如 `ong` 不再匹配 `Song`，但 `Son` 可以。这是 FTS 的标准行为；如果必须保留子串搜索，需要改用 `trigram` tokenizer，或在 UI 中明确说明。

### 2.5 撤销功能：UI 已移除，代码和 schema 仍在

提交 `71e1fe6 feat: simplify import and remove user-facing undo` 移除了用户可见的 undo/redo，但 `LibraryService` 仍保留：

- `undo_last()` / `redo_last()`（`library.py:1293`、`1330`）
- `_undo_import_item` / `_undo_tag_item` / `_undo_organize_item` / `_undo_delete_item` 等约 200 行
- `ts_operations` / `ts_operation_items` 仍然每次操作都写
- 测试仍覆盖 undo/redo

文档说 journal 保留用于内部审计/崩溃恢复，因此这不一定算 bug；但需要明确产品决策：如果不再面向用户提供 undo，就不应该继续让这套代码承担“用户功能”的测试和维护成本；如果保留，应在文档/API 中说明清楚。

### 2.6 死 schema / 死 API / 重复入口

以下内容当前没有生产调用或只有测试调用：

| 位置 | 内容 | 状态 |
|---|---|---|
| `db.py:56` | `albums.artwork BLOB` | 从未写入 |
| `db.py:193` | `ts_saved_views` | 未使用 |
| `db.py:200` | `ts_presets` | 未使用 |
| `db.py:1254` | `track_ids_for_album()` | 无调用 |
| `db.py:1441` | `missing_paths()` | 无调用 |
| `db.py:1663` | `track_paths_under()` | 无调用 |
| `db.py:1841` | `get_content_hash()` | 无生产调用 |
| `library_manager.py:285` | `LibraryManagerDialog` | 仅测试使用，UI 已改为 Settings 内嵌 Panel |
| `db.py` | `track_count()` 与 `library_track_count()` | 语义重复 |

**建议**：要么删除，要么在 schema/API 注释里标记 “planned, not wired”，避免后续维护者误以为它们是有效入口。

### 2.7 设置对话框返回值是 10 元组

`SettingsDialog.values()`（`dialogs.py:1112`）返回：

```python
tuple[str, list[str], str, str, bool, bool, bool, int, int, str]
```

`MainWindow.open_settings()` 再按位置解包并逐项写回数据库。新增一个设置项就要同时改三处：UI、tuple 类型、解包顺序。

**建议**：改为 `SettingsValues` dataclass 或 `TypedDict`，让调用方按字段访问；同时把“保存设置”从 `MainWindow` 移到一个 `SettingsService`。

---

## 3. 性能评审

### 3.1 已修复的性能问题

基准环境：本机 macOS，Python 3.12，SQLite（WAL），合成数据 4,000 / 20,000 首，`list/search/albums` 取 3 次中位数。基线为本次修改前的 `HEAD`。

| 场景 | 修改前 | 修改后 | 变化 |
|---|---:|---:|---:|
| 4k 首 `upsert_tracks` | 2.40s | 0.53s | 4.5x |
| 20k 首 `upsert_tracks` | 49.69s | 3.17s | **15.7x** |
| 20k 首搜索（完整 token） | 21.5ms | 5.0ms | 4.3x |
| 20k 首删除 100 首（Service） | 1.15s | 0.12s | **9.6x** |
| 20k 首 `list_tracks` 全量 | 254.6ms | 250.5ms | 基本不变（架构问题） |
| 20k 首 `list_albums` | 28.8ms | 29.0ms | 基本不变 |
| 4k 首 `list_tracks` 全量 | 44.6ms | 44.6ms | 基本不变 |

连接/清理次数（50 首规模）：

| 操作 | 修改前 | 修改后 |
|---|---:|---:|
| `preview_tag_edits(50)` 的 DB 连接数 | 100 | 2 |
| `preview_auto_number(50)` 的 DB 连接数 | 100 | 2 |
| `delete_tracks(25)` 的 `_cleanup_orphans` 次数 | 25 | 1 |
| `plan_import(6)` 的 DB 连接数 | 13 | 2 |

#### 3.1.1 FTS 维护 O(N²)（本次最大收益）

`_update_fts()` 原先：

```sql
DELETE FROM ts_track_fts WHERE song_id = ?
```

`ts_track_fts.song_id` 是 `UNINDEXED`，FTS5 无法按它索引，删除只能扫描整个虚拟表。导入 N 首时每条都扫描，复杂度 O(N²)。

修复：

- `_fts_rowid(song_id)` 用 BLAKE2b 生成稳定 63-bit rowid；
- 插入时显式写 `rowid`；
- 删除/更新按 `rowid` 进行；
- `_rebuild_fts` 迁移时也按 rowid 重建。

结果：20k 首导入从 49.7s 降到 3.2s。

#### 3.1.2 N+1 数据库连接

- `preview_tag_edits`、`preview_auto_number`：原来每首 2 次连接（`get_track` + `load_tag_set`），改为 `get_tracks_by_ids` + `load_tag_sets` 两次批量查询。
- `preview_organize`：原来每首 3 次连接 + 一次 `read_metadata` 磁盘读取；改为批量 tracks/tags、按库缓存 library、从数据库中的 `format/bitrate` 构造轻量 metadata，不再重读音频文件。
- `plan_import`：原来每个文件 `find_by_content_hash` + `get_track_by_path`；改为一次性 `paths_for_library` + `hash_map`，碰撞检测使用内存集合。6 个文件的连接数 13 → 2。
- `delete_tracks`：原来每首一个 `delete_tracks([id])`，每次都执行 `_cleanup_orphans`；改为先收集待删除 ID，最后批量删除一次。25 首的 orphan cleanup 25 → 1。
- `scan_library`：原来先算一次 `content_hash` 做移动检测，upsert 后再对每首算第二次；现在复用第一次的 digest，并批量写回 `ts_file_state`。
- `execute_import`：每首一个 `update_content_hash` 事务，改为最后批量 `update_content_hashes`。

#### 3.1.3 SQL 侧过滤

`list_tracks` 新增 `format_filter` / `missing_artwork` 参数，过滤在 SQL 中完成，不再把整库 tracks 载入 Python 后再列表推导。

#### 3.1.4 其他

- 列宽/列顺序变更原先在 `sectionResized` / `sectionMoved` 每次触发时都写一次 SQLite；现在 250ms 防抖，拖动结束只写一次。
- `refresh_libraries()` 后重复 `refresh_tracks()`、切 tab 后重复 `refresh_albums()` 已移除。
- 歌曲详情封面增加 32MB 上限的 LRU 缓存，重复选中同一首不再重复解析嵌入式封面。
- 专辑网格图标缓存从 256 降到 64，并把非正方形封面裁剪成正方形，避免极端长宽比图片在内存中放大。
- 选中色统一：`ui/theme.py` 维护唯一色值；AlbumGrid 使用 view 级 palette（delegate 通过 `QStyle` 读取），Tracks 表格和视图切换按钮的 QSS 直接使用同一组色值。`QApplication` palette 不被覆盖，所以 Tracks 表格的交替行颜色保持不变；delegate 的文字颜色按 `State_Active` 选择 Active/Inactive 组。

### 3.2 仍存在的性能问题

#### P0：Track 表不是虚拟化模型

`TrackTableModel` 仍持有完整 `list[Track]`，`Database.list_tracks()` 每次把整库 JOIN 结果转成 dataclass：

- 20k 首：约 250ms；4k 首：约 45ms；按线性外推 100k 首约 1.2s。
- 需求 `NFR-01 / AC-09` 要求缓存搜索和过滤在 100k 首规模 p95 < 100ms，并要求 “SQL-backed virtualized model”。
- 排序也在 Python 内存中做（`TrackTableModel.sort`），10 万首时点击表头会有明显卡顿。

**建议**：
- 改为 `QAbstractTableModel` + `canFetchMore/fetchMore`，按页从 SQLite 取数据；
- 或者使用 `QSqlQueryModel` / `QSqlTableModel` 直接绑定 SQL；
- 把 `ORDER BY` 需要的排序键（artist/album/track/disc/title）落到索引或生成列，避免每次全表排序；
- 搜索框继续走 FTS5，只取当前页。

这是本次评审中唯一没有在代码里解决的“大性能问题”，需要单独立项。

#### P1：重复检测仍会全量读文件

`index_content_hashes()` 已经批量/并行做快速指纹，但 `exact_duplicates()` 确认阶段仍对每个候选组串行执行 `full_content_hash()`，且运行在 UI 线程（只靠 `processEvents`）。大量重复文件时会卡顿。

**建议**：把 full hash 也放进线程池，提供 QProgressDialog/取消；或分阶段确认，只对用户展开的组计算。

#### P1：导入预览会扫描目录两次

`ImportDialog.preview()` 先 `collect_audio_files()` 计算文件数和总大小，然后 `service.plan_import()` 内部再次 `collect_audio_files()`。大目录会多一次完整 `os.walk` + stat。

**建议**：给 `plan_import` 增加 `source_files` 参数，复用对话框已经收集的列表。

#### P1：导入规划中的 metadata 读取是串行的

`scan_library` 已用 `ThreadPoolExecutor` 并行读取 metadata；`plan_import` 仍逐文件 `read_metadata`。大目录导入预览会明显慢于扫描。

**建议**：复用扫描的并行读取模式，但保持“规划/碰撞”阶段的串行，避免复杂化。

#### P2：封面缩放仍在 GUI 线程

`_CoverTask` 只读取原始 bytes；`AlbumGridModel._cover_loaded()` 在 GUI 线程做 `QPixmap.loadFromData` + `scaled(SmoothTransformation)`。大封面、快速滚动时仍可能掉帧。

**建议**：在 worker 中用 `QImage` 解码/缩放，GUI 线程只做 `QPixmap.fromImage()`；或限制封面解码尺寸。

#### P2：`QThreadPool.globalInstance()` 被模型修改

`AlbumGridModel.__init__` 调用 `QThreadPool.globalInstance().setMaxThreadCount(4)`，会影响进程内所有 Qt 任务。建议模型持有自己的 `QThreadPool`。

#### P2：`QApplication.processEvents()` 重入

导入、扫描、重复检测、文件指纹都用 `processEvents()` 在循环中保活。它可能重入窗口事件、触发搜索/刷新。长期应改为 worker + 信号。

---

## 4. 本次修复的正确性问题

| 问题 | 位置 | 修复 |
|---|---|---|
| 专辑封面可能取到另一个库的同名专辑 | `db.list_albums` 封面子查询 | 子查询增加 `s2.library_id = :library_id` |
| 重复导入检测跨库误判 | `plan_import` 使用全局 `find_by_content_hash` | 使用目标库的 `hash_map(library_id)`；`find_by_content_hash` / `exact_duplicate_groups` / `probable_duplicate_groups` 增加库参数 |
| `_remap_song_id` 防御分支会主键冲突 | `db._remap_song_id` | 返回实际有效 ID；冲突时保留已有身份、更新路径并删除旧行 |
| 标签编辑器把 `A1` 音轨号解析成 0 | `dialogs._parse_value` | track/disc 字段保持文本，与 schema v3 一致 |
| 格式/缺封面过滤只在 Python 层 | `MainWindow.refresh_tracks` | 下推到 `list_tracks` SQL |
| 跨库封面/重复检测测试缺失 | 新增 `tests/test_regressions.py` | 已覆盖 |
| 列宽拖动每像素写 DB | `MainWindow._column_layout_changed` | 250ms 防抖 |
| 重复刷新 | `MainWindow` 多处 | 移除冗余 `refresh_tracks` / `refresh_albums` |

---

## 5. 测试与静态检查

### 5.1 结果

```text
pytest -q（默认套件）          127 passed, 2 skipped
pytest -q（带集成测试环境变量） 129 passed
ruff check src tests            All checks passed
ruff format --check src tests   32 files already formatted
mypy                            Success: no issues found in 21 source files
```

两个 skip 是 opt-in 集成测试：

- `TRACKSTASH_TEST_MUSIC` 未设置；
- `TRACKSTASH_TEST_M4A` 未设置。

本次额外用 ffmpeg 生成了临时音频目录，设置这两个变量后运行，129 个测试全部通过。另外执行了 `python -m trackstash --smoke-test`（offscreen），应用可正常启动并退出。

### 5.2 新增测试

新增 21 个测试；其中两个旧的专辑样式测试合并为一个 palette 断言，净增 20 个。

`tests/test_regressions.py`（17 个）：

- FTS 搜索覆盖 title / artist / album_artist / album / genre / comment / path；
- FTS 特殊字符（引号、`*`、括号、纯标点）不抛异常；
- FTS 更新/删除后不残留旧行；
- 旧 schema 打开时自动重建 FTS；
- `list_tracks` 的 format / missing artwork SQL 过滤；
- 专辑封面不跨库；
- 重复组/hash 查询按库隔离；
- 同内容导入到另一个库不会被 skip；
- `plan_import` 数据库连接数恒定；
- `preview_tag_edits` / `preview_auto_number` 批量查询；
- `preview_organize` 不读音频文件；
- `delete_tracks` 只清理一次 orphan；
- 内容指纹只处理缺失项；
- 标签编辑器批量加载 + 文本音轨号；
- `_remap_song_id` 冲突分支；
- 专辑图标裁剪为正方形；
- 重复选中封面走缓存。

`tests/test_ui.py`：

- 专辑选中背景使用 `palette(highlight)`（合并替换原先两个样式测试）；
- 专辑网格、Tracks 表格、视图切换按钮的选中像素颜色完全一致；
- 内联保存只触发一次 `refresh_tracks`；
- 列宽拖动防抖后只保存一次。

`tests/test_smoke.py`：

- `configure_application()` 不覆盖 Fusion 的 Base / AlternateBase / Window / Highlight 等 palette role，避免 Tracks 交替行颜色被误改。

### 5.3 静态检查发现并修复的问题

评审开始时 `mypy` 有 4 个错误：

```text
AlbumItemDelegate.sizeHint / paint 的 index 参数类型
与 QStyledItemDelegate 的 QModelIndex | QPersistentModelIndex 不兼容
```

已改为联合类型，`mypy` 恢复全绿。

---

## 6. 建议优先级

### P0（下一个里程碑前）

1. **虚拟化 Track 模型**：解决 100k 首时 `list_tracks` / 排序卡顿；这是与需求文档最大的偏差。
2. **导入/重复检测 worker 化**：去掉 UI 线程中的长时间循环和 `processEvents` 重入。

### P1（代码健康度）

3. **设置集中迁移**：`Settings` dataclass + versioned migration，替换 `MainWindow.__init__` 里的临时 `if`。
4. **清理死 schema/API**：`ts_saved_views`、`ts_presets`、`albums.artwork`、未使用方法；明确 undo 的去留。
5. **导入预览复用文件列表**：避免二次 `os.walk`，并考虑并行 `read_metadata`。

### P2（体验/细节）

6. 封面解码/缩放移出 GUI 线程；模型自持线程池。
7. `SettingsDialog.values()` 改 dataclass。
8. `_duration_text` 在 `models.py` 与 `dialogs.py` 中格式不一致（超过 1 小时时一个显示 `61:00`，一个显示 `1:01:00`），建议统一。
9. `TrackTableModel.sort()` 的 `layoutAboutToBeChanged/layoutChanged` 没有更新 persistent indexes，排序后选择状态可能丢失；建议用 `beginResetModel` 或正确映射 persistent index。

---

## 7. 变更文件

| 文件 | 说明 |
|---|---|
| `src/trackstash/core/db.py` | FTS rowid/迁移、搜索、SQL 过滤、批量 hash、缓存、索引、remap 修复 |
| `src/trackstash/core/library.py` | 批量预览/删除/扫描/导入、按库去重、hash 批量写回 |
| `src/trackstash/ui/theme.py` | 选中色 token；仅对 AlbumGrid 应用 view 级 palette |
| `src/trackstash/app.py` | 不覆盖全局 palette，保留 Fusion 的交替行/主题颜色 |
| `src/trackstash/ui/main_window.py` | 刷新去重、列宽防抖、封面缓存、专辑网格跳过无变化布局、mypy 类型 |
| `src/trackstash/ui/models.py` | 排序去双 reset、图标缓存上限、正方形裁剪 |
| `src/trackstash/ui/dialogs.py` | 批量标签加载、文本音轨号 |
| `tests/test_regressions.py` | 新增 17 个回归/性能守卫测试 |
| `tests/test_ui.py` | 新增 2 个 UI 回归测试 |
| `docs/IMPLEMENTATION_STATUS.md` | 更新 schema v4 与测试数量 |

---

## 8. 备注

- 本报告中的性能数据来自合成库；真实库的磁盘 I/O、封面大小、文件数量会影响绝对值，但 O(N²) → O(N) 和 N+1 → 批量的方向性结论不依赖合成数据。
- 本次没有做大范围 UI 视觉重构，也没有改 undo 产品行为；相关项作为建议列出，避免在一次评审中引入不可控的回归。
