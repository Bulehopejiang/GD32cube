# -*- coding: utf-8 -*-
"""配置解析与校验：加载 JSON 配置、补齐默认值、引脚解析、外设分组。"""

import json
import sys


def _strip_jsonc_comments(text):
    """去掉 JSONC 风格注释（// 与 /* */），字符串内的注释保留。

    允许配置文件里写中文说明注释，方便使用。
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)

# ---------------------------------------------------------------------------
# 支持的 MCU 与默认配置
# ---------------------------------------------------------------------------
SUPPORTED_MCU = [
    "GD32F405", "GD32F407", "GD32F425", "GD32F427", "GD32F450", "GD32F470",
]

# 各型号系统时钟上限（MHz）
MCU_MAX_CLOCK = {
    "GD32F405": 168, "GD32F407": 168, "GD32F425": 168, "GD32F427": 168,
    "GD32F450": 200, "GD32F470": 240,
}

# 各外设字段默认值
DEFAULTS = {
    "clock": {
        "source": "HXTAL",
        "hxtal_mhz": 8,
        "sysclk_mhz": 168,
        "ahb_prescaler": 1,
        "apb1_prescaler": 4,
        "apb2_prescaler": 2,
        "pll_n": None, "pll_p": None, "pll_q": None,
    },
    "systick": {"enabled": True, "priority": 0},
    "gpio": {"outputs": [], "inputs": [], "analog": []},
    "usart": {}, "timer": {}, "adc": {}, "spi": {}, "i2c": {},
    "can": {}, "dma": {}, "dac": {}, "exti": {}, "fwdgt": {},
    "rtc": {}, "crc": {}, "trng": {}, "pmu": {},
}


def _deep_defaults(cfg, defaults):
    """把 defaults 里缺失的键补进 cfg（浅层即可，dict 逐键补齐）。"""
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v if not isinstance(v, dict) else dict(v)
        elif isinstance(v, dict) and isinstance(cfg[k], dict):
            for kk, vv in v.items():
                if kk not in cfg[k]:
                    cfg[k][kk] = vv
    return cfg


def load_config(path):
    """加载并规范化 JSON 配置。返回 dict；失败抛异常。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = json.loads(_strip_jsonc_comments(f.read()))
    if not isinstance(cfg, dict) or "project" not in cfg:
        raise ValueError("配置文件格式错误：缺少顶层 project 字段")
    # 补齐默认值
    cfg = _deep_defaults(cfg, DEFAULTS)
    for group in ("usart", "timer", "adc", "spi", "i2c", "can", "dma", "dac",
                  "exti", "fwdgt", "rtc", "crc", "trng", "pmu"):
        if group not in cfg:
            cfg[group] = {}
    if "gpio" not in cfg:
        cfg["gpio"] = dict(DEFAULTS["gpio"])
    # 校验 MCU
    mcu = cfg["project"].get("mcu", "GD32F407")
    if mcu not in SUPPORTED_MCU:
        print("警告：MCU %s 不在已知列表 %s，继续生成（API 可能略有差异）"
              % (mcu, SUPPORTED_MCU), file=sys.stderr)
    _warn_extra_periph(cfg, mcu)
    # 系统时钟超上限提醒（如 F407 配 200MHz 是超频）
    sysclk = cfg.get("project", {}).get("clock", {}).get("sysclk_mhz")
    limit = MCU_MAX_CLOCK.get(mcu)
    if sysclk and limit and int(sysclk) > limit:
        print("警告：%s 系统时钟上限 %dMHz，当前配置 %dMHz 属于超频 —— 请降低目标频率"
              % (mcu, limit, int(sysclk)), file=sys.stderr)
    return cfg


