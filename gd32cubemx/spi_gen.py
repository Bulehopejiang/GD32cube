# -*- coding: utf-8 -*-
"""SPI 生成器：生成 MX_SPIn_Init()（spi0.c/spi0.h 等）。

覆盖：主/从模式、全双工/收发、帧大小、时钟极性与相位、NSS 软件/硬件、
预分频、大小端。SCK/MISO/MOSI 复用引脚 + 软件片选 CS 输出引脚。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .af_table import lookup_af

# SPI 实例 -> (RCU 宏, 所在总线, 中断号, 中断处理函数名)
SPI_INFO = {
    "spi0": ("RCU_SPI0", "APB2", "SPI0_IRQn", "SPI0_IRQHandler"),
    "spi1": ("RCU_SPI1", "APB1", "SPI1_IRQn", "SPI1_IRQHandler"),
    "spi2": ("RCU_SPI2", "APB1", "SPI2_IRQn", "SPI2_IRQHandler"),
    "spi3": ("RCU_SPI3", "APB2", "SPI3_IRQn", "SPI3_IRQHandler"),
    "spi4": ("RCU_SPI4", "APB2", "SPI4_IRQn", "SPI4_IRQHandler"),
    "spi5": ("RCU_SPI5", "APB2", "SPI5_IRQn", "SPI5_IRQHandler"),
}

SPI_DEFAULTS = {
    "mode": "master",                     # master / slave
    "trans_mode": "SPI_TRANSMODE_FULLDUPLEX",
    "frame_size": "SPI_FRAMESIZE_8BIT",
    "endian": "SPI_ENDIAN_MSB",
    "clock_polarity_phase": "SPI_CK_PL_LOW_PH_1EDGE",
    "prescale": "SPI_PSC_64",
    "nss": "SPI_NSS_SOFT",
    "sck_pin": None, "miso_pin": None, "mosi_pin": None,
    "cs_pin": None, "cs_label": "CS",
    "af": None,
    "dma_tx": False, "dma_rx": False,
    "interrupt": False, "tx_interrupt": False,
    "interrupt_priority": (2, 0),
}

# SPI -> (TX_DMA, TX通道, TX子外设, RX_DMA, RX通道, RX子外设)
# GD32F4xx 用户手册表 10-2 DMA0 / 表 10-3 DMA1：
#   SPI1=DMA0_CH4/CH3(SUBPERI0, PERIEN000)、SPI2=DMA0_CH5/CH0(SUBPERI0, PERIEN000)、
#   SPI0=DMA1_CH3/CH0(SUBPERI3, PERIEN011)、SPI3=DMA1_CH4/CH3(SUBPERI5, PERIEN101)、
#   SPI4=DMA1_CH4/CH3(SUBPERI2, PERIEN010)、SPI5=DMA1_CH5/CH6(SUBPERI1, PERIEN001)。
# 与官方例程(SPI_master_slave_fullduplex_ti_mode)的 SPI1/SPI3 一致。
SPI_DMA_MAP = {
    "SPI0": ("DMA1", "DMA_CH3", "DMA_SUBPERI3", "DMA1", "DMA_CH0", "DMA_SUBPERI3"),
    "SPI1": ("DMA0", "DMA_CH4", "DMA_SUBPERI0", "DMA0", "DMA_CH3", "DMA_SUBPERI0"),
    "SPI2": ("DMA0", "DMA_CH5", "DMA_SUBPERI0", "DMA0", "DMA_CH0", "DMA_SUBPERI0"),
    "SPI3": ("DMA1", "DMA_CH4", "DMA_SUBPERI5", "DMA1", "DMA_CH3", "DMA_SUBPERI5"),
    "SPI4": ("DMA1", "DMA_CH4", "DMA_SUBPERI2", "DMA1", "DMA_CH3", "DMA_SUBPERI2"),
    "SPI5": ("DMA1", "DMA_CH5", "DMA_SUBPERI1", "DMA1", "DMA_CH6", "DMA_SUBPERI1"),
}


def resolve_spi_dma(spi_name, direction="tx"):
    """查 SPI 的 DMA 通道映射；未知外设或该方向未确认返回 None。"""
    key = spi_name.upper()
    entry = SPI_DMA_MAP.get(key)
    if not entry:
        return None
    start = 0 if direction == "tx" else 3
    dma, ch, sub = entry[start:start + 3]
    if dma is None:
        return None
    return dma, ch, sub


def generate_spi(ctx):
    from .model import enabled_instances
    files = {}
    for name, raw in enabled_instances(ctx.cfg, "spi").items():
        conf = dict(SPI_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        files.update(_gen_one(ctx, name, conf))
        ctx.add_init_call("MX_%s_Init" % name.upper(), "初始化 %s 串行外设" % name.upper())
        ctx.add_libopt("gd32f4xx_spi.h")
    return files


def _gen_spi_hal_helpers(b, name, periph, systick_on, conf):
    """生成 HAL 风格的 SPI 读写辅助函数（轮询 + DMA，带超时；片选 CS 由用户自行控制）。"""
    up = name.upper()
    wait = "%s_WaitFlag" % name

    b.line()
    b.box_comment(["HAL 风格 SPI 读写辅助函数（轮询 + DMA，带超时；片选 CS 由用户自行控制）",
                   "返回 0 表示成功，非 0 表示超时"])

    b.doc_func(wait, "等待 SPI 标志置位，超时返回 1", "flag: SPI 标志", "Timeout: 超时(ms)")
    b.line("static uint8_t %s(uint32_t flag, uint32_t Timeout)" % wait)
    b.line("{")
    b.inc()
    b.line("uint32_t t = 0;")
    b.line("while(RESET == spi_i2s_flag_get(%s, flag)) {" % periph)
    b.inc()
    b.line("if(Timeout && (++t >= Timeout)) return 1;")
    if systick_on:
        b.line("delay_1ms(1);")
    b.dec()
    b.line("}")
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_Transmit" % up,
               "写 Size 字节（全双工，忽略读回），HAL 风格",
               params="pData: 发送数据, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 超时")
    b.line("uint8_t %s_Transmit(uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("if(%s(SPI_FLAG_TBE, Timeout)) return 1;" % wait)
    b.line("spi_i2s_data_transmit(%s, pData[i]);" % periph)
    b.line("if(%s(SPI_FLAG_RBNE, Timeout)) return 1;" % wait)
    b.line("(void)spi_i2s_data_receive(%s);   /* 清 RBNE */" % periph)
    b.dec()
    b.line("}")
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_Receive" % up,
               "读 Size 字节（发送哑元 0xFF），HAL 风格",
               params="pData: 接收缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 超时")
    b.line("uint8_t %s_Receive(uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("if(%s(SPI_FLAG_TBE, Timeout)) return 1;" % wait)
    b.line("spi_i2s_data_transmit(%s, 0xFF);   /* 哑元 */" % periph)
    b.line("if(%s(SPI_FLAG_RBNE, Timeout)) return 1;" % wait)
    b.line("pData[i] = spi_i2s_data_receive(%s);" % periph)
    b.dec()
    b.line("}")
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_TransmitReceive" % up,
               "全双工：同时发送 pTxData 并接收 pRxData，HAL 风格",
               params="pTxData: 发送数据, pRxData: 接收缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 超时")
    b.line("uint8_t %s_TransmitReceive(uint8_t *pTxData, uint8_t *pRxData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("if(%s(SPI_FLAG_TBE, Timeout)) return 1;" % wait)
    b.line("spi_i2s_data_transmit(%s, pTxData[i]);" % periph)
    b.line("if(%s(SPI_FLAG_RBNE, Timeout)) return 1;" % wait)
    b.line("pRxData[i] = spi_i2s_data_receive(%s);" % periph)
    b.dec()
    b.line("}")
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    # ---- DMA 收发（SPI DMA 请求已在 MX_Init 使能；此处启动 DMA 并阻塞等待完成）----
    tx = resolve_spi_dma(name, "tx") if conf.get("dma_tx") else None
    rx = resolve_spi_dma(name, "rx") if conf.get("dma_rx") else None
    if tx:
        b.line()
        b.comment("DMA 发送：%s.%s 通道（见 dma.c）" % (tx[0], tx[1]))
        _gen_spi_dma_transfer(b, name, periph, systick_on, "Transmit", "发送", tx)
    if rx:
        b.line()
        b.comment("DMA 接收：%s.%s 通道（见 dma.c）" % (rx[0], rx[1]))
        _gen_spi_dma_transfer(b, name, periph, systick_on, "Receive", "接收", rx)
    if tx and rx:
        b.line()
        b.comment("全双工 DMA：TX=%s.%s，RX=%s.%s" % (tx[0], tx[1], rx[0], rx[1]))
        _gen_spi_dma_full(b, name, periph, systick_on, tx, rx)


def _gen_spi_dma_transfer(b, name, periph, systick_on, suffix, cn, dma_ch):
    """生成 SPIn_Transmit_DMA / SPIn_Receive_DMA（单通道 DMA 传输，阻塞等待完成）。"""
    up = name.upper()
    dma, ch, _sub = dma_ch
    b.doc_func("%s_%s_DMA" % (up, suffix),
               "DMA %s Size 字节（阻塞等待传输完成），HAL 风格" % cn,
               params="pData: 数据缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 超时")
    b.line("uint8_t %s_%s_DMA(uint8_t *pData, uint16_t Size, uint32_t Timeout)" % (up, suffix))
    b.line("{")
    b.inc()
    b.line("dma_memory_address_config(%s, %s, DMA_MEMORY_0, (uint32_t)pData);" % (dma, ch))
    b.line("dma_transfer_number_config(%s, %s, Size);" % (dma, ch))
    b.line("dma_channel_enable(%s, %s);" % (dma, ch))
    b.line("uint32_t t = 0;")
    b.line("while(RESET == dma_flag_get(%s, %s, DMA_FLAG_FTF)) {" % (dma, ch))
    b.inc()
    b.line("if(Timeout && (++t >= Timeout)) { dma_channel_disable(%s, %s); return 1; }" % (dma, ch))
    if systick_on:
        b.line("delay_1ms(1);")
    b.dec()
    b.line("}")
    b.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (dma, ch))
    b.line("dma_channel_disable(%s, %s);" % (dma, ch))
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()


def _gen_spi_dma_full(b, name, periph, systick_on, tx, rx):
    """生成 SPIn_TransmitReceive_DMA（全双工：TX/RX 两个 DMA 通道同时启停）。"""
    up = name.upper()
    b.doc_func("%s_TransmitReceive_DMA" % up,
               "全双工 DMA：TX 发 pTxData、RX 收 pRxData（阻塞等待完成），HAL 风格",
               params="pTxData: 发送缓冲, pRxData: 接收缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 超时")
    b.line("uint8_t %s_TransmitReceive_DMA(uint8_t *pTxData, uint8_t *pRxData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("dma_memory_address_config(%s, %s, DMA_MEMORY_0, (uint32_t)pTxData);" % (tx[0], tx[1]))
    b.line("dma_transfer_number_config(%s, %s, Size);" % (tx[0], tx[1]))
    b.line("dma_channel_enable(%s, %s);" % (tx[0], tx[1]))
    b.line("dma_memory_address_config(%s, %s, DMA_MEMORY_0, (uint32_t)pRxData);" % (rx[0], rx[1]))
    b.line("dma_transfer_number_config(%s, %s, Size);" % (rx[0], rx[1]))
    b.line("dma_channel_enable(%s, %s);" % (rx[0], rx[1]))
    b.line("uint32_t t = 0;")
    b.line("while((RESET == dma_flag_get(%s, %s, DMA_FLAG_FTF)) ||" % (tx[0], tx[1]))
    b.line("      (RESET == dma_flag_get(%s, %s, DMA_FLAG_FTF))) {" % (rx[0], rx[1]))
    b.inc()
    b.line("if(Timeout && (++t >= Timeout)) {")
    b.inc()
    b.line("dma_channel_disable(%s, %s);" % (tx[0], tx[1]))
    b.line("dma_channel_disable(%s, %s);" % (rx[0], rx[1]))
    b.line("return 1;")
    b.dec()
    b.line("}")
    if systick_on:
        b.line("delay_1ms(1);")
    b.dec()
    b.line("}")
    b.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (tx[0], tx[1]))
    b.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (rx[0], rx[1]))
    b.line("dma_channel_disable(%s, %s);" % (tx[0], tx[1]))
    b.line("dma_channel_disable(%s, %s);" % (rx[0], rx[1]))
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()


def _spi_dma_irqn(dma_periph, channel):
    """由 DMA 控制器与通道宏生成 IRQn 名：DMA0 + DMA_CH4 -> DMA0_Channel4_IRQn。"""
    ch = str(channel).replace("DMA_CH", "")
    return "%s_Channel%s_IRQn" % (dma_periph, ch)


def _gen_spi_dma_it(ctx, b, name, periph, conf):
    """生成 HAL 风格非阻塞 DMA 收发（SPIn_Transmit_DMA_IT / Receive_DMA_IT）。

    启动 DMA + 开完成中断后立即返回；传完由 DMA 通道 ISR 清标志/关通道并调弱回调。
    """
    from .common import emit_weak_fallback
    up = name.upper()
    tx = resolve_spi_dma(name, "tx") if conf.get("dma_tx") else None
    rx = resolve_spi_dma(name, "rx") if conf.get("dma_rx") else None
    if not (tx or rx):
        return

    emit_weak_fallback(b)
    b.line()
    b.box_comment(["HAL 风格非阻塞 DMA 收发（_DMA_IT：启动 DMA 立即返回，传完由回调通知）",
                   "回调为弱实现，可在 USER CODE 块里重写"])

    for suffix, cn, dma_ch in (("Transmit", "发送", tx), ("Receive", "接收", rx)):
        if not dma_ch:
            continue
        dma, ch, _sub = dma_ch
        irqn = _spi_dma_irqn(dma, ch)
        handler = irqn.replace("_IRQn", "_IRQHandler")
        cb = "%s_%s_DMA_CpltCallback" % (up, suffix)

        b.doc_func("%s_%s_DMA_IT" % (up, suffix),
                   "非阻塞 DMA %s（启动 DMA 立即返回，传完回调 %s）" % (cn, cb),
                   params="pData: 数据缓冲, Size: 字节数", retval="0 启动成功 / 非 0 失败")
        b.line("uint8_t %s_%s_DMA_IT(uint8_t *pData, uint16_t Size)" % (up, suffix))
        b.line("{")
        b.inc()
        b.line("dma_memory_address_config(%s, %s, DMA_MEMORY_0, (uint32_t)pData);" % (dma, ch))
        b.line("dma_transfer_number_config(%s, %s, Size);" % (dma, ch))
        b.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (dma, ch))
        b.line("dma_interrupt_enable(%s, %s, DMA_CHXCTL_FTFIE);" % (dma, ch))
        b.line("nvic_irq_enable(%s, 2, 0);" % irqn)
        b.line("dma_channel_enable(%s, %s);" % (dma, ch))
        b.line("return 0;")
        b.dec()
        b.line("}")
        b.line()

        b.doc_func(cb, "%s 非阻塞 DMA %s完成回调（弱实现，可重定义）" % (periph, cn))
        b.line("__WEAK void %s(void)" % cb)
        b.line("{")
        b.inc()
        b.line("/* USER CODE BEGIN %s */" % cb)
        b.line("/* TODO: DMA %s完成 */" % cn)
        b.line("/* USER CODE END %s */" % cb)
        b.dec()
        b.line("}")
        b.line()

        isr = CodeBuilder()
        isr.comment("%s %s DMA 完成（FTF），清标志、关通道、调回调" % (periph, cn))
        isr.line("if(RESET != dma_flag_get(%s, %s, DMA_FLAG_FTF)) {" % (dma, ch))
        isr.inc()
        isr.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (dma, ch))
        isr.line("dma_channel_disable(%s, %s);" % (dma, ch))
        isr.line("%s();" % cb)
        isr.dec()
        isr.line("}")
        ctx.add_irq_handler(handler, "%s %s DMA 完成（非阻塞回调）" % (periph, cn), str(isr))
        ctx.add_nvic(irqn, 2, 0, "%s %s DMA IT" % (periph, cn))


def _gen_one(ctx, name, conf):
    rcu_macro, bus, irqn, handler = SPI_INFO[name]
    periph = name.upper()

    b = CodeBuilder()
    b.line(file_header("%s.c" % name, "%s 初始化（MX_%s_Init）" % (periph, periph)))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name)
    if ctx.systick_enabled:
        b.line('#include "systick.h"')
    b.line()

    b.doc_func("MX_%s_Init" % periph, "初始化 %s 串行外设接口" % periph)
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()
    b.line("spi_parameter_struct spi_init_struct;")
    b.line()

    b.comment("使能 %s 时钟（位于 %s）" % (periph, bus))
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 %s" % periph)
    b.line("spi_i2s_deinit(%s);" % periph)
    b.line()
    b.comment("配置 %s 参数" % periph)
    b.line("spi_init_struct.device_mode          = %s;  /* %s */" %
           ("SPI_MASTER" if conf["mode"] == "master" else "SPI_SLAVE",
            "主机" if conf["mode"] == "master" else "从机"))
    b.line("spi_init_struct.trans_mode           = %s;  /* 传输模式 */" % conf["trans_mode"])
    b.line("spi_init_struct.frame_size           = %s;  /* 帧大小 */" % conf["frame_size"])
    b.line("spi_init_struct.clock_polarity_phase = %s;  /* 时钟极性与相位 */" %
           conf["clock_polarity_phase"])
    b.line("spi_init_struct.nss                  = %s;  /* NSS 片选控制 */" % conf["nss"])
    b.line("spi_init_struct.prescale             = %s;  /* 预分频（决定 SCK 频率） */" % conf["prescale"])
    b.line("spi_init_struct.endian               = %s;  /* 大小端 */" % conf["endian"])
    b.line("spi_init(%s, &spi_init_struct);" % periph)
    b.line()
    b.comment("使能 %s" % periph)
    b.line("spi_enable(%s);" % periph)

    # DMA
    if conf["dma_tx"] or conf["dma_rx"]:
        b.line()
        b.comment("使能 SPI DMA 请求（通道由工具自动分配，见 dma.c）")
        if conf["dma_tx"]:
            b.line("spi_dma_enable(%s, SPI_DMA_TRANSMIT);" % periph)
        if conf["dma_rx"]:
            b.line("spi_dma_enable(%s, SPI_DMA_RECEIVE);" % periph)

    if conf["interrupt"] or conf["tx_interrupt"]:
        pre, sub = conf["interrupt_priority"]
        b.line()
        if conf["interrupt"]:
            b.comment("使能 %s 接收中断（RBNE 触发）" % periph)
            b.line("spi_i2s_interrupt_enable(%s, SPI_I2S_INT_RBNE);" % periph)
        if conf["tx_interrupt"]:
            b.comment("使能 %s 发送中断（TBE 触发）" % periph)
            b.line("spi_i2s_interrupt_enable(%s, SPI_I2S_INT_TBE);" % periph)
        b.line("nvic_irq_enable(%s, %d, %d);" % (irqn, pre, sub))
        ctx.add_nvic(irqn, pre, sub, periph + " SPI 中断")

    b.dec()
    b.line("}")
    b.line()

    # ---- 弱回调（开中断时生成；用户可重定义，也可直接改 USER CODE 块）----
    if conf["interrupt"] or conf["tx_interrupt"]:
        emit_weak_fallback(b)
        if conf["interrupt"]:
            b.doc_func("%s_rx_callback" % name,
                       "%s 接收回调（弱实现，收到数据(RBNE)时调用，可在用户代码中重定义）" % periph,
                       params="uint16_t data")
            b.line("__WEAK void %s_rx_callback(uint16_t data)" % name)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN %s_RX */" % periph)
            b.line("/* TODO: 在这里处理收到的一帧数据 */")
            b.line("/* USER CODE END %s_RX */" % periph)
            b.line("(void)data;")
            b.dec()
            b.line("}")
            b.line()
        if conf["tx_interrupt"]:
            b.doc_func("%s_tx_callback" % name,
                       "%s 发送回调（弱实现，TBE 发送缓冲空时调用，用户在此发送下一字节）" % periph)
            b.line("__WEAK void %s_tx_callback(void)" % name)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN %s_TX */" % periph)
            b.line("/* TODO: 在这里发送下一字节，如 spi_i2s_data_transmit(%s, data) */" % periph)
            b.line("/* USER CODE END %s_TX */" % periph)
            b.dec()
            b.line("}")
            b.line()

    # ---- 引脚复用 ----
    for role, pin_key in (("SCK", "sck_pin"), ("MISO", "miso_pin"), ("MOSI", "mosi_pin")):
        pin_str = conf.get(pin_key)
        if not pin_str:
            continue
        port_macro, pin_macro, _l, _n = parse_pin(pin_str)
        af = lookup_af(periph, pin_str, conf["af"])
        if af is None:
            af = 5
            ctx.warn("%s %s 引脚 %s 的 AF 号未知，默认用 AF5，请显式指定 af 字段"
                     % (periph, role, pin_str))
        ctx.add_af(port_macro, pin_macro, af, "%s %s 引脚" % (periph, role))
    # 软件片选：普通推挽输出（6 元组：port,pin,speed,level,label,otype）
    if conf.get("cs_pin"):
        port_macro, pin_macro, _l, _n = parse_pin(conf["cs_pin"])
        ctx.gpio_outputs.append((port_macro, pin_macro,
                                 "GPIO_OSPEED_50MHZ", "HIGH",
                                 conf.get("cs_label") or "CS", "GPIO_OTYPE_PP"))
        ctx.add_gpio_clock(port_macro)

    # ---- 登记中断处理函数（gd32f4xx_it.c 会按 handler 名合并生成）----
    if conf["interrupt"] or conf["tx_interrupt"]:
        body = CodeBuilder()
        if conf["interrupt"]:
            body.comment("接收：RBNE，读出数据交给回调")
            body.line("if(SET == spi_i2s_interrupt_flag_get(%s, SPI_I2S_INT_FLAG_RBNE)) {" % periph)
            body.inc()
            body.comment("读数据寄存器（自动清除 RBNE 标志）")
            body.line("uint16_t rxdata = spi_i2s_data_receive(%s);" % periph)
            body.line("%s_rx_callback(rxdata);" % name)
            body.dec()
            body.line("}")
        if conf["tx_interrupt"]:
            body.line()
            body.comment("发送：TBE（发送缓冲空），交给回调发送下一字节")
            body.line("if(SET == spi_i2s_interrupt_flag_get(%s, SPI_I2S_INT_FLAG_TBE)) {" % periph)
            body.inc()
            body.line("%s_tx_callback();" % name)
            body.dec()
            body.line("}")
        ctx.add_irq_handler(handler, "%s 中断处理（收/发）" % periph, str(body))

    # ---- HAL 风格读写辅助函数（含 DMA + 非阻塞 IT）----
    _gen_spi_hal_helpers(b, name, periph, ctx.systick_enabled, conf)
    _gen_spi_dma_it(ctx, b, name, periph, conf)

    # ---- .h ----
    h = CodeBuilder()
    guard = include_guard("%s_h" % name)
    h.line(file_header("%s.h" % name, "%s 初始化声明" % periph))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_%s_Init(void);" % periph)
    if conf["interrupt"]:
        h.line()
        h.comment("SPI 接收回调（默认弱实现，可在用户代码中重定义）")
        h.line("void %s_rx_callback(uint16_t data);" % name)
    if conf["tx_interrupt"]:
        h.line()
        h.comment("SPI 发送回调（默认弱实现，可在用户代码中重定义）")
        h.line("void %s_tx_callback(void);" % name)
    h.line()
    h.comment("HAL 风格 SPI 读写辅助函数（返回 0 成功 / 非 0 超时；片选 CS 由用户控制）")
    h.line("uint8_t %s_Transmit(uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    h.line("uint8_t %s_Receive(uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    h.line("uint8_t %s_TransmitReceive(uint8_t *pTxData, uint8_t *pRxData, uint16_t Size, uint32_t Timeout);" % periph)
    if conf.get("dma_tx"):
        h.line("uint8_t %s_Transmit_DMA(uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    if conf.get("dma_rx"):
        h.line("uint8_t %s_Receive_DMA(uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    if conf.get("dma_tx") and conf.get("dma_rx"):
        h.line("uint8_t %s_TransmitReceive_DMA(uint8_t *pTxData, uint8_t *pRxData, uint16_t Size, uint32_t Timeout);" % periph)
    if conf.get("dma_tx"):
        h.line("uint8_t %s_Transmit_DMA_IT(uint8_t *pData, uint16_t Size);" % periph)
        h.line("void %s_Transmit_DMA_CpltCallback(void);" % periph)
    if conf.get("dma_rx"):
        h.line("uint8_t %s_Receive_DMA_IT(uint8_t *pData, uint16_t Size);" % periph)
        h.line("void %s_Receive_DMA_CpltCallback(void);" % periph)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"%s.c" % name: str(b), "%s.h" % name: str(h)}
