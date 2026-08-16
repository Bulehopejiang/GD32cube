# -*- coding: utf-8 -*-
"""tkinter 表单控件辅助：Field（带标签控件）、RowTable（可增删行表格）、
ScrollableFrame（滚动容器）、TabBase（页签基类）。"""

import tkinter as tk
from tkinter import ttk


def _to_int(v, default=0):
    """把字符串转 int，失败返回默认值。"""
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


def _combo_width(values, width=None):
    """计算下拉框宽度：取最长选项长度 + 2，且不小于给定宽度。"""
    if not values:
        return width or 12
    needed = max(len(str(v)) for v in values) + 2
    return max(width or 12, needed)


class ScrollableFrame(ttk.Frame):
    """带垂直/横向滚动条的内容容器，child 应放进 .inner。

    inner 宽度取「画布宽度 与 内容实际宽度」的较大者：
    内容窄时铺满画布，内容宽（表格列多）时可横向滚动，不丢列。
    """

    def __init__(self, master, height=180):
        super().__init__(master)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.hsb.pack(side="bottom", fill="x")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(
                            scrollregion=self.canvas.bbox("all")))
        # 关键：inner 宽度至少等于画布宽度；内容更宽时保留内容宽度，从而出现横向滚动
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(
                             self._win, width=max(e.width, self.inner.winfo_reqwidth())))
        # 鼠标滚轮滚动
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _bind_wheel(self, _e):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _e):
        self.canvas.unbind_all("<MouseWheel>")


class Field:
    """一行带标签的输入控件。

    kind: entry 文本框 / combo 下拉 / spin 数字 / check 勾选
    values: combo 的选项列表；from_/to: spin 范围
    """

    def __init__(self, parent, label, kind="entry", values=None, default="",
                 from_=0, to=100, width=10, grid=False, row=0, col=0, padx=2, pady=2,
                 label_width=10):
        self.label = label
        self.kind = kind
        self.var = tk.StringVar(value="" if default is None else str(default))
        self.frame = None
        if kind == "check":
            # 勾选框自带文字，不需要左侧标签
            self.widget = ttk.Checkbutton(parent, text=label, variable=self.var,
                                          onvalue="1", offvalue="0")
        else:
            self.frame = ttk.Frame(parent)
            # 统一标签宽度 + 右对齐，保证同页签内各输入框起点对齐
            ttk.Label(self.frame, text=label, anchor="e", width=label_width,
                      justify="right").pack(side="left", padx=(0, 3))
            if kind == "combo":
                eff = _combo_width(values, width)
                self.widget = ttk.Combobox(self.frame, textvariable=self.var,
                                           values=values or [], width=eff,
                                           state="readonly")
            elif kind == "spin":
                self.widget = ttk.Spinbox(self.frame, textvariable=self.var,
                                          from_=from_, to=to, width=width)
            else:
                self.widget = ttk.Entry(self.frame, textvariable=self.var, width=width)
            self.widget.pack(side="left")
        if grid:
            (self.frame or self.widget).grid(row=row, column=col, padx=padx, pady=pady,
                                             sticky="w")
        elif self.frame is not None:
            self.frame.pack(fill="x", pady=1)
        else:
            self.widget.pack(anchor="w", pady=1)

    def get(self):
        v = self.var.get().strip()
        if self.kind == "check":
            return v == "1"
        if self.kind == "spin":
            return _to_int(v)
        return v

    def set(self, value):
        if value is None:
            value = ""
        if isinstance(value, bool):
            self.var.set("1" if value else "0")
        else:
            self.var.set(str(value))