def _warn_extra_periph(cfg, mcu):
    """提示在当前 MCU 上不存在的外设实例（防止配错芯片型号）。"""
    if mcu in ("GD32F450", "GD32F470"):
        return  # 大容量芯片包含全部外设
    # 仅 GD32F450/470 有的外设实例
    F470_ONLY = {
        "usart": ("uart6", "uart7"),
        "timer": ("timer8", "timer9", "timer10", "timer11", "timer12", "timer13"),
        "spi": ("spi3", "spi4", "spi5"),
    }
    for section, insts in F470_ONLY.items():
        for inst in insts:
            if cfg.get(section, {}).get(inst):
                print("警告：%s 是 GD32F450/470 才有的外设，在 %s 上不存在 —— 请核对芯片型号"
                      % (inst.upper(), mcu), file=sys.stderr)
    if mcu in ("GD32F405", "GD32F425"):
        for group in ("enet", "exmc", "ipa", "tli", "dci"):
            if cfg.get(group):
                print("警告：%s 在 %s 上不可用" % (group.upper(), mcu), file=sys.stderr)


# ---------------------------------------------------------------------------
# 引脚解析
# ---------------------------------------------------------------------------
def parse_pin(pin_str):
    """解析 'PA9' 这类引脚写法，返回 (port_macro, pin_macro, port_letter, pin_num)。

    - port_macro: GPIOA / GPIOB / ...（用于 gpio_mode_set 等）
    - pin_macro:  GPIO_PIN_9（用于同一函数）
    - port_letter: 'A'（用于 AF 表 / EXTI 源）
    - pin_num:     9（用于 EXTI 线号）
    """
    if not isinstance(pin_str, str) or len(pin_str) < 3:
        raise ValueError("引脚格式错误（应为 PA9 这类写法）：%r" % pin_str)
    # "PA9" -> port='A', num=9；"PB10" -> port='B', num=10
    port = pin_str[1].upper()
    try:
        num = int(pin_str[2:])
    except ValueError:
        raise ValueError("引脚格式错误（应为 PA9 这类写法）：%r" % pin_str)
    if port not in "ABCDEFGHI" or not (0 <= num <= 15):
        raise ValueError("引脚超出范围（端口 A-I，引脚 0-15）：%r" % pin_str)
    return ("GPIO%s" % port, "GPIO_PIN_%d" % num, port, num)


def pin_to_exti_source(port_letter):
    """端口字母 -> EXTI_SOURCE_GPIOx 宏。"""
    return "EXTI_SOURCE_GPIO%s" % port_letter


def pin_to_exti_line(pin_num):
    """引脚号 -> exti_line_enum 宏（EXTI_0..EXTI_15）。"""
    return "EXTI_%d" % pin_num


def pin_to_exti_irq(pin_num):
    """引脚号 -> EXTI 中断号。0-4 单引脚；5-9 / 10-15 合并中断。"""
    if pin_num <= 4:
        return "EXTI%d_IRQn" % pin_num
    if pin_num <= 9:
        return "EXTI5_9_IRQn"
    return "EXTI10_15_IRQn"


def pin_to_exti_handler(pin_num):
    """引脚号 -> 中断处理函数名（gd32f4xx_it.c 中）。"""
    if pin_num <= 4:
        return "EXTI%d_IRQHandler" % pin_num
    if pin_num <= 9:
        return "EXTI5_9_IRQHandler"
    return "EXTI10_15_IRQHandler"


def pin_label(port_macro, pin_macro):
    """GPIOA + GPIO_PIN_9 -> 'PA9'（用于注释显示）。"""
    return "%s%s" % (port_macro[-1], pin_macro.replace("GPIO_PIN_", ""))


# ---------------------------------------------------------------------------
# 外设分组访问（返回"启用的外设"字典；值为 None/False/空表示未启用）
# ---------------------------------------------------------------------------
def enabled_instances(cfg, group):
    """返回 {实例名: 配置dict}，过滤掉未启用（false / null）的实例。"""
    out = {}
    for name, conf in (cfg.get(group) or {}).items():
        if not isinstance(conf, dict):
            continue
        if conf.get("enabled", True) is False:
            continue
        out[name] = conf
    return out


def get_mcu(cfg):
    return cfg["project"].get("mcu", "GD32F407")


def get_project_name(cfg):
    return cfg["project"].get("name", "gd32_project")
