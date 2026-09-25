from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_05_01_extreme_three_soldiers import ExtremeThreeSoldiers

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_red_three_soldiers_immediate_entry():
    bars = make_bars([
        (10025, 10028, 10005, 10008),  # setup1，低點 10005 > 10000
        (10008, 10012, 10004, 10007),  # setup2，低點 10004 > 10000
        (10010, 10015, 10000, 10012),  # a：紅K，最低點 10000（盤中最低）
        (10012, 10018, 10003, 10016),  # b：紅K，收盤 10016 > 10012
        (10016, 10020, 10004, 10019),  # c：紅K，收盤 10019 > 10016，幅度 20 點
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="none"), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "紅三兵"
    assert sig.price == 10019 and sig.stop == 10000


def test_black_three_soldiers_pullback_entry():
    bars = make_bars([
        (10060, 10070, 10055, 10062),  # setup1，高點 10070 < 10100
        (10062, 10075, 10058, 10065),  # setup2，高點 10075 < 10100
        (10090, 10100, 10085, 10080),  # a：黑K，最高點 10100（盤中最高）
        (10080, 10095, 10060, 10065),  # b：黑K，收盤 10065 < 10080
        (10065, 10090, 10030, 10035),  # c：黑K，收盤 10035 < 10065，幅度 70 點 > 30 → 補進場
        (10040, 10085, 10038, 10082),  # 拉回到 10080 觸價成交
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="none"), bars)
    assert res.signals[0].reason == "黑三兵(補進場)"
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 10080 and t.entry_i == 6


def test_amplitude_too_small_is_filtered():
    bars = make_bars([
        (10020, 10022, 10008, 10010),
        (10010, 10011, 10006, 10008),
        (10008, 10010, 10000, 10004),  # a：紅K，最低點 10000
        (10004, 10006, 10001, 10005),  # b：紅K，收盤 10005 > 10004
        (10005, 10007, 10002, 10006),  # c：紅K，收盤 10006 > 10005，幅度僅 7 點 < 10
    ], prev_day=PREV)
    assert run(ExtremeThreeSoldiers(), bars).signals == []


def test_not_extreme_position_is_filtered():
    bars = make_bars([
        (10020, 10022, 9990, 10008),   # 早盤先探至 9990（比 a 低點更低）
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),  # a：紅K，最低點 10000，但非當下盤中最低（早盤 9990 更低）
        (10012, 10018, 10003, 10016),
        (10016, 10020, 10004, 10019),
    ], prev_day=PREV)
    assert run(ExtremeThreeSoldiers(), bars).signals == []


def test_doji_breaks_pattern():
    bars = make_bars([
        (10025, 10028, 10005, 10008),
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),  # a：紅K，最低點 10000
        (10012, 10012, 10003, 10012),  # b：十字線（收盤=開盤），破壞型態
        (10016, 10020, 10004, 10019),
    ], prev_day=PREV)
    assert run(ExtremeThreeSoldiers(), bars).signals == []


def test_stopped_signal_not_repeated_same_session():
    bars = make_bars([
        (10025, 10028, 10005, 10008),
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),  # a1：紅K，最低點 10000
        (10012, 10018, 10003, 10016),  # b1
        (10016, 10020, 10004, 10019),  # c1：紅三兵成立，進場，停損 10000
        (10019, 10019, 9995, 9996),    # 觸及停損 10000 出場
        (9996, 10001, 9990, 9994),     # setup1'，低點 9990 > 9985
        (9994, 9996, 9985, 9992),      # setup2'
        (9990, 10000, 9985, 9995),     # a2：紅K，最低點 9985（新的盤中最低，但同方向已停損過）
        (9995, 10005, 9989, 10000),    # b2
        (10000, 10012, 9990, 10008),   # c2：本應構成第二次紅三兵，但 F5 應過濾
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="none"), bars)
    assert len(res.signals) == 1
    assert res.signals[0].reason == "紅三兵"


def test_retrace_exit_after_pullback_to_entry():
    bars = make_bars([
        (10025, 10028, 10005, 10008),
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),  # a：紅K，最低點 10000
        (10012, 10018, 10003, 10016),  # b
        (10016, 10020, 10004, 10019),  # c：紅三兵成立，進場價 10019
        (10019, 10040, 10018, 10038),  # 獲利拉開，最高來到 10040（獲利 21 點 > 15）
        (10038, 10039, 10018, 10019),  # 折返回到進場價 10019 附近 → 出場
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="retrace"), bars)
    assert res.trades[0].reason_out == "折返停利"


def test_equal_lows_in_three_soldiers_allowed():
    """p.162：三根K線低點相同是允許的（層級2轉折點以不嚴格比較認定）。"""
    bars = make_bars([
        (10025, 10028, 10005, 10008),
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),  # a：紅K，最低點 10000
        (10012, 10018, 10000, 10016),  # b：低點與 a 相同
        (10016, 10020, 10000, 10019),  # c：低點與 a 相同，幅度 20
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="none"), bars)
    assert res.signals and res.signals[0].reason == "紅三兵" and res.signals[0].stop == 10000


def test_ladder_exit_trails_20_points_from_best():
    """p.171 圖5-20：初始獲利 20 點後啟動折返 20 點停利，停利點隨新高上移。"""
    bars = make_bars([
        (10025, 10028, 10005, 10008),
        (10008, 10012, 10004, 10007),
        (10010, 10015, 10000, 10012),
        (10012, 10018, 10003, 10016),
        (10016, 10020, 10004, 10019),  # 進場 10019
        (10019, 10045, 10018, 10044),  # 獲利 26 > 20 啟動
        (10044, 10070, 10043, 10068),  # 最高 10070 → 停利線 10050
        (10068, 10069, 10049, 10050),  # 收盤回落 20 點 → 出場
    ], prev_day=PREV)
    res = run(ExtremeThreeSoldiers(exit_mode="ladder"), bars)
    t = res.trades[0]
    assert t.reason_out == "階梯式移動停利" and t.exit_price == 10050
