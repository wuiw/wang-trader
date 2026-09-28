from datetime import time

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_06_five_in_a_row_reversal import FiveInARowReversal


def test_five_black_then_red_long_signal():
    bars = make_bars([
        (10100, 10105, 10085, 10090),  # 1 黑
        (10090, 10092, 10070, 10075),  # 2 黑
        (10075, 10077, 10055, 10060),  # 3 黑
        (10060, 10062, 10040, 10045),  # 4 黑
        (10045, 10047, 10020, 10025),  # 5 黑，當下最低，下影線5點
        (10025, 10040, 10022, 10035),  # 隔根收紅，未破新低、未過前高 → 買訊
        (10035, 10038, 10030, 10032),
    ])
    res = run(FiveInARowReversal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "連五黑遇首紅"
    assert sig.price == 10035 and sig.stop == 10015
    assert res.trades[-1].entry_i == 5 and res.trades[-1].entry_price == 10035


def test_five_red_then_black_short_and_exit_on_new_low():
    bars = make_bars([
        (9900, 9920, 9895, 9915),   # 1 紅
        (9915, 9945, 9910, 9940),   # 2 紅
        (9940, 9970, 9935, 9965),   # 3 紅
        (9965, 9995, 9960, 9990),   # 4 紅
        (9990, 10035, 9985, 10030),  # 5 紅，當下最高，上影線5點
        (10025, 10032, 9995, 10005),  # 隔根收黑，未過新高、收盤未破前低 → 空訊，進場
        (10005, 10008, 9880, 9885),  # 黑，繼續下殺（延續空單）
        (9885, 9887, 9800, 9805),   # 黑
        (9805, 9807, 9700, 9705),   # 黑
        (9705, 9707, 9600, 9605),   # 黑，5根黑K，當下最低，下影線5點
        (9605, 9615, 9590, 9610),   # 隔根收紅但影線創新低 → 僅作既有空單出場，非新買訊
    ])
    res = run(FiveInARowReversal(), bars)
    entries = [s for s in res.signals if True]
    assert len(entries) == 1
    assert entries[0].side == Side.SHORT and entries[0].reason == "連五紅遇首黑"
    assert entries[0].price == 10005 and entries[0].stop == 10025
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 10005
    assert t.exit_price == 9610 and t.reason_out == "平倉(創新低)"


def test_v_shape_diversion_is_not_this_signal():
    bars = make_bars([
        (10100, 10105, 10085, 10090),
        (10090, 10092, 10070, 10075),
        (10075, 10077, 10055, 10060),
        (10060, 10062, 10040, 10045),
        (10045, 10047, 10020, 10025),  # 5 黑，最後一根黑K最高點 10047
        (10025, 10055, 10022, 10050),  # 隔根收紅，未破新低，但收盤 10050 過前高 10047 → V字轉折，非本訊號
    ])
    assert run(FiveInARowReversal(), bars).signals == []


def test_last_bar_shadow_too_long_is_filtered():
    bars = make_bars([
        (10100, 10105, 10085, 10090),
        (10090, 10092, 10070, 10075),
        (10075, 10077, 10055, 10060),
        (10060, 10062, 10040, 10045),
        (10045, 10047, 9990, 10025),  # 5 黑，但下影線 35點，遠超過5點濾網
        (10025, 10040, 10022, 10035),  # 反色K線正常，但因濾網未成立訊號
    ])
    assert run(FiveInARowReversal(), bars).signals == []


def test_run_shorter_than_five_is_filtered():
    bars = make_bars([
        (10100, 10105, 10085, 10090),
        (10090, 10092, 10070, 10075),
        (10075, 10077, 10055, 10060),
        (10060, 10062, 10040, 10045),  # 只有 4 根黑K
        (10045, 10060, 10042, 10055),  # 隔根收紅
    ])
    assert run(FiveInARowReversal(), bars).signals == []


def test_no_entry_after_close_cutoff_is_filtered():
    # p.123：訊號發生時間距當日收盤不到1小時，一般忽略不操作（此處以絕對收盤前時刻模擬）
    bars = make_bars([
        (10100, 10105, 10085, 10090),  # 1 黑
        (10090, 10092, 10070, 10075),  # 2 黑
        (10075, 10077, 10055, 10060),  # 3 黑
        (10060, 10062, 10040, 10045),  # 4 黑
        (10045, 10047, 10020, 10025),  # 5 黑，當下最低，下影線5點
        (10025, 10040, 10022, 10035),  # 隔根收紅，未破新低、未過前高 → 訊號時間 09:10，晚於 09:00 cutoff
        (10035, 10038, 10030, 10032),
    ])
    res = run(FiveInARowReversal(no_entry_after=time(9, 0)), bars)
    assert res.signals == []


def test_red_bar_closing_below_prior_close_breaks_the_run():
    # 「上漲K線」＝收盤高於前一根收盤（p.55, 127）：第 3 根雖收紅且創高，但收盤低於前一根，連續段重新起算
    bars = make_bars([
        (9900, 9920, 9895, 9915),   # 1 紅
        (9915, 9945, 9910, 9940),   # 2 紅
        (9900, 9950, 9898, 9925),   # 3 紅，高點創新高但收盤 9925 < 9940 → 非上漲K線
        (9925, 9960, 9920, 9955),   # 4 紅
        (9955, 10000, 9950, 9995),  # 5 紅，當下最高，上影線 5 點
        (9995, 9997, 9970, 9975),   # 隔根收黑：若把 1~5 視為連五紅會成立空訊，但連續段只有 3 根
    ])
    assert run(FiveInARowReversal(), bars).signals == []


def _long_then_flat_rows():
    return [
        (10100, 10105, 10085, 10090),
        (10090, 10092, 10070, 10075),
        (10075, 10077, 10055, 10060),
        (10060, 10062, 10040, 10045),
        (10045, 10047, 10020, 10025),
        (10025, 10040, 10022, 10035),  # 買訊，進場 10035（i=5）
        (10035, 10038, 10030, 10032),  # 經過 5 分鐘，無獲利
        (10032, 10036, 10028, 10030),  # 經過 10 分鐘，無獲利
        (10030, 10034, 10026, 10031),
    ]


def test_stale_minutes_exit_when_no_profit():
    """stale_minutes：持倉經過分鐘數達門檻仍無獲利 → 平倉（p.134 圖6-16，以時間戳計、不綁週期）。"""
    res = run(FiveInARowReversal(stale_minutes=10), make_bars(_long_then_flat_rows()))
    t = res.trades[0]
    assert t.reason_out == "逾時平倉" and t.exit_i == 7
    # 1 分K 下同樣 10 分鐘尚未到 → 不平倉，由收盤平倉
    res1 = run(FiveInARowReversal(stale_minutes=10), make_bars(_long_then_flat_rows(), freq="1min"))
    assert res1.trades[0].reason_out == "收盤平倉"


def test_stale_minutes_takes_precedence_over_bars():
    res = run(FiveInARowReversal(stale_minutes=10, stale_bars=1), make_bars(_long_then_flat_rows()))
    assert res.trades[0].exit_i == 7
    res_bars = run(FiveInARowReversal(stale_bars=1), make_bars(_long_then_flat_rows()))
    assert res_bars.trades[0].exit_i == 6  # 預設 stale_minutes=None → 用根數
