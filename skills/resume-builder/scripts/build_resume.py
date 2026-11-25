#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_resume.py — 把 resume.json 渲染成中文一页纸简历 .docx

零第三方依赖：只用 Python 标准库（zipfile / zlib / struct / json / re）。
任何能跑 python3 的 agent 环境都能执行，不需要 Word、LibreOffice、node。

三个子命令：

    python3 build_resume.py preview resume.json          # 输出 Markdown 草稿，给人过目
    python3 build_resume.py check   resume.json          # 输出 JSON 体检报告，给 agent 读
    python3 build_resume.py build   resume.json -o 简历.docx

通用参数： --theme 1F3864  --cjk-font 微软雅黑  --latin-font Calibri  --slant forward|back
"""

import argparse
import json
import math
import os
import re
import struct
import sys
import zipfile
import zlib

# ---------------------------------------------------------------- 单位换算
TWIPS_PER_CM = 566.929133858
EMU_PER_CM = 360000


def cm(v):
    return int(round(v * TWIPS_PER_CM))


def pt(v):
    return int(round(v * 20))


# ---------------------------------------------------------------- 版面常量
PAGE_W = 11906          # A4 宽（twips）
PAGE_H = 16838          # A4 高
M_L = M_R = cm(2.0)
M_T = cm(1.6)
M_B = cm(1.5)
TEXT_W = PAGE_W - M_L - M_R      # 9638 twips ≈ 17.0cm

SIZE_NAME = 20
SIZE_META = 9.5
SIZE_BODY = 10.5
SIZE_DATE = 9
SIZE_TITLE = 11

LINE_BODY = 280          # 正文行距（exact, twips = 14pt）
LINE_OVERVIEW = 290
LINE_DATE = 250

H_TITLE_ROW = 340        # 模块标题色块高度
W_TITLE_BLOCK_CM = 3.6   # 色块宽度
W_TITLE_SLANT_CM = 0.25  # 斜切横向进深
W_TITLE_BLOCK = cm(W_TITLE_BLOCK_CM)
W_TITLE_SLANT = cm(W_TITLE_SLANT_CM)

COLOR_TEXT = "1A1A1A"
COLOR_MUTED = "595959"
COLOR_SOFT = "333333"
COLOR_LINE = "D9D9D9"


# ---------------------------------------------------------------- 富文本
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_rich(text):
    """把 '前**中**后' 拆成 [(片段, 是否加粗), ...]"""
    out = []
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out or [("", False)]


def xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def em_width(s):
    """估算文本宽度，单位 em。CJK 记 1.0，拉丁字母数字约 0.55。"""
    total = 0.0
    for ch in s:
        o = ord(ch)
        if o < 0x2E80:
            if ch == " ":
                total += 0.30
            elif ch.isdigit():
                total += 0.56
            elif ch.isupper():
                total += 0.62
            else:
                total += 0.52
        else:
            total += 1.0
    return total


def est_lines(text, avail_twips, size_pt):
    if not text.strip():
        return 1
    width = em_width(text) * size_pt * 20
    return max(1, int(math.ceil(width / avail_twips)))


# ---------------------------------------------------------------- PNG 生成
def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png(width, height, rgba):
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def make_slant_png(w_cm, h_cm, hex_color, forward=True, dpi=600, ss=4):
    """生成右斜切三角块（透明底 + 主题色实心）。

    forward=True  底边向右延伸（"／"），false 顶边向右延伸（"＼"）。
    """
    w = max(2, int(round(w_cm / 2.54 * dpi)))
    h = max(2, int(round(h_cm / 2.54 * dpi)))
    r, g, b = _rgb(hex_color)
    px = bytearray(w * h * 4)

    for y in range(h):
        for x in range(w):
            hits = 0
            for sy in range(ss):
                yy = (y + (sy + 0.5) / ss) / h
                edge = yy if forward else (1.0 - yy)
                for sx in range(ss):
                    xx = (x + (sx + 0.5) / ss) / w
                    if xx <= edge:
                        hits += 1
            if hits:
                a = int(round(255 * hits / (ss * ss)))
                i = (y * w + x) * 4
                px[i:i + 4] = bytes((r, g, b, a))
    return _png(w, h, px)


def luminance(hex_color):
    r, g, b = _rgb(hex_color)
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


# ---------------------------------------------------------------- OOXML 片段
def rpr(size=None, bold=False, color=None, cjk=None, latin=None, spacing=None):
    parts = []
    if cjk or latin:
        parts.append('<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>'
                     % (latin or cjk, latin or cjk, cjk or latin, latin or cjk))
    if bold:
        parts.append("<w:b/><w:bCs/>")
    if color:
        parts.append('<w:color w:val="%s"/>' % color)
    if spacing:
        parts.append('<w:spacing w:val="%d"/>' % spacing)
    if size:
        parts.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size * 2, size * 2))
    return "<w:rPr>%s</w:rPr>" % "".join(parts) if parts else ""


def run(text, **kw):
    attrs = ' xml:space="preserve"' if text[:1] == " " or text[-1:] == " " else ""
    return '<w:r>%s<w:t%s>%s</w:t></w:r>' % (rpr(**kw), attrs, xml_escape(text))


def rich_runs(text, **kw):
    base_bold = kw.pop("bold", False)
    out = []
    for seg, bold in parse_rich(text):
        if seg:
            out.append(run(seg, bold=(base_bold or bold), **dict(kw)))
    return "".join(out)


def para(inner, style="", before=0, after=0, line=None, rule="exact",
         left=0, hanging=0, right=0, tabs=None, jc=None, mark_size=None):
    p = []
    if style:
        p.append(style)
    if tabs:
        p.append("<w:tabs>%s</w:tabs>" % "".join(
            '<w:tab w:val="%s" w:pos="%d"/>' % (v, pos) for v, pos in tabs))
    sp = ['w:before="%d"' % before, 'w:after="%d"' % after]
    if line:
        sp += ['w:line="%d"' % line, 'w:lineRule="%s"' % rule]
    p.append("<w:spacing %s/>" % " ".join(sp))
    if left or hanging or right:
        p.append('<w:ind w:left="%d" w:right="%d" w:hanging="%d"/>' % (left, right, hanging))
    if jc:
        p.append('<w:jc w:val="%s"/>' % jc)
    if mark_size:
        p.append('<w:rPr><w:sz w:val="%d"/></w:rPr>' % (mark_size * 2))
    return "<w:p><w:pPr>%s</w:pPr>%s</w:p>" % ("".join(p), inner)


IMAGE_RID = "rIdImg1"


def inline_image(rid, cx, cy, pic_id, name):
    return (
        '<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="%d" name="%s"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing>'
        % (cx, cy, pic_id, name, pic_id, name, rid, cx, cy))


def section_header(title, ctx):
    """主题色右斜切色块 + 通栏浅灰细线。"""
    w_block, w_slant = W_TITLE_BLOCK, W_TITLE_SLANT
    w_rest = TEXT_W - w_block - w_slant
    h = H_TITLE_ROW

    def tc(width, inner, extra=""):
        return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>%s</w:tc>'
                % (width, extra, inner))

    block_p = para(
        rich_runs(title, size=SIZE_TITLE, bold=True, color=ctx["title_text"],
                  cjk=ctx["cjk"], latin=ctx["latin"], spacing=6),
        left=cm(0.3), line=H_TITLE_ROW)
    slant_p = para(
        '<w:r>%s</w:r>' % inline_image(IMAGE_RID, int(round(W_TITLE_SLANT_CM * EMU_PER_CM)),
                                       H_TITLE_ROW * 635, ctx["pic_id"], "slant"),
        line=H_TITLE_ROW, mark_size=1)

    return (
        '<w:tbl><w:tblPr>'
        '<w:tblW w:w="%d" w:type="dxa"/><w:jc w:val="left"/><w:tblInd w:w="0" w:type="dxa"/>'
        '<w:tblBorders>'
        '<w:top w:val="nil"/><w:left w:val="nil"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="%s"/>'
        '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/>'
        '</w:tblBorders>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="0" w:noVBand="0"/>'
        '</w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="%d"/><w:gridCol w:w="%d"/><w:gridCol w:w="%d"/></w:tblGrid>'
        '<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="%d" w:hRule="exact"/></w:trPr>'
        '%s%s%s'
        '</w:tr></w:tbl>'
        % (TEXT_W, COLOR_LINE, w_block, w_slant, w_rest, h,
           tc(w_block, block_p,
              '<w:shd w:val="clear" w:color="auto" w:fill="%s"/><w:vAlign w:val="center"/>'
              % ctx["theme"]),
           tc(w_slant, slant_p),
           tc(w_rest, para("", line=H_TITLE_ROW, mark_size=1)))
    )


def spacer(height_twips):
    return para("", line=height_twips, mark_size=1)


# ---------------------------------------------------------------- 数据规整
def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def s(v):
    return ("" if v is None else str(v)).strip()


def fmt_range(start, end):
    def norm(x):
        x = s(x)
        if not x:
            return ""
        x = x.replace("-", ".").replace("/", ".")
        m = re.match(r"^(\d{4})\.?(\d{1,2})?$", x)
        if m:
            return "%s年%s月" % (m.group(1), (m.group(2) or "01").zfill(2))
        return x
    a, b = norm(start), norm(end)
    if a and b:
        return "%s - %s" % (a, b)
    return a or b


def opt(data, key, default=None):
    return (data.get("options") or {}).get(key, default)


# ---------------------------------------------------------------- 渲染
def render(data, ctx):
    out = []
    name = s(data.get("name")) or "姓名"
    headline = s(data.get("headline"))
    contact = [s(x) for x in as_list(data.get("contact")) if s(x)]

    # ---- 抬头
    head = run(name, size=SIZE_NAME, bold=True, color=ctx["theme"],
               cjk=ctx["cjk"], latin=ctx["latin"], spacing=10)
    if headline:
        head += '<w:r><w:tab/></w:r>'
        head += run(headline, size=10, bold=True, color=COLOR_MUTED,
                    cjk=ctx["cjk"], latin=ctx["latin"])
    out.append(para(head, after=30, line=520, tabs=[("right", TEXT_W)]))
    if contact:
        out.append(para(
            run("  ·  ".join(contact), size=SIZE_META, color=COLOR_MUTED,
                cjk=ctx["cjk"], latin=ctx["latin"]),
            after=60, line=260, tabs=[("right", TEXT_W)]))

    edu = as_list(data.get("education"))
    exp = as_list(data.get("experience"))
    prj = as_list(data.get("projects"))
    skills = as_list(data.get("skills"))

    order = opt(data, "section_order")
    if not order:
        fulltime = any(s(e.get("type")).lower() in ("fulltime", "full-time", "工作")
                       for e in exp)
        order = (["experience", "projects", "education", "skills"] if fulltime
                 else ["education", "experience", "projects", "skills"])

    has_exp = any(s(e.get("type")).lower() in ("fulltime", "full-time", "工作") for e in exp)

    def exp_title():
        custom = opt(data, "experience_title")
        if custom:
            return custom
        if not exp:
            return "工作经历"
        return "工作经历" if has_exp and not any(
            s(e.get("type")).lower() in ("intern", "internship", "实习") for e in exp
        ) else ("实习经历" if not has_exp else "实习与工作经历")

    emitted = 0
    for key in order:
        blocks = []
        if key == "education" and edu:
            for e in edu:
                blocks.append(edu_block(e, ctx))
        elif key == "experience" and exp:
            for e in exp:
                blocks.append(exp_block(e, ctx))
        elif key == "projects" and prj:
            for p in prj:
                blocks.append(project_block(p, ctx))
        elif key == "skills" and skills:
            blocks.append(skills_block(skills, ctx))
        if not blocks:
            continue
        title = {"education": "教育经历", "experience": exp_title(),
                 "projects": "项目经历", "skills": "专业技能"}[key]
        out.append(spacer(240 if emitted else 140))
        out.append(section_header(title, ctx))
        out.append("".join(blocks))
        emitted += 1

    return "".join(out)


def edu_block(e, ctx):
    school, major = s(e.get("school")), s(e.get("major"))
    degree, date = s(e.get("degree")), fmt_range(e.get("start"), e.get("end"))
    tabs = [("left", cm(4.4)), ("left", cm(10.0)), ("right", TEXT_W)]

    line = (run(school, size=SIZE_BODY, bold=True, cjk=ctx["cjk"], latin=ctx["latin"])
            + '<w:r><w:tab/></w:r>'
            + run(major, size=SIZE_BODY, bold=True, cjk=ctx["cjk"], latin=ctx["latin"])
            + '<w:r><w:tab/></w:r>'
            + run(degree, size=SIZE_BODY, bold=True, cjk=ctx["cjk"], latin=ctx["latin"])
            + '<w:r><w:tab/></w:r>'
            + run(date, size=SIZE_DATE, color=COLOR_MUTED, cjk=ctx["cjk"], latin=ctx["latin"]))
    out = [para(line, before=40, after=0, line=290, tabs=tabs)]

    honors = s(e.get("honors"))
    if honors:
        out.append(para(rich_runs(honors, size=SIZE_META, bold=True, color=COLOR_SOFT,
                                  cjk=ctx["cjk"], latin=ctx["latin"]),
                        before=20, after=0, line=265))
    return "".join(out)


def entry_header(left, right, date, ctx, left_size=SIZE_BODY, right_bold=True):
    parts = rich_runs(left, size=left_size, bold=True, cjk=ctx["cjk"], latin=ctx["latin"])
    parts += '<w:r><w:tab/></w:r>'
    parts += run(right, size=SIZE_BODY, bold=right_bold, cjk=ctx["cjk"], latin=ctx["latin"])
    parts += '<w:r><w:tab/></w:r>'
    parts += run(date, size=SIZE_DATE, color=COLOR_MUTED, cjk=ctx["cjk"], latin=ctx["latin"])
    return para(parts, before=40, after=0, line=290,
                tabs=[("left", cm(7.3)), ("right", TEXT_W)])


def bullets(items, ctx):
    """列表项用 Word 原生编号（numPr）而非手写 "•"+tab。

    Word 在「整行刚好占满」时会对行内字符做压缩，手写 tab 会被压没，
    导致圆点和正文贴在一起。交给列表引擎定位就不会有这个问题。
    """
    out = []
    for b in items:
        topic, text = s(b.get("topic")), s(b.get("text"))
        body = ""
        if topic:
            body += run(topic + "：", size=SIZE_BODY, bold=True,
                        cjk=ctx["cjk"], latin=ctx["latin"])
        body += rich_runs(text, size=SIZE_BODY, cjk=ctx["cjk"], latin=ctx["latin"])
        out.append(
            '<w:p><w:pPr>'
            '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
            '<w:spacing w:before="0" w:after="40" w:line="%d" w:lineRule="exact"/>'
            '<w:ind w:left="340" w:hanging="340"/>'
            '</w:pPr>%s</w:p>' % (LINE_BODY, body))
    return "".join(out)


def exp_block(e, ctx):
    org = s(e.get("org"))
    tag = s(e.get("tag"))
    left = org + ("（%s）" % tag if tag else "")
    out = [entry_header(left, s(e.get("title")),
                        fmt_range(e.get("start"), e.get("end")), ctx)]
    overview = s(e.get("overview"))
    if overview:
        out.append(para(rich_runs(overview, size=10, color=COLOR_TEXT,
                                  cjk=ctx["cjk"], latin=ctx["latin"]),
                        before=40, after=40, line=LINE_OVERVIEW))
    out.append(bullets(as_list(e.get("bullets")), ctx))
    out.append(spacer(120))
    return "".join(out)


def project_block(p, ctx):
    out = [entry_header(s(p.get("name")), s(p.get("role")),
                        fmt_range(p.get("start"), p.get("end")), ctx, right_bold=False)]
    bg = s(p.get("background"))
    if bg:
        out.append(para(run("项目背景", size=SIZE_META + 0.5, bold=True, color=COLOR_SOFT,
                            cjk=ctx["cjk"], latin=ctx["latin"]),
                        before=50, after=0, line=250))
        out.append(para(rich_runs(bg, size=10, color=COLOR_TEXT,
                                  cjk=ctx["cjk"], latin=ctx["latin"]),
                        before=10, after=30, line=LINE_OVERVIEW))
    items = as_list(p.get("bullets"))
    if items:
        out.append(para(run("工作内容", size=SIZE_META + 0.5, bold=True, color=COLOR_SOFT,
                            cjk=ctx["cjk"], latin=ctx["latin"]),
                        before=30, after=20, line=250))
        out.append(bullets(items, ctx))
    out.append(spacer(120))
    return "".join(out)


def skills_block(items, ctx):
    return bullets(items, ctx)


# ---------------------------------------------------------------- 页面估算
def estimate(data, ctx):
    h = 520 + 30 + 260 + 60
    edu = as_list(data.get("education"))
    exp = as_list(data.get("experience"))
    prj = as_list(data.get("projects"))
    skills = as_list(data.get("skills"))

    if edu:
        h += 240 + H_TITLE_ROW + 60
        for e in edu:
            h += 40 + 290
            if s(e.get("honors")):
                h += 20 + 265
    if exp:
        h += 240 + H_TITLE_ROW + 60
        for e in exp:
            h += 40 + 290
            if s(e.get("overview")):
                h += 40 + est_lines(s(e["overview"]).replace("**", ""), TEXT_W - 120, 10) * LINE_OVERVIEW + 40
            for b in as_list(e.get("bullets")):
                txt = s(b.get("topic")) + "：" + s(b.get("text")).replace("**", "")
                h += est_lines(txt, TEXT_W - 340, SIZE_BODY) * LINE_BODY + 40
            h += 120
    if prj:
        h += 240 + H_TITLE_ROW + 60
        for p in prj:
            h += 40 + 290
            if s(p.get("background")):
                h += 50 + 250 + 10 + est_lines(s(p["background"]).replace("**", ""), TEXT_W - 120, 10) * LINE_OVERVIEW + 30
            items = as_list(p.get("bullets"))
            if items:
                h += 30 + 250 + 20
                for b in items:
                    txt = s(b.get("topic")) + "：" + s(b.get("text")).replace("**", "")
                    h += est_lines(txt, TEXT_W - 340, SIZE_BODY) * LINE_BODY + 40
            h += 120
    if skills:
        h += 240 + H_TITLE_ROW + 60
        for b in skills:
            txt = s(b.get("topic")) + "：" + s(b.get("text")).replace("**", "")
            h += est_lines(txt, TEXT_W - 340, SIZE_BODY) * LINE_BODY + 40

    usable = PAGE_H - M_T - M_B
    # 经验系数：行数估算偏保守（Word 的 CJK 断行比逐字累加更省空间），
    # 拿真实 Word 输出回归过 3 份样例，统一乘 0.93 后误差在 ±5% 内。
    return round(h / usable * 0.93, 2)


# ---------------------------------------------------------------- 检查
def check(data):
    errs, warns = [], []
    edu = as_list(data.get("education"))
    exp = as_list(data.get("experience"))
    prj = as_list(data.get("projects"))
    skills = as_list(data.get("skills"))

    if not s(data.get("name")):
        errs.append("缺少 name（姓名）")
    if not as_list(data.get("contact")):
        errs.append("缺少 contact（联系方式列表）")
    if not edu:
        errs.append("缺少 education（至少一条教育经历）")
    if not exp and not prj:
        errs.append("experience 与 projects 全空：简历没有任何经历内容")

    for i, e in enumerate(edu):
        for k in ("school", "major", "degree"):
            if not s(e.get(k)):
                errs.append("education[%d] 缺少 %s" % (i, k))
        if not s(e.get("honors")):
            warns.append("education[%d] 没有 honors（荣誉/GPA 行），招聘方会少一个判断依据" % i)

    def check_bullets(container, label, lo, hi, cmin, cmax):
        items = as_list(container.get("bullets"))
        if not items:
            errs.append("%s 没有 bullets" % label)
            return
        if not (lo <= len(items) <= hi):
            warns.append("%s 有 %d 条 bullet，建议 %d-%d 条" % (label, len(items), lo, hi))
        for j, b in enumerate(items):
            topic = s(b.get("topic"))
            text = s(b.get("text"))
            if not topic:
                errs.append("%s bullets[%d] 缺少 topic" % (label, j))
            if not text:
                errs.append("%s bullets[%d] 缺少 text" % (label, j))
                continue
            n_bold = text.count("**") // 2 + (1 if topic else 0)
            if n_bold < cmin:
                warns.append("%s bullets[%d] 只有 %d 处加粗，建议 %d-%d 处（主题词+方法/工具+数字）"
                             % (label, j, n_bold, cmin, cmax))
            if n_bold > cmax:
                warns.append("%s bullets[%d] 有 %d 处加粗，超过 %d 处会稀释重点"
                             % (label, j, n_bold, cmax))
            length = em_width(topic + "：" + text.replace("**", ""))
            if length < 28:
                warns.append("%s bullets[%d] 偏短（约 %.0f 字），信息量可能不足" % (label, j, length))
            elif length > 95:
                warns.append("%s bullets[%d] 偏长（约 %.0f 字），会超过 3 行" % (label, j, length))

    for i, e in enumerate(exp):
        label = "experience[%d](%s)" % (i, s(e.get("org")) or "?")
        if not s(e.get("title")):
            errs.append("%s 缺少 title（岗位）" % label)
        if not s(e.get("overview")):
            warns.append("%s 没有 overview（概览段），三段式结构会缺一环" % label)
        else:
            n = em_width(s(e["overview"]).replace("**", ""))
            if n < 45:
                warns.append("%s overview 偏短（约 %.0f 字），建议 2-3 行" % (label, n))
            elif n > 130:
                warns.append("%s overview 偏长（约 %.0f 字），建议压到 2-3 行" % (label, n))
        check_bullets(e, label, 3, 5, 2, 4)

    for i, p in enumerate(prj):
        label = "projects[%d](%s)" % (i, s(p.get("name")) or "?")
        if not s(p.get("name")):
            errs.append("%s 缺少 name" % label)
        if not s(p.get("background")):
            warns.append("%s 没有 background（项目背景）" % label)
        check_bullets(p, label, 3, 5, 2, 4)

    if skills:
        if not (3 <= len(skills) <= 5):
            warns.append("skills 有 %d 条，建议 3-5 条" % len(skills))
        for i, b in enumerate(skills):
            if not s(b.get("topic")):
                errs.append("skills[%d] 缺少 topic（技能维度名）" % i)
            n = em_width(s(b.get("text", "")).replace("**", ""))
            if n > 70:
                warns.append("skills[%d] 偏长（约 %.0f 字），技能条目建议 1-2 行" % (i, n))
    else:
        warns.append("没有 skills 模块")

    # 日期格式
    for e in edu + exp + prj:
        for k in ("start", "end"):
            v = s(e.get(k))
            if v and not re.match(r"^\d{4}([.\-/]\d{1,2})?$", v):
                warns.append("日期 %s=%r 不是 YYYY.MM 形式，渲染时会原样输出" % (k, v))

    assumed = [s(x) for x in as_list(data.get("assumed_metrics"))]
    blob = json.dumps(data, ensure_ascii=False)
    for a in assumed:
        if a and a not in blob.replace('\\"', '"'):
            warns.append("assumed_metrics 里的 %r 在正文中找不到，记得同步" % a)

    pages = estimate(data, {"theme": "1F3864"})
    if pages > 2:
        warns.append("估算约 %.1f 页，超过 2 页，需要删减内容" % pages)
    elif pages > 1 and not opt(data, "allow_two_pages"):
        warns.append("估算约 %.1f 页（1-2 页可接受，但一页信息密度更高）" % pages)
    elif pages < 0.8:
        warns.append(
            "估算仅 %.2f 页，版面明显不满一页：先按 references/writing.md「版面不满一页时怎么补」"
            "补齐内容再交付。首选把工作经历里的子系统/模块拆成独立的「项目经历」条目"
            "（每段 3-5 条 bullet），其次把经历 bullet 从 3 条补到 4-5 条、补技能维度、"
            "补教育荣誉行；仍然不够就把缺的素材列出来问用户。不要把页面留白交付。" % pages)

    return {"ok": not errs, "errors": errs, "warnings": warns,
            "pages_estimate": pages,
            "counts": {"education": len(edu), "experience": len(exp),
                       "projects": len(prj), "skills": len(skills),
                       "bullets": sum(len(as_list(x.get("bullets"))) for x in exp + prj)},
            "assumed_metrics": assumed}


# ---------------------------------------------------------------- 预览
def preview(data):
    L = []
    name = s(data.get("name")) or "姓名"
    head = s(data.get("headline"))
    L.append("# %s%s" % (name, ("　｜　" + head) if head else ""))
    contact = [s(x) for x in as_list(data.get("contact")) if s(x)]
    if contact:
        L.append("　·　".join(contact))
    L.append("")

    edu = as_list(data.get("education"))
    exp = as_list(data.get("experience"))
    prj = as_list(data.get("projects"))
    skills = as_list(data.get("skills"))

    if edu:
        L += ["## 教育经历", ""]
        for e in edu:
            L.append("**%s**　**%s**　**%s**　　%s" % (
                s(e.get("school")), s(e.get("major")), s(e.get("degree")),
                fmt_range(e.get("start"), e.get("end")).replace("年", ".").replace("月", "").replace(" - ", " – ")))
            if s(e.get("honors")):
                L.append("**%s**" % s(e.get("honors")))
            L.append("")

    if exp:
        L += ["## 实习 / 工作经历", ""]
        for e in exp:
            tag = ("（%s）" % s(e["tag"])) if s(e.get("tag")) else ""
            L.append("**%s**%s　**%s**　　%s" % (
                s(e.get("org")), tag, s(e.get("title")),
                fmt_range(e.get("start"), e.get("end")).replace("年", ".").replace("月", "").replace(" - ", " – ")))
            if s(e.get("overview")):
                L.append("")
                L.append(s(e["overview"]))
            L.append("")
            for b in as_list(e.get("bullets")):
                L.append("- **%s：** %s" % (s(b.get("topic")), s(b.get("text"))))
            L.append("")

    if prj:
        L += ["## 项目经历", ""]
        for p in prj:
            L.append("**%s**　%s　　%s" % (
                s(p.get("name")), s(p.get("role")),
                fmt_range(p.get("start"), p.get("end")).replace("年", ".").replace("月", "").replace(" - ", " – ")))
            if s(p.get("background")):
                L.append("")
                L.append("**项目背景**")
                L.append(s(p["background"]))
            items = as_list(p.get("bullets"))
            if items:
                L.append("")
                L.append("**工作内容**")
                for b in items:
                    L.append("- **%s：** %s" % (s(b.get("topic")), s(b.get("text"))))
            L.append("")

    if skills:
        L += ["## 专业技能", ""]
        for b in skills:
            L.append("- **%s：** %s" % (s(b.get("topic")), s(b.get("text"))))
        L.append("")

    assumed = [s(x) for x in as_list(data.get("assumed_metrics")) if s(x)]
    if assumed:
        L += ["---", "", "> ⚠️ 以下量化数据未由你提供，是按场景保守推算的，请确认或替换：", ">"]
        for a in assumed:
            L.append("> - %s" % a)
    return "\n".join(L)


# ---------------------------------------------------------------- 打包 docx
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>')

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    '</Relationships>')

DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
    '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/slant.png"/>'
    '</Relationships>' % IMAGE_RID)


def numbering_xml(ctx):
    """单层列表：实心黑圆点，悬挂缩进 0.6cm。"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:abstractNum w:abstractNumId="0">'
        '<w:multiLevelType w:val="singleLevel"/>'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
        '<w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
        '<w:pPr><w:ind w:left="340" w:hanging="340"/></w:pPr>'
        '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>'
        '<w:b/><w:bCs/><w:color w:val="000000"/><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
        '</w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        '</w:numbering>'
        % (ctx["latin"], ctx["latin"], ctx["cjk"], ctx["latin"], SIZE_BODY * 2, SIZE_BODY * 2))

APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '<Application>resume-builder</Application></Properties>')


def styles_xml(ctx):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>'
        '<w:color w:val="%s"/>'
        '<w:sz w:val="%d"/><w:szCs w:val="%d"/>'
        '</w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr>'
        '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        '</w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:widowControl w:val="0"/></w:pPr>'
        '</w:style>'
        '</w:styles>'
        % (ctx["latin"], ctx["latin"], ctx["cjk"], ctx["latin"], COLOR_TEXT,
           SIZE_BODY * 2, SIZE_BODY * 2))


def core_xml(data):
    name = s(data.get("name"))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>%s</dc:title><dc:creator>%s</dc:creator>'
        '</cp:coreProperties>' % (xml_escape(name or "简历"), xml_escape(name or "")))


def document_xml(body, ctx):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<w:body>%s'
        '<w:sectPr>'
        '<w:pgSz w:w="%d" w:h="%d"/>'
        '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
        'w:header="%d" w:footer="%d" w:gutter="0"/>'
        '<w:cols w:space="425"/><w:docGrid w:type="default" w:linePitch="312"/>'
        '</w:sectPr></w:body></w:document>'
        % (body, PAGE_W, PAGE_H, M_T, M_R, M_B, M_L, cm(0.8), cm(0.8)))


def build(data, out_path, ctx):
    body = render(data, ctx)
    png = make_slant_png(W_TITLE_SLANT_CM, H_TITLE_ROW / TWIPS_PER_CM,
                         ctx["theme"], forward=ctx["slant"] == "forward")
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", document_xml(body, ctx))
        z.writestr("word/styles.xml", styles_xml(ctx))
        z.writestr("word/numbering.xml", numbering_xml(ctx))
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/media/slant.png", png)
        z.writestr("docProps/core.xml", core_xml(data))
        z.writestr("docProps/app.xml", APP_XML)
    os.replace(tmp, out_path)
    return out_path


