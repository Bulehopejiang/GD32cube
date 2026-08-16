# -*- coding: utf-8 -*-
"""公共输出辅助：代码生成器、文件头、C 语法工具。"""

# ---------------------------------------------------------------------------
# 与固件库一致的 GigaDevice 许可证头（精简版，与库中风格保持一致）
# ---------------------------------------------------------------------------
LICENSE_HEADER = """/*
    Copyright (c) 2026, GigaDevice Semiconductor Inc.

    Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice, this
       list of conditions and the following disclaimer.
    2. Redistributions in binary form must reproduce the above copyright notice,
       this list of conditions and the following disclaimer in the documentation
       and/or other materials provided with the distribution.
    3. Neither the name of the copyright holder nor the names of its contributors
       may be used to endorse or promote products derived from this software without
       specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY
OF SUCH DAMAGE.
*/"""


def file_header(filename, brief):
    """生成与库风格一致的文件头（含简短说明 + 许可证头）。"""
    return (
        "/*!\n"
        "    \\file    %s\n"
        "    \\brief   %s\n"
        "\n"
        "    \\note    本文件由 GD32Cube 自动生成，请勿手动修改；重新生成时会被覆盖。\n"
        "    \\note    GD32Cube: 类 CubeMX 的 GD32 初始化代码生成工具。\n"
        "*/\n\n%s\n" % (filename, brief, LICENSE_HEADER)
    )


# GD32 固件库 V3.3.3 的 CMSIS 未定义 __WEAK，这里自行兼容各编译器。
# Keil AC5 用 __weak；AC6 / GCC 用 __attribute__((weak))。
WEAK_FALLBACK = (
    "#ifndef __WEAK\n"
    "/* 弱符号宏：兼容 Keil AC5(__weak) / AC6 / GCC(__attribute__((weak))) */\n"
    "#if defined(__CC_ARM)\n"
    "#define __WEAK __weak\n"
    "#elif defined(__GNUC__)\n"
    "#define __WEAK __attribute__((weak))\n"
    "#else\n"
    "#define __WEAK\n"
    "#endif\n"
    "#endif\n"
)


def emit_weak_fallback(b):
    """在 CodeBuilder 当前输出中追加 __WEAK 兼容宏块。"""
    for ln in WEAK_FALLBACK.strip("\n").split("\n"):
        b.line(ln)
    b.line()


class CodeBuilder:
    """C 代码构建器：按缩进级别收集行，便于生成结构化代码。"""

    def __init__(self, indent="    "):
        self._lines = []
        self._level = 0
        self._indent = indent

    # -- 基础输出 ----------------------------------------------------------
    def line(self, text=""):
        """输出一行代码；text 为空输出空行。"""
        if text:
            self._lines.append(self._indent * self._level + text)
        else:
            self._lines.append("")
        return self

    def raw(self, text):
        """输出一行不做缩进处理的原文（用于已带缩进的多行块）。"""
        for ln in text.split("\n"):
            self._lines.append(ln)
        return self

    def inc(self):
        """缩进级别 +1。"""
        self._level += 1
        return self

    def dec(self):
        """缩进级别 -1。"""
        self._level = max(0, self._level - 1)
        return self

    # -- 注释 ---------------------------------------------------------------
    def comment(self, text):
        """行内/整行注释：/* ... */。"""
        self.line("/* " + text + " */")
        return self

    def box_comment(self, lines):
        """多行框注释（每行带星号，匹配库风格）。"""
        self.line("/* ---------------------------------------")
        for ln in lines:
            self.line(ln)
        self.line("--------------------------------------- */")
        return self

    def doc_func(self, name, brief="", params="none", retval="none"):
        """函数 doc 注释块（/*! ... */ 风格，与库一致）。

        name:   函数名（显示在 \\brief 首位）
        brief:  功能说明（拼接在 \\brief 后）
        params: \\param[in] 内容，默认 none
        """
        self.line("/*!")
        if brief:
            self.line("    \\brief      %s —— %s" % (name, brief))
        else:
            self.line("    \\brief      %s" % name)
        self.line("    \\param[in]  %s" % params)
        self.line("    \\param[out] none")
        self.line("    \\retval     %s" % retval)
        self.line("*/")
        return self

    # -- 代码块 ---------------------------------------------------------------
    def block(self, header, body_lines):
        """{} 代码块；body_lines 可为 list 或 CodeBuilder。"""
        self.line(header + " {")
        if isinstance(body_lines, CodeBuilder):
            self.raw(str(body_lines))
        else:
            self.inc()
            for ln in body_lines:
                self.line(ln)
            self.dec()
        self.line("}")
        return self

    def empty_block(self, header):
        """空 {} 代码块（用于空 while/if 循环体）。"""
        self.line(header + " {")
        self.inc()
        self.line("")
        self.dec()
        self.line("}")
        return self

    def c_comment(self, text):
        """整行 C 注释，支持多行文本用 \n 分隔。"""
        for ln in text.split("\n"):
            self.line("/* " + ln + " */")
        return self

    def __str__(self):
        return "\n".join(self._lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 命名辅助
# ---------------------------------------------------------------------------
def func_name(prefix, periph):
    """生成 CubeMX 风格函数名，如 MX_USART0_Init / MX_TIMER1_Init。"""
    return "MX_%s_%s" % (periph.upper(), prefix)


def include_guard(identifier):
    """生成头文件 include guard。"""
    return identifier.upper().replace(".", "_").replace("-", "_")
