from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare, run
from wangtrader.methods.q2_04_02_four_pillars import FourPillars

# prev_high/prev_low 刻意設在不可能觸及的極端值，讓測試只聚焦在「昨收」這個關卡上，
# 不被其他三柱（昨高/昨低/今開）干擾。sess_open 也用同樣手法（第一根開盤設在不可能再被
# 觸及的極端值）讓「今開」這一柱永遠停在同一側、不會翻邊。
PREV = (9990, 999999, -999999, 10000)  # 昨收＝10000

# 多方：開盤後 3 根收在昨收(10000)下方 → 向上突破 → N型三步驟 → 買訊
LONG_BARS = [
    (-999999, 9995, -999999, 9990),   # 今開＝-999999（永不再觸及），弱側第1根（收盤9990<10000）
    (9990, 9996, 9985, 9992),         # 弱側第2根
    (9992, 9997, 9988, 9994),         # 弱側第3根（達到 min_side_bars=3）
    (9994, 10008, 9993, 10005),       # 突破昨收，翻邊，0點候選＝9993
    (10005, 10012, 10001, 10008),
    (10008, 10015, 10003, 10012),
    (10012, 10025, 10008, 10020),     # (1) 峰點候選 10025
    (10020, 10022, 10010, 10015),
    (10015, 10018, 10005, 10008),     # (2) 谷點候選 10005（confirm 於下下根）
    (10008, 10010, 10006, 10007),
    (10007, 10009, 10006, 10007),     # (2) 於此根確認
    (10009, 10030, 10008, 10028),     # 收盤10028 > 10025 → 買訊
]

# 空方：以 20000 為中心整體反射多方序列，得到對稱的「昨收之下」突破訊號
SHORT_BARS = [
    (1019999, 1019999, 10005, 10010),
    (10010, 10015, 10004, 10008),
    (10008, 10012, 10003, 10006),
    (10006, 10007, 9992, 9995),
    (9995, 9999, 9988, 9992),
    (9992, 9997, 9985, 9988),
    (9988, 9992, 9975, 9980),
    (9980, 9990, 9978, 9985),
    (9985, 9995, 9982, 9992),
    (9992, 9994, 9990, 9993),
    (9993, 9994, 9991, 9993),
    (9991, 9992, 9970, 9972),
]


def test_breakout_above_prev_close_long_signal():
    # 結構停損（層級2谷點10005）距進場價23點 > stop_points_cap(20) → 預設情況下改用進場價-20
    bars = make_bars(LONG_BARS, prev_day=PREV)
    res = run(FourPillars(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "四柱突破(prev_close)"
    assert sig.price == 10028 and sig.stop == 10008


def test_breakdown_below_prev_close_short_signal():
    # 結構停損（層級2峰點9995）距進場價23點 > 20 → 預設情況下改用進場價+20
    bars = make_bars(SHORT_BARS, prev_day=PREV)
    res = run(FourPillars(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "四柱跌破(prev_close)"
    assert sig.price == 9972 and sig.stop == 9992


def test_major_event_stop_allows_exceeding_cap():
    """重大事件（如公投、選舉開票，p.152–153）停損可超過20點；預設關閉，開啟後改用結構性停損原值。"""
    bars = make_bars(LONG_BARS, prev_day=PREV)
    res = run(FourPillars(major_event_stop=True), bars)
    sig = res.signals[0]
    assert sig.stop == 10005  # 不受 stop_points_cap 限制，維持結構性層級2谷點


def test_stop_points_cap_is_configurable():
    bars = make_bars(LONG_BARS, prev_day=PREV)
    res = run(FourPillars(stop_points_cap=30), bars)
    assert res.signals[0].stop == 10005  # 23點在30點上限內，維持結構停損


def test_weak_side_less_than_three_bars_is_filtered():
    # 弱側只有 2 根（F1），即使之後價格同樣突破並完成N型三步驟，也不應產生訊號。
    rows = list(LONG_BARS)
    del rows[1]  # 拿掉一根弱側K線，讓翻邊前只剩 2 根收在昨收下方
    bars = make_bars(rows, prev_day=PREV)
    res = run(FourPillars(), bars)
    assert res.signals == []


def test_retrace_exit_after_pullback_to_entry():
    # 進場後拉出足夠獲利，再折返回進場價附近應觸發折返停利。
    extra = [
        (10028, 10060, 10027, 10058),  # 最高來到 10060，獲利 32 點 > 15
        (10058, 10059, 10027, 10028),  # 折返回到進場價 10028 附近 → 出場
    ]
    bars = make_bars(LONG_BARS + extra, prev_day=PREV)
    res = run(FourPillars(), bars)
    assert res.trades[0].reason_out == "折返停利"


def test_level_tracking_continues_while_position_held():
    """回歸測試（修 bug）：四柱關卡的根數/翻邊追蹤須每根K線持續更新，與是否持有部位無關
    （書中的「關卡前後K線根數」是對盤面的持續觀察，p.141；並非只在空手時才計數）。
    修正前 on_bar 在 ctx.pos 非 None 時完全不呼叫 _update_level，導致持倉期間所有四柱狀態
    整段凍結，出場後續用進場當下的陳舊根數/翻邊狀態繼續判斷，與盤面已經走出的行情脫節。"""
    bars = make_bars(LONG_BARS, prev_day=PREV)
    df = prepare(bars)
    strat = FourPillars()
    df = strat.prepare(df)
    pos = Position(Side.LONG, entry_i=0, entry_price=float(df.at[0, "close"]), stop=None, best=float(df.at[0, "close"]))
    lv = strat._levels["prev_high"]
    assert lv["run"] == 0
    ctx = Context(i=3, df=df, pos=pos, trades=[], stopped=None)
    strat.on_bar(ctx)
    assert strat._levels["prev_high"]["run"] > 0  # 持倉中仍應照常累加根數，而非維持凍結於 0
