"""AGEN-1002 Unicode 归一化抽样实证脚本（只读，不修改任何产品代码）。

用法：python3 verify_samples.py
依赖：仅标准库 + 仓库内 deeptutor.utils.document_validator（无第三方依赖）。
"""

import json
import re
import sys
import unicodedata

sys.path.insert(0, "/Users/Shared/DeepTutor/dt-agen1002-uni-wt")
from deeptutor.utils.document_validator import DocumentValidator  # noqa: E402

out = {}
nfc = unicodedata.normalize("NFC", "café.pdf")
nfd = unicodedata.normalize("NFD", "café.pdf")

# S1 deeptutor/utils/document_validator.py:97 — 上传文件名 NFC 化
r1 = DocumentValidator.validate_upload_safety(nfd, None, allowed_extensions={".pdf"})
out["S1_upload_basename"] = {
    "bytes_in": nfd.encode().decode("latin1"),
    "output": r1,
    "nfc": r1 == nfc,
}

# S2 deeptutor/api/routers/knowledge.py:379-383 — 目录段不归一
BAD = re.compile(r'[\\:*?"<>|\x00-\x1f]')
seg = BAD.sub("", nfd.rsplit("/", 1)[-1]).strip().strip(".")[:128]
seg = unicodedata.normalize("NFD", "résumés")
seg = BAD.sub("", seg).strip().strip(".")[:128]
out["S2_folder_segment"] = {
    "still_nfd": seg != unicodedata.normalize("NFC", seg),
}

# S3 deeptutor/services/chat_hints.py:183-184 — \w+casefold 随形式变化
def normal_form(value):
    return re.sub(r"[^\w㐀-鿿]+", "", value).casefold()

a, b = normal_form(nfc), normal_form(nfd)
out["S3_normal_form"] = {"nfc_form": a, "nfd_form": b, "differ": a != b}

# S4 deeptutor/services/courses.py:324-325 — casefold 查重跨形式失效
out["S4_dedup"] = {
    "nfc_nfd_dedupe": nfc.casefold() == nfd.casefold(),
}

# S5 lower vs casefold（ß）— 排序/去重口径差异
names = ["Straße", "Strasse", "Zug"]
out["S5"] = {
    "ss_lower": "ß".lower(),
    "ss_casefold": "ß".casefold(),
    "js_toLowerCase_ss": "ß",
    "sort_lower": sorted(names, key=str.lower),
    "sort_casefold": sorted(names, key=str.casefold),
    "sort_differ": sorted(names, key=str.lower) != sorted(names, key=str.casefold),
}

# S6 Python strip 不去 U+FEFF（JS trim 按规范去除）
bom = "﻿hello"
out["S6_strip_bom"] = {
    "py_strip_keeps_bom": bom.strip() == bom,
    "codepoint_kept": hex(ord(bom.strip()[0])),
}

# S7 pageindex manifest 键精确匹配（storage.upsert_doc 原文键 / pipeline.py:273 查找）
docs = {nfc: {"doc_id": "d1"}}
out["S7_manifest_lookup"] = {
    "direct_hit": nfd in docs,
    "fallback_name_hit": nfd.rsplit("/", 1)[-1] in docs,
}

# S8 NFC/NFD 同名排序非邻
out["S8_nfc_nfd_order"] = {
    "order": [x.encode("utf-8").decode("latin1") for x in sorted([nfd, nfc])],
}

print(json.dumps(out, ensure_ascii=False, indent=1))
