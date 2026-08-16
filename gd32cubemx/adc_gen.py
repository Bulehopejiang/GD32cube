# -*- coding: utf-8 -*-
"""ADC 生成器：生成 MX_ADCn_Init()（adc0.c/adc0.h 等）。

覆盖：ADC 时钟、分辨率/对齐、独立/同步模式、连续/扫描、规则通道序列、
软件触发、DMA、采样完成中断。模拟输入引脚登记到 MX_GPIO_Init。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .clock import ADC_CLK_MAX_MHZ

ADC_INFO = {
    # (RCU, DMA, 通道, 子外设) —— GD32F4xx 用户手册表 10-3 DMA1：
    #   ADC0=DMA1_CH0/SUBPERI0（PERIEN000）、ADC1=DMA1_CH2/SUBPERI1（PERIEN001）、
    #   ADC2=DMA1_CH0/SUBPERI2（PERIEN010）。与官方例程 ADC0_routine_sequence_with_DMA 一致。
    "adc0": ("RCU_ADC0", "DMA1", "DMA_CH0", "DMA_SUBPERI0"),
    "adc1": ("RCU_ADC1", "DMA1", "DMA_CH2", "DMA_SUBPERI1"),
    "adc2": ("RCU_ADC2", "DMA1", "DMA_CH0", "DMA_SUBPERI2"),
}

# ADC 通道 -> 默认引脚（数据手册 GD32F470xx Datasheet 引脚复用表权威数据）。
#   ADC0/ADC1（ADC01_INx）：通道 0-7 = PA0-PA7，8 = PB0，9 = PB1，
#                           10-13 = PC0-PC3，14 = PC4，15 = PC5；
#   ADC2（ADC2_INx）：通道 0-3 = PA0-PA3，4 = PF6，5 = PF7，6 = PF8，7 = PF9，
#                     8 = PF10，9 = PF3，10-13 = PC0-PC3，14 = PF4，15 = PF5。
# 注意：ADC2 的通道 4-9/14-15 在 PF 端口，与 ADC0/1（PA/PB/PC）不同。
# 通道 16-18：ADC0 为内部信号（温度/内部参考/VBAT），ADC1/2 内部接 VSSA，均无引脚。
ADC_CHANNEL_PIN = {
    "adc0": {0: "PA0", 1: "PA1", 2: "PA2", 3: "PA3", 4: "PA4", 5: "PA5",
             6: "PA6", 7: "PA7", 8: "PB0", 9: "PB1", 10: "PC0", 11: "PC1",
             12: "PC2", 13: "PC3", 14: "PC4", 15: "PC5"},
    "adc1": {0: "PA0", 1: "PA1", 2: "PA2", 3: "PA3", 4: "PA4", 5: "PA5",
             6: "PA6", 7: "PA7", 8: "PB0", 9: "PB1", 10: "PC0", 11: "PC1",
             12: "PC2", 13: "PC3", 14: "PC4", 15: "PC5"},
    "adc2": {0: "PA0", 1: "PA1", 2: "PA2", 3: "PA3", 4: "PF6", 5: "PF7",
             6: "PF8", 7: "PF9", 8: "PF10", 9: "PF3", 10: "PC0", 11: "PC1",
             12: "PC2", 13: "PC3", 14: "PF4", 15: "PF5"},
}

# ADC 时钟分频宏 -> (来源总线, 分频值)。用户手册 14.4.2：CK_ADC 最大 40MHz。
_ADC_CLK_DIV = {
    "ADC_ADCCK_PCLK2_DIV2": ("APB2", 2), "ADC_ADCCK_PCLK2_DIV4": ("APB2", 4),
    "ADC_ADCCK_PCLK2_DIV6": ("APB2", 6), "ADC_ADCCK_PCLK2_DIV8": ("APB2", 8),
    "ADC_ADCCK_HCLK_DIV5": ("AHB", 5), "ADC_ADCCK_HCLK_DIV6": ("AHB", 6),
    "ADC_ADCCK_HCLK_DIV10": ("AHB", 10), "ADC_ADCCK_HCLK_DIV20": ("AHB", 20),
}


def _check_adc_clock(ctx, conf, periph):
    """校验 ADC 时钟不超过 40MHz（用户手册 14.4.2）。"""
    div = _ADC_CLK_DIV.get(conf["clock_div"])
    if not div:
        return
    bus, d = div
    src = ctx.clock.apb2 if bus == "APB2" else ctx.clock.ahb
    adc_clk = src // d
    if adc_clk > ADC_CLK_MAX_MHZ:
        ctx.warn("%s 的 ADC 时钟 %dMHz 超过上限 %dMHz（%s/%d），请增大分频"
                 % (periph, adc_clk, ADC_CLK_MAX_MHZ, bus, d))

ADC_DEFAULTS = {
    "clock_div": "ADC_ADCCK_PCLK2_DIV8",
    "resolution": "ADC_RESOLUTION_12B",
    "alignment": "ADC_DATAALIGN_RIGHT",
    "continuous": False,
    "scan": False,
    "sync_mode": "ADC_SYNC_MODE_INDEPENDENT",
    "channels": [],       # [{"channel":"ADC_CHANNEL_1","sampletime":"ADC_SAMPLETIME_15","pin":"PA1"}]
    "dma": False,
    "interrupt": False,
    "interrupt_priority": (2, 0),
}


def generate_adc(ctx):
    from .model import enabled_instances
    files = {}
    for name, raw in enabled_instances(ctx.cfg, "adc").items():
        conf = dict(ADC_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        files.update(_gen_one(ctx, name, conf))
        ctx.add_init_call("MX_%s_Init" % name.upper(), "初始化 %s 模数转换器" % name.upper())
        ctx.add_libopt("gd32f4xx_adc.h")
    return files


def _gen_one(ctx, name, conf):
    rcu_macro, dma_periph, dma_ch, dma_sub = ADC_INFO[name]
    periph = name.upper()

    _check_adc_clock(ctx, conf, periph)

    b = CodeBuilder()
    b.line(file_header("%s.c" % name, "%s 初始化（MX_%s_Init）" % (periph, periph)))
    b.line('#include "gd32f4xx.h"')
    if ctx.systick_enabled:
        b.line('#include "systick.h"')
    b.line('#include "%s.h"' % name)
    b.line()
    emit_weak_fallback(b)

    b.doc_func("MX_%s_Init" % periph, "初始化 %s 模数转换器" % periph)
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()

    b.comment("使能 %s 时钟" % periph)
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 ADC")
    b.line("adc_deinit();")
    b.line()
    b.comment("配置 ADC 时钟（%s）" % conf["clock_div"])
    b.line("adc_clock_config(%s);" % conf["clock_div"])
    b.line()
    b.comment("ADC 工作模式：%s" % ("同步" if conf["sync_mode"] != "ADC_SYNC_MODE_INDEPENDENT" else "独立"))
    b.line("adc_sync_mode_config(%s);" % conf["sync_mode"])
    b.line()
    b.comment("分辨率：%s" % conf["resolution"])
    b.line("adc_resolution_config(%s, %s);" % (periph, conf["resolution"]))
    b.comment("数据对齐：%s" % conf["alignment"])
    b.line("adc_data_alignment_config(%s, %s);" % (periph, conf["alignment"]))

    n_ch = len(conf["channels"])
    b.line()
    b.comment("规则通道数量 = %d" % n_ch)
    b.line("adc_channel_length_config(%s, ADC_ROUTINE_CHANNEL, %dU);" % (periph, n_ch))

    b.line()
    b.comment("连续模式：%s / 扫描模式：%s" %
              ("开启" if conf["continuous"] else "关闭",
               "开启" if conf["scan"] else "关闭"))
    b.line("adc_special_function_config(%s, ADC_CONTINUOUS_MODE, %s);" %
           (periph, "ENABLE" if conf["continuous"] else "DISABLE"))
    b.line("adc_special_function_config(%s, ADC_SCAN_MODE, %s);" %
           (periph, "ENABLE" if conf["scan"] else "DISABLE"))

    # 规则通道
    for i, ch in enumerate(conf["channels"]):
        rank = ch.get("rank", i)
        b.line()
        b.comment("规则序列第 %d 项：%s，采样时间 %s" %
                  (rank, ch["channel"], ch.get("sampletime", "ADC_SAMPLETIME_15")))
        b.line("adc_routine_channel_config(%s, %dU, %s, %s);" %
               (periph, rank, ch["channel"],
                ch.get("sampletime", "ADC_SAMPLETIME_15")))
        # 登记模拟引脚
        pin = ch.get("pin")
        if not pin:
            # 未填引脚时按数据手册的通道-引脚对应表推导默认值
            num = int(ch["channel"].replace("ADC_CHANNEL_", ""))
            pin = ADC_CHANNEL_PIN.get(name, {}).get(num)
        if pin:
            try:
                port_macro, pin_macro, _l, _n = parse_pin(pin)
                ch_num = ch["channel"].split("_")[-1]
                ctx.gpio_analog.append((port_macro, pin_macro,
                                        "%s_CH%s" % (periph, ch_num)))
                ctx.add_gpio_clock(port_macro)
            except ValueError:
                pass

    b.line()
    b.comment("软件触发（关闭外部触发）")
    b.line("adc_external_trigger_config(%s, ADC_ROUTINE_CHANNEL, EXTERNAL_TRIGGER_DISABLE);" % periph)

    if conf["dma"]:
        b.line()
        b.comment("使能 %s 的 DMA 传输（对应 %s.%s(%s) 通道，由工具自动分配，见 dma.c）" %
                  (periph, dma_periph, dma_ch, dma_sub))
        b.line("adc_dma_request_after_last_enable(%s);  /* 序列末尾才发一次 DMA 请求 */" % periph)
        b.line("adc_dma_mode_enable(%s);" % periph)

    if conf["interrupt"]:
        b.line()
        b.comment("使能规则转换结束中断")
        b.line("adc_interrupt_enable(%s, ADC_INT_EOC);" % periph)
        pre, sub = conf["interrupt_priority"]
        b.line("nvic_irq_enable(ADC_IRQn, %d, %d);" % (pre, sub))
        ctx.add_nvic("ADC_IRQn", pre, sub, periph + " 转换完成中断")

    b.line()
    b.comment("使能 %s 并校准（需先等待短暂时间）" % periph)
    b.line("adc_enable(%s);" % periph)
    if ctx.systick_enabled:
        b.line("delay_1ms(1U);  /* 等待 ADC 稳定 */")
    else:
        b.line("/* 注意：若未启用 SysTick，请在此加入短暂延时再校准 */")
    b.line("adc_calibration_enable(%s);" % periph)

    b.dec()
    b.line("}")
    b.line()

    # 采样辅助函数
    b.doc_func("%s_channel_sample" % name,
               "软件触发采样指定规则通道（轮询等待转换完成）",
               "channel: 通道宏，如 ADC_CHANNEL_1", "采样值")
    b.line("uint16_t %s_channel_sample(uint8_t channel)" % name)
    b.line("{")
    b.inc()
    b.line("/* 配置当前要采样的通道（第 0 序列项） */")
    b.line("adc_routine_channel_config(%s, 0U, channel, ADC_SAMPLETIME_15);" % periph)
    b.line("/* 软件触发开始转换 */")
    b.line("adc_software_trigger_enable(%s, ADC_ROUTINE_CHANNEL);" % periph)
    b.line("/* 等待转换完成 */")
    b.line("while(!adc_flag_get(%s, ADC_FLAG_EOC));" % periph)
    b.line("/* 清除标志并返回结果 */")
    b.line("adc_flag_clear(%s, ADC_FLAG_EOC);" % periph)
    b.line("return adc_routine_data_read(%s);" % periph)
    b.dec()
    b.line("}")

    # 中断回调
    if conf["interrupt"]:
        b.line()
        cb = "%s_eoc_callback" % name
        b.doc_func(cb, "%s 转换完成回调（__WEAK，用户可重定义）" % periph)
        b.line("__WEAK void %s(uint16_t value)" % cb)
        b.line("{")
        b.inc()
        b.line("/* USER CODE BEGIN %s_EOC */" % name.upper())
        b.line("/* TODO: 在这里使用转换结果 */")
        b.line("/* USER CODE END %s_EOC */" % name.upper())
        b.line("(void)value;")
        b.dec()
        b.line("}")
        body = CodeBuilder()
        body.comment("转换完成（EOC）")
        body.line("if(SET == adc_interrupt_flag_get(%s, ADC_INT_FLAG_EOC)) {" % periph)
        body.inc()
        body.line("adc_interrupt_flag_clear(%s, ADC_INT_FLAG_EOC);" % periph)
        body.line("%s(adc_routine_data_read(%s));" % (cb, periph))
        body.dec()
        body.line("}")
        ctx.add_irq_handler("ADC_IRQHandler", "ADC 转换完成中断", str(body))

    # ---- .h ----
    h = CodeBuilder()
    guard = include_guard("%s_h" % name)
    h.line(file_header("%s.h" % name, "%s 初始化声明与采样函数" % periph))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_%s_Init(void);" % periph)
    h.line("uint16_t %s_channel_sample(uint8_t channel);" % name)
    if conf["interrupt"]:
        h.line("/* 转换完成回调（弱实现，可在用户代码中重定义） */")
        h.line("void %s_eoc_callback(uint16_t value);" % name)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"%s.c" % name: str(b), "%s.h" % name: str(h)}
