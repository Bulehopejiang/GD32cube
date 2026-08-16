# -*- coding: utf-8 -*-
"""代码生成流程：由配置 dict 运行各生成器，写出全部源文件。

GUI（gd32_cubemx_gui.py）通过 generate_from_cfg() 使用本模块。
"""

import os
import re

from . import context
from . import (clock, gpio_gen, usart_gen, timer_gen, adc_gen,
               spi_gen, i2c_gen, can_gen, dma_gen, dac_gen,
               exti_gen, misc_gen, it_gen, systick_gen, main_gen,
               libopt_gen)


def _build_from_cfg(cfg):
    """由配置 dict 运行所有生成器，返回填充好的 GenContext。"""
    ctx = context.GenContext(cfg)

    # 外设生成（顺序影响 main.c 里 MX_xxx_Init() 的调用顺序）
    gen_funcs = [
        usart_gen.generate_usart,   # USART
        timer_gen.generate_timer,   # TIMER
        adc_gen.generate_adc,       # ADC
        spi_gen.generate_spi,       # SPI
        i2c_gen.generate_i2c,       # I2C
        can_gen.generate_can,       # CAN
        dma_gen.generate_dma,       # DMA
        dac_gen.generate_dac,       # DAC
        exti_gen.generate_exti,     # EXTI
        misc_gen.generate_misc,     # FWDGT/RTC/CRC/TRNG/PMU
    ]
    for gen in gen_funcs:
        try:
            files = gen(ctx)
        except Exception as exc:  # noqa: BLE001 —— 单外设失败不阻断其它
            ctx.warn("外设生成器 %s 出错：%s" % (gen.__name__, exc))
            files = {}
        for name, content in files.items():
            ctx.add_file(name, content)

    # 组装类文件（依赖上面收集到的 GPIO 复用 / NVIC / 中断信息）
    for name, content in clock.generate_clock(cfg["project"]["clock"], mcu=ctx.mcu).items():
        ctx.add_file(name, content)
    for name, content in gpio_gen.generate_gpio(ctx).items():
        ctx.add_file(name, content)
    for name, content in systick_gen.generate_systick(ctx).items():
        ctx.add_file(name, content)
    for name, content in it_gen.generate_it(ctx).items():
        ctx.add_file(name, content)
    for name, content in libopt_gen.generate_libopt(ctx).items():
        ctx.add_file(name, content)
    for name, content in main_gen.generate_main(ctx).items():
        ctx.add_file(name, content)
    return ctx


def generate_from_cfg(cfg, outdir, warnings=None):
    """由配置 dict 直接生成代码到 outdir，返回生成的文件数。

    warnings：可选 list，生成过程中的警告会追加进去（GUI 用它展示给用户）。
    """
    ctx = _build_from_cfg(cfg)
    write_output(ctx, outdir)
    if warnings is not None:
        warnings.extend(ctx.warnings)
    return len(ctx.files)


_MANIFEST_NAME = ".gd32cube_manifest.json"


