from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_07_falling_line_reversal import FallingLineReversal


def test_counter_buy_point_at_high_position():
    bars = make_bars([
        (100, 102, 99, 101, 100),
        (101, 110, 100, 108, 100),
        (108, 116, 107, 115, 100),  # a：長紅K，當下新高 → 高檔
        (110, 111, 103, 105, 100),  # b：跳低開盤，收破a中點與最低點 → 下墜線，最高點116
        (112, 122, 111, 120, 100),  # 收盤突破116 → 反軋買點
    ])
    res = run(FallingLineReversal(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "反軋買點"
    assert sig.price == 120 and sig.stop == 111


def test_downtrend_buy_point_has_no_stop():
    bars = make_bars([
        (200, 205, 195, 203, 100),
        (203, 204, 160, 162, 100),
        (162, 163, 150, 152, 100),
        (100, 112, 98, 110, 100),   # a：長紅反彈，距先前高點205跌幅>=15% → 跌勢中
        (104, 106, 90, 95, 100),    # b：跳低開盤，跌破a中點與最低點 → 下墜線，最高點112
        (100, 118, 99, 115, 100),   # 收盤突破112 → 跌勢中買點
    ])
    res = run(FallingLineReversal(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "跌勢中買點(下墜線)"
    assert sig.stop is None


def test_c4_confirm_exits_long_position():
    bars = make_bars([
        (100, 102, 99, 101, 100),
        (101, 110, 100, 108, 100),
        (108, 116, 107, 115, 100),  # a1：長紅K，高檔
        (110, 111, 103, 105, 100),  # b1：下墜線，最高點116
        (112, 122, 111, 120, 100),  # 突破116 → 進場 多，停損111
        (120, 132, 119, 130, 100),  # a2：長紅K，再創新高
        (125, 126, 113, 115, 100),  # b2：下墜線，最高點132
        (118, 119, 112, 113, 100),  # 隔一根收黑 → C5確認，出場多單
    ])
    res = run(FallingLineReversal(), bars)
    assert len(res.signals) == 1  # 第二個下墜線未被突破，不產生新訊號
    assert res.trades[0].side == Side.LONG and res.trades[0].entry_price == 120
    assert res.trades[0].reason_out == "下墜線反轉確認出場" and res.trades[0].exit_price == 113


def test_surge_volume_needs_shrink_before_breakout():
    bars = make_bars([
        (100, 102, 99, 101, 100),
        (101, 102, 100, 101, 100),
        (101, 116, 100, 115, 400),  # a：長紅K爆量（400 >= 均量100*2）
        (110, 111, 90, 95, 200),    # b：下墜線，最高點116
        (112, 120, 111, 118, 300),  # 收盤突破116，但量仍大(300 > 100*1.2) → 不成立
        (117, 121, 116.5, 119, 90),  # 量縮到位(90 <= 120) → 反軋買點成立
    ])
    res = run(FallingLineReversal(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "反軋買點"
    assert sig.price == 119 and sig.stop == 116.5
