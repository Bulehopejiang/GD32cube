# -*- coding: utf-8 -*-
"""USART 生成器：生成 MX_USARTn_Init()（usart0.c/usart0.h 等）。

覆盖：波特率/字长/停止位/校验、收发使能、DMA 请求、接收中断（含弱回调）、
printf 重定向。引脚复用 AF 登记到 ctx 由 MX_GPIO_Init 统一输出。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .af_table import lookup_af

# USART 实例 -> (RCU 使能宏, 所在总线, 中断号, 中断处理函数名)
USART_INFO = {
    "USART0": ("RCU_USART0", "APB2", "USART0_IRQn", "USART0_IRQHandler"),
    "USART1": ("RCU_USART1", "APB1", "USART1_IRQn", "USART1_IRQHandler"),
    "USART2": ("RCU_USART2", "APB1", "USART2_IRQn", "USART2_IRQHandler"),
    "UART3":  ("RCU_UART3",  "APB1", "UART3_IRQn",  "UART3_IRQHandler"),
    "UART4":  ("RCU_UART4",  "APB1", "UART4_IRQn",  "UART4_IRQHandler"),
    "USART5": ("RCU_USART5", "APB2", "USART5_IRQn", "USART5_IRQHandler"),
    "UART6":  ("RCU_UART6",  "APB1", "UART6_IRQn",  "UART6_IRQHandler"),
    "UART7":  ("RCU_UART7",  "APB1", "UART7_IRQn",  "UART7_IRQHandler"),
}

# USART -> DMA 通道映射（GD32F4xx 用户手册 Rev3.3 表 10-2 DMA0 / 表 10-3 DMA1 权威数据）。
# 格式: {名称: (TX_DMA, TX通道, TX子外设, RX_DMA, RX通道, RX子外设)}
# 外设请求所在的「通道 × PERIEN」对即通道号与 SUBPERI（PERIEN000=SUBPERI0 ... 111=SUBPERI7）。
# 此表同时用于「自动生成 DMA 通道」：在 USART 勾选 DMA 发送/接收即可，无需手填 DMA 页签。
USART_DMA_MAP = {
    "USART0": ("DMA1", "DMA_CH7", "DMA_SUBPERI4", "DMA1", "DMA_CH2", "DMA_SUBPERI4"),
    "USART1": ("DMA0", "DMA_CH6", "DMA_SUBPERI4", "DMA0", "DMA_CH5", "DMA_SUBPERI4"),
    "USART2": ("DMA0", "DMA_CH3", "DMA_SUBPERI4", "DMA0", "DMA_CH1", "DMA_SUBPERI4"),
    "UART3":  ("DMA0", "DMA_CH4", "DMA_SUBPERI4", "DMA0", "DMA_CH2", "DMA_SUBPERI4"),
    "UART4":  ("DMA0", "DMA_CH7", "DMA_SUBPERI4", "DMA0", "DMA_CH0", "DMA_SUBPERI4"),
    "USART5": ("DMA1", "DMA_CH6", "DMA_SUBPERI5", "DMA1", "DMA_CH1", "DMA_SUBPERI5"),
    "UART6":  ("DMA0", "DMA_CH1", "DMA_SUBPERI5", "DMA0", "DMA_CH2", "DMA_SUBPERI5"),
    "UART7":  ("DMA0", "DMA_CH0", "DMA_SUBPERI5", "DMA0", "DMA_CH4", "DMA_SUBPERI5"),
}

# 每个 USART 的方向 -> 该方向在 USART_DMA_MAP 里的字段序号（TX/RX 三元组起点）
_USART_DMA_TX = 0   # TX 三元组在元组中的起始下标
_USART_DMA_RX = 3   # RX 三元组在元组中的起始下标


def resolve_usart_dma(usart_name, direction="tx"):
    """查 USART 的 DMA 通道映射，返回 (dma, channel, subperiph)。

    - usart_name: 'USART2'（大写）或 'usart2'（小写均可）
    - direction: 'tx' 或 'rx'
    未知 USART 返回 None。
    """
    key = usart_name.upper()
    if key not in USART_DMA_MAP:
        return None
    start = _USART_DMA_TX if direction == "tx" else _USART_DMA_RX
    dma, channel, sub = USART_DMA_MAP[key][start:start + 3]
    return dma, channel, sub

# 配置项默认值
USART_DEFAULTS = {
    "baudrate": 115200,
    "word_length": "USART_WL_8BIT",
    "stop_bits": "USART_STB_1BIT",
    "parity": "USART_PM_NONE",
    "tx_pin": None, "rx_pin": None,
    "af": None,
    "interrupt": False,
    "interrupt_priority": (2, 0),
    "dma_tx": False, "dma_rx": False,
    "printf": False,
}


def _merge_defaults(conf):
    out = dict(USART_DEFAULTS)
    out.update({k: v for k, v in conf.items() if v is not None})
    return out


def generate_usart(ctx):
    """处理所有启用的 USART，返回 {文件名: 内容}。"""
    from .model import enabled_instances
    files = {}
    instances = list(enabled_instances(ctx.cfg, "usart").items())
    # printf 只能重定向到一个串口：确定唯一目标，其余设 printf 的只告警
    printf_target = None
    printf_count = 0
    for name, raw in instances:
        if _merge_defaults(raw)["printf"]:
            printf_count += 1
            if printf_target is None:
                printf_target = name
    if printf_count > 1:
        ctx.warn("%d 个串口设置了 printf，仅 %s 生效（fputc 只能重定向一个串口）"
                 % (printf_count, printf_target))
    for name, raw in instances:
        conf = _merge_defaults(raw)
        c, h, periph, bus = _gen_one(ctx, name, conf, is_printf=(name == printf_target))
        files.update(c)
        files.update(h)
        ctx.add_init_call("MX_%s_Init" % periph, "初始化 %s 串口" % periph)
        if conf["printf"] and ctx.printf_uart is None:
            ctx.printf_uart = (periph, name)
        ctx.add_libopt("gd32f4xx_usart.h")
    return files


def _gen_one(ctx, name, conf, is_printf=False):
    """生成单个 USART 的 .c/.h。is_printf 表示本串口是 printf 重定向目标。"""
    name_key = name.upper()  # usart0 -> USART0（与固件库宏一致）
    rcu_macro, bus, irqn, handler = USART_INFO[name_key]
    periph = name_key
    # 波特率注释用的 PCLK
    pclk = ctx.clock.apb2 if bus == "APB2" else ctx.clock.apb1

    # ---- 登记引脚复用 ----
    tx_pin = rx_pin = None
    if conf.get("tx_pin"):
        tx_pin = parse_pin(conf["tx_pin"])
        _register_af(ctx, periph, conf["tx_pin"], tx_pin, conf["af"], "TX")
    if conf.get("rx_pin"):
        rx_pin = parse_pin(conf["rx_pin"])
        _register_af(ctx, periph, conf["rx_pin"], rx_pin, conf["af"], "RX")

    # ---- .c 文件 ----
    b = CodeBuilder()
    b.line(file_header("%s.c" % name.lower(),
                       "%s 初始化（MX_%s_Init）" % (periph, periph)))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name.lower())
    if conf["printf"]:
        b.line('#include <stdio.h>')
    b.line()
    emit_weak_fallback(b)

    # MX 初始化函数
    b.doc_func("MX_%s_Init" % periph,
               "初始化 %s 串口（波特率 %d）" % (periph, conf["baudrate"]))
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()
    b.comment("使能 %s 时钟（所在总线：%s）" % (periph, bus))
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 %s，恢复默认配置" % periph)
    b.line("usart_deinit(%s);" % periph)
    b.line()
    b.comment("配置波特率 %d bps（PCLK = %dMHz，硬件自动计算分频系数）" %
              (conf["baudrate"], pclk))
    b.line("usart_baudrate_set(%s, %dU);" % (periph, conf["baudrate"]))
    b.line()
    b.comment("字长 / 停止位 / 校验")
    b.line("usart_word_length_set(%s, %s);" % (periph, conf["word_length"]))
    b.line("usart_stop_bit_set(%s, %s);" % (periph, conf["stop_bits"]))
    b.line("usart_parity_config(%s, %s);" % (periph, conf["parity"]))
    b.line()
    b.comment("使能接收与发送")
    b.line("usart_receive_config(%s, USART_RECEIVE_ENABLE);" % periph)
    b.line("usart_transmit_config(%s, USART_TRANSMIT_ENABLE);" % periph)

    # DMA
    if conf["dma_tx"] or conf["dma_rx"]:
        tx_dma, tx_ch, tx_sp, rx_dma, rx_ch, rx_sp = USART_DMA_MAP[name_key]
        b.line()
        b.comment("使能 %s 的 DMA 请求（DMA 通道由工具自动分配，见 dma 段）" % periph)
        if conf["dma_tx"]:
            b.line("/* TX 走 %s.%s(%s) 通道 */" % (tx_dma, tx_ch, tx_sp))
            b.line("usart_dma_transmit_config(%s, USART_TRANSMIT_DMA_ENABLE);" % periph)
        if conf["dma_rx"]:
            b.line("/* RX 走 %s.%s(%s) 通道 */" % (rx_dma, rx_ch, rx_sp))
            b.line("usart_dma_receive_config(%s, USART_RECEIVE_DMA_ENABLE);" % periph)

    b.line()
    b.comment("使能 %s" % periph)
    b.line("usart_enable(%s);" % periph)

    # 中断
    if conf["interrupt"]:
        pre, sub = conf["interrupt_priority"]
        b.line()
        b.comment("使能 %s 接收中断（收到数据触发 RBNE）" % periph)
        b.line("usart_interrupt_enable(%s, USART_INT_RBNE);" % periph)
        b.line("nvic_irq_enable(%s, %d, %d);  /* 抢占 %d / 子优先级 %d */" %
               (irqn, pre, sub, pre, sub))
        ctx.add_nvic(irqn, pre, sub, periph + " 接收中断")

    b.dec()
    b.line("}")
    b.line()

    # 弱回调（用户可重定义，也可直接改下面 USER CODE 块）
    cb = "__WEAK void %s_rx_callback(uint16_t data)" % name.lower()
    b.doc_func("%s_rx_callback" % name.lower(),
               "%s 接收回调（弱实现，用户可在别处重定义或改 USER CODE 块）" % periph)
    b.line(cb)
    b.line("{")
    b.inc()
    b.line("/* USER CODE BEGIN %s_RX */" % name.upper())
    b.line("/* TODO: 在这里处理接收到的数据 */")
    b.line("/* USER CODE END %s_RX */" % name.upper())
    b.line("(void)data;")
    b.dec()
    b.line("}")
    b.line()

    # printf 重定向（仅 printf 目标串口生成 fputc，避免多个串口重复定义 fputc）
    if is_printf:
        b.comment("重定向 printf 输出到 %s（Keil MDK 方式：实现 fputc）" % periph)
        b.line("int fputc(int ch, FILE *f)")
        b.line("{")
        b.inc()
        b.line("(void)f;  /* 未用到文件指针，避免 -Wunused-parameter 警告 */")
        b.line("/* 等待发送缓冲空 */")
        b.line("while(RESET == usart_flag_get(%s, USART_FLAG_TBE));" % periph)
        b.line("/* 发送一个字节 */")
        b.line("usart_data_transmit(%s, (uint8_t)ch);" % periph)
        b.line("return ch;")
        b.dec()
        b.line("}")
        b.line()
        b.line("/* 注意：若使用 GCC 工具链，应改实现 _write() 而不是 fputc()。 */")

    # ---- .h 文件 ----
    h = CodeBuilder()
    guard = include_guard("%s_h" % name.lower())
    h.line(file_header("%s.h" % name.lower(), "%s 初始化声明与回调" % periph))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("/* 初始化函数声明 */")
    h.line("void MX_%s_Init(void);" % periph)
    if conf["interrupt"]:
        h.line()
        h.line("/* 接收回调（默认弱实现，可在用户代码中重定义） */")
        h.line("void %s_rx_callback(uint16_t data);" % name.lower())
    if conf["dma_tx"]:
        # 注意：映射表键是大写（USART0/USART1/...），这里必须用 name_key 而非 name
        tx_dma, tx_ch, tx_sp, _a, _b, _c = USART_DMA_MAP[name_key]
        h.line()
        h.line("/* TX DMA 通道：%s.%s(%s)，由工具自动分配 */" % (tx_dma, tx_ch, tx_sp))
    h.line()
    h.line("#endif /* %s */" % guard)
    files_c = {"%s.c" % name.lower(): str(b)}
    files_h = {"%s.h" % name.lower(): str(h)}

    # ---- 登记中断处理函数（it.c 用）----
    if conf["interrupt"]:
        body = CodeBuilder()
        body.comment("收到数据（RBNE）")
        body.line("if(SET == usart_interrupt_flag_get(%s, USART_INT_FLAG_RBNE)) {" % periph)
        body.inc()
        body.line("/* 读取数据（自动清除标志）并交给用户回调 */")
        body.line("uint16_t rxdata = usart_data_receive(%s);" % periph)
        body.line("usart_interrupt_flag_clear(%s, USART_INT_FLAG_RBNE);" % periph)
        body.line("%s_rx_callback(rxdata);" % name.lower())
        body.dec()
        body.line("}")
        ctx.add_irq_handler(handler, "%s 中断处理" % periph, str(body))

    return files_c, files_h, periph, bus


def _register_af(ctx, periph, pin_str, pin_tuple, cfg_af, role):
    """登记一个 USART 引脚的复用配置。"""
    port_macro, _pin_macro, port_letter, pin_num = pin_tuple
    af = lookup_af(periph, pin_str, cfg_af)
    if af is None:
        af = 7
        ctx.warn("%s.%s(%s) 的 AF 号未知，默认用 AF7，请在配置里显式指定 af 字段"
                 % (periph, pin_str, role))
    ctx.add_af(port_macro, _pin_macro, af,
               "%s %s 引脚" % (periph, role))
