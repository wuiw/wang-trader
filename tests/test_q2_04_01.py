from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_04_01_cross_kd_n_type import CrossKDNType

HTF = 9  # htf_bars：9根小週期合成1根大週期，方便用「整組重複同一根K線」手算 KD 交叉
BARS = dict(htf_bars=HTF, htf_minutes=None)  # 既有測試用根數版；分鐘版另見文末

# 前 18 根（2 組大週期K線，各由 9 根相同K線構成）製造一次黃金交叉：
#   group0＝9根(100,105,95,97) → k0=40.0, d0=46.67（k<=d）
#   group1＝9根(97,130,96,128) → k1=58.1, d1=50.5（k>d）→ 第18根（index17）確認黃金交叉
# 隔根（index18）起，於小週期尋找N型三步驟（幅度刻意壓小，使訊號距0點<=15點可立即進場）：
#   0=95(idx18) →(1)峰105(idx20,confirm=22) →(2)谷96(idx22,confirm=24) →(3) idx25收盤108>105 → 買訊
_GOLDEN_PREFIX = [(100, 105, 95, 97)] * HTF + [(97, 130, 96, 128)] * HTF
_LONG_N_SHAPE = [
    (95, 97, 95, 96),
    (96, 99, 96, 98),
    (98, 105, 97, 103),
    (103, 104, 99, 101),
    (101, 103, 96, 99),
    (99, 101, 97, 100),
    (100, 102, 97, 101),
    (101, 110, 100, 108),
]
LONG_BARS = _GOLDEN_PREFIX + _LONG_N_SHAPE

# 同理，2 組大週期K線製造一次死亡交叉：
#   group0＝9根(100,105,95,103) → k0=60.0, d0=53.3（k>=d）
#   group1＝9根(103,104,65,66) → k1=40.8, d1=49.2（k<d）→ 確認死亡交叉
# 隔根起尋找倒N型三步驟（與上面買訊結構以 400 為中心鏡射）。
_DEAD_PREFIX = [(100, 105, 95, 103)] * HTF + [(103, 104, 65, 66)] * HTF
_SHORT_N_SHAPE = [
    (305, 305, 303, 304),
    (304, 304, 301, 302),
    (302, 303, 295, 297),
    (297, 301, 296, 299),
    (299, 304, 297, 301),
    (301, 303, 299, 300),
    (300, 303, 298, 300),
    (299, 300, 290, 292),
]
SHORT_BARS = _DEAD_PREFIX + _SHORT_N_SHAPE


