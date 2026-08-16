# -*- coding: utf-8 -*-
"""系统时钟生成器：根据用户时钟树配置输出 RCU 初始化代码。

生成函数参考固件库 system_gd32f4xx.c 中 system_clock_168m_8m_hxtal() 等
预设时钟函数的写法（寄存器直接操作 + 中文注释），输出为独立的
system_clock.c，在 main() 开头显式调用即可完成时钟树配置。
"""

from .common import CodeBuilder, file_header, include_guard

# ---------------------------------------------------------------------------
# 预分频宏映射
# ---------------------------------------------------------------------------
AHB_PSC_MAP = {
    1: "RCU_AHB_CKSYS_DIV1", 2: "RCU_AHB_CKSYS_DIV2", 4: "RCU_AHB_CKSYS_DIV4",
    8: "RCU_AHB_CKSYS_DIV8", 16: "RCU_AHB_CKSYS_DIV16", 64: "RCU_AHB_CKSYS_DIV64",
    128: "RCU_AHB_CKSYS_DIV128", 256: "RCU_AHB_CKSYS_DIV256",
    512: "RCU_AHB_CKSYS_DIV512",
}
APB_PSC_MAP = {
    1: "RCU_APB1_CKAHB_DIV1", 2: "RCU_APB1_CKAHB_DIV2", 4: "RCU_APB1_CKAHB_DIV4",
    8: "RCU_APB1_CKAHB_DIV8", 16: "RCU_APB1_CKAHB_DIV16",
}
APB2_PSC_MAP = {
    1: "RCU_APB2_CKAHB_DIV1", 2: "RCU_APB2_CKAHB_DIV2", 4: "RCU_APB2_CKAHB_DIV4",
    8: "RCU_APB2_CKAHB_DIV8", 16: "RCU_APB2_CKAHB_DIV16",
}

# ---------------------------------------------------------------------------
# PLL 参数约束（来自固件库 gd32f4xx_rcu.h CHECK_PLL_*_VALID 与 RCU_PLL 寄存器位宽）
#   PLL_PSC:  BITS(0,5) —— 6 位，合法 2..63
#   PLL_N:    BITS(6,14) —— 9 位，库要求 64..500
#   PLL_P:    BITS(16,17)—— 2/4/6/8
#   PLL_Q:    BITS(24,27)—— 2..15
# ---------------------------------------------------------------------------
RCU_PLLPSC_MIN = 2
RCU_PLLPSC_MAX = 63
RCU_PLLN_MIN = 64
RCU_PLLN_MAX = 500

# 各型号 PLL VCO 典型上限（MHz）。GD32F405/407/425/427 最高 168MHz 系统时钟，
# VCO 上限 432MHz；GD32F450/470 最高 240MHz（VCO=480MHz，固件库 240m 配置 PLL_N=480 佐证）。
MCU_VCO_MAX = {
    "GD32F405": 432, "GD32F407": 432, "GD32F425": 432, "GD32F427": 432,
    "GD32F450": 480, "GD32F470": 480,
}

# APB 总线频率上限（用户手册时钟树：APB1 60MHz max，APB2 120MHz max）
APB1_MAX_MHZ = 60
APB2_MAX_MHZ = 120

# ADC 时钟上限（用户手册 14.4.2：CK_ADC 最大 40MHz）
ADC_CLK_MAX_MHZ = 40


