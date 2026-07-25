# -*- coding: utf-8 -*-
import sys
import os
os.system('chcp 65001 >nul 2>&1')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, '.')
from src.stock_analysis.services.stock_loader import StockLoader
from src.stock_analysis.services.matcher import Matcher

loader = StockLoader()
matcher = Matcher(loader.get_name_index(), loader.get_code_index())

# 从数据库读取msg_id=2964的完整内容
import sqlite3
conn = sqlite3.connect('data/messages.db')
c = conn.cursor()
c.execute("SELECT id, message_content FROM group_messages WHERE id=2964")
row = c.fetchone()
conn.close()

if not row:
    print("msg_id=2964 not found!")
    sys.exit(1)

content = row[1]
print(f"content length: {len(content)}")
print(f"content repr (first 200): {repr(content[:200])}")

# Step 1: clean
cleaned = matcher._clean_content(content)
print(f"\ncleaned is None: {cleaned is None}")
if cleaned is not None:
    print(f"cleaned length: {len(cleaned)}")
    idx = cleaned.find('美利信')
    print(f"美利信 position in cleaned: {idx}")
    if idx >= 0:
        end = idx + 3
        prev_char = cleaned[idx-1] if idx > 0 else '<START>'
        next_char = cleaned[end] if end < len(cleaned) else '<END>'
        print(f"prev={repr(prev_char)} next={repr(next_char)}")
        ok = matcher._check_boundary(cleaned, idx, end)
        print(f"boundary check: {ok}")
else:
    print("Content was filtered by _clean_content!")
    # Check why - hex ratio?
    stripped = content.strip()
    hex_chars = set("0123456789abcdefABCDEF")
    hex_ratio = sum(1 for c in stripped if c in hex_chars) / len(stripped) if stripped else 0
    print(f"  length={len(stripped)}, hex_ratio={hex_ratio:.4f}")
    # Check XML markers
    from src.stock_analysis.config.settings import XML_START_MARKERS, ENCRYPTED_DATA_MIN_LENGTH
    print(f"  ENCRYPTED_DATA_MIN_LENGTH={ENCRYPTED_DATA_MIN_LENGTH}")
    for marker in XML_START_MARKERS:
        if stripped.startswith(marker):
            print(f"  starts with XML marker: {marker}")
    # Check if emoji causes high hex ratio
    non_ascii = sum(1 for c in stripped if ord(c) > 127)
    print(f"  non-ascii chars: {non_ascii}/{len(stripped)}")