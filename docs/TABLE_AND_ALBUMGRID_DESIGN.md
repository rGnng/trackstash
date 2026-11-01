# Tracks 表格与 AlbumGrid 的设计说明

本文说明两个视图的数据模型、绘制路径、颜色来源，以及为什么同一套“选中色”在它们之间反复出现不一致。

## 1. 总体结构

```text
MainWindow
├── Tracks tab
│   ├── QTableView
│   │   ├── TrackTableModel（QAbstractTableModel）
│   │   ├── QSS：选中色 / 文字色
│   │   └── Fusion style：交替行、网格、表头
│   └── 视图切换按钮（QPushButton + QSS）
│
└── Albums tab
    ├── AlbumGridView（QListView, IconMode）
    │   ├── AlbumGridModel（QAbstractListModel + 异步封面）
    │   ├── AlbumItemDelegate（QStyledItemDelegate）
    │   │   ├── QStyle.CE_ItemViewItem：背景 / 选中 / 焦点
    │   │   └── 自绘：封面 + 两行文字
    │   └── Fusion style：rubber band、滚动、布局
    └── 视图切换按钮（同一组 QSS）
```

两个视图虽然都叫“选中”，但绘制管线完全不同。

## 2. Tracks 表格

### 2.1 数据模型

`TrackTableModel` 是一个内存型 `QAbstractTableModel`：

- 数据源：`Database.list_tracks()` 返回的 `list[Track]`；
- `rowCount` = 当前列表长度；
- `data()` 按 `COLUMNS` 映射到 `Track` 字段；
- 排序在 `TrackTableModel.sort()` 中用 Python `sorted()` 完成；
- 目前**没有**分页/虚拟化，整库数据一次性进入模型。

### 2.2 绘制路径

表格使用标准 `QTableView` + 默认 delegate：

```text
QTableView
  └── QStyleSheetStyle（表格 QSS）
        └── Fusion style（未覆盖的部分）
```

当前 QSS 只负责选中态：

```css
QTableView {
    selection-background-color: <SELECTION_HIGHLIGHT>;
    selection-color: <SELECTION_TEXT>;
}
QTableView::item:selected {
    background-color: <SELECTION_HIGHLIGHT>;
    color: <SELECTION_TEXT>;
}
```

交替行**不**由这段 QSS 控制。它来自：

```text
setAlternatingRowColors(True)
  -> QPalette.Base / QPalette.AlternateBase
```

因此：

- 改 `Highlight` 只影响选中行；
- 改 `Base` / `AlternateBase` 才会影响普通行/交替行；
- 改 `QApplication` 全局 palette 会同时影响这两个角色，容易误伤表格。

### 2.3 QSS 的坑

`QStyleSheetStyle` 在 polish 时解析 QSS。旧的写法是：

```css
background-color: palette(highlight);
```

这个写法看起来“动态”，但实际有两个问题：

1. 它依赖控件 polish 时的 palette；
2. 在运行时修改 widget palette 后，QSS 可能仍使用旧值；
3. 调用 `unpolish/polish` 强制刷新时，`QStyleSheetStyle` 又可能把 widget palette 重置回应用 palette。

所以本次最终改为：QSS 直接使用 `ui/theme.py` 的固定 token，不再依赖 `palette(highlight)`。

## 3. AlbumGrid

### 3.1 数据模型

`AlbumGridModel` 是 `QAbstractListModel`：

- 每个 row 对应一个 `AlbumRow`；
- `DisplayRole` 返回 `"专辑名\n艺术家"`；
- `DecorationRole` 返回懒加载的 `QIcon`；
- 封面读取在 `QThreadPool` 中执行，`_CoverTask` 只读取原始 bytes；
- `_cover_loaded()` 在 GUI 线程解码、缩放、裁剪成正方形并写入 LRU；
- 图标缓存上限 64，避免 256 张大封面占用过多内存。

### 3.2 绘制路径

`AlbumItemDelegate` 是混合绘制：

```text
AlbumItemDelegate.paint()
├── QStyleOptionViewItem + initStyleOption()
├── QStyle.CE_ItemViewItem
│   └── 背景 / 选中 / hover / focus / disabled
└── 自绘
    ├── 正方形封面
    └── 两行文字（标题、艺术家、省略号）
```

关键点：

- 背景和选中态交给 `QStyle`，颜色来自 `option.palette`；
- `option.palette` 来自 `QListView`（`initViewItemOption`）；
- 选中背景使用 `QPalette.Highlight`；
- 选中文字使用 `QPalette.HighlightedText`；
- `State_Active` 决定使用 Active 还是 Inactive 颜色组；
- 自绘文字不再写死颜色。

### 3.3 为什么不能用 QSS 控制 AlbumGrid 选中背景

因为 `AlbumItemDelegate` 直接调用 `QStyle.CE_ItemViewItem` 绘制背景，而不是让 `QStyleSheetStyle` 通过 `QTableView::item:selected` 规则绘制。

