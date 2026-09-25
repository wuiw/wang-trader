from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_06_01_fake_extreme_divergence import FakeExtremeDivergence

PREV = (9990, 10001, 9989, 10000)

# 空方序列：bar0 建立 B(=10000)；bar1(C)/bar2(D) 皆未輸給 B，B 更新為10040（真實延續）；
# bar3 再創新高但收盤10036<B(10040)，立即判定假性峰點（level=10045,bound=10050，範圍窄僅5點，
# 但盤中總幅度 sess_high-sess_low=55>40 符合極端位置）；bar4 收盤10044<10045 無遮蔽跌破濾網，
# 距停損|10044-10050|=6<=20，立即進場。
_SHORT_ROWS = [
    (10000, 10005, 9995, 10000),
    (10000, 10045, 9998, 10040),
    (10040, 10042, 10030, 10035),
    (10035, 10050, 10045, 10036),
    (10046, 10047, 10040, 10044),
    (10044, 10046, 10030, 10032),
]


def _mirror(rows, m=10000):
    return [(2 * m - o, 2 * m - lo, 2 * m - hi, 2 * m - c) for (o, hi, lo, c) in rows]


def test_short_divergence_immediate_entry():
    bars = make_bars(_SHORT_ROWS, prev_day=PREV)
    res = run(FakeExtremeDivergence(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "假性創新高背離"
    assert sig.price == 10044 and sig.stop == 10050


def test_long_divergence_immediate_entry():
    bars = make_bars(_mirror(_SHORT_ROWS), prev_day=_mirror([PREV])[0])
    res = run(FakeExtremeDivergence(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "假性創新低背離"
    assert sig.price == 20000 - 10044 and sig.stop == 20000 - 10050


def test_swing_too_small_filtered():
    # F1：C 的收盤已比 B 低，但盤中幅度只有 30 點（<=40）→ 不成立候選
    rows = [
        (10000, 10010, 9995, 10005),
        (10005, 10025, 10015, 9998),
        (9998, 10000, 9990, 9993),
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(FakeExtremeDivergence(), bars)
    assert res.signals == []


def test_recover_to_b_abandons_signal():
    # F2/3.3：濾網形成後，收盤回到（>=）前波最高收盤 B，放棄本次訊號尋找，之後即使再跌破舊濾網也不算
    rows = _SHORT_ROWS[:4] + [
        (10036, 10047, 10034, 10046),  # 收盤10046>=B(10040) → 打平/超過，放棄
        (10046, 10048, 10020, 10025),  # 雖然跌破舊濾網10045，但濾網已被放棄，不成立訊號
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(FakeExtremeDivergence(), bars)
    assert res.signals == []


def test_new_higher_high_invalidates_then_reforms_filter():
    # F3/C5：舊濾網(level=10045,bound=10050)被更高的新高(10060)取代而失效，
    # 新高K線本身收盤仍低於 B(10040) → 以它重新形成假性峰點(level=10040,bound=10060)
    rows = _SHORT_ROWS[:4] + [
        (10046, 10060, 10040, 10036),  # 創新高 10060 > 舊bound(10050)，收盤 10036 < B → 新假性峰點
        (10036, 10038, 10020, 10025),  # 跌破新濾網(10040)，距停損|10025-10060|=35>20 → 補進場
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(FakeExtremeDivergence(), bars)
    sig = res.signals[0]
    assert sig.reason == "假性創新高背離(補進場)"
    assert sig.stop == 10060  # 若沿用舊濾網會是10050，證明已重新判定


def test_genuine_new_high_followed_by_down_bar_is_not_fake_peak():
    """C3：只有創新高的 K 線（C）才可能是假性峰點；同步創新高後的下一根黑K不是峰點，不得拿它畫濾網。"""
    rows = [
        (10000, 10005, 9995, 10000),
        (10000, 10045, 9998, 10040),  # 影線與收盤同步創新高 → 正常
        (10040, 10042, 9990, 9995),   # 下一根收盤低於舊 B(10000)，但它不是新高K線
        (9995, 9996, 9980, 9985),     # 跌破前一根低點 9990，不應被當成背離空訊
    ]
    res = run(FakeExtremeDivergence(), make_bars(rows, prev_day=PREV))
    assert res.signals == []


def test_wave_highest_close_used_for_comparison():
    """C3（p.191 圖6-3、p.195）：比較的是「本波最高收盤」與前波最高收盤 B；
    本波稍早已有收盤 ≥ B 者，新高K線收盤略低也不算假性創新高。"""
    rows = [
        (10000, 10005, 9995, 10000),
        (10000, 10020, 9998, 10018),  # A：同步創新高，B=10018
        (10018, 10019, 9985, 9992),   # 拉回（本波起點）
        (9992, 10015, 9990, 10012),
        (10012, 10019, 10010, 10019),  # 本波收盤 10019 ≥ B
        (10019, 10030, 10015, 10017),  # C：影線創新高，收盤 10017 < B，但本波最高收盤 10019 ≥ B → 非假性
        (10017, 10018, 10005, 10008),  # 跌破 C 低點 10015 → 不得視為訊號
    ]
    res = run(FakeExtremeDivergence(), make_bars(rows, prev_day=PREV))
    assert res.signals == []


def test_swing_includes_gap_from_prev_close():
    """F1（p.194「包括跳空至盤中高低點」）：跳空幅度計入極端位置的震幅。"""
    rows = [
        (10040, 10045, 10035, 10040),  # 跳空 40 點開高，盤中震幅本身只有 30 點
        (10040, 10060, 10038, 10055),  # 同步創新高
        (10055, 10065, 10050, 10052),  # 影線創新高、收盤 < B(10055) → 假性峰點；震幅含跳空 = 65 > 40
        (10052, 10053, 10040, 10045),  # 跌破濾網 10050 → 訊號
    ]
    res = run(FakeExtremeDivergence(), make_bars(rows, prev_day=PREV))
    assert res.signals and res.signals[0].side == Side.SHORT


def test_far_stop_uses_pullback_limit_order():
    bars = make_bars(_SHORT_ROWS, prev_day=PREV)
    res = run(FakeExtremeDivergence(stop_points=3), bars)
    sig = res.signals[0]
    assert sig.reason == "假性創新高背離(補進場)"
    assert sig.stop == 10050 and sig.price == 10047  # limit = stop - stop_points
