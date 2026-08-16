# -*- coding: utf-8 -*-
"""EXTI 生成器：生成 MX_EXTI_Init()（exti.c/exti.h）。

把 GPIO 引脚配置为外部中断/事件源，处理 EXTI0-4 与 EXTI5_9/EXTI10_15
合并中断的中断处理函数（含每线独立的弱回调）。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import (parse_pin, pin_to_exti_source, pin_to_exti_line,
                    pin_to_exti_irq, pin_to_exti_handler)

EXTI_DEFAULTS = {
    "mode": "interrupt",            # interrupt / event
    "trig": "EXTI_TRIG_RISING",
    "pull": "GPIO_PUPD_PULLUP",
    "priority": (2, 0),
}


def generate_exti(ctx):
    from .model import enabled_instances
    raw = ctx.cfg.get("exti") or {}
    items = raw if isinstance(raw, list) else raw.get("items", [])
    if not items:
        return {}
    files = _gen(ctx, items)
    ctx.add_init_call("MX_EXTI_Init", "初始化外部中断 EXTI")
    ctx.add_libopt("gd32f4xx_exti.h")
    return files


def _gen(ctx, items):
    confs = []
    for it in items:
        conf = dict(EXTI_DEFAULTS)
        conf.update({k: v for k, v in it.items() if v is not None})
        confs.append(conf)

    b = CodeBuilder()
    b.line(file_header("exti.c", "外部中断 EXTI 初始化（MX_EXTI_Init）"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "exti.h"')
    b.line()
    emit_weak_fallback(b)

    # 端口去重
    ports = set()
    for conf in confs:
        _pm, _pin, letter, _num = parse_pin(conf["pin"])
        ports.add("GPIO%s" % letter)

    b.doc_func("MX_EXTI_Init", "配置 GPIO 外部中断线")
    b.line("void MX_EXTI_Init(void)")
    b.line("{")
    b.inc()
    for port in sorted(ports, key=lambda p: p[-1]):
        b.comment("使能 %s 端口时钟" % port)
        b.line("rcu_periph_clock_enable(RCU_%s);" % port)
    b.line()
    b.comment("使能 SYSCFG 时钟（GPIO 与 EXTI 的桥接）")
    b.line("rcu_periph_clock_enable(RCU_SYSCFG);")
    b.line()

    for i, conf in enumerate(confs):
        port_macro, pin_macro, letter, num = parse_pin(conf["pin"])
        line = pin_to_exti_line(num)
        src = pin_to_exti_source(letter)
        label = conf.get("label") or ("EXTI%d" % num)
        trig = conf["trig"]
        mode = conf["mode"]
        mode_word = "中断" if mode == "interrupt" else "事件"

        b.comment("配置 %s%s 为输入模式（%s）作为 %s 触发源" %
                  (letter, num, conf["pull"], label))
        b.line("gpio_mode_set(%s, GPIO_MODE_INPUT, %s, %s);" %
               (port_macro, conf["pull"], pin_macro))
        b.comment("把 %s%s 接到 EXTI%d" % (letter, num, num))
        b.line("syscfg_exti_line_config(%s, EXTI_SOURCE_PIN%d);" % (src, num))
        b.comment("配置 EXTI%d 为%s，%s 触发" % (num, mode_word, trig))
        b.line("exti_init(%s, %s, %s);" %
               (line, "EXTI_INTERRUPT" if mode == "interrupt" else "EXTI_EVENT", trig))
        if mode == "interrupt":
            irq = pin_to_exti_irq(num)
            pre, sub = conf["priority"]
            b.line("nvic_irq_enable(%s, %d, %d);  /* 抢占 %d / 子优先级 %d */" %
                   (irq, pre, sub, pre, sub))
            ctx.add_nvic(irq, pre, sub, "%s 外部中断" % label)
        b.line()

    b.dec()
    b.line("}")
    b.line()

    # 每线回调（弱）与合并中断处理函数
    handlers = {}
    for conf in confs:
        _pm, _pin, letter, num = parse_pin(conf["pin"])
        line = pin_to_exti_line(num)
        label = conf.get("label") or ("EXTI%d" % num)
        cb = "exti%d_callback" % num
        b.doc_func(cb, "EXTI%d（%s）触发回调（__WEAK，用户可重定义）" % (num, label))
        b.line("__WEAK void %s(void)" % cb)
        b.line("{")
        b.inc()
        b.line("/* USER CODE BEGIN %s_EXTI */" % label.upper())
        b.line("/* TODO: 在这里处理 %s 外部中断 */" % label)
        b.line("/* USER CODE END %s_EXTI */" % label.upper())
        b.dec()
        b.line("}")
        b.line()
        # 合并到对应处理函数
        handler = pin_to_exti_handler(num)
        if handler not in handlers:
            handlers[handler] = []
        handlers[handler].append((line, cb, label))

    # 生成 it.c 里的中断处理
    for handler, lines in handlers.items():
        body = CodeBuilder()
        body.comment("依次检查本组中配置的 EXTI 线")
        for line, cb, label in lines:
            body.line("if(SET == exti_interrupt_flag_get(%s)) {" % line)
            body.inc()
            body.line("exti_interrupt_flag_clear(%s);" % line)
            body.line("%s();  /* %s */" % (cb, label))
            body.dec()
            body.line("}")
        ctx.add_irq_handler(handler, "外部中断处理（%s）" % ", ".join(l[2] for l in lines),
                            str(body))

    # .h
    h = CodeBuilder()
    guard = include_guard("exti_h")
    h.line(file_header("exti.h", "外部中断初始化声明与回调"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_EXTI_Init(void);")
    h.line()
    for conf in confs:
        _pm, _pin, _letter, num = parse_pin(conf["pin"])
        h.line("/* EXTI%d 回调（弱实现，可在用户代码中重定义） */" % num)
        h.line("void exti%d_callback(void);" % num)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"exti.c": str(b), "exti.h": str(h)}
