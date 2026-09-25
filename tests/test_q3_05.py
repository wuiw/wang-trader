from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_05_break_three_high_low import BreakThreeHighLow

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000，開盤價與平盤相同以避免跳空前提影響


def test_break_three_low_immediate_entry():
    bars = make_bars([
        (10000, 10010, 9995, 10005),
        (10005, 10050, 10040, 10045),  # A：當下最高
        (10045, 10048, 10038, 10040),
        (10040, 10042, 10035, 10038),
        (10038, 10039, 10028, 10032),  # 收盤同時跌破前1、前3根低點，距極端18點
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "破三低"
    assert sig.price == 10032 and sig.stop == 10051  # 停損在極端點 10050 上方 1 跳（p.113「觸及 A 高點停損」）
    assert res.trades[0].entry_price == 10032


def test_break_three_low_one_bar_after_extreme():
    # 圖5-4／5-11／5-12：最高K線後隔一根即以大黑K跌破前三根低點，比較區間可含最高K線之前的K線
    bars = make_bars([
        (10000, 10035, 9998, 10033),
        (10034, 10040, 10032, 10038),
        (10038, 10045, 10035, 10043),
        (10043, 10050, 10041, 10048),  # A：當下最高 10050
        (10048, 10049, 10028, 10031),  # 隔根收盤 10031 跌破前1根低點 10041 與前3根區間低點 10032，距極端19點
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "破三低" and sig.price == 10031 and sig.stop == 10051


def test_extreme_bar_itself_breaking_three_lows_is_a_signal():
    # 圖5-2（p.103）：最高K線當根收盤即跌破前三根區間低點
    bars = make_bars([
        (10000, 10010, 9995, 10005),
        (10005, 10015, 10002, 10012),
        (10012, 10020, 10008, 10018),
        (10018, 10030, 9990, 9993),    # 創新高 10030 後收 9993，跌破前三根低點；距極端 37 → 補進場
        (9993, 10012, 9990, 10008),    # 反彈到 10010 → 成交
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    assert res.signals[0].side == Side.SHORT and res.signals[0].reason == "破三低(補進場)"
    assert res.trades[0].entry_price == 10010 and res.trades[0].entry_i == 5


def test_break_three_high_needs_pullback_when_far():
    bars = make_bars([
        (10000, 10005, 9998, 10002),
        (10002, 10004, 9985, 9990),   # B：當下最低
        (9990, 9994, 9987, 9992),
        (9992, 9996, 9989, 9994),
        (9998, 10012, 9996, 10010),   # 收盤同時突破前1、前3根高點，距極端25點 → 補進場
        (10008, 10009, 9995, 10000),  # 拉回跌破 10005（極端+20）→ 成交
        (10000, 10003, 9997, 10001),
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    assert res.signals[0].reason == "過三高(補進場)"
    assert res.signals[0].stop == 9985  # 補進場後停損在極端點
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 10005 and t.entry_i == 6


def test_not_enough_bars_before_signal_is_filtered():
    # 圖5-3（p.104）：開盤第一根即最高，第三根就跌破前兩根低點，前面不足三根 → 不算破三低
    bars = make_bars([
        (10040, 10050, 10038, 10045),  # A：開盤第一根即當下最高
        (10045, 10047, 10036, 10040),
        (10040, 10041, 10020, 10025),  # 只有兩根可比較（距極端 25，若成立會掛補進場單）
        (10025, 10030, 10022, 10028),
    ], prev_day=PREV)
    assert run(BreakThreeHighLow(), bars).signals == []


def test_gap_up_blocks_long_before_pivot_confirmed():
    bars = make_bars([
        (10000, 10010, 9995, 10005),
        (10005, 10012, 10000, 10008),
        (10008, 10014, 10002, 10011),
        (10011, 10020, 10009, 10018),  # 收盤突破前1、前3根高點，但跳高開盤尚無層級1谷點
    ], prev_day=(9800, 9850, 9700, 9800))
    res = run(BreakThreeHighLow(), bars)
    assert [s for s in res.signals if s.side == Side.LONG] == []


def test_distance_beyond_40_is_ignored():
    bars = make_bars([
        (10000, 10005, 9995, 10002),
        (10002, 10050, 10040, 10045),  # 最高K線
        (10045, 10048, 10010, 10042),
        (10042, 10043, 10005, 10012),
        (10005, 10006, 9995, 9999),    # 距極端 51 點，忽略不操作
    ], prev_day=PREV)
    assert run(BreakThreeHighLow(), bars).signals == []


def test_overlapping_body_blocks_reversal():
    bars = make_bars([
        (10000, 10005, 9998, 10002),
        (10002, 10004, 9985, 9990),   # 極端低點
        (9990, 9994, 9987, 9992),
        (9992, 9996, 9989, 9994),
        (9998, 10008, 9996, 10005),   # 過三高買訊，收盤10005（多單進場，實體9998~10005）
        (10005, 10015, 10000, 10010),  # 新的極端高點
        (10010, 10012, 10002, 10006),
        (10006, 10009, 10001, 10004),
        (10004, 10005, 9997, 9999),   # 破三低空訊訊號K，實體9999~10004 與原多單實體重疊 → 忽略
        (9999, 10002, 9995, 10000),
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    assert len([s for s in res.signals if s.side == Side.SHORT]) == 0
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 10005 and t.reason_out == "收盤平倉"


def test_signal_beyond_4_bars_after_extreme_is_ignored():
    # p.107：訊號K須在極端K後最多4根K線以內，超過即無效（結構上原本會成立破三低）
    bars = make_bars([
        (10005, 10050, 10040, 10045),  # A：當下最高
        (10045, 10048, 10038, 10040),
        (10040, 10042, 10035, 10038),
        (10038, 10039, 10032, 10036),
        (10036, 10037, 10030, 10034),
        (10034, 10035, 10015, 10020),  # 收盤同時跌破前1、前3根低點，但距 A 已達5根K線 → C4 過濾
    ], prev_day=PREV)
    assert run(BreakThreeHighLow(), bars).signals == []


def test_signal_close_masked_by_intervening_bar_is_ignored():
    # p.106：極端K與訊號K之間，若有K線最低點低於訊號K收盤，視為遮蔽，訊號不成立
    # 用 max_signal_delay 放寬到6，讓遮蔽K線（D）落在「前3根」結構比較窗口之外，凸顯C5獨立於C2/C3窗口
    bars = make_bars([
        (10005, 10050, 10040, 10045),  # A：當下最高
        (10045, 10046, 9980, 9990),    # D：緊接極端K，低點9980（遮蔽用）
        (9990, 10005, 9985, 10000),
        (10000, 10010, 9995, 10005),
        (10005, 10015, 10000, 10010),
        (10010, 10012, 10002, 10008),
        (10008, 10009, 9970, 9985),    # 訊號K：收盤9985，結構上跌破前1/前3根低點，但被D（低點9980<9985）遮蔽
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(max_signal_delay=6), bars)
    assert res.signals == []


def test_retrace_15pts_flat_exit():
    # p.111：獲利曾達15點以上又折返回進場價 → 撤單平倉
    bars = make_bars([
        (10000, 10010, 9995, 10005),
        (10005, 10050, 10040, 10045),  # A：當下最高
        (10045, 10048, 10038, 10040),
        (10040, 10042, 10035, 10038),
        (10038, 10039, 10028, 10032),  # 破三低空訊，進場 10032，停損 10051
        (10032, 10033, 10010, 10015),  # 行情下行，獲利達15點以上（最低10010，距10032達22點）
        (10015, 10038, 10012, 10035),  # 折返回到進場價以上（獲利<=0）→ 撤單平倉
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 10032
    assert t.reason_out == "折返停利" and t.exit_price == 10035


def test_stop_without_15pts_reverses_on_new_extreme_close():
    bars = make_bars([
        (10000, 10010, 9995, 10005),
        (10005, 10050, 10040, 10045),  # A：當下最高
        (10045, 10048, 10038, 10040),
        (10040, 10042, 10035, 10038),
        (10038, 10039, 10028, 10032),  # 破三低空訊，停損 10051
        (10040, 10060, 10038, 10055),  # 觸及停損，且收盤創session新高(>10050) → 反手做多
        (10055, 10058, 10050, 10053),
    ], prev_day=PREV)
    res = run(BreakThreeHighLow(), bars)
    assert len(res.signals) == 2
    rev = res.signals[1]
    assert rev.side == Side.LONG and rev.reason == "停損反手" and rev.stop == 10035
    assert res.trades[0].reason_out == "停損" and res.trades[0].exit_price == 10051
    assert res.trades[1].side == Side.LONG and res.trades[1].entry_price == 10055
