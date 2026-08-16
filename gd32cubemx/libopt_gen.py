# -*- coding: utf-8 -*-
"""gd32f4xx_libopt.h 生成器。

按 MCU 型号生成外设头文件包含列表（与固件库模板的宏分组一致）。
"""

from .common import file_header

# 基础外设（所有 GD32F4xx 型号）
BASE_HEADERS = [
    "gd32f4xx_rcu.h", "gd32f4xx_adc.h", "gd32f4xx_can.h", "gd32f4xx_crc.h",
    "gd32f4xx_ctc.h", "gd32f4xx_dac.h", "gd32f4xx_dbg.h", "gd32f4xx_dci.h",
    "gd32f4xx_dma.h", "gd32f4xx_exti.h", "gd32f4xx_fmc.h", "gd32f4xx_fwdgt.h",
    "gd32f4xx_gpio.h", "gd32f4xx_syscfg.h", "gd32f4xx_i2c.h", "gd32f4xx_iref.h",
    "gd32f4xx_pmu.h", "gd32f4xx_rtc.h", "gd32f4xx_sdio.h", "gd32f4xx_spi.h",
    "gd32f4xx_timer.h", "gd32f4xx_trng.h", "gd32f4xx_usart.h", "gd32f4xx_wwdgt.h",
    "gd32f4xx_misc.h",
]

# 大容量型号额外外设
EXTRA_HEADERS = {
    "GD32F450": ["gd32f4xx_enet.h", "gd32f4xx_exmc.h", "gd32f4xx_ipa.h", "gd32f4xx_tli.h"],
    "GD32F470": ["gd32f4xx_enet.h", "gd32f4xx_exmc.h", "gd32f4xx_ipa.h", "gd32f4xx_tli.h"],
    "GD32F407": ["gd32f4xx_enet.h", "gd32f4xx_exmc.h"],
    "GD32F427": ["gd32f4xx_enet.h", "gd32f4xx_exmc.h"],
}


def generate_libopt(ctx):
    mcu = ctx.mcu
    guard_mcu = "GD32F450" if mcu in ("GD32F450", "GD32F470") else \
                ("GD32F407" if mcu in ("GD32F407", "GD32F427") else mcu)

    lines = []
    lines.append("/*!")
    lines.append("    \\file    gd32f4xx_libopt.h")
    lines.append("    \\brief   library optional for gd32f4xx（由 GD32Cube 生成）")
    lines.append("")
    lines.append("    \\note    工程已编译的外设头文件列表；可按需精简以减少编译时间。")
    lines.append("*/")
    lines.append("")
    lines.append("/*")
    lines.append("    Copyright (c) 2026, GigaDevice Semiconductor Inc.")
    lines.append("    （许可证文本与固件库一致，略）")
    lines.append("*/")
    lines.append("")
    lines.append("#ifndef GD32F4XX_LIBOPT_H")
    lines.append("#define GD32F4XX_LIBOPT_H")
    lines.append("")
    lines.append("#if defined (GD32F450) || defined (GD32F405) || defined (GD32F407) || defined (GD32F470) || defined (GD32F425) || defined (GD32F427)")
    for h in BASE_HEADERS:
        lines.append('#include "%s"' % h)
    lines.append("#endif")
    lines.append("")
    for m, hs in EXTRA_HEADERS.items():
        macro_list = " || ".join("defined (%s)" % x for x in
                                 (("GD32F450", "GD32F470") if m in ("GD32F450", "GD32F470")
                                  else ("GD32F407", "GD32F427")))
        lines.append("#if %s" % macro_list)
        for h in hs:
            lines.append('#include "%s"' % h)
        lines.append("#endif")
        lines.append("")
    lines.append("#endif /* GD32F4XX_LIBOPT_H */")
    lines.append("")

    # 生成注释：当前配置启用了哪些外设
    used = ctx.libopt_headers
    if used:
        note = "/* 当前配置启用的外设：%s */\n" % ", ".join(
            h.replace("gd32f4xx_", "").replace(".h", "") for h in used)
        content = file_header("gd32f4xx_libopt.h", "library optional for gd32f4xx") + \
            note + "\n" + "\n".join(lines)
    else:
        content = file_header("gd32f4xx_libopt.h", "library optional for gd32f4xx") + \
            "\n" + "\n".join(lines)

    return {"gd32f4xx_libopt.h": content}