class ClockInfo:
    """时钟树的解析结果：总线频率 + 定时器时钟倍频信息 + PLL 参数。"""

    def __init__(self, sysclk, ahb, apb1, apb2, apb1_timer, apb2_timer,
                 psc, pll_n, pll_p, pll_q, source, hxtal_mhz, vco_in_mhz,
                 warnings=None):
        self.sysclk = sysclk          # MHz
        self.ahb = ahb                # MHz
        self.apb1 = apb1              # MHz
        self.apb2 = apb2              # MHz
        self.apb1_timer = apb1_timer  # MHz（APB1 上的定时器时钟）
        self.apb2_timer = apb2_timer  # MHz（APB2 上的定时器时钟）
        self.psc = psc                # PLL 输入预分频
        self.pll_n = pll_n            # PLL 倍频
        self.pll_p = pll_p            # PLL 输出分频（系统时钟）
        self.pll_q = pll_q            # PLL Q 分频（USB/SDIO）
        self.source = source
        self.hxtal_mhz = hxtal_mhz
        self.vco_in_mhz = vco_in_mhz
        self.warnings = list(warnings or [])   # 时钟树校验警告（GUI 可展示）


def _timer_mult(apb_prescaler, use_mul4):
    """APB 预分频 + 全局 TIMERSEL 选择 -> 定时器时钟倍频数。

    依据固件库 gd32f4xx_rcu.h RCU_TIMER_PSC_MUL2 / MUL4 的说明：
      MUL2（TIMERSEL=0）：div1 -> 1x，div>=2 -> 2x；
      MUL4（TIMERSEL=1）：div1 -> 1x，div2 -> 2x，div>=4 -> 4x。
    """
    if apb_prescaler <= 1:
        return 1
    if use_mul4:
        return 4 if apb_prescaler >= 4 else 2
    return 2


def _choose_timer_mult(apb1_p, apb2_p):
    """决定全局 TIMERSEL：任一域预分频 >=8（需要 4 倍定时器时钟）时选 MUL4。"""
    return max(apb1_p, apb2_p) >= 8


