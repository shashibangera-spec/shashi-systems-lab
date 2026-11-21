from scripts.backtest_btcusd_amt_pa import summary_for


def _trade(net, reason, *, funding_complete=True, net_funding=None):
    return {
        "gross_pnl_usd": net,
        "fees_and_gst_usd": "0",
        "net_ex_funding_usd": net,
        "funding_complete": funding_complete,
        "net_including_funding_usd": net_funding if funding_complete else None,
        "final_exit_reason": reason,
    }


def test_summary_separates_strategy_exits_from_end_of_data_liquidations():
    trades = [
        _trade("-0.6", "INITIAL_PROTECTIVE_STOP", net_funding="-0.6"),
        _trade("5.9", "END_OF_DATA", funding_complete=False),
    ]

    summary = summary_for(trades)

    assert summary["trade_count"] == 2
    assert summary["net_ex_funding_usd"] == "5.3"
    assert summary["strategy_exits_excluding_end_of_data"]["trade_count"] == 1
    assert summary["strategy_exits_excluding_end_of_data"]["net_ex_funding_usd"] == "-0.6"
    assert summary["end_of_data_liquidations"]["trade_count"] == 1
    assert summary["end_of_data_liquidations"]["net_ex_funding_usd"] == "5.9"
    assert summary["all_trades_including_end_of_data"]["trade_count"] == 2
    assert summary["end_of_data_liquidations"]["net_including_funding_usd"] is None
