# -*- coding: utf-8 -*-
"""系统外设生成器：FWDGT / RTC / CRC / TRNG / PMU 的 MX_xxx_Init()。

每个外设独立成文件（fwdgt.c / rtc.c / crc.c / trng.c / pmu.c）。
"""

from .common import CodeBuilder, file_header, include_guard

FWDGT_PSC_VAL = {
    "FWDGT_PSC_DIV4": 4, "FWDGT_PSC_DIV8": 8, "FWDGT_PSC_DIV16": 16,
    "FWDGT_PSC_DIV32": 32, "FWDGT_PSC_DIV64": 64, "FWDGT_PSC_DIV128": 128,
    "FWDGT_PSC_DIV256": 256,
}


def generate_misc(ctx):
    files = {}
    cfg = ctx.cfg

    if cfg.get("fwdgt"):
        files.update(_gen_fwdgt(cfg["fwdgt"]))
        ctx.add_init_call("MX_FWDGT_Init", "初始化独立看门狗 FWDGT")
        ctx.add_libopt("gd32f4xx_fwdgt.h")
    if cfg.get("rtc"):
        files.update(_gen_rtc(cfg["rtc"]))
        ctx.add_init_call("MX_RTC_Init", "初始化实时时钟 RTC")
        ctx.add_libopt("gd32f4xx_rtc.h")
    if cfg.get("crc"):
        files.update(_gen_crc())
        ctx.add_init_call("MX_CRC_Init", "初始化 CRC 计算单元")
        ctx.add_libopt("gd32f4xx_crc.h")
    if cfg.get("trng"):
        files.update(_gen_trng())
        ctx.add_init_call("MX_TRNG_Init", "初始化真随机数发生器 TRNG")
        ctx.add_libopt("gd32f4xx_trng.h")
    if cfg.get("pmu"):
        files.update(_gen_pmu())
        ctx.add_init_call("MX_PMU_Init", "初始化电源管理单元 PMU")
        ctx.add_libopt("gd32f4xx_pmu.h")
    return files


def _wrap(name, brief, body_lines):
    """生成一个标准外设文件（.c + .h）。"""
    b = CodeBuilder()
    b.line(file_header("%s.c" % name, "%s 初始化（MX_%s_Init）" % (name.upper(), name.upper())))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "%s.h"' % name)
    b.line()
    b.doc_func("MX_%s_Init" % name.upper(), brief)
    b.line("void MX_%s_Init(void)" % name.upper())
    b.line("{")
    b.inc()
    for ln in body_lines:
        b.line(ln)
    b.dec()
    b.line("}")
    h = CodeBuilder()
    guard = include_guard("%s_h" % name)
    h.line(file_header("%s.h" % name, "%s 初始化声明" % name.upper()))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_%s_Init(void);" % name.upper())
    h.line()
    h.line("#endif /* %s */" % guard)
    return {"%s.c" % name: str(b), "%s.h" % name: str(h)}


def _gen_fwdgt(conf):
    psc = conf.get("prescaler", "FWDGT_PSC_DIV64")
    reload = conf.get("reload", 500)
    div = FWDGT_PSC_VAL.get(psc, 64)
    timeout_ms = (reload + 1) * div / 32000.0 * 1000  # IRC32K = 32kHz
    body = [
        "/* 独立看门狗配置：预分频 %s，重载值 %d（超时约 %.0f ms） */" % (psc, reload, timeout_ms),
        "fwdgt_config(%d, %s);" % (reload, psc),
        "/* 重载计数器（喂狗一次） */",
        "fwdgt_counter_reload();",
        "/* 启动看门狗：此后必须在超时前周期性调用 fwdgt_counter_reload() 喂狗，否则系统复位 */",
        "fwdgt_enable();",
    ]
    return _wrap("fwdgt", "初始化独立看门狗 FWDGT", body)


