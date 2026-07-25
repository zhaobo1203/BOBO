# -*- coding: utf-8 -*-
"""测试边界检查逻辑"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 模拟Matcher的边界检查
BOUNDARY_CHARS = set(
    "，。！？、；：""''【】《》（）""''…—·\n\r\t "
    ",.!?;:\"'[]{}()<>/\\|@#$%^&*+=~`"
)

CONTEXT_SUFFIX_WORDS = [
    "合资", "科技", "集团", "股份", "控股", "银行", "证券",
    "信息", "电子", "发展", "实业", "能源", "电力", "医药",
    "通信", "建设", "机械", "材料", "新材", "产业", "投资",
    "基金", "有限", "责任", "公司", "股份制", "上市", "A股",
    "板块", "涨停", "跌停", "买入", "卖出", "加仓", "减仓",
    "看多", "看空", "走势", "行情", "复盘", "龙头", "白马",
    "蓝筹", "妖股", "停牌", "复牌", "分红", "配股", "增发",
    "半年报", "年报", "季报", "财报", "业绩", "公告", "研报",
    "评级", "目标价", "市盈率", "市净率", "净利润", "营收",
]

# 中文常见动词/副词/助词（与matcher.py同步）
CHINESE_VERB_PARTICLES = set(
    # 助词/语气词
    "了着过地得呢吗吧啊呀嘛"
    # 副词/连词
    "已经也已正在将将要会能不能得可以可"
    "还还有又却但而且或者与及和跟比较更"
    "最就才只是到从被把给让向对于按"
    # 财经新闻常见动词
    "披发布宣告称说表显提涨跌停收开"
    "完该此其每各另再因如若则虽"
    "进成获受持买卖换操盘拉砸冲破"
    "创超达占涵盖包扩预估计测算"
    "在是于为与由以据依经通借"
)

def check_boundary(text, start, end):
    """检查名称匹配的边界条件"""
    if start > 0:
        prev_char = text[start - 1]
        if prev_char not in BOUNDARY_CHARS and not prev_char.isdigit():
            return False, f"前字符'{prev_char}'不是边界/数字"

    if end < len(text):
        next_char = text[end]
        if next_char not in BOUNDARY_CHARS and not next_char.isdigit():
            remaining = text[end:]
            if not any(remaining.startswith(suffix) for suffix in CONTEXT_SUFFIX_WORDS):
                if next_char not in CHINESE_VERB_PARTICLES:
                    return False, f"后字符'{next_char}'不是边界/数字/后缀词/动词助词"

    return True, "通过"

# 测试第1条消息
msg1 = "美利信已经走出了趋势，只要不跌破5日均线就可以放心，因为这波行情起来都是在5日线运行，华微电子也走出了趋势，如果回踩5日均线再承接上去更佳。大元泵业，汉中精机还观察是否有效突破，作为潜力来观察。"

test_stocks = ["美利信", "华微电子", "大元泵业", "汉中精机"]

print("=== 第1条消息边界检查 ===")
print(f"消息: {msg1[:80]}...")
print()

for name in test_stocks:
    pos = msg1.find(name)
    if pos == -1:
        print(f"  {name}: 未找到")
        continue
    end = pos + len(name)
    prev_char = msg1[pos-1] if pos > 0 else "<START>"
    next_char = msg1[end] if end < len(msg1) else "<END>"
    ok, reason = check_boundary(msg1, pos, end)
    print(f"  {name}: 位置{pos}-{end}, 前='{prev_char}', 后='{next_char}', 结果={ok} ({reason})")

# 测试其他消息
print()
print("=== 其他消息边界检查 ===")
test_cases = [
    ("美利信", "$美利信(SZ301307)$ 最近涨是因为AI服务器"),
    ("美利信", "美利信，精密铸造"),
    ("美利信", "【美利信】半导体零部件"),
    ("美利信", "美利信已经走出了趋势"),
    ("华微电子", "华微电子也走出了趋势"),
    ("大元泵业", "大元泵业，汉中精机"),
    # 新增：民德电子动词边界测试
    ("民德电子", "民德电子披露投资者关系活动记录表"),
    ("民德电子", "2026年7月5日，民德电子披露投资者关系"),
    ("民德电子", "民德电子发布涨价函"),
    ("民德电子", "民德电子宣布涨价"),
    ("民德电子", "民德电子涨停"),
    ("民德电子", "民德电子跌停"),
]

for name, text in test_cases:
    pos = text.find(name)
    if pos == -1:
        print(f"  {name} in '{text[:40]}': 未找到")
        continue
    end = pos + len(name)
    prev_char = text[pos-1] if pos > 0 else "<START>"
    next_char = text[end] if end < len(text) else "<END>"
    ok, reason = check_boundary(text, pos, end)
    print(f"  {name} in '{text[:40]}': 前='{prev_char}', 后='{next_char}', 结果={ok} ({reason})")