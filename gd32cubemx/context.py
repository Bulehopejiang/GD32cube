# -*- coding: utf-8 -*-
"""生成上下文：各外设生成模块把公共信息（GPIO 复用、NVIC、中断处理、
libopt 头文件、初始化调用顺序）汇集到这里，最后由组装模块统一输出。"""

from .model import load_config, enabled_instances, get_mcu, get_project_name
from .clock import compute_clock


class GenContext:
    """一次生成过程的工作上下文。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.mcu = get_mcu(cfg)
        self.project_name = get_project_name(cfg)
        # 生成过程警告收集（GUI 生成后统一展示，避免只在控制台可见）
        self.warnings = []
        # 时钟树
        self.clock = compute_clock(cfg["project"]["clock"], mcu=self.mcu)
        self.warnings.extend(self.clock.warnings)
        # 系统定时器
        self.systick_enabled = cfg["project"]["systick"].get("enabled", True)
        self.systick_priority = cfg["project"]["systick"].get("priority", 0)

        # ---- GPIO（MX_GPIO_Init 汇总）----
        self.gpio_outputs = []   # (port, pin, speed, init_level, label)
        self.gpio_inputs = []    # (port, pin, pull, label)
        self.gpio_analog = []    # (port, pin, label)
        self.af_configs = []     # (port, pin, af, note) —— 外设复用引脚
        self.af_ports = set()    # 用到复用功能的 GPIO 端口（RCU_GPIOx 去重）

        # ---- NVIC ----
        self.nvic_group = "NVIC_PRIGROUP_PRE4_SUB0"
        self.nvic_enables = []   # (irqn, pre, sub, note)

        # ---- 外设初始化函数（main.c 调用顺序）----
        self.init_calls = []     # (call, comment)
        self.files = {}          # filename -> content（按文件名合并）

        # ---- 中断处理（gd32f4xx_it.c）----
        # handler名 -> [(brief, body_str), ...]
        # 同一 handler 可登记多个处理体（如同一中断号的多个实例 ADC0/ADC1、
        # TIMER1/TIMER11 等），生成时合并到同一个 IRQ 函数里。
        self.irq_handlers = {}

        # ---- libopt.h ----
        self.libopt_headers = []  # 需在 gd32f4xx_libopt.h 中包含的头文件名

        # ---- main.c 额外内容 ----
        self.printf_uart = None   # (periph宏, 名字) 若启用了 printf 重定向
        self.main_extra_includes = []
        # 自动分配的 DMA 缓冲（由 DMA 页签勾选自动生成通道时登记）：
        # [(变量名, C类型如 uint8_t, 说明), ...]，main.c 自动定义、main.h 自动 extern
        self.dma_buffers = []

    # -- 工具方法 ------------------------------------------------------------
    def warn(self, msg):
        """记录一条生成警告（打印到控制台 + 收集到 ctx.warnings 供 GUI 展示）。"""
        self.warnings.append(msg)
        print("警告：%s" % msg)

    def add_file(self, filename, content):
        self.files[filename] = content

    def add_init_call(self, call, comment):
        self.init_calls.append((call, comment))

    def add_nvic(self, irqn, pre, sub, note=""):
        self.nvic_enables.append((irqn, pre, sub, note))

    def add_irq_handler(self, handler, brief, body):
        """登记一个中断处理函数体；同一 handler 名可登记多个（会自动合并）。"""
        self.irq_handlers.setdefault(handler, []).append((brief, body))

    def add_af(self, port, pin, af, note="", otype="GPIO_OTYPE_PP"):
        """登记一个复用引脚，MX_GPIO_Init 会统一输出 AF 配置。

        otype: 输出类型（推挽 PP / 开漏 OD，如 I2C 需开漏）
        """
        self.af_configs.append((port, pin, af, note, otype))
        self.af_ports.add(port)

    def add_gpio_clock(self, port):
        """登记需使能时钟的 GPIO 端口（由 GPIO 配置或外设 AF 使用）。"""
        self.af_ports.add(port)

    def add_libopt(self, header):
        if header not in self.libopt_headers:
            self.libopt_headers.append(header)
