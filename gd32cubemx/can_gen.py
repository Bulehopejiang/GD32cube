# -*- coding: utf-8 -*-
"""CAN 生成器：生成 MX_CANn_Init()（can0.c/can0.h 等）。

覆盖：波特率（预分频+时间段1/2+同步跳变）、工作模式、过滤器、TX/RX 复用引脚。
"""

from .common import CodeBuilder, file_header, include_guard, emit_weak_fallback
from .model import parse_pin
from .af_table import lookup_af

CAN_INFO = {
    "can0": ("RCU_CAN0", "CAN0", "CAN0_RX0_IRQn"),
    "can1": ("RCU_CAN1", "CAN1", "CAN1_RX0_IRQn"),
}

CAN_DEFAULTS = {
    "prescaler": 5,
    "bs1": "CAN_BT_BS1_7TQ",
    "bs2": "CAN_BT_BS2_2TQ",
    "sjw": "CAN_BT_SJW_1TQ",
    "working_mode": "CAN_NORMAL_MODE",
    "auto_bus_off_recovery": "ENABLE",
    "auto_retrans": "ENABLE",
    "tx_pin": None, "rx_pin": None,
    "af": None,
    "filter": [],       # 过滤器列表
    "interrupt": False,
    "interrupt_priority": (2, 0),
}

CAN_BT_MACRO = {
    "sjw": {1: "CAN_BT_SJW_1TQ", 2: "CAN_BT_SJW_2TQ", 3: "CAN_BT_SJW_3TQ", 4: "CAN_BT_SJW_4TQ"},
    "bs1": {n: "CAN_BT_BS1_%dTQ" % n for n in range(1, 17)},
    "bs2": {n: "CAN_BT_BS2_%dTQ" % n for n in range(1, 9)},
}


def _bt_macro(kind, value):
    """把数字或宏字符串统一成 CAN_BT_xxx 宏。"""
    if isinstance(value, int):
        return CAN_BT_MACRO[kind].get(value, "CAN_BT_SJW_1TQ")
    return value


def generate_can(ctx):
    from .model import enabled_instances
    files = {}
    for name, raw in enabled_instances(ctx.cfg, "can").items():
        conf = dict(CAN_DEFAULTS)
        conf.update({k: v for k, v in raw.items() if v is not None})
        files.update(_gen_one(ctx, name, conf))
        ctx.add_init_call("MX_%s_Init" % name.upper(), "初始化 %s CAN 控制器" % name.upper())
        ctx.add_libopt("gd32f4xx_can.h")
    return files


