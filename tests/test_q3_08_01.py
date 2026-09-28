import pandas as pd
from helpers import make_bars

from wangtrader.core import Side, prepare, run
from wangtrader.methods.q3_08_01_ma_breakout import MaBreakout

PREV = (10000, 10005, 9995, 10000)


def test_long_breakout_immediate_entry():
    """突破均線 -> 攻擊創新高 -> 休息 -> 收盤突破峰位濾網，距極端 <=20 點立即進場。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 收盤站上MA10，趨勢轉折起點
        (10005, 10040, 10003, 10018),  # 攻擊新高
        (10018, 10050, 10015, 10028),  # 攻擊新高
        (10028, 10045, 10020, 10035),  # 休息（高點未過前高）
        (10035, 10040, 10025, 10036),  # 休息
        (10046, 10058, 10040, 10052),  # 收盤突破峰位濾網(10045) -> 買訊
    ], prev_day=PREV)
    res = run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="none"), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "均線買訊"
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 10052 and t.entry_i == 8


def test_short_breakout_stop_is_close_plus_20():
    """跌破均線 -> 休息 -> 收盤跌破谷位濾網；訊號K高點距收盤 <=20 立即進場，停損＝收盤+20（圖8-9）。"""
    bars = make_bars([
        (10000, 10012, 9998, 10010),
        (10010, 10015, 10008, 10015),
        (10015, 10017, 9992, 9995),    # 跌破MA10，趨勢轉折起點，攻擊低點 9992
        (9995, 9998, 9994, 9985),      # 休息（低點未破前低）
        (9985, 9990, 9975, 9980),      # 收盤跌破谷位濾網(9992) -> 空訊
    ], prev_day=PREV)
    res = run(MaBreakout(ma_period=3, strict_distance=True, exit_mode="none"), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "均線空訊"
    assert sig.price == 9980 and sig.stop == 10000


def test_large_bar_waits_for_pullback_with_stop_at_extreme():
    """大K線（p.162-163）：訊號K高點距收盤 >20 -> 掛「高點-20」補進場限價單，停損設在該高點。"""
    bars = make_bars([
        (10000, 10012, 9998, 10010),
        (10010, 10015, 10008, 10015),
        (10015, 10017, 9992, 9995),
        (9995, 9998, 9994, 9985),
        (9990, 10030, 9960, 9965),     # 收盤跌破谷位 9992，但高點距收盤 65 點
        (9965, 9990, 9950, 9960),      # 未反彈到 10010，限價未成交
    ], prev_day=PREV)
    res = run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="none"), bars)
    sig = res.signals[0]
    assert sig.reason == "均線空訊(補進場)" and sig.price == 10010 and sig.stop == 10030
    assert res.trades == []


def test_filter_line_is_attack_peak_not_rest_bar_high():
    """峰位濾網＝休息前最高點 C（p.157）：休息K收盤高於前一根休息K高點但未過 C 高點，不算訊號；
    之後收盤突破 C 高點才成立。rest_extreme_filter=True（圖8-17 讀法）則前者即成立。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 站上MA10
        (10005, 10050, 10003, 10040),  # 攻擊高點 C=10050
        (10040, 10042, 10030, 10035),  # 休息1，高 10042
        (10035, 10046, 10033, 10045),  # 休息2：收盤 10045 > 休息1高點，但 < C
        (10045, 10058, 10043, 10055),  # 收盤突破 C -> 買訊
    ], prev_day=PREV)
    df = prepare(bars)
    sig = MaBreakout(ma_period=3).prepare(df)["sig_side"].tolist()
    assert sig[6] == 0 and sig[7] == 1
    sig2 = MaBreakout(ma_period=3, rest_extreme_filter=True).prepare(df)["sig_side"].tolist()
    assert sig2[6] == 1