def test_golden_cross_n_type_long_signal():
    bars = make_bars(LONG_BARS)
    res = run(CrossKDNType(**BARS), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "N型買訊"
    assert sig.i == 25 and sig.price == 108 and sig.stop == 95


def test_dead_cross_inverse_n_type_short_signal():
    bars = make_bars(SHORT_BARS)
    res = run(CrossKDNType(**BARS), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "倒N型空訊"
    assert sig.i == 25 and sig.price == 292 and sig.stop == 305


def test_pullback_below_zero_invalidates_structure():
    # 與 test_golden_cross_n_type_long_signal 相同的黃金交叉前緣，
    # 但拉回谷點(idx23，低點90)跌破了0點(95)：依 C6/F5 該次結構作廢，
    # 舊的(1)峰點(105) 因 index 未大於新0點(idx23)而失效；到資料結尾為止
    # 尚未形成新的(1)峰點，因此不應出現訊號。
    shape = [
        (95, 97, 95, 96),
        (96, 99, 96, 98),
        (98, 105, 97, 103),   # (1) 峰點候選 105
        (103, 104, 99, 101),
        (101, 103, 99, 100),  # 峰點於此根確認（confirm=idx22），此根本身非違規根
        (100, 102, 90, 91),   # (2) 谷點候選 90 ＜ 0點95 → 違規
        (91, 93, 91, 92),
        (92, 94, 91, 93),
    ]
    bars = make_bars(_GOLDEN_PREFIX + shape)
    res = run(CrossKDNType(**BARS), bars)
    assert res.signals == []


def test_incomplete_trailing_htf_bar_is_not_used():
    # 只給第一組大週期K線（9根），第二組尚未收完（只有 3 根）：
    # 此時只有 1 根已收完的大週期K線，尚不足以判斷任何交叉，regime 應全部為 0，不產生任何搜尋。
    rows = [(100, 105, 95, 97)] * HTF + [(97, 130, 96, 128)] * 3
    bars = make_bars(rows)
    res = run(CrossKDNType(**BARS), bars)
    assert res.signals == []


def test_five_bar_reversal_exit_on_short_position():
    # 空單進場（idx25收盤292）後連續6根黑K，第一根紅K立刻平倉（不需先達獲利目標）。
    rows = list(SHORT_BARS)
    rows += [
        (292, 293, 285, 286),  # 黑K 1
        (286, 287, 280, 281),  # 黑K 2
        (281, 282, 275, 276),  # 黑K 3
        (276, 277, 270, 271),  # 黑K 4
        (271, 272, 265, 266),  # 黑K 5
        (266, 267, 260, 261),  # 黑K 6（run=6 > five_bar_n=5）
        (261, 268, 260, 267),  # 首根紅K → 平倉
    ]
    bars = make_bars(rows)
    res = run(CrossKDNType(**BARS), bars)
    trade = res.trades[0]
    assert trade.side == Side.SHORT and trade.reason_out == "五黑過首紅"


def test_zero_point_excludes_bars_after_peak():
    """0 點只到(1)形成為止；(1)之後跌破 0 點的走勢屬拉回(2)違規（C6/F5），不能把 0 點往下「追平」後再收訊號。"""
    shape = [
        (95, 97, 95, 96),
        (96, 99, 96, 98),
        (98, 105, 97, 103),   # (1) 峰點 105
        (103, 104, 93, 101),  # 拉回跌破 0 點 95
        (101, 103, 92, 99),   # 谷 92（於第 24 根確認）< 0 點 → 結構作廢，0 點改為 92、須重新找(1)
        (99, 101, 97, 100),
        (100, 102, 97, 101),
        (101, 110, 100, 108),  # 收盤 108 > 舊峰 105，但舊結構已作廢 → 不得成為訊號
    ]
    res = run(CrossKDNType(**BARS), make_bars(_GOLDEN_PREFIX + shape))
    assert res.signals == []


def test_f3_uses_signal_bar_body_not_distance_to_zero():
    """F3（p.127）：看的是訊號K線的漲跌點數；小實體但距 0 點較遠者仍立即進場。"""
    rows = list(LONG_BARS)
    rows[25] = (106, 110, 105, 108)  # 實體 2 點、距 0 點 13 點
    res = run(CrossKDNType(**BARS, max_signal_points=5), make_bars(rows))
    assert res.signals[0].reason == "N型買訊"
    rows[25] = (101, 110, 100, 108)  # 實體 7 點 > 5 → 補進場
    res = run(CrossKDNType(**BARS, max_signal_points=5), make_bars(rows))
    assert res.signals[0].reason == "N型買訊(補進場)" and res.signals[0].price == 105


def test_retrace_exit_trails_from_best_price():
    """折返停利（p.133）：通過目標後自最有利價折返 15 點即出場，不是只回到進場價才出場。"""
    rows = LONG_BARS + [(108, 130, 107, 128), (128, 129, 112, 113)]
    res = run(CrossKDNType(**BARS), make_bars(rows))
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 113


def test_structure_keeps_advancing_while_position_held():
    """持倉期間 N 型狀態機仍逐根推進（峰谷不因持倉而凍結）。"""
    from wangtrader.core import Context, Position, prepare

    rows = LONG_BARS + [(108, 112, 107, 110), (110, 116, 109, 114), (114, 115, 111, 112), (112, 114, 110, 111)]
    strat = CrossKDNType(**BARS)
    df = strat.prepare(prepare(make_bars(rows)))
    for i in range(0, 26):  # 先照常跑到訊號根（第 25 根），之後模擬持倉
        strat.on_bar(Context(i=i, df=df, pos=None, trades=[], stopped=None))
    pos = Position(Side.LONG, entry_i=25, entry_price=108.0, stop=95.0, best=108.0)
    for i in range(26, 30):
        strat.on_bar(Context(i=i, df=df, pos=pos, trades=[], stopped=None))
    assert strat._state["peak"] is not None and strat._state["peak"].price == 116


def test_c3_exception_signal_on_cross_confirmation_bar():
    """C3（p.129）：交叉確認當根（大週期收盤那根）若小週期剛好完成 N 型步驟(3)，允許在當根使用訊號。"""
    group1 = [
        (97, 99, 95, 96), (96, 98, 95.5, 97), (97, 105, 99, 104), (104, 104.5, 100, 101),
        (101, 102, 98, 99), (99, 101, 98.5, 100), (100, 102, 99, 101), (101, 104, 100, 103),
        (103, 108, 102, 107),  # 第 17 根：大週期收盤確認黃金交叉，且收盤 107 突破峰(1)=105
    ]
    rows = [(100, 105, 95, 97)] * HTF + group1 + [(107, 108, 106, 107)] * 3
    res = run(CrossKDNType(**BARS), make_bars(rows))
    assert [s.i for s in res.signals] == [17]
    assert res.signals[0].stop == 95 and res.signals[0].price == 107


def test_htf_minutes_matches_bar_ratio_on_any_timeframe():
    """htf_minutes（預設15，原文 15 分鐘K線）：依交易分鐘分組，5 分K×9 根＝45 分鐘、1 分K×9 根＝9 分鐘，
    與根數版 htf_bars=9 結果相同。"""
    for freq, minutes in (("5min", 45.0), ("1min", 9.0)):
        res = run(CrossKDNType(htf_minutes=minutes), make_bars(LONG_BARS, freq=freq))
        assert res.signals[0].i == 25 and res.signals[0].price == 108 and res.signals[0].stop == 95


def test_htf_minutes_incomplete_trailing_group_is_not_used():
    rows = [(100, 105, 95, 97)] * HTF + [(97, 130, 96, 128)] * 3
    assert run(CrossKDNType(htf_minutes=45.0), make_bars(rows)).signals == []


def test_htf_minutes_group_with_missing_bar_waits_for_next_bar():
    """組內缺K線、最後一根未走到分組終點：不能在該根就認定大週期收完，延到下一根才採用（不偷看未來）。"""
    import pandas as pd

    from wangtrader.core import prepare

    strat = CrossKDNType(htf_minutes=45.0)
    full = strat.prepare(prepare(make_bars(LONG_BARS)))
    assert full.at[16, "htf_regime"] == 0 and full.at[17, "htf_regime"] == 1
    gap = make_bars(LONG_BARS).drop(pd.Timestamp("2024-01-02 08:45") + pd.Timedelta(minutes=5 * 17))  # 刪第二組最後一根
    df = CrossKDNType(htf_minutes=45.0).prepare(prepare(gap))
    assert df.at[16, "htf_regime"] == 0 and df.at[17, "htf_regime"] == 1  # 第17根已是下一組第一根


def test_max_wait_minutes_converts_to_bars():
    import pandas as pd

    from wangtrader.methods.q2_04_01_cross_kd_n_type import _wait_bars

    df = pd.DataFrame({"trade_min": [0.0, 5.0, 10.0]})
    assert _wait_bars(df, 2, 10.0, 10) == 2  # 5 分K：10 分鐘＝2 根
    assert _wait_bars(df, 2, 12.0, 10) == 3  # 無條件進位
    assert _wait_bars(df, 2, None, 10) == 10  # 預設 None：用 max_wait 根數
