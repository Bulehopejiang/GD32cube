# -*- coding: utf-8 -*-
"""TIMER 生成器：生成 MX_TIMERn_Init()（timer1.c/timer1.h 等）。

支持三种模式（参考 CubeMX 的 Timer Mode）：
  base —— 基本定时（仅计数，周期中断）
  pwm  —— PWM 输出（指定通道 + 占空比 + 引脚）
  ic   —— 输入捕获（指定通道 + 引脚 + 极性）
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .af_table import lookup_af

# TIMER 实例 -> (RCU 使能宏, 所在总线, 更新中断号)
TIMER_INFO = {
    "timer0":  ("RCU_TIMER0",  "APB2", "TIMER0_UP_TIMER9_IRQn"),
    "timer1":  ("RCU_TIMER1",  "APB1", "TIMER1_IRQn"),
    "timer2":  ("RCU_TIMER2",  "APB1", "TIMER2_IRQn"),
    "timer3":  ("RCU_TIMER3",  "APB1", "TIMER3_IRQn"),
    "timer4":  ("RCU_TIMER4",  "APB1", "TIMER4_IRQn"),
    "timer5":  ("RCU_TIMER5",  "APB1", "TIMER5_DAC_IRQn"),
    "timer6":  ("RCU_TIMER6",  "APB1", "TIMER6_IRQn"),
    # GD32F4xx 定时器中断按两组共享：TIMER0/8/9/10 一组，TIMER7/11/12/13 一组
    "timer7":  ("RCU_TIMER7",  "APB2", "TIMER7_UP_TIMER12_IRQn"),
    "timer8":  ("RCU_TIMER8",  "APB2", "TIMER0_UP_TIMER9_IRQn"),
    "timer9":  ("RCU_TIMER9",  "APB2", "TIMER0_UP_TIMER9_IRQn"),
    "timer10": ("RCU_TIMER10", "APB2", "TIMER0_TRG_CMT_TIMER10_IRQn"),
    "timer11": ("RCU_TIMER11", "APB1", "TIMER7_BRK_TIMER11_IRQn"),
    "timer12": ("RCU_TIMER12", "APB1", "TIMER7_UP_TIMER12_IRQn"),
    "timer13": ("RCU_TIMER13", "APB1", "TIMER7_TRG_CMT_TIMER13_IRQn"),
}

# 高级定时器的"通道捕获"用独立 IRQ 线（基础定时器与更新中断共用同一线）
TIMER_CH_IRQ = {
    "timer0": "TIMER0_Channel_IRQn",
    "timer7": "TIMER7_Channel_IRQn",
    "timer8": "TIMER0_Channel_IRQn",  # TIMER8 与 TIMER0 共用通道中断组
}

def _periph_name(name):
    """timer1 -> TIMER1。"""
    return "TIMER%d" % int(name.lower().replace("timer", ""))


TIMER_DEFAULTS = {
    "mode": "pwm",
    "prescaler": 0,
    "period": 999,
    "repetition": 0,
    "channels": [],        # [{"ch":1,"pulse":500,"pin":"PA0"}, ...]
    "ic_channels": [],     # [{"ch":1,"pin":"PA0","polarity":"TIMER_IC_POLARITY_RISING"}, ...]
    "af": None,
    "interrupt": False,
    "interrupt_priority": (2, 0),
}


def generate_timer(ctx):
    from .model import enabled_instances
    files = {}
    for name, raw in enabled_instances(ctx.cfg, "timer").items():
        conf = dict(TIMER_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        files.update(_gen_one(ctx, name, conf))
        ctx.add_init_call("MX_%s_Init" % _periph_name(name),
                          "初始化 %s（%s 模式）" % (_periph_name(name), conf["mode"]))
        ctx.add_libopt("gd32f4xx_timer.h")
    return files


def _gen_one(ctx, name, conf):
    name_key = name.lower()
    rcu_macro, bus, irqn = TIMER_INFO[name_key]
    periph = _periph_name(name)
    timer_clk = ctx.clock.apb2_timer if bus == "APB2" else ctx.clock.apb1_timer
    mode = conf["mode"]
    psc, period = conf["prescaler"], conf["period"]

    b = CodeBuilder()
    b.line(file_header("%s.c" % name_key,
                       "%s 初始化（MX_%s_Init，模式：%s）" % (periph, periph, mode)))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name_key)
    b.line()
    emit_weak_fallback(b)

    b.doc_func("MX_%s_Init" % periph, "初始化 %s（%s 模式）" % (periph, mode))
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()
    b.line("timer_parameter_struct timer_initpara;")
    if mode == "pwm":
        b.line("timer_oc_parameter_struct timer_ocintpara;")
    elif mode == "ic":
        b.line("timer_ic_parameter_struct timer_icintpara;")
    b.line()

    b.comment("使能 %s 时钟（位于 %s，定时器时钟 %dMHz）" % (periph, bus, timer_clk))
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 %s" % periph)
    b.line("timer_deinit(%s);" % periph)

    # 频率注释
    f_hz = timer_clk * 1000000 / ((psc + 1) * (period + 1))
    b.line()
    b.comment("定时器基本参数：")
    b.comment("  计数时钟 = %dMHz / (预分频 %d + 1) = %d KHz" %
              (timer_clk, psc, timer_clk * 1000 / (psc + 1)))
    b.comment("  溢出/翻转频率 = 计数时钟 / (自动重载 %d + 1) ≈ %.3f Hz" %
              (period, f_hz))
    b.line("timer_initpara.prescaler         = %d;" % psc)
    b.line("timer_initpara.alignedmode       = TIMER_COUNTER_EDGE;")
    b.line("timer_initpara.counterdirection  = TIMER_COUNTER_UP;")
    b.line("timer_initpara.period            = %d;" % period)
    b.line("timer_initpara.clockdivision     = TIMER_CKDIV_DIV1;")
    b.line("timer_initpara.repetitioncounter = %d;" % conf["repetition"])
    b.line("timer_init(%s, &timer_initpara);" % periph)

    if mode == "pwm":
        b.line()
        b.comment("PWM 通道配置（输出极性高、使能输出、空闲低电平）")
        b.line("timer_ocintpara.outputstate  = TIMER_CCX_ENABLE;")
        b.line("timer_ocintpara.ocpolarity   = TIMER_OC_POLARITY_HIGH;")
        b.line("timer_ocintpara.ocnpolarity  = TIMER_OCN_POLARITY_HIGH;")
        b.line("timer_ocintpara.outputnstate = TIMER_CCXN_DISABLE;")
        b.line("timer_ocintpara.ocidlestate  = TIMER_OC_IDLE_STATE_LOW;")
        b.line("timer_ocintpara.ocnidlestate = TIMER_OCN_IDLE_STATE_LOW;")
        for ch_cfg in conf["channels"]:
            ch = int(ch_cfg["ch"]) or 1
            ch0 = ch - 1  # 配置里 1 基通道 -> GD32 0 基宏（TIMER_CH_0=第一通道）
            pulse = ch_cfg.get("pulse", period // 2)
            duty = 100.0 * pulse / (period + 1) if period > 0 else 0.0
            b.line()
            b.comment("通道%d：PWM0 模式，脉宽 %d（占空比 ≈ %.1f%%）" %
                      (ch, pulse, duty))
            b.line("timer_channel_output_config(%s, TIMER_CH_%d, &timer_ocintpara);" %
                   (periph, ch0))
            b.line("timer_channel_output_pulse_value_config(%s, TIMER_CH_%d, %d);" %
                   (periph, ch0, pulse))
            b.line("timer_channel_output_mode_config(%s, TIMER_CH_%d, TIMER_OC_MODE_PWM0);" %
                   (periph, ch0))
            b.line("timer_channel_output_shadow_config(%s, TIMER_CH_%d, TIMER_OC_SHADOW_DISABLE);" %
                   (periph, ch0))
            # 引脚复用（AF 表按 0 基通道键查找）
            if ch_cfg.get("pin"):
                _register_ch_pin(ctx, periph, ch0, ch_cfg["pin"], conf["af"])
        # 高级定时器(TIMER0/7/8)需使能主输出(POEN)，否则 PWM 不会输出到引脚
        if periph in ("TIMER0", "TIMER7", "TIMER8"):
            b.line()
            b.comment("高级定时器：使能主输出 POEN，否则 PWM 不会出现在引脚上")
            b.line("timer_primary_output_config(%s, ENABLE);" % periph)
    elif mode == "ic":
        for ch_cfg in conf["ic_channels"]:
            ch = int(ch_cfg["ch"]) or 1
            ch0 = ch - 1  # 配置里 1 基通道 -> GD32 0 基宏
            pol = ch_cfg.get("polarity", "TIMER_IC_POLARITY_RISING")
            b.line()
            b.comment("通道%d：输入捕获（%s）" % (ch, pol))
            b.line("timer_icintpara.icpolarity  = %s;" % pol)
            b.line("timer_icintpara.icselection = TIMER_IC_SELECTION_DIRECTTI;")
            b.line("timer_icintpara.icprescaler = TIMER_IC_PSC_DIV1;")
            b.line("timer_icintpara.icfilter    = 0;")
            b.line("timer_input_capture_config(%s, TIMER_CH_%d, &timer_icintpara);" %
                   (periph, ch0))
            if ch_cfg.get("pin"):
                _register_ch_pin(ctx, periph, ch0, ch_cfg["pin"], conf["af"])

    if mode in ("base", "pwm"):
        b.line()
        b.comment("使能自动重载预装载")
        b.line("timer_auto_reload_shadow_enable(%s);" % periph)

    # 中断使能：base/pwm 使能更新中断；ic 使能通道捕获中断
    if conf["interrupt"]:
        b.line()
        if mode == "ic":
            for ch_cfg in conf["ic_channels"]:
                ch0 = int(ch_cfg["ch"]) - 1
                b.comment("先清除通道%d 捕获标志再使能中断（避免残留标志导致误触发）" %
                          int(ch_cfg["ch"]))
                b.line("timer_interrupt_flag_clear(%s, TIMER_INT_FLAG_CH%d);" %
                      (periph, ch0))
                b.line("timer_interrupt_enable(%s, TIMER_INT_CH%d);" % (periph, ch0))
            chan_irqn = TIMER_CH_IRQ.get(name_key, irqn)
            pre, sub = conf["interrupt_priority"]
            b.line("nvic_irq_enable(%s, %d, %d);" % (chan_irqn, pre, sub))
            ctx.add_nvic(chan_irqn, pre, sub, periph + " 捕获中断")
        else:
            b.comment("使能更新中断（计数器溢出触发）")
            b.line("timer_interrupt_enable(%s, TIMER_INT_UP);" % periph)
            pre, sub = conf["interrupt_priority"]
            b.line("nvic_irq_enable(%s, %d, %d);" % (irqn, pre, sub))
            ctx.add_nvic(irqn, pre, sub, periph + " 更新中断")

    b.line()
    b.comment("启动 %s" % periph)
    b.line("timer_enable(%s);" % periph)
    b.dec()
    b.line("}")
    b.line()

    # 中断回调与处理函数
    if conf["interrupt"]:
        if mode == "ic":
            # 每通道捕获弱回调 + 合并的中断处理函数
            chan_irqn = TIMER_CH_IRQ.get(name_key, irqn)
            handler = chan_irqn.replace("_IRQn", "_IRQHandler")
            body = CodeBuilder()
            for ch_cfg in conf["ic_channels"]:
                ch_disp = int(ch_cfg["ch"])
                ch0 = ch_disp - 1
                cb = "%s_ch%d_capture_callback" % (name_key, ch_disp)
                b.doc_func(cb, "%s 通道%d 捕获回调（__WEAK，用户可重定义）"
                           % (periph, ch_disp))
                b.line("__WEAK void %s(uint32_t value)" % cb)
                b.line("{")
                b.inc()
                b.line("/* USER CODE BEGIN %s_CH%d_CAPTURE */" % (name_key.upper(), ch_disp))
                b.line("/* TODO: 在这里处理通道%d 捕获事件 */" % ch_disp)
                b.line("/* USER CODE END %s_CH%d_CAPTURE */" % (name_key.upper(), ch_disp))
                b.line("(void)value;")
                b.dec()
                b.line("}")
                b.line()
                body.comment("通道%d 捕获" % ch_disp)
                body.line("if(SET == timer_interrupt_flag_get(%s, TIMER_INT_FLAG_CH%d)) {" %
                          (periph, ch0))
                body.inc()
                body.line("timer_interrupt_flag_clear(%s, TIMER_INT_FLAG_CH%d);" %
                          (periph, ch0))
                body.line("%s(timer_channel_capture_value_register_read(%s, TIMER_CH_%d));" %
                          (cb, periph, ch0))
                body.dec()
                body.line("}")
            ctx.add_irq_handler(handler, "%s 捕获中断" % periph, str(body))
        else:
            # 更新中断回调
            cb = "%s_update_callback" % name_key
            b.doc_func(cb, "%s 溢出（更新）回调（__WEAK，用户可重定义）" % periph)
            b.line("__WEAK void %s(void)" % cb)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN %s_UPDATE */" % name_key.upper())
            b.line("/* TODO: 在这里处理定时器溢出事件 */")
            b.line("/* USER CODE END %s_UPDATE */" % name_key.upper())
            b.dec()
            b.line("}")
            b.line()
            # 登记中断处理函数
            body = CodeBuilder()
            body.comment("清除更新中断标志并调用用户回调")
            body.line("if(SET == timer_interrupt_flag_get(%s, TIMER_INT_FLAG_UP)) {" % periph)
            body.inc()
            body.line("timer_interrupt_flag_clear(%s, TIMER_INT_FLAG_UP);" % periph)
            body.line("%s();" % cb)
            body.dec()
            body.line("}")
            # 中断处理函数名 = IRQn 名去掉 _IRQn 加 _IRQHandler，与启动文件向量名一致。
            handler = irqn.replace("_IRQn", "_IRQHandler")
            ctx.add_irq_handler(handler, "%s 中断处理" % periph, str(body))

    # ---- .h ----
    h = CodeBuilder()
    guard = include_guard("%s_h" % name_key)
    h.line(file_header("%s.h" % name_key, "%s 初始化声明与回调" % periph))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_%s_Init(void);" % periph)
    if conf["interrupt"]:
        h.line()
        if mode == "ic":
            for ch_cfg in conf["ic_channels"]:
                ch_disp = int(ch_cfg["ch"])
                h.line("/* 通道%d 捕获回调（弱实现，可在用户代码中重定义） */" % ch_disp)
                h.line("void %s_ch%d_capture_callback(uint32_t value);" % (name_key, ch_disp))
        else:
            h.line("/* 溢出回调（弱实现，可在用户代码中重定义） */")
            h.line("void %s_update_callback(void);" % name_key)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"%s.c" % name_key: str(b), "%s.h" % name_key: str(h)}


def _register_ch_pin(ctx, periph, ch, pin_str, cfg_af):
    """登记定时器通道引脚的复用配置。"""
    port_macro, pin_macro, _letter, _num = parse_pin(pin_str)
    af = lookup_af("%s_CH%d" % (periph, ch), pin_str, cfg_af)
    if af is None:
        af = 1
        ctx.warn("%s 通道%d 引脚 %s 的 AF 号未知，默认用 AF1，请显式指定 af 字段"
                 % (periph, ch, pin_str))
    ctx.add_af(port_macro, pin_macro, af,
               "%s 通道%d 引脚" % (periph, ch))