def test_shadow_breach_requires_new_rest_before_signal():
    """只有影線突破峰位、收盤縮回 -> 失敗，須另尋峰位（p.156）：影線高點成為新攻擊高點，
    隔根直接收盤高於舊峰位但未過影線高點不算訊號。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10005, 10050, 10003, 10040),  # C=10050
        (10040, 10042, 10030, 10035),  # 休息
        (10035, 10060, 10033, 10045),  # 影線突破 10050，收盤未過 -> 新攻擊高點 10060
        (10045, 10055, 10043, 10053),  # 收盤 10053 > 舊峰位，但屬新一輪休息，不是訊號
        (10053, 10070, 10050, 10065),  # 收盤突破新峰位 10060 -> 買訊
    ], prev_day=PREV)
    df = prepare(bars)
    sig = MaBreakout(ma_period=3).prepare(df)["sig_side"].tolist()
    assert sig[6] == 0 and sig[7] == 0 and sig[8] == 1


def test_nearer_lower_peak_filter_used_before_original_peak():
    """L7（p.160-161，圖8-5）：休息期間若形成另一個較低的層級1峰點 B，濾網改用較近的 B，
    收盤突破 B 即成立買訊，不必等突破原先較高的峰點 A。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 站上MA10
        (10005, 10050, 10003, 10040),  # A：層級1峰點，高點10050
        (10040, 10042, 10030, 10035),  # 休息
        (10035, 10046, 10033, 10044),  # B：休息中的較低層級1峰點，高點10046（> 前後兩根）
        (10041, 10043, 10036, 10041),  # B 的右鄰（高10043<10046），確認 B 為層級1峰點
        (10041, 10049, 10037, 10048),  # 收盤10048突破B(10046)但未突破A(10050) -> 仍應成立買訊
    ], prev_day=PREV)
    df = prepare(bars)
    sig = MaBreakout(ma_period=3).prepare(df)["sig_side"].tolist()
    assert sig[8] == 1

    # 對照組：休息期間高點單調遞減，未形成新的層級1峰點 -> 濾網仍是原峰點A(10050)，同樣的收盤位置不成立
    bars2 = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10005, 10050, 10003, 10040),
        (10040, 10042, 10030, 10035),
        (10035, 10041, 10033, 10038),
        (10038, 10040, 10036, 10039),
        (10039, 10049, 10037, 10048),
    ], prev_day=PREV)
    df2 = prepare(bars2)
    sig2 = MaBreakout(ma_period=3).prepare(df2)["sig_side"].tolist()
    assert sig2[8] == 0


def test_f1_gap_turn_uses_session_range():
    """F1 跳空情境（p.162）：均線轉折發生在本日第一根時，距轉折 >40 改看開盤後高低震幅 <=40。"""
    prev = [
        (10000, 10005, 9995, 10000),
        (10000, 10004, 9996, 10001),
        (10001, 10005, 9997, 10002),
    ]
    day = [
        (9900, 9905, 9880, 9890),    # 跳低開盤，收盤跌破 MA -> 轉折在第一根（bar_no 0）
        (9890, 9892, 9870, 9875),
        (9875, 9880, 9872, 9878),    # 休息
        (9878, 9879, 9860, 9862),    # 收盤跌破谷位 9870 -> 空訊，距轉折 28 點
    ]
    bars = make_bars(prev + day, freq="5min")
    # 讓 day 成為第二個交易日
    idx = list(bars.index[: len(prev)]) + [pd.Timestamp("2024-01-03 08:45") + k * pd.Timedelta("5min") for k in range(len(day))]
    bars.index = pd.DatetimeIndex(idx)
    res = run(MaBreakout(ma_period=3, use_swing_filter=False, exit_mode="none"), bars)
    assert len(res.signals) == 1  # 距轉折 28 點在 10~40 之間，一般規則通過

    day_far = [
        (9900, 9905, 9880, 9890),
        (9890, 9892, 9850, 9855),
        (9855, 9860, 9852, 9858),
        (9858, 9859, 9835, 9838),    # 距轉折 52 點 >40；開盤後震幅 70 點 >40 -> 忽略
    ]
    bars2 = make_bars(prev + day_far, freq="5min")
    bars2.index = pd.DatetimeIndex(idx)
    assert run(MaBreakout(ma_period=3, use_swing_filter=False), bars2).signals == []
    # 放寬震幅界限到 80 點則視為有效
    res3 = run(MaBreakout(ma_period=3, use_swing_filter=False, gap_open_range_max=80, exit_mode="none"), bars2)
    assert len(res3.signals) == 1


