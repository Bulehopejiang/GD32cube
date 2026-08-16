# -*- coding: utf-8 -*-
"""I2C 生成器：生成 MX_I2Cn_Init()（i2c0.c/i2c0.h 等）。

覆盖：I2C 时钟速率、从机地址格式/地址、ACK、SCL/SDA 复用引脚、中断。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .af_table import lookup_af

# I2C 实例 -> (RCU 宏, 所在总线, 事件中断号, 错误中断号, 事件处理函数名, 错误处理函数名)
I2C_INFO = {
    "i2c0": ("RCU_I2C0", "APB1", "I2C0_EV_IRQn", "I2C0_ER_IRQn",
             "I2C0_EV_IRQHandler", "I2C0_ER_IRQHandler"),
    "i2c1": ("RCU_I2C1", "APB1", "I2C1_EV_IRQn", "I2C1_ER_IRQn",
             "I2C1_EV_IRQHandler", "I2C1_ER_IRQHandler"),
    "i2c2": ("RCU_I2C2", "APB1", "I2C2_EV_IRQn", "I2C2_ER_IRQn",
             "I2C2_EV_IRQHandler", "I2C2_ER_IRQHandler"),
}

I2C_DEFAULTS = {
    "clkspeed": 100000,               # I2C SCL 频率（Hz）
    "dutycyc": "I2C_DTCY_2",
    "addformat": "I2C_ADDFORMAT_7BITS",
    "addr": 0x50,
    "scl_pin": None, "sda_pin": None,
    "af": None,
    "dma_tx": False, "dma_rx": False,
    "interrupt": False, "tx_interrupt": False,
    "interrupt_priority": (2, 0),
}

# I2C -> (TX_DMA, TX通道, TX子外设, RX_DMA, RX通道, RX子外设)
# GD32F4xx 用户手册表 10-2 DMA0：
#   I2C0_TX=DMA0_CH6(SUBPERI1, PERIEN001)、I2C0_RX=DMA0_CH0(SUBPERI1, PERIEN001)、
#   I2C1_TX=DMA0_CH7(SUBPERI7, PERIEN111)、I2C1_RX=DMA0_CH2(SUBPERI7, PERIEN111)、
#   I2C2_TX=DMA0_CH3(SUBPERI3, PERIEN011)、I2C2_RX=DMA0_CH1(SUBPERI3, PERIEN011)。
# 与官方例程(Master_transmitter&slave_receiver_dma)的 I2C0_TX / I2C1_RX 一致。
I2C_DMA_MAP = {
    "I2C0": ("DMA0", "DMA_CH6", "DMA_SUBPERI1", "DMA0", "DMA_CH0", "DMA_SUBPERI1"),
    "I2C1": ("DMA0", "DMA_CH7", "DMA_SUBPERI7", "DMA0", "DMA_CH2", "DMA_SUBPERI7"),
    "I2C2": ("DMA0", "DMA_CH3", "DMA_SUBPERI3", "DMA0", "DMA_CH1", "DMA_SUBPERI3"),
}


def resolve_i2c_dma(i2c_name, direction="tx"):
    """查 I2C 的 DMA 通道映射；未知或该方向未确认返回 None。"""
    key = i2c_name.upper()
    entry = I2C_DMA_MAP.get(key)
    if not entry:
        return None
    start = 0 if direction == "tx" else 3
    dma, ch, sub = entry[start:start + 3]
    if dma is None:
        return None
    return dma, ch, sub


def generate_i2c(ctx):
    from .model import enabled_instances
    files = {}
    for name, raw in enabled_instances(ctx.cfg, "i2c").items():
        conf = dict(I2C_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        files.update(_gen_one(ctx, name, conf))
        ctx.add_init_call("MX_%s_Init" % name.upper(), "初始化 %s 串行总线" % name.upper())
        ctx.add_libopt("gd32f4xx_i2c.h")
    return files


def _gen_i2c_hal_helpers(b, name, periph, systick_on):
    """生成 HAL 风格 I2C 主设备读写辅助函数。

    自动处理 START / 地址 / ACK / STOP，带超时（防卡死）。
    函数名与 HAL 对齐：I2C0_Master_Transmit / Master_Receive / Mem_Write / Mem_Read。
    返回 0 表示成功，非 0 表示出错或超时。
    """
    up = name.upper()
    wait = "%s_WaitFlag" % name

    b.line()
    b.box_comment(["HAL 风格主设备读写辅助函数（自动处理 START/地址/ACK/STOP，带超时）",
                   "返回 0 表示成功，非 0 表示出错或超时"])

    b.doc_func(wait, "等待 I2C 标志置位，超时返回 1", "flag: I2C 标志", "Timeout: 超时(ms)")
    b.line("static uint8_t %s(uint32_t flag, uint32_t Timeout)" % wait)
    b.line("{")
    b.inc()
    b.line("uint32_t t = 0;")
    b.line("while(RESET == i2c_flag_get(%s, flag)) {" % periph)
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

    b.doc_func("%s_Master_Transmit" % up,
               "写 Size 字节到从机（START + 地址(写) + 数据 + STOP），HAL 风格",
               params="DevAddress: 从机写地址(如 0x70), pData: 数据, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 出错")
    b.line("uint8_t %s_Master_Transmit(uint8_t DevAddress, uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("i2c_start_on_bus(%s);" % periph)
    b.line("if(%s(I2C_FLAG_SBSEND, Timeout)) return 1;" % wait)
    b.line("i2c_master_addressing(%s, DevAddress, I2C_TRANSMITTER);" % periph)
    b.line("if(%s(I2C_FLAG_ADDSEND, Timeout)) return 1;" % wait)
    b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("i2c_data_transmit(%s, pData[i]);" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.dec()
    b.line("}")
    b.line("i2c_stop_on_bus(%s);" % periph)
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_Master_Receive" % up,
               "读 Size 字节（START + 地址(读) + 数据 + STOP，首字节 ACK、末字节 NACK），HAL 风格",
               params="DevAddress: 从机写地址(如 0x70), pData: 接收缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 出错")
    b.line("uint8_t %s_Master_Receive(uint8_t DevAddress, uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("i2c_start_on_bus(%s);" % periph)
    b.line("if(%s(I2C_FLAG_SBSEND, Timeout)) return 1;" % wait)
    b.line("i2c_master_addressing(%s, DevAddress, I2C_RECEIVER);" % periph)
    b.line("if(%s(I2C_FLAG_ADDSEND, Timeout)) return 1;" % wait)
    b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
    b.line("i2c_ack_config(%s, I2C_ACK_ENABLE);   /* 首字节必须应答，否则从机停止发送 */" % periph)
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("if(i == Size - 1) i2c_ack_config(%s, I2C_ACK_DISABLE);   /* 末字节不应答 */" % periph)
    b.line("if(%s(I2C_FLAG_RBNE, Timeout)) return 1;" % wait)
    b.line("pData[i] = i2c_data_receive(%s);" % periph)
    b.dec()
    b.line("}")
    b.line("i2c_stop_on_bus(%s);" % periph)
    b.line("i2c_ack_config(%s, I2C_ACK_ENABLE);" % periph)
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_Mem_Write" % up,
               "写寄存器/内存：START + 地址(写) + 内存地址 + 数据 + STOP，HAL 风格",
               params="DevAddress: 从机地址, MemAddress: 内存/寄存器地址, MemAddSize: 地址字节数(1或2), "
                      "pData: 数据, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 出错")
    b.line("uint8_t %s_Mem_Write(uint8_t DevAddress, uint16_t MemAddress, uint8_t MemAddSize, uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("i2c_start_on_bus(%s);" % periph)
    b.line("if(%s(I2C_FLAG_SBSEND, Timeout)) return 1;" % wait)
    b.line("i2c_master_addressing(%s, DevAddress, I2C_TRANSMITTER);" % periph)
    b.line("if(%s(I2C_FLAG_ADDSEND, Timeout)) return 1;" % wait)
    b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
    b.line("if(MemAddSize == 2) {   /* 16 位内存地址：先发高字节 */")
    b.inc()
    b.line("i2c_data_transmit(%s, (uint8_t)(MemAddress >> 8));" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.dec()
    b.line("}")
    b.line("i2c_data_transmit(%s, (uint8_t)MemAddress);" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("i2c_data_transmit(%s, pData[i]);" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.dec()
    b.line("}")
    b.line("i2c_stop_on_bus(%s);" % periph)
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()

    b.doc_func("%s_Mem_Read" % up,
               "读寄存器/内存：写地址 + 重复起始 + 读数据，HAL 风格",
               params="DevAddress: 从机地址, MemAddress: 内存/寄存器地址, MemAddSize: 地址字节数(1或2), "
                      "pData: 接收缓冲, Size: 字节数, Timeout: 超时(ms)",
               retval="0 成功 / 非 0 出错")
    b.line("uint8_t %s_Mem_Read(uint8_t DevAddress, uint16_t MemAddress, uint8_t MemAddSize, uint8_t *pData, uint16_t Size, uint32_t Timeout)" % up)
    b.line("{")
    b.inc()
    b.line("i2c_start_on_bus(%s);" % periph)
    b.line("if(%s(I2C_FLAG_SBSEND, Timeout)) return 1;" % wait)
    b.line("i2c_master_addressing(%s, DevAddress, I2C_TRANSMITTER);" % periph)
    b.line("if(%s(I2C_FLAG_ADDSEND, Timeout)) return 1;" % wait)
    b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
    b.line("if(MemAddSize == 2) {")
    b.inc()
    b.line("i2c_data_transmit(%s, (uint8_t)(MemAddress >> 8));" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.dec()
    b.line("}")
    b.line("i2c_data_transmit(%s, (uint8_t)MemAddress);" % periph)
    b.line("if(%s(I2C_FLAG_TBE, Timeout)) return 1;" % wait)
    b.line("/* 重复起始（restart），切换到读 */")
    b.line("i2c_start_on_bus(%s);" % periph)
    b.line("if(%s(I2C_FLAG_SBSEND, Timeout)) return 1;" % wait)
    b.line("i2c_master_addressing(%s, DevAddress, I2C_RECEIVER);" % periph)
    b.line("if(%s(I2C_FLAG_ADDSEND, Timeout)) return 1;" % wait)
    b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
    b.line("i2c_ack_config(%s, I2C_ACK_ENABLE);" % periph)
    b.line("for(uint16_t i = 0; i < Size; i++) {")
    b.inc()
    b.line("if(i == Size - 1) i2c_ack_config(%s, I2C_ACK_DISABLE);" % periph)
    b.line("if(%s(I2C_FLAG_RBNE, Timeout)) return 1;" % wait)
    b.line("pData[i] = i2c_data_receive(%s);" % periph)
    b.dec()
    b.line("}")
    b.line("i2c_stop_on_bus(%s);" % periph)
    b.line("i2c_ack_config(%s, I2C_ACK_ENABLE);" % periph)
    b.line("return 0;")
    b.dec()
    b.line("}")
    b.line()


def _i2c_dma_irqn(dma_periph, channel):
    """由 DMA 控制器与通道宏生成 IRQn 名：DMA0 + DMA_CH6 -> DMA0_Channel6_IRQn。"""
    ch = str(channel).replace("DMA_CH", "")
    return "%s_Channel%s_IRQn" % (dma_periph, ch)


def _gen_i2c_dma_it(ctx, b, name, periph, conf):
    """生成 HAL 风格非阻塞 I2C DMA 收发（I2Cn_Master_Transmit_DMA_IT / Receive_DMA_IT）。

    轮询发 START/地址后启动 DMA 立即返回；传完由 DMA 通道 ISR 发 STOP、清标志、关通道并调弱回调。
    """
    from .common import emit_weak_fallback
    up = name.upper()
    wait = "%s_WaitFlag" % name
    tx = resolve_i2c_dma(name, "tx") if conf.get("dma_tx") else None
    rx = resolve_i2c_dma(name, "rx") if conf.get("dma_rx") else None
    if not (tx or rx):
        return

    emit_weak_fallback(b)
    b.line()
    b.box_comment(["HAL 风格非阻塞 I2C DMA 收发（_DMA_IT：发 START/地址后启动 DMA 立即返回，传完回调）",
                   "回调为弱实现，可在 USER CODE 块里重写；接收时末字节不单独 NACK，靠 STOP 结束"])

    for suffix, cn, dma_ch, direction in (
        ("Master_Transmit", "发送", tx, "I2C_TRANSMITTER"),
        ("Master_Receive", "接收", rx, "I2C_RECEIVER"),
    ):
        if not dma_ch:
            continue
        dma, ch, _sub = dma_ch
        irqn = _i2c_dma_irqn(dma, ch)
        handler = irqn.replace("_IRQn", "_IRQHandler")
        cb = "%s_%s_DMA_CpltCallback" % (up, suffix)

        b.doc_func("%s_%s_DMA_IT" % (up, suffix),
                   "非阻塞 DMA %s（轮询发 START/地址后启动 DMA，传完回调 %s）" % (cn, cb),
                   params="DevAddress: 从机写地址(如 0x70), pData: 数据缓冲, Size: 字节数",
                   retval="0 启动成功 / 非 0 失败")
        b.line("uint8_t %s_%s_DMA_IT(uint8_t DevAddress, uint8_t *pData, uint16_t Size)" % (up, suffix))
        b.line("{")
        b.inc()
        b.line("i2c_start_on_bus(%s);" % periph)
        b.line("if(%s(I2C_FLAG_SBSEND, 10)) return 1;" % wait)
        b.line("i2c_master_addressing(%s, DevAddress, %s);" % (periph, direction))
        b.line("if(%s(I2C_FLAG_ADDSEND, 10)) return 1;" % wait)
        b.line("i2c_flag_clear(%s, I2C_FLAG_ADDSEND);" % periph)
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

        b.doc_func(cb, "%s 非阻塞 DMA %s完成回调（弱实现，可重定义；传完自动发 STOP）" % (periph, cn))
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
        isr.comment("%s %s DMA 完成（FTF），发 STOP、清标志、关通道、调回调" % (periph, cn))
        isr.line("if(RESET != dma_flag_get(%s, %s, DMA_FLAG_FTF)) {" % (dma, ch))
        isr.inc()
        isr.line("dma_flag_clear(%s, %s, DMA_FLAG_FTF);" % (dma, ch))
        isr.line("dma_channel_disable(%s, %s);" % (dma, ch))
        isr.line("i2c_stop_on_bus(%s);" % periph)
        isr.line("%s();" % cb)
        isr.dec()
        isr.line("}")
        ctx.add_irq_handler(handler, "%s %s DMA 完成（非阻塞回调）" % (periph, cn), str(isr))
        ctx.add_nvic(irqn, 2, 0, "%s %s DMA IT" % (periph, cn))


def _gen_one(ctx, name, conf):
    rcu_macro, bus, ev_irq, er_irq, ev_handler, er_handler = I2C_INFO[name]
    periph = name.upper()
    pclk = ctx.clock.apb1

    b = CodeBuilder()
    b.line(file_header("%s.c" % name, "%s 初始化（MX_%s_Init）" % (periph, periph)))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name)
    if ctx.systick_enabled:
        b.line('#include "systick.h"')
    b.line()

    b.doc_func("MX_%s_Init" % periph, "初始化 %s 串行总线接口" % periph)
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()
    b.comment("使能 %s 时钟（位于 %s，PCLK = %dMHz）" % (periph, bus, pclk))
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 %s" % periph)
    b.line("i2c_deinit(%s);" % periph)
    b.line()
    b.comment("配置 I2C 时钟：SCL = %dHz（clkspeed 传频率值，duty 占空比参数）" %
              conf["clkspeed"])
    b.line("i2c_clock_config(%s, %d, %s);" % (periph, conf["clkspeed"], conf["dutycyc"]))
    b.line()
    b.comment("配置自身地址：%s 格式，地址 0x%X" % (conf["addformat"], conf["addr"]))
    b.line("i2c_mode_addr_config(%s, I2C_I2CMODE_ENABLE, %s, 0x%X);" %
           (periph, conf["addformat"], conf["addr"]))
    b.line()
    b.comment("使能 ACK 应答")
    b.line("i2c_ack_config(%s, I2C_ACK_ENABLE);" % periph)

    if conf["interrupt"] or conf["tx_interrupt"]:
        pre, sub = conf["interrupt_priority"]
        b.line()
        b.comment("使能事件中断（RBNE 接收 / TBE 发送）")
        b.line("i2c_interrupt_enable(%s, I2C_INT_EV);" % periph)
        b.line("nvic_irq_enable(%s, %d, %d);" % (ev_irq, pre, sub))
        ctx.add_nvic(ev_irq, pre, sub, periph + " 事件中断")
        if conf["interrupt"]:
            b.line()
            b.comment("使能错误中断")
            b.line("i2c_interrupt_enable(%s, I2C_INT_ERR);" % periph)
            b.line("nvic_irq_enable(%s, %d, %d);" % (er_irq, pre, sub))
            ctx.add_nvic(er_irq, pre, sub, periph + " 错误中断")

    b.line()
    b.comment("使能 %s" % periph)
    b.line("i2c_enable(%s);" % periph)

    # DMA（I2C 的 DMA 使能不分方向，统一 I2C_DMA_ON）
    if conf["dma_tx"] or conf["dma_rx"]:
        b.line()
        b.comment("使能 I2C DMA（通道由工具自动分配，见 dma.c）")
        b.line("i2c_dma_config(%s, I2C_DMA_ON);" % periph)

    b.dec()
    b.line("}")
    b.line()

    # ---- 弱回调（开中断时生成；用户可重定义，也可直接改 USER CODE 块）----
    if conf["interrupt"] or conf["tx_interrupt"]:
        emit_weak_fallback(b)
        if conf["interrupt"]:
            b.doc_func("%s_ev_callback" % name,
                       "%s 事件回调（弱实现，收到数据(RBNE)时调用，可在用户代码中重定义）" % periph,
                       params="uint8_t data")
            b.line("__WEAK void %s_ev_callback(uint8_t data)" % name)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN %s_EV */" % periph)
            b.line("/* TODO: 在这里处理收到的一字节数据 */")
            b.line("/* USER CODE END %s_EV */" % periph)
            b.line("(void)data;")
            b.dec()
            b.line("}")
            b.line()
            b.doc_func("%s_er_callback" % name,
                       "%s 错误回调（弱实现，错误发生时调用，可在用户代码中重定义）" % periph)
            b.line("__WEAK void %s_er_callback(void)" % name)
            b.line("{")
            b.inc()
            b.line("/* USER CODE BEGIN %s_ER */" % periph)
            b.line("/* TODO: 在这里处理总线/应答/过载等错误 */")
            b.line("/* USER CODE END %s_ER */" % periph)
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
            b.line("/* TODO: 在这里发送下一字节，如 i2c_data_transmit(%s, data) */" % periph)
            b.line("/* USER CODE END %s_TX */" % periph)
            b.dec()
            b.line("}")
            b.line()

    # ---- 引脚复用 ----
    for role, pin_key in (("SCL", "scl_pin"), ("SDA", "sda_pin")):
        pin_str = conf.get(pin_key)
        if not pin_str:
            continue
        port_macro, pin_macro, _l, _n = parse_pin(pin_str)
        af = lookup_af(periph, pin_str, conf["af"])
        if af is None:
            af = 4
            ctx.warn("%s %s 引脚 %s 的 AF 号未知，默认用 AF4，请显式指定 af 字段"
                     % (periph, role, pin_str))
        # I2C 需要开漏输出
        ctx.add_af(port_macro, pin_macro, af,
                   "%s %s 引脚（I2C 需开漏）" % (periph, role),
                   otype="GPIO_OTYPE_OD")

    # ---- 登记中断处理函数（gd32f4xx_it.c 会按 handler 名合并生成）----
    if conf["interrupt"] or conf["tx_interrupt"]:
        ev_body = CodeBuilder()
        if conf["interrupt"]:
            ev_body.comment("事件中断：RBNE（收到数据），读出交给回调")
            ev_body.line("if(SET == i2c_interrupt_flag_get(%s, I2C_INT_FLAG_RBNE)) {" % periph)
            ev_body.inc()
            ev_body.comment("读数据寄存器（自动清除 RBNE 标志）")
            ev_body.line("uint8_t rxdata = i2c_data_receive(%s);" % periph)
            ev_body.line("%s_ev_callback(rxdata);" % name)
            ev_body.dec()
            ev_body.line("}")
        if conf["tx_interrupt"]:
            ev_body.line()
            ev_body.comment("事件中断：TBE（发送缓冲空），交给回调发送下一字节")
            ev_body.line("if(SET == i2c_interrupt_flag_get(%s, I2C_INT_FLAG_TBE)) {" % periph)
            ev_body.inc()
            ev_body.line("%s_tx_callback();" % name)
            ev_body.dec()
            ev_body.line("}")
        ctx.add_irq_handler(ev_handler, "%s 事件中断处理" % periph, str(ev_body))

    if conf["interrupt"]:
        er_body = CodeBuilder()
        er_body.comment("错误中断：清除常见错误标志后交给用户回调")
        er_body.line("i2c_interrupt_flag_clear(%s, I2C_INT_FLAG_BERR);" % periph)
        er_body.line("i2c_interrupt_flag_clear(%s, I2C_INT_FLAG_LOSTARB);" % periph)
        er_body.line("i2c_interrupt_flag_clear(%s, I2C_INT_FLAG_AERR);" % periph)
        er_body.line("i2c_interrupt_flag_clear(%s, I2C_INT_FLAG_OUERR);" % periph)
        er_body.line("%s_er_callback();" % name)
        ctx.add_irq_handler(er_handler, "%s 错误中断处理" % periph, str(er_body))

    # ---- HAL 风格主设备读写辅助函数（含非阻塞 DMA IT）----
    _gen_i2c_hal_helpers(b, name, periph, ctx.systick_enabled)
    _gen_i2c_dma_it(ctx, b, name, periph, conf)

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
        h.comment("I2C 事件/错误回调（默认弱实现，可在用户代码中重定义）")
        h.line("void %s_ev_callback(uint8_t data);" % name)
        h.line("void %s_er_callback(void);" % name)
    if conf["tx_interrupt"]:
        h.line()
        h.comment("I2C 发送回调（默认弱实现，可在用户代码中重定义）")
        h.line("void %s_tx_callback(void);" % name)
    h.line()
    h.comment("HAL 风格主设备读写辅助函数（返回 0 成功 / 非 0 出错，自动处理 START/ACK/STOP）")
    h.line("uint8_t %s_Master_Transmit(uint8_t DevAddress, uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    h.line("uint8_t %s_Master_Receive(uint8_t DevAddress, uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    h.line("uint8_t %s_Mem_Write(uint8_t DevAddress, uint16_t MemAddress, uint8_t MemAddSize, uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    h.line("uint8_t %s_Mem_Read(uint8_t DevAddress, uint16_t MemAddress, uint8_t MemAddSize, uint8_t *pData, uint16_t Size, uint32_t Timeout);" % periph)
    if conf.get("dma_tx"):
        h.line("uint8_t %s_Master_Transmit_DMA_IT(uint8_t DevAddress, uint8_t *pData, uint16_t Size);" % periph)
        h.line("void %s_Master_Transmit_DMA_CpltCallback(void);" % periph)
    if conf.get("dma_rx"):
        h.line("uint8_t %s_Master_Receive_DMA_IT(uint8_t DevAddress, uint8_t *pData, uint16_t Size);" % periph)
        h.line("void %s_Master_Receive_DMA_CpltCallback(void);" % periph)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"%s.c" % name: str(b), "%s.h" % name: str(h)}