def compute_clock(clock_cfg, mcu=None):
    """由时钟树配置计算各总线频率与 PLL 参数，返回 ClockInfo。

    clock_cfg 字段：
        source        IRC16M / HXTAL
        hxtal_mhz     外部晶振频率（source=HXTAL 时）
        sysclk_mhz    目标系统时钟（MHz）
        ahb_prescaler / apb1_prescaler / apb2_prescaler
        pll_n / pll_p / pll_q（可选，缺省自动计算）
    mcu：芯片型号（如 GD32F470），用于按型号校验 VCO 上限；缺省用 432MHz 保守值。
    """
    warnings = []
    source = clock_cfg.get("source", "HXTAL")
    hxtal = int(clock_cfg.get("hxtal_mhz", 8))
    sysclk = int(clock_cfg.get("sysclk_mhz", 168))
    ahb_p = int(clock_cfg.get("ahb_prescaler", 1))
    apb1_p = int(clock_cfg.get("apb1_prescaler", 4))
    apb2_p = int(clock_cfg.get("apb2_prescaler", 2))

    vco_max = MCU_VCO_MAX.get(mcu, 432) if mcu else 432

    # 源时钟频率与 PLL 输入预分频（与库约定一致：预分频后 VCO 输入恒为 1MHz）
    if source == "IRC16M":
        src_mhz, psc = 16, 16
    else:
        src_mhz, psc = hxtal, hxtal
    vco_in = src_mhz / psc  # 恒为 1.0

    # PLL_PSC 合法范围校验（2..63）
    if not (RCU_PLLPSC_MIN <= psc <= RCU_PLLPSC_MAX):
        warnings.append("PLL 输入预分频 %d 超出合法范围 %d..%d（晶振 %dMHz 无法分频到 1MHz VCO 输入）"
                        % (psc, RCU_PLLPSC_MIN, RCU_PLLPSC_MAX, src_mhz))

    # 是否需要 PLL（直接使用源时钟时不启用）
    use_pll = not (source == "IRC16M" and sysclk == 16) and \
              not (source == "HXTAL" and sysclk == hxtal)

    pll_n = pll_p = pll_q = None
    if use_pll:
        # 选最小的 P（2/4/6/8），使 N = sysclk*P 同时满足：
        #   库约束 64 <= N <= 500，且 VCO(=N*1MHz) 不超过本型号上限
        pll_p = clock_cfg.get("pll_p")
        if pll_p is None:
            for p in (2, 4, 6, 8):
                n = sysclk * p
                if RCU_PLLN_MIN <= n <= RCU_PLLN_MAX and n <= vco_max:
                    pll_p = p
                    break
            if pll_p is None:
                pll_p = 2
                warnings.append(
                    "目标 %dMHz 在 %s 上找不到满足约束的 PLL 配置"
                    "（需 PLL_N∈[%d,%d] 且 VCO≤%dMHz），已按 PLL_P=2 生成，请核对/手填 pll_n/pll_p"
                    % (sysclk, mcu or "未知型号", RCU_PLLN_MIN, RCU_PLLN_MAX, vco_max))
        vco = sysclk * pll_p
        # VCO = vco_in * N  =>  N = VCO / vco_in
        pll_n = clock_cfg.get("pll_n") or int(round(vco / vco_in))
        # Q 默认取 VCO/48（USB 需要 48MHz），限制在 2..15
        pll_q = clock_cfg.get("pll_q")
        if pll_q is None:
            pll_q = min(15, max(2, int(round(vco / 48))))
        if not (RCU_PLLN_MIN <= pll_n <= RCU_PLLN_MAX):
            warnings.append("PLL_N=%d 超出固件库合法范围 %d..%d，生成的 PLL 配置不可靠"
                            % (pll_n, RCU_PLLN_MIN, RCU_PLLN_MAX))
        if vco > vco_max:
            warnings.append("PLL VCO 频率 %dMHz 超过 %s 的典型上限 %dMHz，请降低目标频率或检查 pll_n/pll_p"
                            % (vco, mcu or "当前型号", vco_max))

    # 总线频率
    ahb = sysclk // ahb_p
    apb1 = ahb // apb1_p
    apb2 = ahb // apb2_p
    if apb1 > APB1_MAX_MHZ:
        warnings.append("APB1 频率 %dMHz 超过上限 %dMHz（用户手册），请增大 APB1 分频"
                        % (apb1, APB1_MAX_MHZ))
    if apb2 > APB2_MAX_MHZ:
        warnings.append("APB2 频率 %dMHz 超过上限 %dMHz（用户手册），请增大 APB2 分频"
                        % (apb2, APB2_MAX_MHZ))

    # 定时器时钟倍频：先定全局 TIMERSEL，再按各域预分频计算（与生成代码一致）
    use_mul4 = _choose_timer_mult(apb1_p, apb2_p)
    apb1_timer = apb1 * _timer_mult(apb1_p, use_mul4)
    apb2_timer = apb2 * _timer_mult(apb2_p, use_mul4)

    return ClockInfo(sysclk=sysclk, ahb=ahb, apb1=apb1, apb2=apb2,
                     apb1_timer=apb1_timer, apb2_timer=apb2_timer,
                     psc=psc, pll_n=pll_n, pll_p=pll_p, pll_q=pll_q,
                     source=source, hxtal_mhz=hxtal, vco_in_mhz=vco_in,
                     warnings=warnings)


# ---------------------------------------------------------------------------
# 代码生成
# ---------------------------------------------------------------------------
def generate_clock(clock_cfg, mcu=None):
    """生成 system_clock.c / system_clock.h，返回 {文件名: 内容}。"""
    files = {}
    files["system_clock.c"] = generate_clock_c(clock_cfg, mcu)
    h = CodeBuilder()
    guard = include_guard("system_clock_h")
    h.line(file_header("system_clock.h", "系统时钟配置函数声明"))
    h.line("#ifndef %s" % guard)
    h.line("#define %s" % guard)
    h.line()
    h.line('#include "gd32f4xx.h"')
    h.line()
    h.line("/* 按配置的时钟树配置系统时钟（RCU / PLL），在 main() 开头调用 */")
    h.line("void system_clock_config(void);")
    h.line()
    h.line("#endif /* %s */" % guard)
    files["system_clock.h"] = str(h)
    return files


