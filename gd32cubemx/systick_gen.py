# -*- coding: utf-8 -*-
"""SysTick 生成器：systick.c / systick.h（1ms 中断延时）。

与固件库模板 systick.c 一致，提供 delay_1ms() 与 delay_decrement()。
"""

from .common import CodeBuilder, file_header, include_guard


def generate_systick(ctx):
    if not ctx.systick_enabled:
        return {}

    b = CodeBuilder()
    b.line(file_header("systick.c", "SysTick 定时器配置与毫秒延时"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "systick.h"')
    b.line()
    b.line("volatile static uint32_t delay;")
    b.line()

    b.doc_func("systick_config", "配置 SysTick 为 1ms 中断（1000Hz）")
    b.line("void systick_config(void)")
    b.line("{")
    b.inc()
    b.comment("配置 SysTick 为 1ms 中断：重载值 = SystemCoreClock / 1000")
    b.line("if(SysTick_Config(SystemCoreClock / 1000U)) {")
    b.inc()
    b.comment("配置失败，死循环等待（正常情况下不会走到）")
    b.line("while(1) {")
    b.inc(); b.line(""); b.dec()
    b.line("}")
    b.dec()
    b.line("}")
    b.comment("配置 SysTick 中断优先级（%d，越小优先级越高）" % ctx.systick_priority)
    b.line("NVIC_SetPriority(SysTick_IRQn, 0x%02XU);" % ctx.systick_priority)
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("delay_1ms", "毫秒级阻塞延时", "count: 延时毫秒数")
    b.line("void delay_1ms(uint32_t count)")
    b.line("{")
    b.inc()
    b.line("delay = count;")
    b.line()
    b.line("while(0U != delay) {")
    b.inc(); b.line(""); b.dec()
    b.line("}")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("delay_decrement", "延时计数递减（在 SysTick 中断里调用）")
    b.line("void delay_decrement(void)")
    b.line("{")
    b.inc()
    b.line("if(0U != delay) {")
    b.inc()
    b.line("delay--;")
    b.dec()
    b.line("}")
    b.dec()
    b.line("}")

    h = CodeBuilder()
    guard = include_guard("systick_h")
    h.line(file_header("systick.h", "SysTick 延时函数声明"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void systick_config(void);")
    h.line("void delay_1ms(uint32_t count);")
    h.line("void delay_decrement(void);")
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"systick.c": str(b), "systick.h": str(h)}
