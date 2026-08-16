# -*- coding: utf-8 -*-
"""main.c / main.h 生成器：按 CubeMX 风格组装各 MX_xxx_Init() 调用。"""

from .common import CodeBuilder, file_header, include_guard


def generate_main(ctx):
    b = CodeBuilder()
    b.line(file_header("main.c", "主程序（由 GD32Cube 生成）"))
    b.line('#include "gd32f4xx.h"')
    # 引入所有生成的头文件
    headers = sorted(n for n in ctx.files if n.endswith(".h")
                     and n not in ("gd32f4xx_it.h", "gd32f4xx_libopt.h"))
    for h in headers:
        b.line('#include "%s"' % h)
    b.line()

    # 自动分配的 DMA 缓冲定义（重新生成时此段会被覆盖，大小可在 DMA 页签调整）
    if ctx.dma_buffers:
        buf_size = int((ctx.cfg.get("project") or {}).get("dma_buffer_size", 64))
        b.line("/* GD32Cube 自动分配的 DMA 缓冲（供外设 DMA 使用；大小可在 DMA 页签调整，")
        b.line("   应用层可直接使用这些变量，或自行重新定义同名的其它缓冲） */")
        for name, ctype, note in ctx.dma_buffers:
            b.line("%s %s[%d];  /* %s DMA 缓冲 */" % (ctype, name, buf_size, note))
        b.line()

    # 文件级 USER CODE 区块：声明全局变量/宏（注意 BEGIN 2 在 main() 函数内部，
    # 只能放语句，不能放跨文件访问的全局变量）
    b.line("/* USER CODE BEGIN 0 */")
    b.line("/* 全局变量 / 宏定义放这里（文件作用域），函数内部的 USER CODE BEGIN 2 只能放语句 */")
    b.line("/* USER CODE END 0 */")
    b.line()
    b.line("int main(void)")
    b.line("{")
    b.inc()
    b.line()
    b.comment("配置系统时钟（RCU / PLL，见 system_clock.c）")
    b.line("system_clock_config();")
    if ctx.nvic_enables:
        b.line()
        b.comment("设置 NVIC 优先级分组（先于任何 nvic_irq_enable 调用）")
        b.line("nvic_priority_group_set(%s);" % ctx.nvic_group)
    if ctx.systick_enabled:
        b.line()
        b.comment("配置 SysTick（1ms 中断），此后 delay_1ms() 可用")
        b.line("systick_config();")
    b.line()
    b.comment("初始化 GPIO（用户引脚 + 各外设复用引脚）")
    b.line("MX_GPIO_Init();")
    b.line()
    for call, comment in ctx.init_calls:
        b.comment(comment)
        b.line("%s();" % call)
    b.line()
    b.line("/* USER CODE BEGIN 2 */")
    b.line("/* USER CODE END 2 */")
    b.line()
    b.line("while(1) {")
    b.inc()
    b.line("/* USER CODE BEGIN while */")
    b.line("/* USER CODE END while */")
    b.dec()
    b.line("}")
    b.dec()
    b.line("}")

    h = CodeBuilder()
    guard = include_guard("main_h")
    h.line(file_header("main.h", "主程序头文件"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    if ctx.dma_buffers:
        h.line("/* GD32Cube 自动分配的 DMA 缓冲（定义在 main.c，供各外设 DMA 使用） */")
        for name, ctype, note in ctx.dma_buffers:
            h.line("extern %s %s[%d];  /* %s DMA 缓冲 */" %
                   (ctype, name, int((ctx.cfg.get("project") or {}).get("dma_buffer_size", 64)),
                    note))
        h.line()
    h.line("#endif /* %s */" % guard)

    return {"main.c": str(b), "main.h": str(h)}
