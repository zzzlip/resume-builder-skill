#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_docx_text.py — 从 .docx 里抽出纯文本，用于重构旧简历。

纯标准库实现，不依赖 python-docx / pandoc / LibreOffice。

    python3 read_docx_text.py 旧简历.docx
    python3 read_docx_text.py 旧简历.docx --json     # 按块输出，便于程序处理
"""

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def para_text(p):
    """把一个 <w:p> 拼成字符串，保留制表符与换行。"""
    buf = []
    for node in p.iter():
        tag = node.tag
        if tag == W + "t":
            buf.append(node.text or "")
        elif tag == W + "tab":
            buf.append("\t")
        elif tag in (W + "br", W + "cr"):
            buf.append("\n")
    text = "".join(buf)
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def walk(container, blocks):
    for child in container:
        if child.tag == W + "p":
            t = para_text(child)
            if t:
                blocks.append({"type": "paragraph", "text": t})
        elif child.tag == W + "tbl":
            rows = []
            for tr in child.findall(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    cells.append(" ".join(para_text(p) for p in tc.findall(W + "p")).strip())
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})


def extract(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            sys.exit("这不是一个 .docx（缺少 word/document.xml）：%s" % path)
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    blocks = []
    walk(body, blocks)
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = ap.parse_args()

    blocks = extract(args.path)
    if args.json:
        print(json.dumps(blocks, ensure_ascii=False, indent=2))
        return

    for b in blocks:
        if b["type"] == "paragraph":
            print(b["text"])
        else:
            for row in b["rows"]:
                print(" | ".join(row))


if __name__ == "__main__":
    main()
