#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GD32Cube 图形化配置工具（tkinter）

下拉勾选配置外设，点"生成代码"直接产出初始化代码，不用手写 JSON。
启动：双击本文件，或 `python gd32_cubemx_gui.py`
"""

import json
import os
import sys

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gd32cubemx import model, clock as clock_mod
from gd32cubemx.generate import generate_from_cfg
from gd32cubemx.gui_widgets import Field, RowTable, TabBase, ScrollableFrame
from gd32cubemx.usart_gen import resolve_usart_dma

# ---------------------------------------------------------------------------
# 常量：下拉选项
# ---------------------------------------------------------------------------
MCU_LIST = ["GD32F405", "GD32F407", "GD32F425", "GD32F427", "GD32F450", "GD32F470"]
CLOCK_SRC = ["HXTAL", "IRC16M"]
AHB_PSC = ["1", "2", "4", "8", "16", "64", "128", "256", "512"]
APB_PSC = ["1", "2", "4", "8", "16"]
SYSCLK_CHOICES = ["16", "24", "48", "72", "120", "144", "168", "200", "240"]

GPIO_PORT = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
GPIO_PIN = [str(i) for i in range(16)]
GPIO_TYPE = ["输出", "输入", "模拟"]
# GPIO 下拉用中文短标签显示，存进配置的仍是库宏（列窄、界面清爽）
GPIO_SPEED_MAP = {"2MHz": "GPIO_OSPEED_2MHZ", "25MHz": "GPIO_OSPEED_25MHZ",
                  "50MHz": "GPIO_OSPEED_50MHZ", "MAX": "GPIO_OSPEED_MAX"}
GPIO_OTYPE_MAP = {"推挽": "GPIO_OTYPE_PP", "开漏": "GPIO_OTYPE_OD"}
GPIO_LEVEL_MAP = {"低": "LOW", "高": "HIGH"}
GPIO_PULL_MAP = {"无": "GPIO_PUPD_NONE", "上拉": "GPIO_PUPD_PULLUP", "下拉": "GPIO_PUPD_PULLDOWN"}


def _d2m(mapping, value, default):
    """显示值 -> 库宏；未知值原样返回（兼容手写配置）。"""
    return mapping.get(value, value if value else default)


def _m2d(mapping, value, default=""):
    """库宏 -> 显示值；未知宏原样返回（保证任何值都能显示）。"""
    for disp, macro in mapping.items():
        if macro == value:
            return disp
    return value if value else default


def _usart_dma_covered(cfg, periph, direction):
    """periph 是否是由 cfg 里已启用对应方向 DMA 的 USART（该 DMA 由工具自动分配）。

    用于在 DMA 页签丢弃对 USART 的手填通道——自动分配优先，避免填错。
    """
    if not periph:
        return False
    key = str(periph).strip().upper()
    for name, conf in (cfg.get("usart") or {}).items():
        if name.upper() != key or not isinstance(conf, dict):
            continue
        if conf.get("enabled", True) is False:
            continue
        if direction == "DMA_MEMORY_TO_PERIPH" and conf.get("dma_tx"):
            return True
        if direction == "DMA_PERIPH_TO_MEMORY" and conf.get("dma_rx"):
            return True
    return False


def _af_pins(periph_key):
    """返回某外设在 AF_TABLE 里支持的所有引脚（按端口+引脚号排序）。

    用户只需从下拉里选引脚，AF 号自动推导，无需查数据手册。
    """
    from gd32cubemx.af_table import AF_TABLE
    pins = {p for (k, p) in AF_TABLE if k == periph_key}
    # "PA9" -> 端口字母 A + 引脚号 9 排序
    return sorted(pins, key=lambda s: (s[1], int(s[2:])))


def _set_pin_combo(field, pins):
    """刷新引脚下拉选项；当前值不在列表里也保留显示（兼容旧配置）。"""
    cur = field.get()
    opts = list(pins)
    if cur and cur not in opts:
        opts = [cur] + opts
    field.widget.configure(values=opts)

USART_NAMES = [("USART0", "usart0"), ("USART1", "usart1"), ("USART2", "usart2"),
               ("UART3", "uart3"), ("UART4", "uart4"), ("USART5", "usart5"),
               ("UART6", "uart6"), ("UART7", "uart7")]
USART_WL = ["USART_WL_8BIT", "USART_WL_9BIT"]
USART_STB = ["USART_STB_1BIT", "USART_STB_0_5BIT", "USART_STB_2BIT", "USART_STB_1_5BIT"]
USART_PM = ["USART_PM_NONE", "USART_PM_EVEN", "USART_PM_ODD"]

TIMER_NAMES = [("TIMER%d" % i, "timer%d" % i) for i in range(14)]
TIMER_MODES = ["base", "pwm", "ic"]
TIMER_CH = ["1", "2", "3", "4"]
IC_POL = ["TIMER_IC_POLARITY_RISING", "TIMER_IC_POLARITY_FALLING"]

ADC_NAMES = [("ADC%d" % i, "adc%d" % i) for i in range(3)]
ADC_CK = ["ADC_ADCCK_PCLK2_DIV2", "ADC_ADCCK_PCLK2_DIV4", "ADC_ADCCK_PCLK2_DIV6",
          "ADC_ADCCK_PCLK2_DIV8", "ADC_ADCCK_HCLK_DIV5", "ADC_ADCCK_HCLK_DIV6",
          "ADC_ADCCK_HCLK_DIV10", "ADC_ADCCK_HCLK_DIV20"]
ADC_RES = ["ADC_RESOLUTION_12B", "ADC_RESOLUTION_10B", "ADC_RESOLUTION_8B", "ADC_RESOLUTION_6B"]
ADC_ALIGN = ["ADC_DATAALIGN_RIGHT", "ADC_DATAALIGN_LEFT"]
ADC_CHANNELS = ["ADC_CHANNEL_%d" % i for i in range(19)]
ADC_SMP = ["ADC_SAMPLETIME_3", "ADC_SAMPLETIME_15", "ADC_SAMPLETIME_28", "ADC_SAMPLETIME_56",
           "ADC_SAMPLETIME_84", "ADC_SAMPLETIME_112", "ADC_SAMPLETIME_144", "ADC_SAMPLETIME_480"]

SPI_NAMES = [("SPI%d" % i, "spi%d" % i) for i in range(6)]
SPI_PSC = ["SPI_PSC_2", "SPI_PSC_4", "SPI_PSC_8", "SPI_PSC_16", "SPI_PSC_32",
           "SPI_PSC_64", "SPI_PSC_128", "SPI_PSC_256"]
SPI_FRAME = ["SPI_FRAMESIZE_8BIT", "SPI_FRAMESIZE_16BIT"]
SPI_CPH = ["SPI_CK_PL_LOW_PH_1EDGE", "SPI_CK_PL_HIGH_PH_1EDGE",
           "SPI_CK_PL_LOW_PH_2EDGE", "SPI_CK_PL_HIGH_PH_2EDGE"]

I2C_NAMES = [("I2C0", "i2c0"), ("I2C1", "i2c1"), ("I2C2", "i2c2")]

CAN_NAMES = [("CAN0", "can0"), ("CAN1", "can1")]
CAN_BS1 = ["CAN_BT_BS1_%dTQ" % i for i in range(1, 17)]
CAN_BS2 = ["CAN_BT_BS2_%dTQ" % i for i in range(1, 9)]
CAN_SJW = ["CAN_BT_SJW_%dTQ" % i for i in range(1, 5)]
CAN_MODE = ["CAN_NORMAL_MODE", "CAN_LOOPBACK_MODE", "CAN_SILENT_MODE", "CAN_SILENT_LOOPBACK_MODE"]

DMA_NAMES = ["DMA0", "DMA1"]
DMA_CH = ["DMA_CH%d" % i for i in range(8)]
DMA_DIR = ["DMA_MEMORY_TO_PERIPH", "DMA_PERIPH_TO_MEMORY"]
DMA_PRIO = ["DMA_PRIORITY_LOW", "DMA_PRIORITY_MEDIUM", "DMA_PRIORITY_HIGH", "DMA_PRIORITY_ULTRA_HIGH"]

DAC_ALIGN = ["DAC_ALIGN_12B_R", "DAC_ALIGN_12B_L", "DAC_ALIGN_8B_R"]
DAC_TRIG = ["DAC_TRIGGER_SOFTWARE", "DAC_TRIGGER_T1_TRGO", "DAC_TRIGGER_T3_TRGO",
            "DAC_TRIGGER_T4_TRGO", "DAC_TRIGGER_T5_TRGO", "DAC_TRIGGER_T6_TRGO",
            "DAC_TRIGGER_T7_TRGO", "DAC_TRIGGER_EXTI_9"]

EXTI_MODE = ["interrupt", "event"]
EXTI_TRIG = ["EXTI_TRIG_RISING", "EXTI_TRIG_FALLING", "EXTI_TRIG_BOTH"]

FWDGT_PSC = ["FWDGT_PSC_DIV4", "FWDGT_PSC_DIV8", "FWDGT_PSC_DIV16", "FWDGT_PSC_DIV32",
             "FWDGT_PSC_DIV64", "FWDGT_PSC_DIV128", "FWDGT_PSC_DIV256"]


# ---------------------------------------------------------------------------
# 页签
# ---------------------------------------------------------------------------
class ClockTab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        f = ttk.LabelFrame(self, text="工程与系统时钟")
        f.pack(fill="x")
        self.name = Field(f, "工程名", "entry", default="my_app", grid=True, row=0, col=0, width=12)
        self.mcu = Field(f, "芯片", "combo", values=MCU_LIST, default="GD32F407",
                         grid=True, row=0, col=2, width=10)
        self.src = Field(f, "时钟源", "combo", values=CLOCK_SRC, default="HXTAL",
                         grid=True, row=1, col=0, width=10)
        self.hxtal = Field(f, "晶振(MHz)", "spin", default=8, from_=4, to=50,
                           grid=True, row=1, col=2, width=6)
        self.sysclk = Field(f, "目标(MHz)", "combo", values=SYSCLK_CHOICES, default="168",
                            grid=True, row=2, col=0, width=10)
        self.ahb = Field(f, "AHB分频", "combo", values=AHB_PSC, default="1",
                         grid=True, row=2, col=2, width=6)
        self.apb1 = Field(f, "APB1分频", "combo", values=APB_PSC, default="4",
                          grid=True, row=3, col=0, width=6)
        self.apb2 = Field(f, "APB2分频", "combo", values=APB_PSC, default="2",
                          grid=True, row=3, col=2, width=6)
        ttk.Button(f, text="计算时钟信息", command=self._calc).grid(row=4, column=0, pady=4, sticky="w")
        self.info = tk.StringVar(value="点击「计算时钟信息」查看总线频率")
        ttk.Label(f, textvariable=self.info, foreground="#0a7").grid(row=4, column=1, columnspan=4, sticky="w")

        s = ttk.LabelFrame(self, text="SysTick 毫秒延时")
        s.pack(fill="x", pady=(8, 0))
        self.systick = Field(s, "启用 SysTick(1ms)", "check", default=True, grid=True, row=0, col=0)
        self.stick_pri = Field(s, "优先级", "spin", default=0, from_=0, to=15, grid=True, row=0, col=2, width=4)

    def _calc(self):
        try:
            cfg = {}
            self.to_config(cfg)
            info = clock_mod.compute_clock(cfg["project"]["clock"], mcu=self.mcu.get())
            t = info
            msg = "SYSCLK=%dM  AHB=%dM  APB1=%dM  APB2=%dM  |  TIMER时钟 APB1=%dM APB2=%dM" \
                  % (t.sysclk, t.ahb, t.apb1, t.apb2, t.apb1_timer, t.apb2_timer)
            # 超频校验（GUI 直接生成时不经过 model.load_config，需在此检查）
            from gd32cubemx.model import MCU_MAX_CLOCK
            limit = MCU_MAX_CLOCK.get(self.mcu.get())
            if limit and t.sysclk > limit:
                info.warnings.append("%s 系统时钟上限 %dMHz，当前 %dMHz 属于超频" %
                                     (self.mcu.get(), limit, t.sysclk))
            if info.warnings:
                msg += "\n警告：%s" % "；".join(info.warnings)
                self.info.set(msg)
                messagebox.showwarning("时钟配置警告", msg)
            else:
                self.info.set(msg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("时钟计算失败", str(exc))

    def to_config(self, cfg):
        cfg["project"] = {
            "name": self.name.get() or "my_app",
            "mcu": self.mcu.get(),
            "clock": {
                "source": self.src.get(),
                "hxtal_mhz": self.hxtal.get(),
                "sysclk_mhz": int(self.sysclk.get()),
                "ahb_prescaler": int(self.ahb.get()),
                "apb1_prescaler": int(self.apb1.get()),
                "apb2_prescaler": int(self.apb2.get()),
            },
            "systick": {"enabled": self.systick.get(), "priority": self.stick_pri.get()},
        }
        return cfg

    def load_config(self, cfg):
        p = cfg.get("project", {})
        clk = p.get("clock", {})
        self.name.set(p.get("name", "my_app"))
        self.mcu.set(p.get("mcu", "GD32F407"))
        self.src.set(clk.get("source", "HXTAL"))
        self.hxtal.set(clk.get("hxtal_mhz", 8))
        self.sysclk.set(clk.get("sysclk_mhz", 168))
        self.ahb.set(clk.get("ahb_prescaler", 1))
        self.apb1.set(clk.get("apb1_prescaler", 4))
        self.apb2.set(clk.get("apb2_prescaler", 2))
        self.systick.set(p.get("systick", {}).get("enabled", True))
        self.stick_pri.set(p.get("systick", {}).get("priority", 0))


class GPIOTab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        ttk.Label(self, text="GPIO 引脚配置：选类型后填端口/引脚/标签，可加多行",
                  foreground="#666").pack(anchor="w")
        self.table = RowTable(self, [
            ("type", "类型", "combo", GPIO_TYPE, 6),
            ("port", "端口", "combo", GPIO_PORT, 4),
            ("pin", "引脚", "combo", GPIO_PIN, 4),
            ("label", "标签", "entry", None, 8),
            ("speed", "速度", "combo", list(GPIO_SPEED_MAP.keys()), 7),
            ("otype", "输出类型", "combo", list(GPIO_OTYPE_MAP.keys()), 7),
            ("level", "初始电平", "combo", list(GPIO_LEVEL_MAP.keys()), 8),
            ("pull", "上下拉", "combo", list(GPIO_PULL_MAP.keys()), 7),
        ], auto_defaults=True)
        self.table.pack(fill="both", expand=True)

    def to_config(self, cfg):
        g = {"outputs": [], "inputs": [], "analog": []}
        for r in self.table.rows():
            port, pin = r.get("port"), r.get("pin")
            if not port or not pin:
                continue
            label = r.get("label", "")
            typ = r.get("type", "输出")
            if typ == "输出":
                g["outputs"].append({"port": port, "pin": int(pin), "label": label,
                                     "speed": _d2m(GPIO_SPEED_MAP, r.get("speed"), "GPIO_OSPEED_50MHZ"),
                                     "otype": _d2m(GPIO_OTYPE_MAP, r.get("otype"), "GPIO_OTYPE_PP"),
                                     "init_level": _d2m(GPIO_LEVEL_MAP, r.get("level"), "LOW")})
            elif typ == "输入":
                g["inputs"].append({"port": port, "pin": int(pin), "label": label,
                                    "pull": _d2m(GPIO_PULL_MAP, r.get("pull"), "GPIO_PUPD_PULLUP")})
            else:
                g["analog"].append({"port": port, "pin": int(pin), "label": label})
        cfg["gpio"] = g
        return cfg

    def load_config(self, cfg):
        g = cfg.get("gpio", {})
        rows = []
        for o in g.get("outputs", []):
            rows.append({"type": "输出", "port": o.get("port"), "pin": str(o.get("pin")),
                         "label": o.get("label", ""),
                         "speed": _m2d(GPIO_SPEED_MAP, o.get("speed")),
                         "otype": _m2d(GPIO_OTYPE_MAP, o.get("otype", "GPIO_OTYPE_PP")),
                         "level": _m2d(GPIO_LEVEL_MAP, o.get("init_level")),
                         "pull": ""})
        for i in g.get("inputs", []):
            rows.append({"type": "输入", "port": i.get("port"), "pin": str(i.get("pin")),
                         "label": i.get("label", ""), "speed": "", "otype": "",
                         "level": "", "pull": _m2d(GPIO_PULL_MAP, i.get("pull"))})
        for a in g.get("analog", []):
            rows.append({"type": "模拟", "port": a.get("port"), "pin": str(a.get("pin")),
                         "label": a.get("label", ""), "speed": "", "otype": "",
                         "level": "", "pull": ""})
        self.table.set_rows(rows) if rows else self.table.set_row(0, {})
class _PeriphInstanceTab(TabBase):
    """外设实例页签基类：实例下拉切换，各实例共用一套字段。"""

    def __init__(self, master, section, inst_names):
        super().__init__(master)
        self.section = section
        self.inst_names = inst_names  # [(显示名, 配置键), ...]
        self.app = None
        # 每个实例各自的配置状态（键为配置键，如 usart0），支持同外设多实例同时配置
        self.inst_state = {}
        self._cur_key = inst_names[0][1]   # 当前选中实例（切换时用于保存旧实例）
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="实例：").pack(side="left")
        self.inst_var = tk.StringVar(value=inst_names[0][0])
        combo = ttk.Combobox(bar, textvariable=self.inst_var,
                             values=[d for d, _ in inst_names], width=10, state="readonly")
        combo.pack(side="left", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>", self._on_switch)
        self.enabled = Field(bar, "启用本实例", "check", default=False)
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, pady=6)

    def inst_key(self):
        for disp, key in self.inst_names:
            if disp == self.inst_var.get():
                return key
        return self.inst_names[0][1]

    def _on_switch(self, _e):
        """切换实例：先把当前实例的字段保存进 inst_state，再加载目标实例。"""
        self.inst_state[self._cur_key] = self._read_fields()
        self._cur_key = self.inst_key()
        self._apply_fields(self.inst_state.get(self._cur_key, {}))

    def to_config(self, cfg):
        """输出所有已启用的实例到 cfg（支持同外设多实例）。"""
        self.inst_state[self._cur_key] = self._read_fields()
        for key, conf in self.inst_state.items():
            if conf.get("enabled"):
                cfg.setdefault(self.section, {})[key] = conf
            else:
                cfg.setdefault(self.section, {}).pop(key, None)
        return cfg

    def load_config(self, cfg):
        """从 cfg 重建各实例状态，并应用当前选中实例。"""
        self.inst_state = {}
        for _disp, key in self.inst_names:
            self.inst_state[key] = dict(cfg.get(self.section, {}).get(key, {}) or {})
        self._cur_key = self.inst_key()
        self._apply_fields(self.inst_state.get(self._cur_key, {}))

    def _read_fields(self):
        """子类实现：读取当前字段，返回该实例的配置 dict（含 enabled）。"""
        raise NotImplementedError

    def _apply_fields(self, conf):
        """子类实现：把配置 dict 填到当前字段。"""
        raise NotImplementedError


class USARTTab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "usart", USART_NAMES)
        f = ttk.LabelFrame(self.body, text="串口参数")
        f.pack(fill="x")
        self.baud = Field(f, "波特率", "spin", default=115200, from_=1200, to=4000000, grid=True, row=0, col=0, width=8)
        self.wl = Field(f, "字长", "combo", values=USART_WL, default="USART_WL_8BIT", grid=True, row=0, col=2, width=12)
        self.stb = Field(f, "停止位", "combo", values=USART_STB, default="USART_STB_1BIT", grid=True, row=1, col=0, width=12)
        self.pm = Field(f, "校验", "combo", values=USART_PM, default="USART_PM_NONE", grid=True, row=1, col=2, width=12)
        self.tx = Field(f, "TX引脚", "combo", values=_af_pins("USART0"), default="PA9",
                        grid=True, row=2, col=0, width=8)
        self.rx = Field(f, "RX引脚", "combo", values=_af_pins("USART0"), default="PA10",
                        grid=True, row=2, col=2, width=8)
        self.af = Field(f, "AF号(可空)", "entry", default="", grid=True, row=3, col=0, width=8)
        g = ttk.LabelFrame(self.body, text="功能")
        g.pack(fill="x", pady=(6, 0))
        self.printf = Field(g, "重定向 printf 到本串口", "check", default=False, grid=True, row=0, col=0)
        self.irq = Field(g, "使能接收中断", "check", default=False, grid=True, row=0, col=2)
        self.pre = Field(g, "抢占优先级", "spin", default=2, from_=0, to=15, grid=True, row=1, col=0, width=4)
        self.sub = Field(g, "子优先级", "spin", default=0, from_=0, to=15, grid=True, row=1, col=2, width=4)
        self.dma_tx = Field(g, "DMA发送", "check", default=False, grid=True, row=2, col=0)
        self.dma_rx = Field(g, "DMA接收", "check", default=False, grid=True, row=2, col=2)
        self.dma_irq = Field(g, "DMA完成中断", "check", default=False, grid=True, row=3, col=0)
        # 自动 DMA 通道提示：勾选 DMA 发送/接收 后，工具自动分配正确通道，无需去 DMA 页签手填
        self.dma_hint = tk.StringVar(value="勾选 DMA发送/接收 后自动分配通道，无需去 DMA 页签")
        ttk.Label(g, textvariable=self.dma_hint, foreground="#06c").grid(
            row=4, column=0, columnspan=4, sticky="w", padx=4)
        self.dma_tx.var.trace_add("write", lambda *a: self._update_dma_hint())
        self.dma_rx.var.trace_add("write", lambda *a: self._update_dma_hint())
        self.dma_irq.var.trace_add("write", lambda *a: self._update_dma_hint())

    def _read_fields(self):
        return {
            "enabled": self.enabled.get(),
            "baudrate": self.baud.get(),
            "word_length": self.wl.get(),
            "stop_bits": self.stb.get(),
            "parity": self.pm.get(),
            "tx_pin": self.tx.get() or None,
            "rx_pin": self.rx.get() or None,
            "af": self.af.get() or None,
            "printf": self.printf.get(),
            "interrupt": self.irq.get(),
            "interrupt_priority": [self.pre.get(), self.sub.get()],
            "dma_tx": self.dma_tx.get(),
            "dma_rx": self.dma_rx.get(),
            "dma_interrupt": self.dma_irq.get(),
        }

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.baud.set(c.get("baudrate", 115200))
        self.wl.set(c.get("word_length", "USART_WL_8BIT"))
        self.stb.set(c.get("stop_bits", "USART_STB_1BIT"))
        self.pm.set(c.get("parity", "USART_PM_NONE"))
        self.tx.set(c.get("tx_pin", "PA9"))
        self.rx.set(c.get("rx_pin", "PA10"))
        self.af.set(c.get("af", ""))
        self.printf.set(c.get("printf", False))
        self.irq.set(c.get("interrupt", False))
        pri = c.get("interrupt_priority", [2, 0])
        self.pre.set(pri[0] if isinstance(pri, (list, tuple)) else 2)
        self.sub.set(pri[1] if isinstance(pri, (list, tuple)) else 0)
        self.dma_tx.set(c.get("dma_tx", False))
        self.dma_rx.set(c.get("dma_rx", False))
        self.dma_irq.set(c.get("dma_interrupt", False))
        self._update_dma_hint()
        self._refresh_pins()

    def _refresh_pins(self):
        """按当前实例刷新 TX/RX 引脚下拉选项（只列该外设支持的引脚）。"""
        pins = _af_pins(self.inst_key().upper())
        if pins:
            _set_pin_combo(self.tx, pins)
            _set_pin_combo(self.rx, pins)

    def _update_dma_hint(self):
        """根据当前实例的 DMA 勾选状态，实时显示自动分配的 DMA 通道。"""
        try:
            key = self.inst_key().upper()
            tx = resolve_usart_dma(key, "tx")
            rx = resolve_usart_dma(key, "rx")
        except Exception:
            tx = rx = None
        parts = []
        if self.dma_tx.get() and tx:
            parts.append("发送→%s.%s(%s) 缓冲:%s_Buf" % (tx[0], tx[1], tx[2], key))
        if self.dma_rx.get() and rx:
            parts.append("接收→%s.%s(%s) 缓冲:%s_RxBuf" % (rx[0], rx[1], rx[2], key))
        if parts:
            self.dma_hint.set("自动分配：%s（缓冲在 main.c 定义、main.h 加 extern）" % "  ".join(parts))
        else:
            self.dma_hint.set("勾选 DMA发送/接收 后自动分配通道，无需去 DMA 页签")


class TIMERTab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "timer", TIMER_NAMES)
        f = ttk.LabelFrame(self.body, text="定时器参数")
        f.pack(fill="x")
        self.mode = Field(f, "模式", "combo", values=TIMER_MODES, default="base", grid=True, row=0, col=0, width=6)
        self.psc = Field(f, "预分频", "spin", default=0, from_=0, to=65535, grid=True, row=0, col=2, width=8)
        self.period = Field(f, "周期", "spin", default=999, from_=0, to=65535, grid=True, row=1, col=0, width=8)
        self.rep = Field(f, "重复计数", "spin", default=0, from_=0, to=255, grid=True, row=1, col=2, width=4)
        self.irq = Field(f, "使能溢出中断", "check", default=False, grid=True, row=2, col=0)
        # ic 模式下中断勾选框显示"使能捕获中断"
        self.mode.var.trace_add("write", lambda *a: self._update_irq_label())
        self._update_irq_label()
        self.pre = Field(f, "抢占优先级", "spin", default=2, from_=0, to=15, grid=True, row=2, col=2, width=4)
        self.sub = Field(f, "子优先级", "spin", default=0, from_=0, to=15, grid=True, row=3, col=0, width=4)
        ttk.Label(f, text="模式说明：base=基本定时  pwm=输出PWM  ic=输入捕获",
                  foreground="#888").grid(row=3, column=2, sticky="w")
        ch = ttk.LabelFrame(self.body, text="通道（pwm 填脉宽+引脚；ic 填引脚+极性）")
        ch.pack(fill="both", expand=True, pady=(6, 0))
        self.channels = RowTable(ch, [
            ("ch", "通道", "combo", TIMER_CH, 6),
            ("pulse", "脉宽", "entry", None, 8),
            ("pin", "引脚", "combo", [], 8),
            ("polarity", "捕获极性(ic)", "combo", IC_POL, 14),
        ], height=120, on_change=self._on_channels_change)
        self.channels.pack(fill="both", expand=True)
        # 模式(base/pwm/ic)切换时刷新引脚下拉（pwm/ic 才需要引脚）
        self.mode.var.trace_add("write", lambda *a: self._refresh_channel_pins())
        # 基本定时器（TIMER5/6 无通道）只允许 base 模式：实例切换时收敛模式选项
        self.inst_var.trace_add("write", lambda *a: self._update_mode_options())
        self._update_mode_options()
        self._refresh_channel_pins()

    def _update_mode_options(self):
        """TIMER5/6 是基本定时器（无通道、无比较输出），禁用 PWM/IC 模式。"""
        inst = self.inst_key().lower()
        if inst in ("timer5", "timer6"):
            self.mode.widget.configure(values=["base"])
            if self.mode.get() != "base":
                self.mode.set("base")
        else:
            self.mode.widget.configure(values=TIMER_MODES)

    def _update_irq_label(self):
        """ic 模式：中断勾选框显示"使能捕获中断"；base/pwm 显示"使能溢出中断"。"""
        label = "使能捕获中断" if self.mode.get() == "ic" else "使能溢出中断"
        self.irq.widget.configure(text=label)

    def _read_fields(self):
        mode = self.mode.get()
        conf = {
            "enabled": self.enabled.get(),
            "mode": mode,
            "prescaler": self.psc.get(),
            "period": self.period.get(),
            "repetition": self.rep.get(),
            "interrupt": self.irq.get(),
            "interrupt_priority": [self.pre.get(), self.sub.get()],
        }
        if mode == "pwm":
            conf["channels"] = [{"ch": int(r.get("ch", 1) or 1), "pulse": int(r.get("pulse", 0) or 0),
                                 "pin": r.get("pin", "")} for r in self.channels.rows() if r.get("pin")]
        elif mode == "ic":
            conf["ic_channels"] = [{"ch": int(r.get("ch", 1) or 1), "pin": r.get("pin", ""),
                                    "polarity": r.get("polarity", "TIMER_IC_POLARITY_RISING")}
                                   for r in self.channels.rows() if r.get("pin")]
        return conf

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.mode.set(c.get("mode", "base"))
        self.psc.set(c.get("prescaler", 0))
        self.period.set(c.get("period", 999))
        self.rep.set(c.get("repetition", 0))
        self.irq.set(c.get("interrupt", False))
        pri = c.get("interrupt_priority", [2, 0])
        self.pre.set(pri[0] if isinstance(pri, (list, tuple)) else 2)
        self.sub.set(pri[1] if isinstance(pri, (list, tuple)) else 0)
        rows = []
        for ch in c.get("channels", []):
            rows.append({"ch": str(ch.get("ch")), "pulse": str(ch.get("pulse", 0)),
                         "pin": ch.get("pin", ""), "polarity": ""})
        for ch in c.get("ic_channels", []):
            rows.append({"ch": str(ch.get("ch")), "pulse": "",
                         "pin": ch.get("pin", ""), "polarity": ch.get("polarity")})
        if rows:
            self.channels.set_rows(rows)
        else:
            self.channels.set_row(0, {})
        self._update_mode_options()
        self._refresh_channel_pins()

    def _on_channels_change(self, *_a):
        """通道/模式等单元格变化时刷新该行引脚下拉。"""
        self._refresh_channel_pins()

    def _refresh_channel_pins(self):
        """按当前定时器实例 + 每行通道号刷新引脚下拉选项（配置 ch 为 1 基，AF 键 0 基）。"""
        inst = self.inst_key().upper()
        mode = self.mode.get()
        for i, row_vars in enumerate(self.channels.vars):
            ch = "1"
            for rk, var, _w, _col in row_vars:
                if rk == "ch" and var is not None:
                    v = var.get().strip()
                    if v:
                        ch = v
                    break
            key = "%s_CH%d" % (inst, int(ch) - 1)
            if mode == "ic":
                key = key.replace("_CH", "_IC")
            pins = _af_pins(key)
            if pins:
                self.channels.set_cell_options(i, "pin", pins)


class ADCTab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "adc", ADC_NAMES)
        f = ttk.LabelFrame(self.body, text="ADC 参数")
        f.pack(fill="x")
        self.ck = Field(f, "ADC时钟", "combo", values=ADC_CK, default="ADC_ADCCK_PCLK2_DIV8", grid=True, row=0, col=0, width=18)
        self.res = Field(f, "分辨率", "combo", values=ADC_RES, default="ADC_RESOLUTION_12B", grid=True, row=0, col=2, width=16)
        self.align = Field(f, "对齐", "combo", values=ADC_ALIGN, default="ADC_DATAALIGN_RIGHT", grid=True, row=1, col=0, width=16)
        self.cont = Field(f, "连续模式", "check", default=False, grid=True, row=1, col=2)
        self.scan = Field(f, "扫描模式", "check", default=False, grid=True, row=2, col=0)
        self.dma = Field(f, "DMA输出", "check", default=False, grid=True, row=2, col=2)
        self.dma_irq = Field(f, "DMA完成中断", "check", default=False, grid=True, row=4, col=2)
        self.irq = Field(f, "转换完成中断", "check", default=False, grid=True, row=3, col=0)
        ttk.Label(f, text="DMA 缓冲变量名：ADCn_Data（uint16_t，在 main.c 定义、main.h 加 extern）",
                  foreground="#888").grid(row=5, column=0, columnspan=4, sticky="w", padx=4)
        self.pre = Field(f, "抢占优先级", "spin", default=2, from_=0, to=15, grid=True, row=3, col=2, width=4)
        self.sub = Field(f, "子优先级", "spin", default=0, from_=0, to=15, grid=True, row=4, col=0, width=4)
        ch = ttk.LabelFrame(self.body, text="规则通道（引脚可空，按数据手册自动对应：CH0-7=PA0-7、CH8=PB0、CH9=PB1、CH10-13=PC0-3、CH14=PC4、CH15=PC5；ADC2 的 CH4-9/14-15 在 PF 端口）")
        ch.pack(fill="both", expand=True, pady=(6, 0))
        self.channels = RowTable(ch, [
            ("channel", "通道", "combo", ADC_CHANNELS, 14),
            ("sampletime", "采样时间", "combo", ADC_SMP, 14),
            ("pin", "引脚", "entry", None, 8),
        ], height=120)
        self.channels.pack(fill="both", expand=True)

    def _read_fields(self):
        return {
            "enabled": self.enabled.get(),
            "clock_div": self.ck.get(),
            "resolution": self.res.get(),
            "alignment": self.align.get(),
            "continuous": self.cont.get(),
            "scan": self.scan.get(),
            "dma": self.dma.get(),
            "dma_interrupt": self.dma_irq.get(),
            "interrupt": self.irq.get(),
            "interrupt_priority": [self.pre.get(), self.sub.get()],
            "channels": [{"channel": r.get("channel", "ADC_CHANNEL_0"),
                          "sampletime": r.get("sampletime", "ADC_SAMPLETIME_15"),
                          "pin": r.get("pin", "")} for r in self.channels.rows()],
        }

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.ck.set(c.get("clock_div", "ADC_ADCCK_PCLK2_DIV8"))
        self.res.set(c.get("resolution", "ADC_RESOLUTION_12B"))
        self.align.set(c.get("alignment", "ADC_DATAALIGN_RIGHT"))
        self.cont.set(c.get("continuous", False))
        self.scan.set(c.get("scan", False))
        self.dma.set(c.get("dma", False))
        self.dma_irq.set(c.get("dma_interrupt", False))
        self.irq.set(c.get("interrupt", False))
        pri = c.get("interrupt_priority", [2, 0])
        self.pre.set(pri[0] if isinstance(pri, (list, tuple)) else 2)
        self.sub.set(pri[1] if isinstance(pri, (list, tuple)) else 0)
        rows = [{"channel": ch.get("channel"), "sampletime": ch.get("sampletime", "ADC_SAMPLETIME_15"),
                 "pin": ch.get("pin", "")} for ch in c.get("channels", [])]
        if rows:
            self.channels.set_rows(rows)
        else:
            self.channels.set_row(0, {})


class SPITab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "spi", SPI_NAMES)
        f = ttk.LabelFrame(self.body, text="SPI 参数")
        f.pack(fill="x")
        self.mode = Field(f, "主/从", "combo", values=["master", "slave"], default="master", grid=True, row=0, col=0, width=6)
        self.psc = Field(f, "预分频", "combo", values=SPI_PSC, default="SPI_PSC_64", grid=True, row=0, col=2, width=12)
        self.frame = Field(f, "帧大小", "combo", values=SPI_FRAME, default="SPI_FRAMESIZE_8BIT", grid=True, row=1, col=0, width=16)
        self.cph = Field(f, "时钟相位", "combo", values=SPI_CPH, default="SPI_CK_PL_LOW_PH_1EDGE", grid=True, row=1, col=2, width=22)
        self.sck = Field(f, "SCK引脚", "combo", values=_af_pins("SPI0"), default="PA5",
                         grid=True, row=2, col=0, width=8)
        self.miso = Field(f, "MISO引脚", "combo", values=_af_pins("SPI0"), default="PA6",
                          grid=True, row=2, col=2, width=8)
        self.mosi = Field(f, "MOSI引脚", "combo", values=_af_pins("SPI0"), default="PA7",
                          grid=True, row=3, col=0, width=8)
        self.cs = Field(f, "片选CS", "entry", default="", grid=True, row=3, col=2, width=8)
        g = ttk.LabelFrame(self.body, text="功能")
        g.pack(fill="x", pady=(6, 0))
        self.irq = Field(g, "使能接收中断", "check", default=False, grid=True, row=0, col=0)
        self.pre = Field(g, "抢占优先级", "spin", default=2, from_=0, to=15, grid=True, row=0, col=2, width=4)
        self.sub = Field(g, "子优先级", "spin", default=0, from_=0, to=15, grid=True, row=1, col=0, width=4)
        self.dma_tx = Field(g, "DMA发送", "check", default=False, grid=True, row=2, col=0)
        self.dma_rx = Field(g, "DMA接收", "check", default=False, grid=True, row=2, col=2)
        self.tx_irq = Field(g, "使能发送中断", "check", default=False, grid=True, row=3, col=0)
        self.dma_irq = Field(g, "DMA完成中断", "check", default=False, grid=True, row=3, col=2)
        ttk.Label(g, text="接收中断=RBNE→spi_rx_callback；发送中断=TBE→spi_tx_callback",
                  foreground="#888").grid(row=1, column=2, sticky="w")
        ttk.Label(g, text="DMA 缓冲变量名：发送 SPIn_Buf / 接收 SPIn_RxBuf（在 main.c 定义、main.h 加 extern）",
                  foreground="#888").grid(row=4, column=0, columnspan=4, sticky="w", padx=4)

    def _read_fields(self):
        return {
            "enabled": self.enabled.get(),
            "mode": self.mode.get(),
            "prescale": self.psc.get(),
            "frame_size": self.frame.get(),
            "clock_polarity_phase": self.cph.get(),
            "sck_pin": self.sck.get() or None,
            "miso_pin": self.miso.get() or None,
            "mosi_pin": self.mosi.get() or None,
            "cs_pin": self.cs.get() or None,
            "dma_tx": self.dma_tx.get(),
            "dma_rx": self.dma_rx.get(),
            "dma_interrupt": self.dma_irq.get(),
            "interrupt": self.irq.get(),
            "tx_interrupt": self.tx_irq.get(),
            "interrupt_priority": [self.pre.get(), self.sub.get()],
        }

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.mode.set(c.get("mode", "master"))
        self.psc.set(c.get("prescale", "SPI_PSC_64"))
        self.frame.set(c.get("frame_size", "SPI_FRAMESIZE_8BIT"))
        self.cph.set(c.get("clock_polarity_phase", "SPI_CK_PL_LOW_PH_1EDGE"))
        self.sck.set(c.get("sck_pin", "PA5"))
        self.miso.set(c.get("miso_pin", "PA6"))
        self.mosi.set(c.get("mosi_pin", "PA7"))
        self.cs.set(c.get("cs_pin", ""))
        self.dma_tx.set(c.get("dma_tx", False))
        self.dma_rx.set(c.get("dma_rx", False))
        self.dma_irq.set(c.get("dma_interrupt", False))
        self.irq.set(c.get("interrupt", False))
        self.tx_irq.set(c.get("tx_interrupt", False))
        pri = c.get("interrupt_priority", [2, 0])
        self.pre.set(pri[0] if isinstance(pri, (list, tuple)) else 2)
        self.sub.set(pri[1] if isinstance(pri, (list, tuple)) else 0)
        self._refresh_pins()

    def _refresh_pins(self):
        """按当前实例刷新 SCK/MISO/MOSI 引脚下拉（只列该 SPI 支持的引脚）。"""
        pins = _af_pins(self.inst_key().upper())
        if pins:
            _set_pin_combo(self.sck, pins)
            _set_pin_combo(self.miso, pins)
            _set_pin_combo(self.mosi, pins)


class I2CTab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "i2c", I2C_NAMES)
        f = ttk.LabelFrame(self.body, text="I2C 参数")
        f.pack(fill="x")
        self.speed = Field(f, "速率(Hz)", "spin", default=100000, from_=10000, to=400000, grid=True, row=0, col=0, width=8)
        self.addr = Field(f, "自身地址", "spin", default=80, from_=1, to=1023, grid=True, row=0, col=2, width=10)
        self.scl = Field(f, "SCL引脚", "combo", values=_af_pins("I2C0"), default="PB8",
                         grid=True, row=1, col=0, width=8)
        self.sda = Field(f, "SDA引脚", "combo", values=_af_pins("I2C0"), default="PB9",
                         grid=True, row=1, col=2, width=8)
        g = ttk.LabelFrame(self.body, text="功能")
        g.pack(fill="x", pady=(6, 0))
        self.irq = Field(g, "使能事件/错误中断", "check", default=False, grid=True, row=0, col=0)
        self.pre = Field(g, "抢占优先级", "spin", default=2, from_=0, to=15, grid=True, row=0, col=2, width=4)
        self.sub = Field(g, "子优先级", "spin", default=0, from_=0, to=15, grid=True, row=1, col=0, width=4)
        self.dma_tx = Field(g, "DMA发送", "check", default=False, grid=True, row=2, col=0)
        self.dma_rx = Field(g, "DMA接收", "check", default=False, grid=True, row=2, col=2)
        self.tx_irq = Field(g, "使能发送中断", "check", default=False, grid=True, row=3, col=0)
        self.dma_irq = Field(g, "DMA完成中断", "check", default=False, grid=True, row=3, col=2)
        ttk.Label(g, text="事件中断=RBNE接收→ev_callback，TBE发送→tx_callback；错误中断=总线/应答错误",
                  foreground="#888").grid(row=1, column=2, sticky="w")
        ttk.Label(g, text="DMA 缓冲变量名：发送 I2Cn_Buf / 接收 I2Cn_RxBuf（在 main.c 定义、main.h 加 extern）",
                  foreground="#888").grid(row=4, column=0, columnspan=4, sticky="w", padx=4)

    def _read_fields(self):
        return {
            "enabled": self.enabled.get(),
            "clkspeed": self.speed.get(),
            "addr": self.addr.get(),
            "scl_pin": self.scl.get() or None,
            "sda_pin": self.sda.get() or None,
            "dma_tx": self.dma_tx.get(),
            "dma_rx": self.dma_rx.get(),
            "dma_interrupt": self.dma_irq.get(),
            "interrupt": self.irq.get(),
            "tx_interrupt": self.tx_irq.get(),
            "interrupt_priority": [self.pre.get(), self.sub.get()],
        }

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.speed.set(c.get("clkspeed", 100000))
        self.addr.set(c.get("addr", 80))
        self.scl.set(c.get("scl_pin", "PB8"))
        self.sda.set(c.get("sda_pin", "PB9"))
        self.dma_tx.set(c.get("dma_tx", False))
        self.dma_rx.set(c.get("dma_rx", False))
        self.dma_irq.set(c.get("dma_interrupt", False))
        self.irq.set(c.get("interrupt", False))
        self.tx_irq.set(c.get("tx_interrupt", False))
        pri = c.get("interrupt_priority", [2, 0])
        self.pre.set(pri[0] if isinstance(pri, (list, tuple)) else 2)
        self.sub.set(pri[1] if isinstance(pri, (list, tuple)) else 0)
        self._refresh_pins()

    def _refresh_pins(self):
        """按当前实例刷新 SCL/SDA 引脚下拉（只列该 I2C 支持的引脚）。"""
        pins = _af_pins(self.inst_key().upper())
        if pins:
            _set_pin_combo(self.scl, pins)
            _set_pin_combo(self.sda, pins)


class CANTab(_PeriphInstanceTab):
    def __init__(self, master):
        super().__init__(master, "can", CAN_NAMES)
        f = ttk.LabelFrame(self.body, text="CAN 参数")
        f.pack(fill="x")
        self.psc = Field(f, "预分频", "spin", default=5, from_=1, to=1024, grid=True, row=0, col=0, width=6)
        self.bs1 = Field(f, "时间段1", "combo", values=CAN_BS1, default="CAN_BT_BS1_7TQ", grid=True, row=0, col=2, width=14)
        self.bs2 = Field(f, "时间段2", "combo", values=CAN_BS2, default="CAN_BT_BS2_2TQ", grid=True, row=1, col=0, width=14)
        self.sjw = Field(f, "同步跳变", "combo", values=CAN_SJW, default="CAN_BT_SJW_1TQ", grid=True, row=1, col=2, width=14)
        self.mode = Field(f, "工作模式", "combo", values=CAN_MODE, default="CAN_NORMAL_MODE", grid=True, row=2, col=0, width=18)
        self.tx = Field(f, "TX引脚", "combo", values=_af_pins("CAN0"), default="PD1",
                        grid=True, row=2, col=2, width=8)
        self.rx = Field(f, "RX引脚", "combo", values=_af_pins("CAN0"), default="PD0",
                        grid=True, row=3, col=0, width=8)

    def _read_fields(self):
        return {
            "enabled": self.enabled.get(),
            "prescaler": self.psc.get(),
            "bs1": self.bs1.get(),
            "bs2": self.bs2.get(),
            "sjw": self.sjw.get(),
            "working_mode": self.mode.get(),
            "tx_pin": self.tx.get() or None,
            "rx_pin": self.rx.get() or None,
        }

    def _apply_fields(self, c):
        self.enabled.set(bool(c))
        if not c:
            return
        self.psc.set(c.get("prescaler", 5))
        self.bs1.set(c.get("bs1", "CAN_BT_BS1_7TQ"))
        self.bs2.set(c.get("bs2", "CAN_BT_BS2_2TQ"))
        self.sjw.set(c.get("sjw", "CAN_BT_SJW_1TQ"))
        self.mode.set(c.get("working_mode", "CAN_NORMAL_MODE"))
        self.tx.set(c.get("tx_pin", "PD1"))
        self.rx.set(c.get("rx_pin", "PD0"))
        self._refresh_pins()

    def _refresh_pins(self):
        """按当前实例刷新 TX/RX 引脚下拉（只列该 CAN 支持的引脚）。"""
        pins = _af_pins(self.inst_key().upper())
        if pins:
            _set_pin_combo(self.tx, pins)
            _set_pin_combo(self.rx, pins)


class DMATab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="DMA 通道（外设填 USART0/SPI0… 自动取数据寄存器地址；内存变量填你的缓冲变量名）",
                  foreground="#666").pack(anchor="w")
        # 自动分配缓冲的大小（main.c 里自动定义 USART0_Buf 等）
        row = ttk.Frame(top)
        row.pack(fill="x", pady=2)
        self.buf_size = Field(row, "自动缓冲大小(字节)", "spin", default=64, from_=1, to=4096,
                              grid=True, row=0, col=0, width=6)
        ttk.Label(row, text="勾选外设 DMA 时在 main.c 自动定义缓冲（USART0_Buf 等）并在 main.h 加 extern",
                  foreground="#888").grid(row=0, column=1, sticky="w", padx=4)
        self.table = RowTable(self, [
            ("name", "名称", "entry", None, 8),
            ("dma", "DMA", "combo", DMA_NAMES, 6),
            ("channel", "通道", "combo", DMA_CH, 8),
            ("direction", "方向", "combo", DMA_DIR, 16),
            ("periph", "外设", "entry", None, 10),
            ("memory", "内存变量", "entry", None, 10),
            ("priority", "优先级", "combo", DMA_PRIO, 12),
            ("circular", "循环", "combo", ["0", "1"], 4),
            ("interrupt", "完成中断", "combo", ["0", "1"], 4),
        ], height=140)
        self.table.pack(fill="both", expand=True)

    def to_config(self, cfg):
        cfg.setdefault("project", {})["dma_buffer_size"] = self.buf_size.get()
        rows = []
        for r in self.table.rows():
            if not r.get("dma") or not r.get("channel"):
                continue
            direction = r.get("direction", "DMA_MEMORY_TO_PERIPH")
            if _usart_dma_covered(cfg, r.get("periph"), direction):
                continue   # 该 USART 的 DMA 由工具自动分配，丢弃手填的（可能填错）
            rows.append({
                "name": r.get("name", ""),
                "dma": r["dma"], "channel": r["channel"],
                "direction": direction,
                "periph": r.get("periph", ""), "memory": r.get("memory", "tx_buffer"),
                "priority": r.get("priority", "DMA_PRIORITY_HIGH"),
                "circular": r.get("circular", "0") == "1",
                "interrupt": r.get("interrupt", "0") == "1",
            })
        if rows:
            cfg["dma"] = {"channels": rows}
        else:
            cfg.pop("dma", None)
        return cfg

    def load_config(self, cfg):
        self.buf_size.set(cfg.get("project", {}).get("dma_buffer_size", 64))
        rows = []
        for ch in cfg.get("dma", {}).get("channels", []):
            direction = ch.get("direction", "DMA_MEMORY_TO_PERIPH")
            if _usart_dma_covered(cfg, ch.get("periph"), direction):
                continue   # 由 USART 自动分配，不显示在手动表里
            rows.append({"name": ch.get("name", ""), "dma": ch.get("dma"),
                         "channel": ch.get("channel"), "direction": direction,
                         "periph": ch.get("periph", ""), "memory": ch.get("memory", ""),
                         "priority": ch.get("priority"), "circular": "1" if ch.get("circular") else "0",
                         "interrupt": "1" if ch.get("interrupt") else "0"})
        if rows:
            self.table.set_rows(rows)
        else:
            self.table.set_row(0, {})


class DACTab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        f0 = ttk.LabelFrame(self, text="输出通道 0")
        f0.pack(fill="x")
        self.en0 = Field(f0, "使能 OUT0", "check", default=False, grid=True, row=0, col=0)
        self.al0 = Field(f0, "数据对齐", "combo", values=DAC_ALIGN, default="DAC_ALIGN_12B_R", grid=True, row=0, col=2, width=14)
        self.tr0 = Field(f0, "触发源", "combo", values=DAC_TRIG, default="DAC_TRIGGER_SOFTWARE", grid=True, row=1, col=0, width=20)
        self.v0 = Field(f0, "初始值", "spin", default=0, from_=0, to=4095, grid=True, row=1, col=2, width=8)
        f1 = ttk.LabelFrame(self, text="输出通道 1")
        f1.pack(fill="x", pady=(6, 0))
        self.en1 = Field(f1, "使能 OUT1", "check", default=False, grid=True, row=0, col=0)
        self.al1 = Field(f1, "数据对齐", "combo", values=DAC_ALIGN, default="DAC_ALIGN_12B_R", grid=True, row=0, col=2, width=14)
        self.tr1 = Field(f1, "触发源", "combo", values=DAC_TRIG, default="DAC_TRIGGER_SOFTWARE", grid=True, row=1, col=0, width=20)
        self.v1 = Field(f1, "初始值", "spin", default=0, from_=0, to=4095, grid=True, row=1, col=2, width=8)

    def to_config(self, cfg):
        if not (self.en0.get() or self.en1.get()):
            cfg.pop("dac", None)
            return cfg
        cfg["dac"] = {
            "out0": {"enable": self.en0.get(), "align": self.al0.get(),
                     "trigger": self.tr0.get(), "init_value": self.v0.get()},
            "out1": {"enable": self.en1.get(), "align": self.al1.get(),
                     "trigger": self.tr1.get(), "init_value": self.v1.get()},
        }
        return cfg

    def load_config(self, cfg):
        c = cfg.get("dac", {})
        o0 = c.get("out0", {})
        o1 = c.get("out1", {})
        self.en0.set(o0.get("enable", False))
        self.al0.set(o0.get("align", "DAC_ALIGN_12B_R"))
        self.tr0.set(o0.get("trigger", "DAC_TRIGGER_SOFTWARE"))
        self.v0.set(o0.get("init_value", 0))
        self.en1.set(o1.get("enable", False))
        self.al1.set(o1.get("align", "DAC_ALIGN_12B_R"))
        self.tr1.set(o1.get("trigger", "DAC_TRIGGER_SOFTWARE"))
        self.v1.set(o1.get("init_value", 0))


class EXTITab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        ttk.Label(self, text="外部中断：引脚如 PA0，触发选上升/下降/双沿，标签用于回调命名",
                  foreground="#666").pack(anchor="w")
        self.table = RowTable(self, [
            ("pin", "引脚", "entry", None, 6),
            ("mode", "模式", "combo", EXTI_MODE, 8),
            ("trig", "触发", "combo", EXTI_TRIG, 14),
            ("label", "标签", "entry", None, 10),
            ("pull", "上下拉", "combo", list(GPIO_PULL_MAP.keys()), 7),
            ("priority", "优先级", "entry", None, 8),
        ], height=140)
        self.table.pack(fill="both", expand=True)

    def to_config(self, cfg):
        rows = []
        for r in self.table.rows():
            if not r.get("pin"):
                continue
            pri = r.get("priority", "2,0").split(",")
            rows.append({"pin": r["pin"], "mode": r.get("mode", "interrupt"),
                         "trig": r.get("trig", "EXTI_TRIG_RISING"),
                         "label": r.get("label", ""),
                         "pull": _d2m(GPIO_PULL_MAP, r.get("pull"), "GPIO_PUPD_PULLUP"),
                         "priority": [int(pri[0].strip()) if pri[0].strip().isdigit() else 2,
                                      int(pri[1].strip()) if len(pri) > 1 and pri[1].strip().isdigit() else 0]})
        cfg["exti"] = rows
        return cfg

    def load_config(self, cfg):
        rows = []
        for e in cfg.get("exti", []) or []:
            pri = e.get("priority", [2, 0])
            rows.append({"pin": e.get("pin"), "mode": e.get("mode", "interrupt"),
                         "trig": e.get("trig", "EXTI_TRIG_RISING"),
                         "label": e.get("label", ""),
                         "pull": _m2d(GPIO_PULL_MAP, e.get("pull", "GPIO_PUPD_PULLUP")),
                         "priority": "%d,%d" % (pri[0], pri[1]) if isinstance(pri, (list, tuple)) else "2,0"})
        if rows:
            self.table.set_rows(rows)
        else:
            self.table.set_row(0, {})


class MiscTab(TabBase):
    def __init__(self, master):
        super().__init__(master)
        fw = ttk.LabelFrame(self, text="FWDGT 独立看门狗")
        fw.pack(fill="x")
        self.fw_en = Field(fw, "启用看门狗", "check", default=False, grid=True, row=0, col=0)
        self.fw_psc = Field(fw, "预分频", "combo", values=FWDGT_PSC, default="FWDGT_PSC_DIV64", grid=True, row=0, col=2, width=14)
        self.fw_rl = Field(fw, "重载值", "spin", default=500, from_=1, to=4095, grid=True, row=1, col=0, width=8)

        rt = ttk.LabelFrame(self, text="RTC 实时时钟")
        rt.pack(fill="x", pady=(6, 0))
        self.rt_en = Field(rt, "启用 RTC", "check", default=False, grid=True, row=0, col=0)
        self.rt_year = Field(rt, "年(如24)", "spin", default=24, from_=0, to=99, grid=True, row=0, col=2, width=4)
        self.rt_month = Field(rt, "月", "spin", default=1, from_=1, to=12, grid=True, row=0, col=4, width=4)
        self.rt_date = Field(rt, "日", "spin", default=1, from_=1, to=31, grid=True, row=1, col=0, width=4)
        self.rt_week = Field(rt, "星期", "spin", default=1, from_=1, to=7, grid=True, row=1, col=2, width=4)
        self.rt_hour = Field(rt, "时", "spin", default=0, from_=0, to=23, grid=True, row=1, col=4, width=4)
        self.rt_min = Field(rt, "分", "spin", default=0, from_=0, to=59, grid=True, row=2, col=0, width=4)
        self.rt_sec = Field(rt, "秒", "spin", default=0, from_=0, to=59, grid=True, row=2, col=2, width=4)
        self.rt_asyn = Field(rt, "异步分频", "spin", default=127, from_=0, to=127, grid=True, row=2, col=4, width=4)
        self.rt_syn = Field(rt, "同步分频", "spin", default=255, from_=0, to=32767, grid=True, row=3, col=0, width=6)

        m = ttk.LabelFrame(self, text="其它系统外设")
        m.pack(fill="x", pady=(6, 0))
        self.crc = Field(m, "CRC 计算单元", "check", default=False, grid=True, row=0, col=0)
        self.trng = Field(m, "TRNG 真随机数", "check", default=False, grid=True, row=0, col=2)
        self.pmu = Field(m, "PMU 电源管理", "check", default=False, grid=True, row=0, col=4)

    def to_config(self, cfg):
        for k in ("fwdgt", "rtc", "crc", "trng", "pmu"):
            cfg.pop(k, None)
        if self.fw_en.get():
            cfg["fwdgt"] = {"prescaler": self.fw_psc.get(), "reload": self.fw_rl.get()}
        if self.rt_en.get():
            cfg["rtc"] = {"year": self.rt_year.get(), "month": self.rt_month.get(),
                          "date": self.rt_date.get(), "day_of_week": self.rt_week.get(),
                          "hour": self.rt_hour.get(), "minute": self.rt_min.get(),
                          "second": self.rt_sec.get(),
                          "prescaler_asyn": self.rt_asyn.get(), "prescaler_syn": self.rt_syn.get()}
        cfg["crc"] = self.crc.get()
        cfg["trng"] = self.trng.get()
        cfg["pmu"] = self.pmu.get()
        return cfg

    def load_config(self, cfg):
        fw = cfg.get("fwdgt", {})
        self.fw_en.set(bool(fw))
        self.fw_psc.set(fw.get("prescaler", "FWDGT_PSC_DIV64"))
        self.fw_rl.set(fw.get("reload", 500))
        rt = cfg.get("rtc", {})
        self.rt_en.set(bool(rt))
        self.rt_year.set(rt.get("year", 24))
        self.rt_month.set(rt.get("month", 1))
        self.rt_date.set(rt.get("date", 1))
        self.rt_week.set(rt.get("day_of_week", 1))
        self.rt_hour.set(rt.get("hour", 0))
        self.rt_min.set(rt.get("minute", 0))
        self.rt_sec.set(rt.get("second", 0))
        self.rt_asyn.set(rt.get("prescaler_asyn", 127))
        self.rt_syn.set(rt.get("prescaler_syn", 255))
        self.crc.set(cfg.get("crc", False))
        self.trng.set(cfg.get("trng", False))
        self.pmu.set(cfg.get("pmu", False))


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("GD32Cube 配置工具")
        root.geometry("1020x680")

        # 工具栏
        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="输出目录:").pack(side="left")
        self.outdir = tk.StringVar(value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_gui"))
        ttk.Entry(bar, textvariable=self.outdir, width=40).pack(side="left", padx=4)
        ttk.Button(bar, text="浏览…", command=self._pick_outdir).pack(side="left")
        ttk.Button(bar, text="加载配置", command=self._load).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="保存配置", command=self._save).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="生成代码", command=self._generate).pack(side="right", padx=(4, 0))

        # 页签
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.last_cfg = None  # 最近一次加载/生成的配置，供实例切换加载
        self.tabs = [
            ClockTab(nb), GPIOTab(nb), USARTTab(nb), TIMERTab(nb), ADCTab(nb),
            SPITab(nb), I2CTab(nb), CANTab(nb), DMATab(nb), DACTab(nb),
            EXTITab(nb), MiscTab(nb),
        ]
        titles = ["工程/时钟", "GPIO", "USART", "TIMER", "ADC", "SPI", "I2C", "CAN",
                  "DMA", "DAC", "EXTI", "系统外设"]
        for t, title in zip(self.tabs, titles):
            t.app = self
            nb.add(t, text=title)

        self.status = tk.StringVar(value="就绪：配置好后点「生成代码」")
        ttk.Label(root, textvariable=self.status, foreground="#0a0").pack(side="bottom", anchor="w", padx=8, pady=4)

        # 加载内置示例（LED + USART0 printf），打开即可用
        self._load_default()

    def build_cfg(self):
        """汇总所有页签为完整配置 dict，并记录为最近配置。"""
        cfg = {"project": {}, "gpio": {}, "usart": {}, "timer": {}, "adc": {},
               "spi": {}, "i2c": {}, "can": {}, "dma": {}, "dac": {},
               "exti": [], "fwdgt": {}, "rtc": {}, "crc": False, "trng": False, "pmu": False}
        for t in self.tabs:
            t.to_config(cfg)
        self.last_cfg = cfg
        return cfg

    def _load_default(self):
        """加载内置默认配置（若 configs/simple.json 存在则用之，否则用空配置）。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "simple.json")
        try:
            if os.path.isfile(path):
                cfg = model.load_config(path)
                self._apply(cfg)
                self.status.set("已加载内置示例：LED + USART0 printf")
        except Exception as exc:  # noqa: BLE001
            self.status.set("默认配置加载失败：%s" % exc)

    def _apply(self, cfg):
        self.last_cfg = cfg
        for t in self.tabs:
            try:
                t.load_config(cfg)
            except Exception as exc:  # noqa: BLE001
                print("页签 %s 加载失败：%s" % (type(t).__name__, exc))

    def _pick_outdir(self):
        d = filedialog.askdirectory(initialdir=self.outdir.get())
        if d:
            self.outdir.set(d)

    def _generate(self):
        outdir = self.outdir.get().strip()
        if not outdir:
            messagebox.showwarning("输出目录为空", "请先选择输出目录。")
            return
        warnings = []
        try:
            cfg = self.build_cfg()
            n = generate_from_cfg(cfg, outdir, warnings=warnings)
            if warnings:
                self.status.set("生成完成（%d 个文件，%d 条警告）→ %s" % (n, len(warnings), outdir))
                messagebox.showwarning(
                    "生成完成（有 %d 条警告）" % len(warnings),
                    "已生成 %d 个文件到：\n%s\n\n警告：\n- %s" %
                    (n, outdir, "\n- ".join(warnings)))
            else:
                self.status.set("生成完成：%d 个文件 → %s" % (n, outdir))
                messagebox.showinfo("生成完成", "已生成 %d 个文件到：\n%s" % (n, outdir))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("生成失败", str(exc))

    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON 配置", "*.json")],
                                            initialfile="my_config.json")
        if not path:
            return
        try:
            cfg = self.build_cfg()
            header = ("// GD32Cube 配置，由图形界面生成。\n"
                      "// 命令行重新生成：python gd32_cubemx.py <此文件> -o <输出目录>\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + json.dumps(cfg, ensure_ascii=False, indent=2))
            self.status.set("配置已保存：%s" % path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    def load_config_file(self, path):
        """从配置文件加载（JSON/JSONC），供按钮与测试共用。"""
        cfg = model.load_config(path)
        self._apply(cfg)
        self.status.set("已加载配置：%s" % path)
        return cfg

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[("JSON 配置", "*.json"),
                                                     ("所有文件", "*.*")])
        if not path:
            return
        try:
            self.load_config_file(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("加载失败", str(exc))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