class RowTable(ttk.Frame):
    """可增删行的表格（自身即 Frame，可直接 pack/grid）。

    表头与数据行放在**同一个网格容器**里，各列严格对齐。
    columns: [(key, 标题, kind, values, width), ...]
    kind: combo（下拉）/ entry（文本框）；values 为下拉选项。
    行数据用 list[dict] 存取（key -> 字符串值）。
    """

    def __init__(self, parent, columns, height=150, auto_defaults=False, on_change=None):
        super().__init__(parent)
        self.columns = columns
        self.auto_defaults = auto_defaults  # True 时新增行自动选第一个下拉值
        self.on_change = on_change          # 单元格变化回调（用于依赖其它列的动态下拉）
        self.vars = []                      # 每行: [(key, StringVar, widget, col), ...]
        self._next_row = 1                  # 第 0 行是表头
        # 每列有效宽度：下拉取最长选项+2，表头标题也不截断
        self.col_widths = []
        for key, title, kind, values, width in columns:
            w = _combo_width(values, width) if kind == "combo" else (width or 8)
            if kind != "combo" and title and len(title) > w:
                w = len(title) + 1
            self.col_widths.append(w)
        # 滚动网格容器（表头 + 数据行共用，保证列对齐）
        self.scroll = ScrollableFrame(self, height=height)
        self.scroll.pack(fill="both", expand=True)
        for i, (key, title, kind, values, width) in enumerate(columns):
            ttk.Label(self.scroll.inner, text=title, width=self.col_widths[i],
                      anchor="w", font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=i, padx=1, pady=1, sticky="w")
        ttk.Label(self.scroll.inner, text="", width=2).grid(row=0, column=len(columns))
        # 增删按钮
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=2)
        ttk.Button(bar, text="＋ 添加行", command=self.add_row).pack(side="left")
        ttk.Button(bar, text="－ 删除最后一行", command=self.del_row).pack(side="left", padx=4)
        self.add_row()

    def add_row(self, defaults=None):
        """新增一行；defaults 为 {key: 值} 的初始值。"""
        row = self._next_row
        self._next_row += 1
        row_vars = []
        for i, (key, title, kind, values, width) in enumerate(self.columns):
            var = tk.StringVar()
            if kind == "combo":
                w = ttk.Combobox(self.scroll.inner, textvariable=var,
                                 values=list(values or []), width=self.col_widths[i],
                                 state="readonly")
                if self.auto_defaults and values:
                    var.set(values[0])
            else:
                w = ttk.Entry(self.scroll.inner, textvariable=var, width=self.col_widths[i])
            w.grid(row=row, column=i, padx=1, pady=1, sticky="w")
            if self.on_change is not None:
                if isinstance(w, ttk.Combobox):
                    w.bind("<<ComboboxSelected>>", lambda _e: self.on_change())
                else:
                    w.bind("<KeyRelease>", lambda _e: self.on_change())
            row_vars.append((key, var, w, i))
        btn = ttk.Button(self.scroll.inner, text="✕", width=2)
        btn.grid(row=row, column=len(self.columns), padx=1)
        btn.configure(command=lambda rv=row_vars: self._remove_row(rv))
        row_vars.append(("__del__", None, btn, len(self.columns)))
        self.vars.append(row_vars)
        if defaults:
            self.set_row(-1, defaults)

    def del_row(self):
        if len(self.vars) > 1:
            self._remove_row(self.vars[-1])
        else:
            self.set_row(0, {})

    def _remove_row(self, row_vars):
        if len(self.vars) <= 1:
            self.set_row(0, {})
            return
        idx = self.vars.index(row_vars)
        self.vars.remove(row_vars)
        for _key, _var, w, _col in row_vars:
            if w is not None:
                w.destroy()
        # 把后面的行整体上移一格网格行号，避免留空洞
        for r in range(idx, len(self.vars)):
            row = r + 1
            for _key, _var, w, col in self.vars[r]:
                if w is not None:
                    w.grid(row=row, column=col, padx=1, pady=1, sticky="w")

    def set_row(self, index, values):
        """把 dict 写入某一行（index<0 表示最后一行）；values 为空则清空该行。"""
        row_vars = self.vars[index]
        if not values:
            for _key, var, _w, _col in row_vars:
                if var is not None:
                    var.set("")
            return
        for key, var, w, _col in row_vars:
            if var is None or key not in values or values[key] is None:
                continue
            val = str(values[key])
            # 下拉框：若值不在选项里则动态加进去，保证载入后可见
            if isinstance(w, ttk.Combobox):
                opts = list(w.cget("values"))
                if val not in opts:
                    opts.append(val)
                    w.configure(values=opts)
            var.set(val)

    def set_cell_options(self, row_index, key, values):
        """设置某行某列下拉框的选项（用于依赖其它列的动态下拉）。

        row_index: vars 列表下标；key: 列名；values: 新选项列表。
        """
        if not (0 <= row_index < len(self.vars)):
            return
        for rk, _var, w, _col in self.vars[row_index]:
            if rk == key and isinstance(w, ttk.Combobox):
                w.configure(values=list(values))
                return

    def rows(self):
        """返回 list[dict]，跳过全空行。"""
        result = []
        for row_vars in self.vars:
            d = {}
            for key, var, _w, _col in row_vars:
                if var is None:
                    continue
                v = var.get().strip()
                if v:
                    d[key] = v
            if d:
                result.append(d)
        return result

    def set_rows(self, list_of_dict):
        """清空并填入多行；空列表则清空成一行空行。"""
        while len(self.vars) > 1:
            self.del_row()
        if list_of_dict:
            self.set_row(0, list_of_dict[0])
            for d in list_of_dict[1:]:
                self.add_row(d)
        else:
            self.set_row(0, {})


class TabBase(ttk.Frame):
    """页签基类：子类实现 to_config / load_config。"""

    def __init__(self, master):
        super().__init__(master, padding=8)

    def to_config(self, cfg):
        """把本页签控件写回 cfg（dict）。"""
        raise NotImplementedError

    def load_config(self, cfg):
        """从 cfg 读取值填充控件。"""
        raise NotImplementedError