# ---------------------------------------------------------------- main
def make_ctx(args, data):
    theme = (args.theme or opt(data, "theme", "1F3864")).lstrip("#").upper()
    if not re.match(r"^[0-9A-F]{6}$", theme):
        sys.exit("theme 必须是 6 位十六进制色值，例如 1F3864")
    return {
        "theme": theme,
        "title_text": "1A1A1A" if luminance(theme) > 0.55 else "FFFFFF",
        "cjk": args.cjk_font or opt(data, "cjk_font", "微软雅黑"),
        "latin": args.latin_font or opt(data, "latin_font", "Calibri"),
        "slant": (args.slant or opt(data, "slant", "forward")).lower(),
        "pic_id": 1001,
    }


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("command", choices=["preview", "check", "build"])
    ap.add_argument("data")
    ap.add_argument("-o", "--out", default="简历.docx")
    ap.add_argument("--theme")
    ap.add_argument("--cjk-font", dest="cjk_font")
    ap.add_argument("--latin-font", dest="latin_font")
    ap.add_argument("--slant", choices=["forward", "back"])
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit("resume.json 解析失败：%s" % e)

    ctx = make_ctx(args, data)

    if args.command == "preview":
        print(preview(data))
    elif args.command == "check":
        print(json.dumps(check(data), ensure_ascii=False, indent=2))
    else:
        report = check(data)
        if report["errors"]:
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit("存在阻断性错误，未生成文档")
        path = build(data, args.out, ctx)
        print(json.dumps({"output": os.path.abspath(path),
                          "pages_estimate": report["pages_estimate"],
                          "warnings": report["warnings"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
