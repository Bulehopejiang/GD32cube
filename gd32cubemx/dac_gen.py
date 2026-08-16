# -*- coding: utf-8 -*-
"""DAC 生成器：生成 MX_DAC_Init()（dac.c/dac.h）。

覆盖：OUT0/OUT1 两路输出通道的使能、触发源、输出缓冲、数据对齐。
"""

from .common import CodeBuilder, file_header, include_guard

OUT_DEFAULTS = {
    "enable": False,
    "align": "DAC_ALIGN_12B_R",
    "trigger": "DAC_TRIGGER_SOFTWARE",
    "buffer": True,
    "init_value": 0,     # 初始输出值（0-4095）
}


def generate_dac(ctx):
    raw = ctx.cfg.get("dac") or {}
    if not isinstance(raw, dict) or not (raw.get("out0") or raw.get("out1")):
        return {}
    files = _gen(ctx, raw)
    ctx.add_init_call("MX_DAC_Init", "初始化数模转换器 DAC")
    ctx.add_libopt("gd32f4xx_dac.h")
    return files


def _gen(ctx, raw):
    out0 = dict(OUT_DEFAULTS)
    out0.update({k: v for k, v in raw.get("out0", {}).items() if v is not None})
    out1 = dict(OUT_DEFAULTS)
    out1.update({k: v for k, v in raw.get("out1", {}).items() if v is not None})

    b = CodeBuilder()
    b.line(file_header("dac.c", "DAC 初始化（MX_DAC_Init）"))
    b.line('#include "gd32f4xx.h"')
    b.line('#include "dac.h"')
    b.line()

    b.doc_func("MX_DAC_Init", "初始化数模转换器 DAC")
    b.line("void MX_DAC_Init(void)")
    b.line("{")
    b.inc()
    b.comment("使能 DAC 时钟")
    b.line("rcu_periph_clock_enable(RCU_DAC);")
    b.line()
    b.comment("复位 DAC")
    b.line("dac_deinit(DAC0);")
    b.line()

    for name, out_cfg in (("DAC_OUT0", out0), ("DAC_OUT1", out1)):
        if not out_cfg["enable"]:
            continue
        b.comment("配置输出通道 %s" % name)
        b.line("dac_trigger_source_config(DAC0, %s, %s);  /* 触发源 */" %
               (name, out_cfg["trigger"]))
        if out_cfg["trigger"] == "DAC_TRIGGER_SOFTWARE":
            b.line("dac_trigger_disable(DAC0, %s);  /* 软件触发：关闭外部触发 */" % name)
        else:
            b.line("dac_trigger_enable(DAC0, %s);   /* 使能外部触发 */" % name)
        if out_cfg["buffer"]:
            b.line("dac_output_buffer_enable(DAC0, %s);  /* 输出缓冲 */" % name)
        else:
            b.line("dac_output_buffer_disable(DAC0, %s);" % name)
        b.line("dac_enable(DAC0, %s);" % name)
        b.line()
        b.comment("设置初始输出值 %d（对齐方式 %s）" % (out_cfg["init_value"], out_cfg["align"]))
        b.line("dac_data_set(DAC0, %s, %s, %d);" % (name, out_cfg["align"],
                                                    out_cfg["init_value"]))

    b.dec()
    b.line("}")

    h = CodeBuilder()
    guard = include_guard("dac_h")
    h.line(file_header("dac.h", "DAC 初始化声明"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("void MX_DAC_Init(void);")
    h.line()
    h.line("#endif /* %s */" % guard)

    return {"dac.c": str(b), "dac.h": str(h)}