def test_f4_carryover_measures_from_session_low_for_long():
    """F4 延續開盤（p.184）：轉折在前一日時，多訊看「收盤距開盤後最低點」是否 <=60。"""
    prev = [
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 站上 MA（轉折在前一日）
        (10005, 10030, 10003, 10025),
    ]
    day = [
        (10040, 10060, 10038, 10050),  # 跳高延續，攻擊
        (10050, 10055, 10045, 10048),  # 休息
        (10048, 10070, 10046, 10065),  # 收盤突破峰位 10060 -> 買訊，距開盤後最低點 27
    ]
    bars = make_bars(prev + day)
    idx = list(bars.index[: len(prev)]) + [pd.Timestamp("2024-01-03 08:45") + k * pd.Timedelta("5min") for k in range(len(day))]
    bars.index = pd.DatetimeIndex(idx)
    res = run(MaBreakout(ma_period=3, use_swing_filter=False, exit_mode="none"), bars)
    assert len(res.signals) == 1 and res.signals[0].side == Side.LONG
    # 距開盤後最低點超過 60 點則忽略
    day_far = [
        (10040, 10060, 10038, 10050),
        (10050, 10055, 10045, 10048),
        (10048, 10110, 10046, 10105),  # 收盤距開盤後最低點 67 > 60
    ]
    bars2 = make_bars(prev + day_far)
    bars2.index = pd.DatetimeIndex(idx)
    assert run(MaBreakout(ma_period=3, use_swing_filter=False), bars2).signals == []


def test_f3_too_close_to_turn_point_ignored():
    """F3：訊號K線收盤離均線轉折點不足10點 -> 忽略。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),  # 轉折點 10005
        (10005, 10007, 10002, 10004),
        (10004, 10015, 10001, 10012),  # 距轉折點僅 7 點
    ], prev_day=PREV)
    assert run(MaBreakout(ma_period=3, strict_distance=True), bars).signals == []
    # 關閉距離濾網（海外商品情境）則訊號成立
    res = run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="none"), bars)
    assert res.signals[0].side == Side.LONG


def test_f1_too_far_from_turn_point_ignored():
    """F1：訊號K線收盤離均線轉折點超過40點（非跳空延續）-> 忽略。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 轉折點 10005
        (10005, 10040, 10003, 10018),
        (10018, 10050, 10015, 10028),
        (10028, 10045, 10020, 10035),
        (10035, 10040, 10025, 10036),
        (10036, 10060, 10030, 10055),  # 距轉折點 50 點
    ], prev_day=PREV)
    assert run(MaBreakout(ma_period=3, strict_distance=True), bars).signals == []


