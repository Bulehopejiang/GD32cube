# -*- coding: utf-8 -*-
"""GPIO 生成器：生成 MX_GPIO_Init()（gpio.c / gpio.h）。

汇总三类用户引脚（输出/输入/模拟）和所有外设登记的复用引脚(AF)，
参考 CubeMX 的 MX_GPIO_Init() 组织方式：先使能各端口时钟，再逐引脚配置。
"""

import re

from .common import CodeBuilder, file_header, include_guard
from .model import parse_pin, pin_label

# 合法 C 标识符（用于判断标签能否生成宏）
_C_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _warn_pin_conflicts(ctx):
    """检测同一引脚被配置为多种互斥用途，给出警告（仿 CubeMX 冲突提示）。"""
    usage = {}  # (port, pin) -> 用途列表
    for port, pin, _s, _l, label, _ot in ctx.gpio_outputs:
        usage.setdefault((port, pin), []).append("输出(%s)" % (label or ""))
    for port, pin, _p, label in ctx.gpio_inputs:
        usage.setdefault((port, pin), []).append("输入(%s)" % (label or ""))
    for port, pin, label in ctx.gpio_analog:
        usage.setdefault((port, pin), []).append("模拟输入(%s)" % (label or ""))
    for port, pin, af, note, _ot in ctx.af_configs:
        usage.setdefault((port, pin), []).append("复用AF%d(%s)" % (af, note))
    for (port, pin), uses in sorted(usage.items()):
        if len(uses) > 1:
            ctx.warn("引脚 %s 被配置为多个用途：%s —— 请检查是否有误"
                     % (pin_label(port, pin), " / ".join(uses)))


def _load_user_gpio(ctx):
    """读取配置里 gpio 段的用户引脚，填入 ctx。"""
    gcfg = ctx.cfg.get("gpio") or {}

    def _pin(p):
        return parse_pin("P" + str(p["port"]).upper() + str(p["pin"]))

    for o in gcfg.get("outputs", []):
        port_macro, pin_macro, _l, _n = _pin(o)
        ctx.gpio_outputs.append((port_macro, pin_macro,
                                 o.get("speed", "GPIO_OSPEED_50MHZ"),
                                 o.get("init_level", "LOW"), o.get("label", ""),
                                 o.get("otype", "GPIO_OTYPE_PP")))
    for i in gcfg.get("inputs", []):
        port_macro, pin_macro, _l, _n = _pin(i)
        ctx.gpio_inputs.append((port_macro, pin_macro,
                                i.get("pull", "GPIO_PUPD_PULLUP"), i.get("label", "")))
    for a in gcfg.get("analog", []):
        port_macro, pin_macro, _l, _n = _pin(a)
        ctx.gpio_analog.append((port_macro, pin_macro, a.get("label", "")))


def generate_gpio(ctx):
    """生成 gpio.c / gpio.h，返回 {文件名: 内容}。"""
    _load_user_gpio(ctx)
    _warn_pin_conflicts(ctx)
    files = {}

    # ---- 收集需要使能时钟的端口 ----
    used_ports = set(ctx.af_ports)
    for port, _pin, *_ in ctx.gpio_outputs + ctx.gpio_inputs + ctx.gpio_analog:
        used_ports.add(port)

    b = CodeBuilder()
    b.line(file_header("gpio.c", "GPIO 引脚初始化（MX_GPIO_Init）"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "gpio.h"')
    b.line()
    b.doc_func("MX_GPIO_Init", "配置所有 GPIO 引脚（用户引脚 + 外设复用引脚）")
    b.line("void MX_GPIO_Init(void)")
    b.line("{")
    b.inc()

    # 1) 使能端口时钟
    for port in sorted(used_ports, key=lambda p: p[-1]):
        b.comment("使能 %s 端口时钟" % port)
        b.line("rcu_periph_clock_enable(RCU_%s);" % port)
    if not used_ports:
        b.line("/* 本工程未配置任何 GPIO 引脚 */")

    # 2) 输出引脚
    for port, pin, speed, level, label, otype in ctx.gpio_outputs:
        b.line()
        b.comment("配置 %s 为%s输出（%s）" % (pin_label(port, pin),
                                              "推挽" if otype == "GPIO_OTYPE_PP" else "开漏",
                                              label or "LED/输出"))
        b.line("gpio_mode_set(%s, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, %s);" % (port, pin))
        b.line("gpio_output_options_set(%s, %s, %s, %s);" % (port, otype, speed, pin))
        if level == "HIGH":
            b.line("gpio_bit_set(%s, %s);  /* 初始电平：高 */" % (port, pin))
        else:
            b.line("gpio_bit_reset(%s, %s);  /* 初始电平：低 */" % (port, pin))

    # 3) 输入引脚
    for port, pin, pull, label in ctx.gpio_inputs:
        b.line()
        b.comment("配置 %s 为输入模式（%s）" % (pin_label(port, pin),
                                                label or "KEY/输入"))
        b.line("gpio_mode_set(%s, GPIO_MODE_INPUT, %s, %s);" % (port, pull, pin))

    # 4) 模拟引脚
    for port, pin, label in ctx.gpio_analog:
        b.line()
        b.comment("配置 %s 为模拟模式（%s）" % (pin_label(port, pin),
                                                 label or "ADC/模拟输入"))
        b.line("gpio_mode_set(%s, GPIO_MODE_ANALOG, GPIO_PUPD_NONE, %s);" % (port, pin))

    # 5) 外设复用引脚
    seen = set()
    for port, pin, af, note, otype in ctx.af_configs:
        key = (port, pin)
        if key in seen:
            continue  # 同一引脚已被配置过（如复用 + 用户配置）
        seen.add(key)
        b.line()
        b.comment("配置 %s 为复用功能 AF%d（%s）" % (pin_label(port, pin), af, note))
        b.line("gpio_mode_set(%s, GPIO_MODE_AF, GPIO_PUPD_NONE, %s);" % (port, pin))
        b.line("gpio_output_options_set(%s, %s, GPIO_OSPEED_50MHZ, %s);" % (port, otype, pin))
        b.line("gpio_af_set(%s, GPIO_AF_%d, %s);" % (port, af, pin))

    b.dec()
    b.line("}")
    files["gpio.c"] = str(b)

    # ---- gpio.h ----
    h = CodeBuilder()
    guard = include_guard("gpio_h")
    h.line(file_header("gpio.h", "GPIO 初始化函数声明与引脚宏定义"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    # 引脚宏定义（参考 CubeMX 生成风格；仅对合法 C 标识符的标签生成）
    macros = []
    for port, pin, _s, _l, label, _ot in ctx.gpio_outputs:
        if label and _C_IDENT_RE.match(label):
            macros.append((label, port, pin))
    for port, pin, _pull, label in ctx.gpio_inputs:
        if label and _C_IDENT_RE.match(label):
            macros.append((label, port, pin))
    for port, pin, label in ctx.gpio_analog:
        if label and _C_IDENT_RE.match(label):
            macros.append((label, port, pin))
    if macros:
        h.line("/* 用户引脚宏定义（标签名 -> 端口/引脚） */")
        for label, port, pin in macros:
            h.line("#define %s_Pin        %s" % (label, pin))
            h.line("#define %s_GPIO_Port  %s" % (label, port))
        h.line()
    h.line("/* 函数声明 */")
    h.line("void MX_GPIO_Init(void);")
    h.line()
    h.line("#endif /* %s */" % guard)
    files["gpio.h"] = str(h)

    return files