def _gen_one(ctx, name, conf):
    rcu_macro, periph, rx_irq = CAN_INFO[name]
    pclk = ctx.clock.apb1
    sjw = _bt_macro("sjw", conf["sjw"])
    bs1 = _bt_macro("bs1", conf["bs1"])
    bs2 = _bt_macro("bs2", conf["bs2"])
    # 计算波特率：TQ = PCLK/预分频；bit_time = (1+BS1+BS2) TQ
    bs1_val = int(bs1.split("TQ")[0].split("_")[-1])
    bs2_val = int(bs2.split("TQ")[0].split("_")[-1])
    baud_kbps = int(round(pclk / conf["prescaler"] / (1 + bs1_val + bs2_val) * 1000))

    b = CodeBuilder()
    b.line(file_header("%s.c" % name, "%s 初始化（MX_%s_Init）" % (periph, periph)))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name)
    b.line()

    b.doc_func("MX_%s_Init" % periph, "初始化 %s 控制器局域网接口" % periph)
    b.line("void MX_%s_Init(void)" % periph)
    b.line("{")
    b.inc()
    b.line("can_parameter_struct can_parameter;")
    b.line("can_filter_parameter_struct can_filter;")
    b.line()
    b.comment("使能 %s 时钟" % periph)
    b.line("rcu_periph_clock_enable(%s);" % rcu_macro)
    b.line()
    b.comment("复位 %s 并初始化参数结构体（恢复默认值）" % periph)
    b.line("can_deinit(%s);" % periph)
    b.line("can_struct_para_init(CAN_INIT_STRUCT, &can_parameter);")
    b.line()
    b.comment("配置 CAN 位时序（TQ = PCLK/预分频 = %dMHz/%d = %.2fMHz）" %
              (pclk, conf["prescaler"], pclk / conf["prescaler"]))
    b.comment("波特率 = TQ / (1 + BS1 + BS2) ≈ %dKbps" % baud_kbps)
    b.line("can_parameter.prescaler = %d;" % conf["prescaler"])
    b.line("can_parameter.time_segment_1 = %s;" % bs1)
    b.line("can_parameter.time_segment_2 = %s;" % bs2)
    b.line("can_parameter.resync_jump_width = %s;" % sjw)
    b.line()
    b.comment("工作模式：%s" % conf["working_mode"])
    b.line("can_parameter.working_mode = %s;" % conf["working_mode"])
    b.line("can_parameter.time_triggered = DISABLE;")
    b.line("can_parameter.auto_bus_off_recovery = %s;" % conf["auto_bus_off_recovery"])
    b.line("can_parameter.auto_wake_up = DISABLE;")
    b.line("can_parameter.auto_retrans = %s;" % conf["auto_retrans"])
    b.line("can_parameter.rec_fifo_overwrite = DISABLE;")
    b.line("can_parameter.trans_fifo_order = DISABLE;")
    b.line("can_init(%s, &can_parameter);" % periph)

    # 过滤器
    flt = conf.get("filter") or []
    if flt:
        b.line()
        b.comment("配置接收过滤器（默认放行全部报文，可按需修改）")
        for f in flt:
            b.line("can_filter.filter_number = %d;" % f.get("number", 0))
            b.line("can_filter.filter_mode = %s;" % f.get("mode", "CAN_FILTERMODE_MASK"))
            b.line("can_filter.filter_bits = %s;" % f.get("bits", "CAN_FILTERBITS_32BIT"))
            b.line("can_filter.filter_list_high = 0x%04X;" % f.get("list_high", 0))
            b.line("can_filter.filter_list_low = 0x%04X;" % f.get("list_low", 0))
            b.line("can_filter.filter_mask_high = 0x%04X;" % f.get("mask_high", 0))
            b.line("can_filter.filter_mask_low = 0x%04X;" % f.get("mask_low", 0))
            b.line("can_filter.filter_fifo_number = %s;" % f.get("fifo", "CAN_FIFO0"))
            b.line("can_filter.filter_enable = ENABLE;")
            b.line("can_filter_init(&can_filter);")
    else:
        b.line()
        b.comment("未配置过滤器（默认不过滤，所有报文进入 FIFO0）")
        b.line("can_filter.filter_number = 0;")
        b.line("can_filter.filter_mode = CAN_FILTERMODE_MASK;")
        b.line("can_filter.filter_bits = CAN_FILTERBITS_32BIT;")
        b.line("can_filter.filter_list_high = 0x0000;")
        b.line("can_filter.filter_list_low = 0x0000;")
        b.line("can_filter.filter_mask_high = 0x0000;")
        b.line("can_filter.filter_mask_low = 0x0000;")
        b.line("can_filter.filter_fifo_number = CAN_FIFO0;")
        b.line("can_filter.filter_enable = ENABLE;")
        b.line("can_filter_init(&can_filter);")

    if conf["interrupt"]:
        pre, sub = conf["interrupt_priority"]
        b.line()
        b.comment("使能接收中断（FIFO0 收到报文触发）")
        b.line("can_interrupt_enable(%s, CAN_INT_RFNE0);" % periph)
        b.line("nvic_irq_enable(%s, %d, %d);" % (rx_irq, pre, sub))
        ctx.add_nvic(rx_irq, pre, sub, periph + " 接收中断")

    b.dec()
    b.line("}")
    b.line()

    # ---- 弱回调与中断处理（收到报文时调用，用户可重定义）----
    if conf["interrupt"]:
        emit_weak_fallback(b)
        cb = "%s_rx_callback" % name
        b.doc_func(cb,
                   "%s 接收回调（弱实现，收到报文时调用，可在用户代码中重定义）" % periph,
                   params="msg: 接收到的报文（含 ID/数据）")
        b.line("__WEAK void %s(can_receive_message_struct *msg)" % cb)
        b.line("{")
        b.inc()
        b.line("/* USER CODE BEGIN %s_RX */" % periph)
        b.line("/* TODO: 在这里处理收到的 CAN 报文，如 msg->rx_data[] */")
        b.line("/* USER CODE END %s_RX */" % periph)
        b.line("(void)msg;")
        b.dec()
        b.line("}")
        b.line()
        # 中断处理函数体（it.c 按 handler 名合并生成）
        handler = rx_irq.replace("_IRQn", "_IRQHandler")
        body = CodeBuilder()
        body.comment("接收：FIFO0 非空（收到报文），读出后交给用户回调")
        body.line("if(SET == can_interrupt_flag_get(%s, CAN_INT_FLAG_RFL0)) {" % periph)
        body.inc()
        body.line("can_receive_message_struct rx_msg;")
        body.line("can_message_receive(%s, CAN_FIFO0, &rx_msg);" % periph)
        body.line("can_fifo_release(%s, CAN_FIFO0);" % periph)
        body.line("%s(&rx_msg);" % cb)
        body.dec()
        body.line("}")
        ctx.add_irq_handler(handler, "%s 接收中断" % periph, str(body))

    # ---- 引脚复用 ----
    for role, pin_key in (("TX", "tx_pin"), ("RX", "rx_pin")):
        pin_str = conf.get(pin_key)
        if not pin_str:
            continue
        port_macro, pin_macro, _l, _n = parse_pin(pin_str)
        af = lookup_af(periph, pin_str, conf["af"])
        if af is None:
            af = 9
            ctx.warn("%s %s 引脚 %s 的 AF 号未知，默认用 AF9，请显式指定 af 字段"
                     % (periph, role, pin_str))
        ctx.add_af(port_macro, pin_macro, af, "%s %s 引脚" % (periph, role))

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
        h.comment("CAN 接收回调（弱实现，收到报文时调用，可在用户代码中重定义）")
        h.line("void %s_rx_callback(can_receive_message_struct *msg);" % name)
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"%s.c" % name: str(b), "%s.h" % name: str(h)}