def test_reverse_on_opposite_extreme_signal():
    """持有多單期間出現極端位置頂雙黑逆向訊號 -> 立即平倉並反手（p.169）。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10005, 10040, 10003, 10018),
        (10018, 10050, 10015, 10028),
        (10028, 10045, 10020, 10035),
        (10035, 10040, 10025, 10036),
        (10046, 10058, 10040, 10052),  # 多單進場，停損 10032
        (10060, 10070, 10050, 10055),  # a：當下最高的黑K
        (10055, 10060, 10033, 10035),  # b：黑K收盤跌破a低點 -> 頂雙黑，強制反手（未觸及停損）
        (10035, 10040, 10020, 10025),
    ], prev_day=PREV)
    res = run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="none"), bars)
    assert res.trades[0].side == Side.LONG and res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT and res.trades[1].reason_in == "逆向極端訊號反手"
    assert res.signals[-1].stop == 10055  # 反手停損＝反手收盤 + 20


def test_retrace_exit_gives_back_fixed_points_from_peak():
    """折返停利：達初始獲利後由最高獲利回吐 retrace_points 點觸價出場（p.163, 184-185）。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10005, 10040, 10003, 10018),
        (10018, 10050, 10015, 10028),
        (10028, 10045, 10020, 10035),
        (10035, 10040, 10025, 10036),
        (10046, 10058, 10040, 10052),  # 進場 10052
        (10052, 10070, 10050, 10068),  # 獲利16 > 15 起算
        (10068, 10080, 10065, 10078),  # 最高獲利 28（best 10080）
        (10078, 10079, 10060, 10063),  # 回吐 17 點 >=15 -> 出場
    ], prev_day=PREV)
    res = run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="retrace",
                          reverse_on_opposite_extreme=False), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 10063


def test_wait_bars_minutes_converted_by_bar_interval():
    """max_wait_minutes：以同交易日相鄰K線時間差換成根數；None 或 time 欄非時間戳時用 max_wait 根。"""
    from helpers import make_bars as _mb

    from wangtrader.core import prepare as _prep
    from wangtrader.methods.q3_08_01_ma_breakout import Params as _P, _wait_bars

    df = _prep(_mb([(100, 101, 99, 100)] * 6, freq="3min"))
    assert _wait_bars(df, 5, _P()) == 10
    assert _wait_bars(df, 5, _P(max_wait_minutes=10)) == 3
    assert _wait_bars(df, 5, _P(max_wait_minutes=1)) == 1
    assert _wait_bars(df.assign(time=range(len(df))), 5, _P(max_wait_minutes=10)) == 10


def _ma_touch_rows(untouched: int):
    """進場（i=8，10052）後連續 untouched 根未觸 MA3，接著一根觸及均線。"""
    rows = [
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10005, 10040, 10003, 10018),
        (10018, 10050, 10015, 10028),
        (10028, 10045, 10020, 10035),
        (10035, 10040, 10025, 10036),
        (10046, 10058, 10040, 10052),  # 進場 10052
    ]
    c = 10052
    for _ in range(untouched):
        c += 10
        rows.append((c - 10, c + 2, c - 5, c))  # 低點始終高於 MA3（≈ c-10）
    rows.append((c, c + 2, c - 40, c - 30))  # 觸及均線
    rows.append((c - 30, c - 28, c - 35, c - 32))
    return rows


def _run_touch(rows, freq="5min", **kw):
    return run(MaBreakout(ma_period=3, strict_distance=False, exit_mode="ma_touch",
                          reverse_on_opposite_extreme=False, **kw), make_bars(rows, prev_day=PREV, freq=freq))


def test_ma_touch_minutes_default_60():
    """均線遵循性停利：預設 ma_touch_minutes=60（p.172「連續超過一個小時以上」）。5 分K 12 根＝60 分鐘 → 出場；
    11 根＝55 分鐘 → 不出場。"""
    t = _run_touch(_ma_touch_rows(12)).trades[0]
    assert t.reason_out == "均線遵循性停利" and t.exit_i == 8 + 12 + 1
    assert _run_touch(_ma_touch_rows(11)).trades[0].reason_out != "均線遵循性停利"


def test_ma_touch_minutes_independent_of_bar_period():
    """1 分K 下 12 根只有 12 分鐘 → 不出場；改回根數模式（ma_touch_minutes=None）則 12 根即出場。"""
    assert _run_touch(_ma_touch_rows(12), freq="1min").trades[0].reason_out != "均線遵循性停利"
    t = _run_touch(_ma_touch_rows(12), freq="1min", ma_touch_minutes=None).trades[0]
    assert t.reason_out == "均線遵循性停利"
