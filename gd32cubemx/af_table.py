# -*- coding: utf-8 -*-
"""引脚复用功能(AF)查找表。

GD32F4xx 与 STM32F407 引脚级兼容，常见外设的 AF 号与 STM32F407 一致。
表中数据来源：
  1. 固件库自带 Examples 中实际的 gpio_af_set() 调用（厂商权威数据）；
  2. GD32F4xx / STM32F407 数据手册 AF 复用表。

若配置里已显式指定 "af"，则优先用配置值；查不到时生成器会警告并
使用默认 AF（可用配置显式覆盖）。
"""

# (外设key, 引脚) -> AF 号
# 外设 key：USART0..5 / UART3..7 / SPI0..2 / I2C0..2 / CAN0..1 / TIMERx_CHy
AF_TABLE = {
    # ---------------- USART（全部 AF7） ----------------
    ("USART0", "PA9"): 7, ("USART0", "PA10"): 7,        # 由 Printf 示例证实
    ("USART0", "PA8"): 7,                               # CK 同步时钟引脚，示例证实
    ("USART0", "PB6"): 7, ("USART0", "PB7"): 7,
    ("USART0", "PC10"): 7, ("USART0", "PC11"): 7,
    ("USART0", "PD8"): 7, ("USART0", "PD9"): 7,
    ("USART1", "PA2"): 7, ("USART1", "PA3"): 7,          # Half_duplex 示例证实 PA2
    ("USART1", "PD5"): 7, ("USART1", "PD6"): 7,
    ("USART2", "PB10"): 7, ("USART2", "PB11"): 7,
    ("USART2", "PC10"): 7, ("USART2", "PC11"): 7,
    ("USART2", "PD8"): 7, ("USART2", "PD9"): 7,
    ("UART3", "PC10"): 7, ("UART3", "PC11"): 7,
    ("UART3", "PD8"): 7, ("UART3", "PD9"): 7,
    ("UART4", "PC12"): 7, ("UART4", "PD2"): 7,
    ("USART5", "PC12"): 7, ("USART5", "PD2"): 7,
    # ---------------- SPI ----------------
    ("SPI0", "PA5"): 5, ("SPI0", "PA6"): 5, ("SPI0", "PA7"): 5,
    ("SPI0", "PB3"): 5, ("SPI0", "PB4"): 5, ("SPI0", "PB5"): 5,
    ("SPI0", "PE3"): 5, ("SPI0", "PE4"): 5, ("SPI0", "PE5"): 5, ("SPI0", "PE6"): 5,
    ("SPI1", "PB13"): 5, ("SPI1", "PB14"): 5, ("SPI1", "PB15"): 5,  # I2S 示例证实
    ("SPI1", "PI0"): 5, ("SPI1", "PI1"): 5, ("SPI1", "PI2"): 5, ("SPI1", "PI3"): 5,  # NSS/SCK/MISO/MOSI，示例证实
    ("SPI1", "PB12"): 5, ("SPI1", "PC2"): 5, ("SPI1", "PC3"): 5, ("SPI1", "PD7"): 5,
    # SPI2 仅保留确认的 PC10/11/12（AF6）；PB10/11/12 不属 SPI2，勿配（防幻觉条目）
    ("SPI2", "PC10"): 6, ("SPI2", "PC11"): 6, ("SPI2", "PC12"): 6,
    # SPI3（F450/470，≈STM32 SPI3，AF5）
    ("SPI3", "PE11"): 5, ("SPI3", "PE12"): 5, ("SPI3", "PE13"): 5, ("SPI3", "PE14"): 5,
    # ---------------- I2C（全部 AF4） ----------------
    ("I2C0", "PB6"): 4, ("I2C0", "PB7"): 4,              # Master/Slave 示例证实
    ("I2C0", "PB8"): 4, ("I2C0", "PB9"): 4,
    ("I2C1", "PB10"): 4, ("I2C1", "PB11"): 4,            # 示例证实
    ("I2C2", "PA8"): 4, ("I2C2", "PC9"): 4,
    # ---------------- CAN（全部 AF9） ----------------
    ("CAN0", "PB8"): 9, ("CAN0", "PB9"): 9,              # 示例证实
    ("CAN0", "PD0"): 9, ("CAN0", "PD1"): 9,
    ("CAN0", "PA11"): 9, ("CAN0", "PA12"): 9,
    ("CAN1", "PB5"): 9, ("CAN1", "PB6"): 9,              # 示例证实
    ("CAN1", "PB12"): 9, ("CAN1", "PB13"): 9,
    # ---------------- TIMER0（≈TIM1 高级定时器，AF1） ----------------
    # 注意：GD32 通道宏是 0 基（TIMER_CH_0=第一通道）。配置里 ch=1 对应 TIMER_CH_0，
    # 故这里的键统一用 0 基：CH0=PA8/PE9、CH1=PA9/PE11、CH2=PA10/PE13、CH3=PA11/PE14。
    ("TIMER0_CH0", "PA8"): 1, ("TIMER0_CH1", "PA9"): 1,
    ("TIMER0_CH2", "PA10"): 1, ("TIMER0_CH3", "PA11"): 1,
    ("TIMER0_CH0", "PE9"): 1, ("TIMER0_CH1", "PE11"): 1,
    ("TIMER0_CH2", "PE13"): 1, ("TIMER0_CH3", "PE14"): 1,
    ("TIMER0_CH0N", "PB13"): 1, ("TIMER0_CH1N", "PB14"): 1, ("TIMER0_CH2N", "PB15"): 1,
    # ---------------- TIMER1（≈TIM2，AF1） ----------------
    ("TIMER1_CH0", "PA0"): 1, ("TIMER1_CH1", "PA1"): 1,  # ocactive 示例证实
    ("TIMER1_CH2", "PA2"): 1, ("TIMER1_CH3", "PA3"): 1,
    ("TIMER1_CH0", "PA5"): 1,                            # exttrigger 示例证实
    ("TIMER1_CH1", "PB3"): 1, ("TIMER1_CH2", "PB10"): 1, # pwmout 示例证实
    ("TIMER1_CH3", "PB11"): 1,
    # ---------------- TIMER2（≈TIM3，AF2） ----------------
    ("TIMER2_CH0", "PA6"): 2, ("TIMER2_CH1", "PA7"): 2,
    ("TIMER2_CH2", "PB0"): 2, ("TIMER2_CH3", "PB1"): 2,
    ("TIMER2_CH0", "PB4"): 2, ("TIMER2_CH1", "PB5"): 2,  # inputcapture 示例证实
    # ---------------- TIMER3（≈TIM4，AF2） ----------------
    ("TIMER3_CH0", "PB6"): 2, ("TIMER3_CH1", "PB7"): 2,
    ("TIMER3_CH2", "PB8"): 2, ("TIMER3_CH3", "PB9"): 2,
    # ---------------- TIMER4（≈TIM5，AF2） ----------------
    ("TIMER4_CH0", "PA0"): 2, ("TIMER4_CH1", "PA1"): 2,
    ("TIMER4_CH2", "PA2"): 2, ("TIMER4_CH3", "PA3"): 2,
}

# 定时器输入捕获通道与对应输出通道共用 AF（补齐键）
for (_t, _p), _af in list(AF_TABLE.items()):
    if _t.startswith("TIMER") and "_CH" in _t and not _t.endswith("N"):
        AF_TABLE.setdefault((_t.replace("_CH", "_IC"), _p), _af)


def lookup_af(periph_key, pin_str, config_af=None):
    """查找引脚复用号。

    periph_key   如 "USART0" / "TIMER1_CH1" / "SPI0"
    pin_str      如 "PA9"
    config_af    配置里显式指定的 AF 号（优先）
    返回 int 或 None（未找到）。
    """
    if config_af is not None:
        return int(config_af)
    return AF_TABLE.get((periph_key, pin_str))
