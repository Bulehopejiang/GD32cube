# -*- coding: utf-8 -*-
"""中断文件生成器：gd32f4xx_it.c / gd32f4xx_it.h。

包含核心异常处理函数 + 各外设登记的中断处理函数（调用弱回调）。
"""

from .common import CodeBuilder, file_header, include_guard

# 核心异常处理（与固件库模板一致）
CORE_HANDLERS = [
    ("NMI_Handler", "NMI 不可屏蔽中断"),
    ("HardFault_Handler", "硬件错误"),
    ("MemManage_Handler", "内存管理错误"),
    ("BusFault_Handler", "总线错误"),
    ("UsageFault_Handler", "用法错误"),
    ("SVC_Handler", "系统服务调用"),
    ("DebugMon_Handler", "调试监视"),
    ("PendSV_Handler", "可挂起系统调用"),
]


def _user_block(b, tag):
    """在每个中断处理函数里预置一个 USER CODE 区块。

    标记固定为处理函数名，重新生成时按标记精确匹配保留用户代码
    （比"锚点猜测"可靠得多，仿 CubeMX 的 USER CODE 区块）。
    """
    b.line("/* USER CODE BEGIN %s */" % tag)
    b.line("/* USER CODE END %s */" % tag)


def generate_it(ctx):
    b = CodeBuilder()
    b.line(file_header("gd32f4xx_it.c", "中断服务函数"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "gd32f4xx_it.h"')
    # 需要调用回调的外设头文件（生成目录里的全部 .h，含 systick.h）
    for name in sorted(ctx.files):
        if name.endswith(".h") and not name.startswith("gd32f4xx_it"):
            b.line('#include "%s"' % name)
    b.line()

    # 核心异常
    for handler, brief in CORE_HANDLERS:
        b.doc_func(handler, "%s处理函数" % brief)
        b.line("void %s(void)" % handler)
        b.line("{")
        b.inc()
        _user_block(b, handler)
        b.comment("若 %s 发生，进入死循环（便于调试定位）" % brief)
        b.empty_block("while(1)")
        b.dec()
        b.line("}")
        b.line()

    # SysTick
    if ctx.systick_enabled:
        b.doc_func("SysTick_Handler", "SysTick 中断：递减延时计数")
        b.line("void SysTick_Handler(void)")
        b.line("{")
        b.inc()
        b.line("delay_decrement();")
        _user_block(b, "SysTick_Handler")
        b.dec()
        b.line("}")
        b.line()

    # 外设中断（同一 handler 可登记多个实例的处理体，合并到同一个函数，
    # 例如 ADC0/ADC1 共用一个 ADC_IRQHandler、TIMER1/TIMER11 共用一个 IRQ）
    if ctx.irq_handlers:
        for handler, entries in ctx.irq_handlers.items():
            b.doc_func(handler, "；".join(br for br, _ in entries))
            b.line("void %s(void)" % handler)
            b.line("{")
            b.inc()
            _user_block(b, handler)
            for _brief, body in entries:
                # body 为已按层缩进的行，逐行按当前层再缩进一级
                for ln in body.rstrip("\n").split("\n"):
                    b.line(ln)
            b.dec()
            b.line("}")
            b.line()

    # ---- it.h ----
    h = CodeBuilder()
    guard = include_guard("gd32f4xx_it_h")
    h.line(file_header("gd32f4xx_it.h", "中断服务函数声明"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    for handler, _brief in CORE_HANDLERS:
        h.line("void %s(void);" % handler)
    if ctx.systick_enabled:
        h.line("void SysTick_Handler(void);")
    for handler in ctx.irq_handlers:
        h.line("void %s(void);" % handler)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"gd32f4xx_it.c": str(b), "gd32f4xx_it.h": str(h)}
