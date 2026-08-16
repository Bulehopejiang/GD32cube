# GD32Cube —— GD32F4xx 图形化代码生成工具

像 STM32CubeMX 一样，在图形界面里勾选配置**时钟树 + 外设**，一键生成带详尽中文注释的 GD32F4xx 初始化代码（`MX_GPIO_Init()`、`MX_USART0_Init()`、`MX_TIMER1_Init()` 等），不用手写寄存器配置，也不用写 JSON 配置文件。

基于官方固件库 `GD32F4xx_Firmware_Library_V3.3.3` 的标准外设库 API 生成，已在 **Keil AC5（armcc）与 AC6（armclang）** 下对示例配置全部编译通过。

## 启动

```powershell
cd E:\GD32cube
python gd32_cubemx_gui.py
```

或直接双击 `gd32_cubemx_gui.py`。

## 界面用法

1. **输出目录**（顶部）：直接选你的 Keil 工程 `User\` 目录（建议，不要复制文件过去）
2. **12 个页签**逐项配置：工程/时钟、GPIO、USART、TIMER、ADC、SPI、I2C、CAN、DMA、DAC、EXTI、系统外设
3. 每个外设：选实例 → 勾「启用本实例」→ 填参数（波特率、引脚、预分频…）
4. 点「生成代码」，初始化代码直接写进输出目录

- 时钟页签点「计算时钟信息」可实时查看 SYSCLK / APB1 / APB2 / 定时器时钟
- 「加载配置 / 保存配置」读写配置文件，下次打开直接恢复
- 打开时自带内置示例（LED + USART0 printf），可直接点生成

## 你的应用代码写在哪

生成的 `main.c` 里有「保险箱」区块：

```c
/* USER CODE BEGIN while */
/* USER CODE END while */
```

你的主循环代码写在这两行之间。**重新生成时这些区块原样保留**，初始化部分自动更新。前提是输出目录直接指向工程 `User\` 目录（原地更新，不要复制文件过去，否则保险箱会被覆盖成空块）。

串口收到数据的处理，写在 `usart0.c` 里的弱回调中；中断、溢出、外部中断都有对应的弱回调可重定义。

## 整合到 Keil 工程

1. 用 `E:\GD32\gd32_project_setup` 创建工程骨架（内含固件库）。
2. GUI 输出目录直接选工程的 `User\` 目录，点生成。
3. 在 Keil 中把新增的 `.c` 文件加入工程（Project → Manage → Add Existing Files，只需加一次）。
4. 中断文件：把生成的 `gd32f4xx_it.c` 里**外设中断段**（`USART0_IRQHandler` 等）复制进工程的 `gd32f4xx_it.c`，或直接用生成文件替换（二选一，避免重复符号）。
5. `gd32f4xx_libopt.h` 可替换工程里的同名文件。

## 支持的外设

GPIO / USART(0,1,2,3,4,5,6,7) / TIMER(0-13：基本定时、PWM、输入捕获) / ADC(0,1,2) / SPI(0-5) / I2C(0,1,2) / CAN(0,1) / DMA / DAC(OUT0/OUT1) / EXTI / FWDGT / RTC / CRC / TRNG / PMU

## 目录结构

```
E:\GD32cube\
├── gd32_cubemx_gui.py        # 图形界面入口（双击运行）
├── configs\
│   └── simple.json           # 内置默认配置（LED + USART0 printf）
└── gd32cubemx\               # 生成器模块
    ├── gui_widgets.py        # GUI 控件辅助
    ├── generate.py           # 代码生成流程（generate_from_cfg）
    ├── clock.py / gpio_gen.py / usart_gen.py / timer_gen.py / adc_gen.py
    ├── spi_gen.py / i2c_gen.py / can_gen.py / dma_gen.py / dac_gen.py
    ├── exti_gen.py / misc_gen.py / it_gen.py / systick_gen.py
    ├── main_gen.py / libopt_gen.py / af_table.py / model.py / context.py / common.py
```

## 已知限制

- 仅支持 GD32F4xx 标准外设库 V3.3.3 的 API。
- 暂不支持 USB、SDIO、ENET、EXMC、DCI、IPA、TLI 等复杂外设（API 可直接手写）。
- 引脚冲突会在生成时打印警告，但不会自动分配引脚。

## 与官方资料核对过的实现细节

- **PLL 参数**：按固件库 `gd32f4xx_rcu.h` 约束生成（PSC 2..63、N 64..500、P 2/4/6/8、Q 2..15），
  VCO 上限按型号校验（F405/407/425/427 = 432MHz，F450/470 = 480MHz）；
  系统时钟超型号上限、APB1 > 60MHz / APB2 > 120MHz、ADC 时钟 > 40MHz 都会告警。
- **ADC 通道引脚**：按数据手册引脚复用表自动对应（通道 0-7=PA0-7、8=PB0、9=PB1、10-13=PC0-3、
  14=PC4、15=PC5；**ADC2 的通道 4-9/14-15 在 PF 端口**；通道 16-18 为内部信号无引脚）。
- **定时器时钟倍频**：按 `RCU_CFG1.TIMERSEL`（MUL2/MUL4）的实际语义计算并显示。
- **DMA 通道映射**：USART/SPI/I2C/ADC 的 DMA 通道-子外设表与用户手册及官方例程一致，
  勾选 DMA 后自动分配，并在 `main.c` 自动定义缓冲（`USART0_Buf` 等）、`main.h` 加 extern，
  大小可在 DMA 页签调整。
- **SysTick 优先级**：使用配置值生成（不再硬编码 0）。
- **TIMER5/6 基本定时器**：无通道，界面仅允许 base 模式。
- **废弃文件清理**：重新生成时自动删除上一轮生成、本轮不再生成的文件；
  若文件已被手动修改则保留并警告，不会误删。
- **生成警告**：时钟/引脚冲突/DMA 冲突/AF 回退等警告会汇总弹出，不再只打印到控制台。
