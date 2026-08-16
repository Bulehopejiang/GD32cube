# -*- coding: utf-8 -*-
"""DMA 生成器：生成 MX_DMA_Init()（dma.c/dma.h）。

配置任意多个 DMA 通道（单次数据传输模式）。外设数据寄存器地址支持
用 "periph": "USART0" 这种写法自动展开为 ((uint32_t)&USART_DATA(USART0))。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback

DMA_DEFAULTS = {
    "dma": "DMA0",
    "channel": "DMA_CH0",
    "direction": "DMA_MEMORY_TO_PERIPH",
    "periph": None,          # 外设名（USART0/SPI0/...）→ 自动取数据寄存器地址
    "periph_addr": None,     # 显式外设地址表达式
    "memory": "tx_buffer",   # 内存缓冲变量名（生成 (uint32_t)memory）
    "periph_width": "DMA_PERIPH_WIDTH_8BIT",
    "memory_width": "DMA_MEMORY_WIDTH_8BIT",
    "periph_inc": "DMA_PERIPH_INCREASE_DISABLE",
    "memory_inc": "DMA_MEMORY_INCREASE_ENABLE",
    "number": 0,
    "priority": "DMA_PRIORITY_HIGH",
    "circular": False,
    "subperiph": None,       # 子外设选择（如 DMA_SUBPERI4）；USART 自动推导时自动填
    "interrupt": False,      # 使能传输完成(FTF)中断
    "interrupt_priority": (2, 0),
    "name": "DMA_CHANNEL",   # 用于注释
}


def _cb_name(channel_name):
    """由通道名生成传输完成回调函数名：'USART2_TX' -> 'usart2_tx_done_callback'。"""
    import re
    s = re.sub(r"[^A-Za-z0-9]+", "_", (channel_name or "dma").lower()).strip("_")
    return s + "_done_callback"


def _dma_irq_name(dma_periph, channel):
    """由 DMA 控制器与通道宏生成 IRQn/ISR 名：'DMA0' + 'DMA_CH2' -> 'DMA0_Channel2_IRQn'。"""
    ch_num = str(channel).replace("DMA_CH", "")
    return "%s_Channel%s_IRQn" % (dma_periph, ch_num)


def generate_dma(ctx):
    raw_cfg = ctx.cfg.get("dma") or {}
    explicit = raw_cfg.get("channels", []) if isinstance(raw_cfg, dict) else []
    # 自动为启用了 DMA 的 USART/ADC 生成正确通道（无需手填 DMA 页签）
    auto = auto_periph_dma_channels(ctx)
    _apply_dma_interrupt(auto, ctx.cfg)
    channels = _merge_auto_channels(explicit, auto)
    if not channels:
        return {}
    _warn_channel_conflicts(ctx, channels)
    # 记录自动分配的 DMA 缓冲，供 main.c/main.h 自动定义（见 main_gen）
    for a in auto:
        mem = a.get("memory")
        if mem and not any(m == mem for m, _t, _p in ctx.dma_buffers):
            ctype = "uint16_t" if a.get("memory_width") == "DMA_MEMORY_WIDTH_16BIT" \
                    else "uint8_t"
            ctx.dma_buffers.append((mem, ctype, a.get("periph") or a.get("name", "")))
    files = _gen_all(ctx, channels)
    ctx.add_init_call("MX_DMA_Init", "初始化 DMA 通道")
    ctx.add_libopt("gd32f4xx_dma.h")
    return files


def auto_periph_dma_channels(ctx):
    """根据已启用外设的 DMA 选项自动生成 DMA 通道配置。

    当前覆盖：USART(dma_tx/dma_rx)、ADC(dma)。
    返回 list[dict]，每条含 dma/channel/subperiph/direction/periph/memory 等。
    用户只需在外设页签勾选 DMA，工具自动分配正确通道，无需查手册手填。
    """
    from .usart_gen import resolve_usart_dma
    from .adc_gen import ADC_INFO
    cfg = ctx.cfg
    out = []

    # ---- USART ----
    usart = cfg.get("usart") or {}
    for name, conf in usart.items():
        if not isinstance(conf, dict) or conf.get("enabled", True) is False:
            continue
        key = name.upper()
        if conf.get("dma_tx"):
            r = resolve_usart_dma(key, "tx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_TX" % key,
                    "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_MEMORY_TO_PERIPH",
                    "periph": key,
                    "memory": "%s_Buf" % key,
                    "priority": "DMA_PRIORITY_MEDIUM",
                    "circular": False,
                })
        if conf.get("dma_rx"):
            r = resolve_usart_dma(key, "rx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_RX" % key,
                    "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_PERIPH_TO_MEMORY",
                    "periph": key,
                    "memory": "%s_RxBuf" % key,
                    "priority": "DMA_PRIORITY_MEDIUM",
                    "circular": False,
                })

    # ---- ADC（ADC_INFO 的键是小写：adc0/adc1/adc2）----
    adc = cfg.get("adc") or {}
    for name, conf in adc.items():
        if not isinstance(conf, dict) or conf.get("enabled", True) is False:
            continue
        if not conf.get("dma"):
            continue
        if name not in ADC_INFO:
            continue
        _rcu, dma, ch, sub = ADC_INFO[name]
        key = name.upper()
        out.append({
            "name": "%s_DMA" % key,
            "dma": dma, "channel": ch, "subperiph": sub,
            "direction": "DMA_PERIPH_TO_MEMORY",
            "periph": key,
            "memory": "%s_Data" % key,
            "periph_width": "DMA_PERIPH_WIDTH_16BIT",  # ADC 数据寄存器 16 位
            "memory_width": "DMA_MEMORY_WIDTH_16BIT",
            "priority": "DMA_PRIORITY_HIGH",
            "circular": False,
        })

    # ---- SPI（已确认通道自动推导；未确认的提示手填）----
    from .spi_gen import resolve_spi_dma
    spi = cfg.get("spi") or {}
    for name, conf in spi.items():
        if not isinstance(conf, dict) or conf.get("enabled", True) is False:
            continue
        key = name.upper()
        if conf.get("dma_tx"):
            r = resolve_spi_dma(key, "tx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_TX" % key, "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_MEMORY_TO_PERIPH", "periph": key,
                    "memory": "%s_Buf" % key, "priority": "DMA_PRIORITY_HIGH", "circular": False,
                })
            else:
                ctx.warn("%s 的 TX DMA 通道未确认，请在 DMA 页签手填（查 GD32F4xx 手册）" % key)
        if conf.get("dma_rx"):
            r = resolve_spi_dma(key, "rx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_RX" % key, "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_PERIPH_TO_MEMORY", "periph": key,
                    "memory": "%s_RxBuf" % key, "priority": "DMA_PRIORITY_HIGH", "circular": False,
                })
            else:
                ctx.warn("%s 的 RX DMA 通道未确认，请在 DMA 页签手填（查 GD32F4xx 手册）" % key)

    # ---- I2C（已确认通道自动推导；未确认的提示手填）----
    from .i2c_gen import resolve_i2c_dma
    i2c = cfg.get("i2c") or {}
    for name, conf in i2c.items():
        if not isinstance(conf, dict) or conf.get("enabled", True) is False:
            continue
        key = name.upper()
        if conf.get("dma_tx"):
            r = resolve_i2c_dma(key, "tx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_TX" % key, "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_MEMORY_TO_PERIPH", "periph": key,
                    "memory": "%s_Buf" % key, "priority": "DMA_PRIORITY_HIGH", "circular": False,
                })
            else:
                ctx.warn("%s 的 TX DMA 通道未确认，请在 DMA 页签手填（查 GD32F4xx 手册）" % key)
        if conf.get("dma_rx"):
            r = resolve_i2c_dma(key, "rx")
            if r:
                dma, ch, sub = r
                out.append({
                    "name": "%s_RX" % key, "dma": dma, "channel": ch, "subperiph": sub,
                    "direction": "DMA_PERIPH_TO_MEMORY", "periph": key,
                    "memory": "%s_RxBuf" % key, "priority": "DMA_PRIORITY_HIGH", "circular": False,
                })
            else:
                ctx.warn("%s 的 RX DMA 通道未确认，请在 DMA 页签手填（查 GD32F4xx 手册）" % key)
    return out


def _apply_dma_interrupt(auto, cfg):
    """给自动推导的 DMA 通道补上中断配置（读取外设配置里的 dma_interrupt）。

    自动通道本身不带 interrupt 字段，这里按 periph 名回查外设配置。
    """
    for ch in auto:
        periph = (ch.get("periph") or "").upper()
        src = None
        for section in ("usart", "adc", "spi", "i2c"):
            for name, conf in (cfg.get(section) or {}).items():
                if name.upper() == periph and isinstance(conf, dict):
                    src = conf
                    break
            if src:
                break
        if src and src.get("dma_interrupt"):
            ch["interrupt"] = True
            ch["interrupt_priority"] = tuple(src.get("dma_interrupt_priority", (2, 0)))
    return auto


def _merge_auto_channels(explicit, auto):
    """合并显式配置与自动推导通道。

    对启用了 DMA 的 USART，自动通道优先（纠正手填的错误通道）；
    其余显式通道（ADC/SPI 等）原样保留。
    """
    covered = set()
    for a in auto:
        covered.add(((a.get("periph") or "").upper(), a.get("direction")))
    kept = [c for c in explicit
            if isinstance(c, dict)
            and ((c.get("periph") or "").upper(), c.get("direction")) not in covered]
    return kept + auto


def _warn_channel_conflicts(ctx, channels):
    """检测两个通道占用同一 (DMA, 通道号)，给出告警。"""
    seen = {}
    for c in channels:
        if not isinstance(c, dict):
            continue
        key = (c.get("dma"), c.get("channel"))
        periph = c.get("periph") or c.get("name") or "?"
        if key in seen:
            ctx.warn("DMA %s.%s 被 %s 与 %s 同时占用，需二选一或改通道"
                     % (key[0], key[1], seen[key], periph))
        else:
            seen[key] = periph


def _data_reg_expr(periph):
    """外设名 -> 数据寄存器地址表达式。

    支持 USART / SPI / I2C（其数据寄存器宏名不同）；其余外设（如 ADC、TIMER）
    返回 None，由调用方提示手动填写 periph_addr。
    """
    if periph.startswith("USART") or periph.startswith("UART"):
        return "((uint32_t)&USART_DATA(%s))" % periph
    if periph.startswith("SPI"):
        return "((uint32_t)&SPI_DATA(%s))" % periph
    if periph.startswith("I2C"):
        return "((uint32_t)&I2C_DATA(%s))" % periph
    if periph.startswith("ADC"):
        return "((uint32_t)&ADC_RDATA(%s))" % periph
    return None


def _gen_all(ctx, channels):
    b = CodeBuilder()
    b.line(file_header("dma.c", "DMA 通道初始化（MX_DMA_Init）"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "dma.h"')
    b.line()
    emit_weak_fallback(b)
    b.line()

    # 先扫描所有通道，确定要使能的 DMA 时钟
    dma_clocks = set()
    done_callbacks = []   # (回调名, 说明)
    for raw in channels:
        if isinstance(raw, dict):
            dma_clocks.add(raw.get("dma", "DMA0"))

    b.doc_func("MX_DMA_Init", "配置所有 DMA 通道（单次数据传输模式）")
    b.line("void MX_DMA_Init(void)")
    b.line("{")
    b.inc()
    b.line("dma_single_data_parameter_struct dma_init_struct;")
    b.line()
    for dma_periph in sorted(dma_clocks):
        b.comment("使能 %s 时钟" % dma_periph)
        b.line("rcu_periph_clock_enable(RCU_%s);" % dma_periph)
    b.line()

    for i, raw in enumerate(channels):
        conf = dict(DMA_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        dma_periph = conf["dma"]
        dma_clocks.add(dma_periph)
        label = conf.get("name") or ("通道%d" % i)

        # 外设地址
        if conf["periph_addr"]:
            addr_expr = conf["periph_addr"]
        elif conf["periph"]:
            addr_expr = _data_reg_expr(conf["periph"])
            if addr_expr is None:
                ctx.warn("%s 的 DMA 数据寄存器地址需手动在 periph_addr 字段填写" % conf["periph"])
                addr_expr = "(uint32_t)0U  /* TODO: 填写 %s 数据寄存器地址 */" % conf["periph"]
        else:
            ctx.warn("DMA 通道 %s.%s（%s）未填写外设地址，请在 periph 或 periph_addr 字段填写"
                     % (dma_periph, conf["channel"], label))
            addr_expr = "(uint32_t)0U  /* TODO: 填写外设寄存器地址 */"

        b.comment("配置 %s.%s（%s）" % (dma_periph, conf["channel"], label))
        b.line("dma_deinit(%s, %s);" % (dma_periph, conf["channel"]))
        b.line("dma_init_struct.direction = %s;  /* 传输方向 */" % conf["direction"])
        b.line("dma_init_struct.periph_addr = %s;" % addr_expr)
        if conf["memory"]:
            b.line("dma_init_struct.memory0_addr = (uint32_t)%s;" % conf["memory"])
        else:
            b.line("dma_init_struct.memory0_addr = (uint32_t)0U;  /* TODO: 填写内存缓冲变量名 */")
        b.line("dma_init_struct.periph_inc = %s;" % conf["periph_inc"])
        b.line("dma_init_struct.memory_inc = %s;" % conf["memory_inc"])
        b.line("dma_init_struct.periph_memory_width = %s;" % conf["periph_width"])
        b.line("dma_init_struct.circular_mode = %s;" %
               ("DMA_CIRCULAR_MODE_ENABLE" if conf["circular"] else "DMA_CIRCULAR_MODE_DISABLE"))
        b.line("dma_init_struct.number = %d;  /* 传输长度（可在使用时动态修改） */" %
               conf["number"])
        b.line("dma_init_struct.priority = %s;" % conf["priority"])
        b.line("dma_single_data_mode_init(%s, %s, &dma_init_struct);" %
               (dma_periph, conf["channel"]))
        sub = conf.get("subperiph")
        if sub:
            b.line("dma_channel_subperipheral_select(%s, %s, %s);" %
                   (dma_periph, conf["channel"], sub))
        if conf.get("interrupt"):
            irqn = _dma_irq_name(dma_periph, conf["channel"])
            handler = irqn.replace("_IRQn", "_IRQHandler")
            cb = _cb_name(conf.get("name"))
            pre, ipri = conf.get("interrupt_priority", (2, 0))
            b.line("dma_interrupt_enable(%s, %s, DMA_CHXCTL_FTFIE);  /* 传输完成中断 */" %
                   (dma_periph, conf["channel"]))
            b.line("nvic_irq_enable(%s, %d, %d);" % (irqn, pre, ipri))
            ctx.add_nvic(irqn, pre, ipri, "DMA %s.%s 传输完成" % (dma_periph, conf["channel"]))
            isr = CodeBuilder()
            isr.comment("DMA %s.%s 传输完成（FTF），交给回调" % (dma_periph, conf["channel"]))
            isr.line("if(RESET != dma_flag_get(%s, %s, DMA_FLAG_FTF)) {" %
                     (dma_periph, conf["channel"]))
            isr.inc()
            isr.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (dma_periph, conf["channel"]))
            isr.line("%s();" % cb)
            isr.dec()
            isr.line("}")
            ctx.add_irq_handler(handler,
                                "DMA %s.%s 传输完成中断" % (dma_periph, conf["channel"]),
                                str(isr))
            done_callbacks.append((cb, "%s.%s" % (dma_periph, conf["channel"])))
        b.line("/* 注意：dma_channel_enable() 与 dma_transfer_number_config() 一般在应用层触发传输时调用 */")
        b.line()

    b.dec()
    b.line("}")

    # 传输完成弱回调
    if done_callbacks:
        b.line()
        b.comment("---- DMA 传输完成弱回调（用户可重定义，或直接改 USER CODE 块）----")
        for cb, label in done_callbacks:
            b.doc_func(cb, "%s 传输完成回调（弱实现，DMA 传输完成(FTF)时调用）" % label)
            b.line("__WEAK void %s(void)" % cb)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN DMA_%s_DONE */" % cb.upper())
            b.line("/* TODO: DMA 传输完成，在这里处理 */")
            b.line("/* USER CODE END DMA_%s_DONE */" % cb.upper())
            b.dec()
            b.line("}")
            b.line()

    # .h
    h = CodeBuilder()
    guard = include_guard("dma_h")
    h.line(file_header("dma.h", "DMA 初始化声明"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.comment("DMA 通道引用的内存缓冲（如 USART2_Buf）在 main.c 定义、main.h 里 extern，这里包含 main.h 以便编译")
    h.line('#include "main.h"')
    h.line()
    h.line("void MX_DMA_Init(void);")
    if done_callbacks:
        h.line()
        h.comment("DMA 传输完成回调（弱实现，可在用户代码中重定义）")
        for cb, _label in done_callbacks:
            h.line("void %s(void);" % cb)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"dma.c": str(b), "dma.h": str(h)}