def write_output(ctx, outdir):
    """把 ctx.files 写到输出目录；已存在的文件保留 USER CODE 区块。

    同时维护生成文件清单（.gd32cube_manifest.json）：上一轮生成过、本轮不再
    生成的文件会被删除；若该文件已被手动修改过（内容哈希与清单不符），则保留
    并给出警告，避免误删用户自己接管的内容。
    """
    import hashlib
    import json
    os.makedirs(outdir, exist_ok=True)
    manifest_path = os.path.join(outdir, _MANIFEST_NAME)

    # 读取上一轮清单
    old_manifest = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                old_manifest = json.load(f)
        except Exception:
            old_manifest = {}

    new_manifest = {}
    for name, content in ctx.files.items():
        path = os.path.join(outdir, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                old = f.read()
            content = _restore_user_blocks(old, content)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        new_manifest[name] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        print("生成: %s" % os.path.normpath(path))

    # 清理本轮不再生成的文件（仅限上一轮清单登记过的）
    for name, old_hash in old_manifest.items():
        if name in new_manifest:
            continue
        path = os.path.join(outdir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            cur = f.read()
        if hashlib.sha256(cur.encode("utf-8")).hexdigest() == old_hash:
            os.remove(path)
            print("清理废弃文件: %s" % os.path.normpath(path))
        else:
            ctx.warn("文件 %s 上一轮由本工具生成但已被手动修改，本轮不再生成，已保留未删除"
                     % name)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=1)


_USER_BLOCK_RE = re.compile(
    r"(/\* USER CODE BEGIN ([A-Za-z0-9_]+) \*/)(.*?)(/\* USER CODE END \2 \*/)",
    re.DOTALL)


def _restore_user_blocks(old_content, new_content):
    """把旧文件里的 USER CODE 区块回填到新内容。

    两条规则：
    1. 标记与模板一致（如 while、2）→ 直接替换模板中的空块；
    2. 用户自己放置的标记（模板里没有）→ 依据它前面最近的稳定代码行
       （锚点）重新插入到新文件对应位置，避免重新生成时丢失。
    """
    result = new_content

    # 规则 1：模板已知标记，原地替换
    for m in _USER_BLOCK_RE.finditer(old_content):
        tag = m.group(2)
        preserved = m.group(3)
        nm = _find_block(result, tag)
        if nm and preserved.strip():
            result = result[:nm.start()] + nm.group(1) + preserved + nm.group(3) + result[nm.end():]

    # 规则 2：用户自定义标记，锚点定位后插入
    for m in _USER_BLOCK_RE.finditer(old_content):
        tag = m.group(2)
        if not m.group(3).strip():
            continue  # 空块没有用户内容，不必保留（避免残留无意义标记）
        if _find_block(result, tag):
            continue  # 规则 1 已处理
        anchor = _find_anchor(old_content, m.start(), result)
        if anchor is None:
            print("警告：无法定位用户代码块 %s 的位置，未自动保留。内容：\n%s"
                  % (tag, m.group(0)))
            continue
        line_end = result.find("\n", anchor)
        if line_end == -1:
            line_end = len(result)
        # 缩进对齐锚点行，避免插出来的块顶格
        line_start = result.rfind("\n", 0, anchor) + 1
        indent = result[line_start:anchor]
        body = m.group(3)
        if body.startswith("\n"):
            body = body[1:]
        block = ("\n" + indent + "/* USER CODE BEGIN %s */\n" % tag
                 + body.rstrip("\n ") + "\n" + indent + "/* USER CODE END %s */" % tag)
        result = result[:line_end] + block + result[line_end:]
    return result


def _find_block(content, tag):
    """在新内容里找同标签的 USER CODE 块。"""
    return re.search(
        r"(/\* USER CODE BEGIN %s \*/)(.*?)(/\* USER CODE END %s \*/)"
        % (re.escape(tag), re.escape(tag)), content, re.DOTALL)


def _is_in_comment(text, pos):
    """判断 text 中 pos 位置是否处于 /* */ 块注释或 // 行注释内。

    只做注释边界扫描（不解析字符串字面量），用于 USER CODE 锚点重插入时
    避免把代码块插进注释里（否则会产生悬空 */，导致生成文件编译报错）。
    """
    i, n = 0, len(text)
    in_block = in_line = False
    while i < n and i < pos:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
        elif in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 1
        else:
            if c == "/" and nxt == "*":
                in_block = True
                i += 1
            elif c == "/" and nxt == "/":
                in_line = True
                i += 1
        i += 1
    return in_block or in_line


def _find_anchor(old_content, block_start, new_content):
    """找旧文件里用户块前最近的稳定代码行，且该行在新内容中唯一出现、不在注释内。

    返回该锚点行在新内容中的起始下标；找不到返回 None。
    """
    before = old_content[:block_start]
    for line in reversed(before.split("\n")):
        ls = line.strip()
        if not ls or ls.startswith("/*") or ls.startswith("*") or ls.startswith("//"):
            continue
        # 该行须在新内容中只出现一次，避免插错位置
        if new_content.count(ls) == 1:
            pos = new_content.find(ls)
            if not _is_in_comment(new_content, pos):
                return pos
        # 若多行相同，尝试附带缩进的行文本（更精确）
        if line and new_content.count(line.rstrip("\r")) == 1:
            pos = new_content.find(line.rstrip("\r"))
            if not _is_in_comment(new_content, pos):
                return pos
    return None