def _gen_rtc(conf):
    source = conf.get("source", "RCU_RTCSRC_IRC32K")
    osc = "RCU_IRC32K" if source == "RCU_RTCSRC_IRC32K" else "RCU_LXTAL"
    body = [
        "rtc_parameter_struct rtc_init_struct;",
        "",
        "/* 使能 PMU 时钟并允许备份域写访问（RTC 属于备份域） */",
        "rcu_periph_clock_enable(RCU_PMU);",
        "pmu_backup_write_enable();",
        "",
        "/* 使能 RTC 时钟源并等待就绪（必须先就绪，否则 RTC 无时钟不工作） */",
        "rcu_osci_on(%s);" % osc,
        "rcu_osci_stab_wait(%s);" % osc,
        "/* 先选 RTC 时钟源，再使能 RTC 外设接口，并等待寄存器同步 */",
        "rcu_rtc_clock_config(%s);" % source,
        "rcu_periph_clock_enable(RCU_RTC);",
        "rtc_register_sync_wait();",
        "",
        "/* 填写初始日期时间（BCD 码）与预分频系数。",
        "   注意：不要在此前手动调用 rtc_init_mode_enter()——rtc_register_sync_wait()",
        "   会把写保护重新上锁，导致进初始化模式失败；rtc_init() 内部会先解锁再进模式。 */",
        "rtc_init_struct.year           = 0x%02X;  /* 年（BCD） */" % conf.get("year", 0x26),
        "rtc_init_struct.month          = 0x%02X;  /* 月（BCD） */" % conf.get("month", 0x01),
        "rtc_init_struct.date           = 0x%02X;  /* 日（BCD） */" % conf.get("date", 0x01),
        "rtc_init_struct.day_of_week    = 0x%02X;  /* 星期（1=周一） */" % conf.get("day_of_week", 0x01),
        "rtc_init_struct.hour           = 0x%02X;  /* 时（BCD） */" % conf.get("hour", 0x00),
        "rtc_init_struct.minute         = 0x%02X;  /* 分（BCD） */" % conf.get("minute", 0x00),
        "rtc_init_struct.second         = 0x%02X;  /* 秒（BCD） */" % conf.get("second", 0x00),
        "rtc_init_struct.factor_asyn    = %d;      /* 异步预分频 */" % conf.get("prescaler_asyn", 127),
        "rtc_init_struct.factor_syn     = %d;      /* 同步预分频 */" % conf.get("prescaler_syn", 255),
        "rtc_init_struct.am_pm          = RTC_AM;  /* 24 小时制时无效 */",
        "rtc_init_struct.display_format = RTC_24HOUR;",
        "rtc_init(&rtc_init_struct);",
        "",
        "/* 等待寄存器同步完成（rtc_init 内部已退出初始化模式） */",
        "rtc_register_sync_wait();",
    ]
    return _wrap("rtc", "初始化实时时钟 RTC", body)


def _gen_crc():
    body = [
        "/* 使能 CRC 计算单元时钟 */",
        "rcu_periph_clock_enable(RCU_CRC);",
        "/* 复位 CRC（使用默认多项式 0x04C11DB7），此后可调用 crc_data_register_reset() 或 crc_single_data_calculate() */",
        "crc_deinit();",
    ]
    return _wrap("crc", "初始化循环冗余校验 CRC", body)


def _gen_trng():
    body = [
        "/* 使能 TRNG 时钟 */",
        "rcu_periph_clock_enable(RCU_TRNG);",
        "/* 使能真随机数发生器，此后可调用 trng_get_true_random_data() 读取 32 位随机数 */",
        "trng_enable();",
    ]
    return _wrap("trng", "初始化真随机数发生器 TRNG", body)


def _gen_pmu():
    body = [
        "/* 使能 PMU 时钟（低功耗模式控制 / 电源管理） */",
        "rcu_periph_clock_enable(RCU_PMU);",
    ]
    return _wrap("pmu", "初始化电源管理单元 PMU", body)