于是存在两条互不相同的路径：

| 视图 | 选中背景来源 |
|---|---|
| Tracks 表格 | QSS `QTableView::item:selected` |
| AlbumGrid | `QStyle.CE_ItemViewItem` + `option.palette.Highlight` |

如果只改其中一条，两个视图就会不一致。这正是之前反复出问题的核心原因之一。

## 4. 颜色设计（当前最终方案）

唯一色值在：

`src/trackstash/ui/theme.py`

```python
SELECTION_HIGHLIGHT = "#314F78"
SELECTION_TEXT = "#FFFFFF"
```

应用方式：

### 4.1 AlbumGrid

只对 `album_view` 应用 view 级 palette：

```python
apply_selection_palette(self.album_view)
```

它复制当前 widget palette，只改：

- `Highlight`
- `HighlightedText`

不改 `Base` / `AlternateBase` / `Window`。

### 4.2 Tracks 表格

QSS 直接使用 token：

```css
QTableView::item:selected {
    background-color: #314F78;
    color: #FFFFFF;
}
```

不再使用 `palette(highlight)`，避免 QSS polish 缓存问题。

### 4.3 视图切换按钮

同一组 token 直接写进 QSS：

```css
QPushButton:checked {
    background-color: #314F78;
    color: #FFFFFF;
    border-color: #314F78;
}
```

### 4.4 应用 palette

`configure_application()` **不调用** `QApplication.setPalette()`。

原因：

- Fusion 的 `AlternateBase` / `Base` / `Window` 由 style 管理；
- 全局 palette 会覆盖这些角色，导致 Tracks 交替行颜色异常；
- 只需要改选中色的控件各自应用 palette/QSS 即可。

## 5. 为什么会反复出现问题

### 原因 1：三条颜色管线并存

- Tracks 表格：QSS + Fusion palette
- AlbumGrid：QStyle + 自定义 delegate + widget palette
- 视图切换按钮：QSS

同一颜色在三条管线中分别解析，任何一条改错都会“看起来只坏一个地方”。

### 原因 2：作用域混用

- 全局 `QApplication.setPalette()`：影响所有控件，包括 `AlternateBase`；
- view 级 palette：只影响一个控件；
- QSS：只影响匹配的 selector，但受 polish 时机影响。

之前把 view 级需求误做成全局 palette，直接破坏了 Tracks 的交替行。

### 原因 3：QSS 的动态 palette 引用不是实时绑定

`palette(highlight)` 在 polish 时解析，运行时改 palette 后不一定立即生效；强制 `unpolish/polish` 又可能重置 palette。于是出现“改了没生效 → 再加一层覆盖 → 另一个视图坏掉”的循环。

### 原因 4：测试只验证单点

之前分别加了：

- 专辑选中像素测试；
- 视图按钮颜色测试；
- 全局 palette 测试。

但没有一个测试同时检查：

- AlbumGrid 选中色；
- Tracks 选中色；
- Tracks 交替行色；
- 按钮 checked 色；
- active/inactive 状态。

所以每次修一个点，另一个点回归。

## 6. 设计约束（后续不要再破坏）

1. **不要用 `QApplication.setPalette()` 改选中色。**
2. **Tracks 表格的 QSS 不要再用 `palette(highlight)` 做动态色。**
3. **AlbumGrid 的选中背景必须继续走 `QStyle.CE_ItemViewItem`；不要在 delegate 里 `fillRect` 写死颜色。**
4. **`Base` / `AlternateBase` / `Window` 属于 style，不要覆盖。**
5. **只改 `theme.py` 的两个 token 来换色。**
6. **新增颜色相关改动必须跑三视图像素测试 + 交替行测试。**

## 7. 当前测试覆盖

- `test_selection_color_is_unified_across_views`：
  - AlbumGrid 选中像素 == `SELECTION_HIGHLIGHT`；
  - Tracks 选中像素 == `SELECTION_HIGHLIGHT`；
  - 视图按钮 checked 像素 == `SELECTION_HIGHLIGHT`；
  - `table.palette().AlternateBase == app.palette().AlternateBase`。
- `test_application_does_not_override_style_palette`：
  - `configure_application()` 不改变 Base / AlternateBase / Window / Highlight / HighlightedText。
- `test_album_selection_uses_the_palette_highlight`：
  - delegate 的背景确实来自 palette，而不是内部硬编码。

## 8. 如果以后要支持系统主题色

如果希望选中色跟随系统 accent，而不是固定 `#314F78`：

- 不要恢复 `QApplication.setPalette()`；
- 在启动时从 `QApplication.style().standardPalette()` 或 `QPalette.Highlight` 解析出 token；
- 把 token 同时传给 QSS 和 AlbumGrid 的 view 级 palette；
- 仍然保持 `Base / AlternateBase / Window` 不动。

这样颜色仍然只有一个来源，但不会影响表格的交替行。