def generate_clock_c(clock_cfg, mcu=None):
    """生成 system_clock.c 的完整内容（含文件头）。"""
    info = compute_clock(clock_cfg, mcu)
    src = clock_cfg.get("source", "HXTAL")
    b = CodeBuilder()

    b.line(license_and_header("system_clock.c",
                              "系统时钟初始化（根据时钟树配置生成）"))
    # 时钟树校验警告写入生成文件，便于直接在工程里看到
    if info.warnings:
        b.line("/* 时钟配置检查警告：")
        for w in info.warnings:
            b.line(" *   - %s" % w)
        b.line(" */")
        b.line()
    b.line('#include "gd32f4xx.h"')
    b.line()
    b.line("/*!")
    b.line("    \\brief      system clock configuration function")
    b.line("    \\param[in]  none")
    b.line("    \\param[out] none")
    b.line("    \\retval     none")
    b.line("*/")
    b.line("void system_clock_config(void)")
    b.line("{")
    b.inc()
    b.line("uint32_t timeout = 0U;")
    b.line("__IO uint32_t reg_temp;")
    b.line()

    # ---- 使能并等待时钟源 ----
    if src == "HXTAL":
        b.comment("使能外部高速晶振 HXTAL")
        b.line("RCU_CTL |= RCU_CTL_HXTALEN;")
        b.line("/* 等待 HXTAL 稳定（超时则进入死循环，避免在错误的时钟源上运行 */")
        b.empty_block("while((0U == (RCU_CTL & RCU_CTL_HXTALSTB)) && (HXTAL_STARTUP_TIMEOUT != timeout++))")
        b.line("/* 若启动超时说明晶振未起振，原地死循环便于调试 */")
        b.line("if(0U == (RCU_CTL & RCU_CTL_HXTALSTB)) {")
        b.inc()
        b.empty_block("while(0U == (RCU_CTL & RCU_CTL_HXTALSTB))")
        b.dec()
        b.line("}")
    else:
        b.comment("使能内部高速振荡器 IRC16M")
        b.line("RCU_CTL |= RCU_CTL_IRC16MEN;")
        b.line("/* 等待 IRC16M 稳定（若超时则死循环） */")
        b.line("uint32_t stab_flag = 0U;")
        b.line("do {")
        b.inc()
        b.line("timeout++;")
        b.line("stab_flag = (RCU_CTL & RCU_CTL_IRC16MSTB);")
        b.dec()
        b.line("} while((0U == stab_flag) && (IRC16M_STARTUP_TIMEOUT != timeout));")
        b.line("if(0U == (RCU_CTL & RCU_CTL_IRC16MSTB)) {")
        b.inc()
        b.empty_block("while(1)")
        b.dec()
        b.line("}")

    # ---- PMU 调压器 ----
    if info.pll_n is not None:
        b.line()
        b.comment("使能 PMU 时钟并配置调压器电压标尺（PLL 高频运行必需）")
        b.line("RCU_APB1EN |= RCU_APB1EN_PMUEN;")
        b.line("PMU_CTL |= PMU_CTL_LDOVS;")

    # ---- AHB/APB 预分频 ----
    b.line()
    b.comment("配置 AHB / APB1 / APB2 预分频")
    b.line("RCU_CFG0 |= %s;" % AHB_PSC_MAP[clock_cfg.get("ahb_prescaler", 1)])
    b.line("RCU_CFG0 |= %s;" % APB_PSC_MAP[clock_cfg.get("apb1_prescaler", 4)])
    b.line("RCU_CFG0 |= %s;" % APB2_PSC_MAP[clock_cfg.get("apb2_prescaler", 2)])

    # ---- 定时器时钟倍频 ----
    apb1_p = int(clock_cfg.get("apb1_prescaler", 4))
    apb2_p = int(clock_cfg.get("apb2_prescaler", 2))
    if _choose_timer_mult(apb1_p, apb2_p):
        b.line()
        b.comment("APB 预分频较大，定时器时钟取 4 倍 APB（RCU_CFG1.TIMERSEL）")
        b.line("rcu_timer_clock_prescaler_config(RCU_TIMER_PSC_MUL4);")
    elif max(apb1_p, apb2_p) > 1:
        b.line()
        b.comment("定时器时钟取 2 倍 APB（APB 预分频为 2 或 4）")
        b.line("rcu_timer_clock_prescaler_config(RCU_TIMER_PSC_MUL2);")

    # ---- PLL ----
    if info.pll_n is not None:
        b.line()
        b.box_comment([
            "配置主 PLL：",
            "  PLL_PSC = %d（源 %dMHz 分频为 1MHz VCO 输入）" % (info.psc, info.vco_in_mhz * info.psc),
            "  PLL_N   = %d（VCO = 1MHz * %d = %dMHz）" % (info.pll_n, info.pll_n, info.pll_n),
            "  PLL_P   = %d（系统时钟 = VCO/%d = %dMHz）" % (info.pll_p, info.pll_p, info.sysclk),
            "  PLL_Q   = %d（USB/SDIO 时钟 = VCO/%d = %dMHz）" % (info.pll_q, info.pll_q, info.pll_n // info.pll_q),
        ])
        pllsrc = "RCU_PLLSRC_HXTAL" if src == "HXTAL" else "RCU_PLLSRC_IRC16M"
        b.line("RCU_PLL = (%dU | (%dU << 6U) | (((%dU >> 1U) - 1U) << 16U) |" %
               (info.psc, info.pll_n, info.pll_p))
        b.line("               (%s) | (%dU << 24U));" % (pllsrc, info.pll_q))
        b.line()
        b.comment("使能 PLL 并等待其稳定")
        b.line("RCU_CTL |= RCU_CTL_PLLEN;")
        b.empty_block("while(0U == (RCU_CTL & RCU_CTL_PLLSTB))")

        # high-drive
        if info.sysclk >= 120:
            b.line()
            b.comment("使能 high-drive 以支持 %dMHz 以上频率" % info.sysclk)
            b.line("PMU_CTL |= PMU_CTL_HDEN;")
            b.empty_block("while(0U == (PMU_CS & PMU_CS_HDRF))")
            b.comment("切换到 high-drive 模式")
            b.line("PMU_CTL |= PMU_CTL_HDS;")
            b.empty_block("while(0U == (PMU_CS & PMU_CS_HDSRF))")

    # ---- 选择系统时钟源 ----
    b.line()
    if info.pll_n is not None:
        sel, selstat = "RCU_CKSYSSRC_PLLP", "RCU_SCSS_PLLP"
        b.comment("选择 PLL 输出 PLLP 作为系统时钟")
    elif src == "HXTAL":
        sel, selstat = "RCU_CKSYSSRC_HXTAL", "RCU_SCSS_HXTAL"
        b.comment("选择 HXTAL 直接作为系统时钟")
    else:
        sel, selstat = "RCU_CKSYSSRC_IRC16M", "RCU_SCSS_IRC16M"
        b.comment("选择 IRC16M 直接作为系统时钟")
    b.line("reg_temp = RCU_CFG0;")
    b.line("reg_temp &= ~RCU_CFG0_SCS;")
    b.line("reg_temp |= %s;" % sel)
    b.line("RCU_CFG0 = reg_temp;")
    b.empty_block("while(0U == (RCU_CFG0 & %s))" % selstat)

    b.dec()
    b.line("}")
    return str(b)


def license_and_header(filename, brief):
    """复用 common 里的文件头。"""
    from .common import file_header
    return file_header(filename, brief)


# 供其它模块使用
def timer_clock_comment(info):
    """返回给外设注释用的定时器时钟信息文本。"""
    return "TIMER 时钟(APB1):%dMHz, APB2:%dMHz" % (info.apb1_timer, info.apb2_timer)
