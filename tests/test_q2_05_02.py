from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_05_02_extreme_max_volume import ExtremeMaxVolume

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000（本方法未使用平盤，僅為與其他測試一致）


def test_short_signal_immediate_entry():
    bars = make_bars([
        (10000, 10005, 9995, 10002, 5000),   # bar0：開盤，排除於最大量評選
        (10002, 10050, 10045, 10048, 2000),  # bar1：新高、量2000(>=1500) → 候選；level=10045,bound=10050
        (10048, 10049, 10020, 10030, 500),   # bar2：收盤10030<10045 跌破濾網，距停損|10030-10050|=20<=20 → 立即進場
        (10030, 10032, 10010, 10015, 100),
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "極端位置最大量(空)"
    assert sig.price == 10030 and sig.stop == 10050


def test_long_signal_pullback_entry():
    bars = make_bars([
        (10000, 10005, 9995, 9998, 5000),    # bar0：開盤，sess_high=10005, sess_low=9995，排除於最大量評選
        (9998, 9999, 9950, 9952, 2000),      # bar1：新低9950、量2000 → 候選；level=9999(高點),bound=9950(低點)
        (9952, 9955, 9951, 9940, 500),       # bar2：未創新低(9951>9950)，收盤9940<9999，濾網未破
        (9940, 10010, 9950, 10005, 300),     # bar3：收盤10005>9999 突破濾網，距停損|10005-9950|=55>20 → 補進場
        (10005, 10006, 9968, 9970, 100),     # bar4：拉回到 9970 → 觸及限價 9970 成交
        (9970, 10010, 9969, 10005, 100),
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "極端位置最大量(多)(補進場)"
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 9970


def test_low_volume_not_candidate():
    # F1：新高但量僅 1000 < 1500 門檻 → 不成立候選，濾網不存在，之後跌破也不算訊號
    bars = make_bars([
        (10000, 10005, 9995, 10002, 5000),
        (10002, 10050, 10045, 10048, 1000),  # 量不足 1500
        (10048, 10049, 10020, 10030, 500),   # 即使收盤跌破 10045，也無濾網可破
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals == []


def test_opening_bar_volume_excluded():
    # F2：開盤第一根量高達 9000，但不可列入最大量評選；bar1 以量2000即可成為候選
    bars = make_bars([
        (10000, 10005, 9995, 10002, 9000),   # 開盤大量，排除在外
        (10002, 10050, 10045, 10048, 2000),  # 只要 >= vm_prev(0) 即成立候選（開盤量不計入 vm）
        (10048, 10049, 10020, 10030, 500),   # 跌破 10045 → 訊號成立
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals != []
    assert res.signals[0].side == Side.SHORT


def test_swing_too_small_ignored():
    # F3/C4：新高但盤中幅度僅 (10050-10040=10) <= 30 → 不成立候選
    bars = make_bars([
        (10000, 10040, 10038, 10039, 5000),
        (10039, 10050, 10045, 10048, 2000),  # sess_high-sess_low = 10050-10038 = 12 <= 30
        (10048, 10049, 10020, 10030, 500),
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals == []


def test_new_high_without_max_volume_no_candidate():
    # C3/F4：bar1 建立候選；bar2 創新高但量未同創最大量 → 舊濾網失效且當下無候選
    bars = make_bars([
        (10000, 10005, 9995, 10002, 5000),
        (10002, 10060, 10055, 10058, 3000),  # bar1：新高，量3000 → 候選 level=10055,bound=10060
        (10058, 10080, 10057, 10059, 1000),  # bar2：再創新高(10080)，但量僅1000<3000(vm_prev) → C3失效、F4無候選
        (10059, 10058, 10020, 10030, 500),   # bar3：即使跌破也無濾網可破
    ], prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals == []


def test_filter_expires_after_max_filter_bars():
    # F5/C6：濾網建立後超過 max_filter_bars(15) 根未無遮蔽突破，且已脫離內包（非C7例外）→ 失效
    rows = [(10000, 10005, 9995, 10002, 5000),  # bar0
            (10002, 10050, 10045, 10048, 2000)]  # bar1：候選 level=10045,bound=10050
    # 先讓行情脫離內包（影線觸及但未收盤突破），之後盤整超過 15 根
    rows.append((10048, 10049, 10040, 10047, 100))  # bar2：影線觸及10040<10045，收盤未破 → inside=False
    for _ in range(15):
        rows.append((10047, 10048, 10041, 10046, 100))  # 持續盤整，age 逐漸超過 15
    rows.append((10046, 10047, 10030, 10035, 100))  # 最終跌破，但 age>15 且 inside=False → 應已失效
    bars = make_bars(rows, prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals == []


def test_inside_range_exception_keeps_filter_alive():
    # C7：濾網建立後行情始終盤整在濾網K線高低範圍內（內包走勢），超過15根仍可等待無遮蔽突破
    rows = [(10000, 10005, 9995, 10002, 5000),  # bar0
            (10002, 10050, 10045, 10048, 2000)]  # bar1：候選 level=10045(低),bound=10050(高)
    for _ in range(16):
        rows.append((10047, 10049, 10046, 10047, 100))  # 一直在 [10045,10050] 內盤整，inside 保持 True
    rows.append((10047, 10048, 10030, 10035, 100))  # 超過15根後才無遮蔽跌破 → C7例外仍成立
    bars = make_bars(rows, prev_day=PREV)
    res = run(ExtremeMaxVolume(), bars)
    assert res.signals != []
    assert res.signals[0].side == Side.SHORT
