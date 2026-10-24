"""The fee calculator and the rate tables, with no database.

Every expected figure is worked out in the comment above the assertion. If one disagrees with
the code, recompute it by hand before touching the code: hand figures are wrong more often
than the code is.
"""

from decimal import Decimal

import pytest

from app.trading import brokers, markets
from app.trading.brokers import Broker
from app.trading.errors import UnsupportedMarket
from app.trading.fees import Fee, break_even_price, calculate_charges
from app.trading.markets import Market, market_for
from app.trading.money import money

D = Decimal


def charges(market_code: str, broker_code: str, side: str, qty: str, price: str, **kw):
    """Charges in the market's own currency (account currency = instrument currency)."""
    market = markets.MARKETS[market_code]
    kw.setdefault("instrument_type", "equity")
    kw.setdefault("instrument_currency", market.currency)
    kw.setdefault("account_currency", market.currency)
    kw.setdefault("fx_rate", D(1))
    return calculate_charges(
        market, brokers.get_broker(broker_code), side, D(qty), D(price), **kw
    )  # fmt: skip


def by_name(lines) -> dict[str, Decimal]:
    return {c.name: c.amount for c in lines}


def total(lines) -> Decimal:
    return sum((c.amount for c in lines), D(0))


# --- the Groww anchor ----------------------------------------------------------------------


def test_groww_buy_of_10_reliance_at_1250_costs_29_59():
    lines = charges("NSE", "groww", "buy", "10", "1250")
    # value 10 x 1250 = 12500
    # brokerage  0.1% x 12500                  = 12.50 (inside the Rs 5..20 band)
    # exchange   0.00307% x 12500 = 0.38375    = 0.38  (NSE 0.00297% + IPFT 0.0001%)
    # STT        0.1% x 12500                  = 12.50
    # stamp duty 0.015% x 12500 = 1.875        = 1.88  (half up; buy side only)
    # SEBI       0.0001% x 12500 = 0.0125      = 0.01
    # DP charge: none on a buy
    # GST        18% x (12.50 + 0.38 + 0.01) = 18% x 12.89 = 2.3202 = 2.32
    #            (brokerage + exchange + SEBI; not STT, not stamp duty)
    # total 12.50 + 0.38 + 12.50 + 1.88 + 0.01 + 2.32 = 29.59
    assert by_name(lines) == {
        "Brokerage": D("12.50"),
        "Exchange transaction charge": D("0.38"),
        "Securities transaction tax (STT)": D("12.50"),
        "Stamp duty": D("1.88"),
        "SEBI turnover fee": D("0.01"),
        "GST": D("2.32"),
    }
    assert total(lines) == D("29.59")
    # Broker's fees come first, GST (computed from the lines above it) comes last.
    assert lines[0].category == "brokerage"
    assert lines[-1].category == "gst"


def test_groww_sell_of_14000_pays_the_dp_charge_and_no_stamp_duty():
    lines = charges("NSE", "groww", "sell", "10", "1400")
    # value 14000
    # brokerage 0.1% = 14.00; STT 0.1% = 14.00; exchange 0.00307% x 14000 = 0.4298 = 0.43
    # SEBI 0.0001% x 14000 = 0.014 = 0.01; DP charge 20.00 (sells only); no stamp duty on a sell
    # GST 18% x (14.00 + 0.43 + 0.01 + 20.00) = 18% x 34.44 = 6.1992 = 6.20
    # total 14.00 + 14.00 + 0.43 + 0.01 + 20.00 + 6.20 = 54.64
    assert by_name(lines) == {
        "Brokerage": D("14.00"),
        "Exchange transaction charge": D("0.43"),
        "Securities transaction tax (STT)": D("14.00"),
        "SEBI turnover fee": D("0.01"),
        "Depository (DP) charge": D("20.00"),
        "GST": D("6.20"),
    }
    assert total(lines) == D("54.64")


def test_zerodha_sell_of_14000():
    lines = charges("NSE", "zerodha", "sell", "10", "1400")
    # value 14000; no brokerage (free delivery); STT 14.00; exchange 0.4298 = 0.43; SEBI 0.014 = 0.01
    # DP 13.00; GST 18% x (0.43 + 0.01 + 13.00) = 18% x 13.44 = 2.4192 = 2.42
    # total 14.00 + 0.43 + 0.01 + 13.00 + 2.42 = 29.86
    assert total(lines) == D("29.86")
    assert by_name(lines)["GST"] == D("2.42")


def test_gst_is_charged_on_services_not_on_stt_or_stamp_duty():
    lines = by_name(charges("NSE", "groww", "buy", "10", "1250"))
    services = lines["Brokerage"] + lines["Exchange transaction charge"] + lines["SEBI turnover fee"]
    taxes = lines["Securities transaction tax (STT)"] + lines["Stamp duty"]
    # 18% of 12.89 = 2.32 (services only); 18% of (12.89 + 14.38) = 4.91 would include the taxes
    assert lines["GST"] == money(services * D("0.18")) == D("2.32")
    assert lines["GST"] != money((services + taxes) * D("0.18"))


def test_groww_brokerage_is_capped_at_20_and_floored_at_5():
    # 100 x 5000 = 500000; 0.1% = 500, capped at Rs 20
    big = by_name(charges("NSE", "groww", "buy", "100", "5000"))
    assert big["Brokerage"] == D("20.00")
    # 1 x 100 = 100; 0.1% = 0.10, lifted to the Rs 5 minimum
    small = by_name(charges("NSE", "groww", "buy", "1", "100"))
    assert small["Brokerage"] == D("5.00")


def test_zerodha_delivery_has_no_brokerage_and_a_flat_dp_charge():
    lines = by_name(charges("NSE", "zerodha", "sell", "10", "1250"))
    assert "Brokerage" not in lines
    assert lines["Depository (DP) charge"] == D("13.00")
    # GST 18% x (0.38 + 0.01 + 13.00) = 18% x 13.39 = 2.4102 = 2.41
    assert lines["GST"] == D("2.41")


def test_bse_uses_its_own_exchange_rate():
    lines = by_name(charges("BSE", "groww", "buy", "10", "1250"))
    # 0.00375% x 12500 = 0.46875 = 0.47 (NSE would be 0.38)
    assert lines["Exchange transaction charge"] == D("0.47")


# --- United Kingdom ------------------------------------------------------------------------


def test_uk_stamp_duty_hits_share_buys_only():
    buy = by_name(charges("LSE", "ibkr", "buy", "1000", "5"))
    # 1000 x 5 = 5000 GBP; 0.5% = 25.00
    assert buy["Stamp duty reserve tax"] == D("25.00")
    sell = by_name(charges("LSE", "ibkr", "sell", "1000", "5"))
    assert "Stamp duty reserve tax" not in sell
    etf = by_name(charges("LSE", "ibkr", "buy", "1000", "5", instrument_type="etf"))
    assert "Stamp duty reserve tax" not in etf


def test_uk_ptm_levy_applies_only_above_10000_and_to_the_whole_trade():
    # 1000 x 10.00 = 10000 exactly: not above the threshold
    at_limit = by_name(charges("LSE", "ibkr", "buy", "1000", "10"))
    assert "PTM levy" not in at_limit
    # 1000 x 10.01 = 10010: over it, and the levy is the flat GBP 1.50 for the whole trade
    over = by_name(charges("LSE", "ibkr", "buy", "1000", "10.01"))
    assert over["PTM levy"] == D("1.50")
    # a trade ten times larger pays the same flat levy, not 1.50 per 10,000
    huge = by_name(charges("LSE", "ibkr", "sell", "10000", "10.01"))
    assert huge["PTM levy"] == D("1.50")


# --- Hong Kong -----------------------------------------------------------------------------


def test_hong_kong_stamp_duty_rounds_up_to_a_whole_dollar():
    lines = by_name(charges("HKEX", "ibkr", "buy", "100", "12.34"))
    # value 1234 HKD; stamp duty 0.1% = 1.234, rounded UP to 2.00 (not 1.23)
    assert lines["Stamp duty"] == D("2.00")
    # exactly 1000 HKD: 0.1% = 1.000 -> 1.00 (already whole, so not bumped to 2)
    exact = by_name(charges("HKEX", "ibkr", "buy", "100", "10"))
    assert exact["Stamp duty"] == D("1.00")
    # exchange 0.00565% x 1234 = 0.0697 = 0.07; SFC 0.0027% x 1234 = 0.0333 = 0.03
    assert lines["Exchange trading fee"] == D("0.07")
    assert lines["SFC transaction levy"] == D("0.03")
    # AFRC 0.00015% x 1234 = 0.00185 rounds to nothing, so there is no line for it
    assert "AFRC transaction levy" not in lines
    # IBKR 0.08% x 1234 = 0.99, lifted to its HKD 18 minimum
    assert lines["Brokerage (Hong Kong)"] == D("18.00")


def test_hong_kong_etfs_pay_no_stamp_duty():
    assert "Stamp duty" not in by_name(charges("HKEX", "ibkr", "buy", "100", "12.34", instrument_type="etf"))


# --- minimum and max_percent (IBKR style) --------------------------------------------------


@pytest.mark.parametrize(
    ("qty", "price", "expected"),
    [
        # 10 x 230: 10 x 0.005 = 0.05, lifted to the $1 minimum; 1% of 2300 = 23 is no cap here
        ("10", "230", "1.00"),
        # 1 x 20: 0.005 -> $1 minimum, but the cap is 1% of $20 = $0.20, and the cap wins
        ("1", "20", "0.20"),
        # 1000 x 10 = 10000: 1000 x 0.005 = 5.00; cap 1% x 10000 = 100, not reached
        ("1000", "10", "5.00"),
        # 1000 x 0.30 = 300: 5.00 would be 1.67%; capped at 1% x 300 = 3.00
        ("1000", "0.30", "3.00"),
    ],
)
def test_ibkr_us_commission_minimum_and_percent_cap(qty, price, expected):
    assert by_name(charges("US", "ibkr", "buy", qty, price))["Brokerage (US)"] == D(expected)


def test_a_fixed_maximum_applies_in_the_same_way():
    fee = Fee("Cap", "brokerage", "d", percent=D("1"), maximum=D("25"))
    market = Market("T", "T", "Testland", "USD", (), "international", [fee])
    free = Broker("b", "B", "international", [], markets=("T",))
    lines = calculate_charges(
        market, free, "buy", D(1), D("10000"), instrument_type="equity",
        instrument_currency="USD", account_currency="USD", fx_rate=D(1),
    )  # fmt: skip
    # 1% x 10000 = 100, capped at 25
    assert [c.amount for c in lines] == [D("25.00")]


def test_maker_rate_applies_to_resting_orders_only():
    fee = Fee("Trading fee", "brokerage", "d", percent=D("0.2"), maker_percent=D("0.1"))
    market = Market("T", "T", "Testland", "USD", (), "crypto", [fee])
    free = Broker("b", "B", "crypto", [], markets=("T",))

    def run(maker: bool):
        return calculate_charges(
            market, free, "buy", D(1), D("1000"), instrument_type="crypto",
            instrument_currency="USD", account_currency="USD", fx_rate=D(1), maker=maker,
        )  # fmt: skip

    # value 1000: taker 0.2% = 2.00, maker 0.1% = 1.00
    assert run(False)[0].amount == D("2.00")
    assert run(True)[0].amount == D("1.00")


# --- currency ------------------------------------------------------------------------------


def test_each_charge_is_rounded_in_its_own_currency_then_converted_last():
    # A Hong Kong buy of 100 x 12.34 = 1234 HKD in a USD account at 1 HKD = 0.128 USD.
    lines = charges(
        "HKEX", "ibkr", "buy", "100", "12.34", account_currency="USD", fx_rate=D("0.128")
    )  # fmt: skip
    # Worked out in HKD and rounded there first:
    #   brokerage 18.00 (minimum), stamp duty 2.00 (rounded up), exchange 0.07, SFC 0.03,
    #   FX markup 0.03% x 1234 = 0.3702 = 0.37
    # then each converted at 0.128 and rounded again:
    #   18.00 x 0.128 = 2.304 -> 2.30; 2.00 x 0.128 = 0.256 -> 0.26; 0.07 x 0.128 = 0.00896 -> 0.01
    #   0.03 x 0.128 = 0.00384 -> 0.00; 0.37 x 0.128 = 0.04736 -> 0.05
    expected = {
        "Brokerage (Hong Kong)": (D("2.30"), D("18.00")),
        "Stamp duty": (D("0.26"), D("2.00")),
        "Exchange trading fee": (D("0.01"), D("0.07")),
        "SFC transaction levy": (D("0.00"), D("0.03")),
        "Currency conversion markup": (D("0.05"), D("0.37")),
    }
    assert {c.name: (c.amount, c.native_amount) for c in lines} == expected
    assert all(c.native_currency == "HKD" for c in lines)
    # 2.30 + 0.26 + 0.01 + 0.00 + 0.05
    assert total(lines) == D("2.62")


def test_fx_markup_line_is_absent_when_no_conversion_happens():
    lines = charges("US", "ibkr", "buy", "10", "230")
    assert "fx" not in {c.category for c in lines}


def test_a_flat_fee_in_the_account_currency_is_not_converted():
    fee = Fee("Wire", "brokerage", "d", flat=D("5"), currency="USD")
    market = Market("T", "T", "Testland", "HKD", (), "international", [fee])
    free = Broker("b", "B", "international", [], markets=("T",))
    lines = calculate_charges(
        market, free, "buy", D(1), D(100), instrument_type="equity",
        instrument_currency="HKD", account_currency="USD", fx_rate=D("0.128"),
    )  # fmt: skip
    assert [(c.amount, c.native_amount, c.native_currency) for c in lines] == [(D("5.00"), D("5.00"), "USD")]


def test_a_percentage_fee_in_a_foreign_currency_is_refused():
    fee = Fee("Odd", "brokerage", "d", percent=D("1"), currency="EUR")
    market = Market("T", "T", "Testland", "HKD", (), "international", [fee])
    free = Broker("b", "B", "international", [], markets=("T",))
    with pytest.raises(ValueError, match="flat amount"):
        calculate_charges(
            market, free, "buy", D(1), D(100), instrument_type="equity",
            instrument_currency="HKD", account_currency="USD", fx_rate=D("0.128"),
        )  # fmt: skip


# --- other taxes ---------------------------------------------------------------------------


def test_buy_side_and_sell_side_transaction_taxes():
    # France 0.4% buys only: 100 x 50 = 5000 -> 20.00
    assert by_name(charges("PAR", "ibkr", "buy", "100", "50"))["French financial transaction tax"] == D(
        "20.00"
    )
    assert "French financial transaction tax" not in by_name(charges("PAR", "ibkr", "sell", "100", "50"))
    # Korea 0.20% sells only: 10 x 70000 = 700000 -> 1400.00
    kr = by_name(charges("KOSPI", "ibkr", "sell", "10", "70000"))
    assert kr["Securities transaction tax"] == D("1400.00")
    assert "Securities transaction tax" not in by_name(charges("KOSPI", "ibkr", "buy", "10", "70000"))
    # Ireland 1% buys only: 100 x 20 = 2000 -> 20.00
    assert by_name(charges("IRE", "ibkr", "buy", "100", "20"))["Stamp duty"] == D("20.00")
    # China 0.05% on sells: 100 x 10 = 1000 -> 0.50; transfer fee 0.001% x 1000 = 0.01 both sides
    cn = by_name(charges("SSE", "ibkr", "sell", "100", "10"))
    assert cn["Stamp duty"] == D("0.50")
    assert cn["Transfer fee"] == D("0.01")
    # Taiwan: stocks 0.3% and ETFs 0.1% on sells. 1000 x 20 = 20000 -> 60.00 vs 20.00
    assert by_name(charges("TWSE", "ibkr", "sell", "1000", "20"))["Securities transaction tax"] == D("60.00")
    etf = by_name(charges("TWSE", "ibkr", "sell", "1000", "20", instrument_type="etf"))
    assert etf["Securities transaction tax (ETF)"] == D("20.00")
    # South Africa 0.25% on buys: 100 x 200 = 20000 -> 50.00
    assert by_name(charges("JSE", "ibkr", "buy", "100", "200"))["Securities transfer tax"] == D("50.00")


def test_singapore_gst_applies_to_exchange_fees_only():
    lines = by_name(charges("SGX", "ibkr", "buy", "1000", "3"))
    # value 3000 SGD; trading fee 0.0075% = 0.225 -> 0.23 (half up); clearing 0.0325% = 0.975 -> 0.98
    # GST 9% x (0.23 + 0.98) = 9% x 1.21 = 0.1089 -> 0.11. IBKR's own commission carries no GST.
    assert lines["Exchange trading fee"] == D("0.23")
    assert lines["Clearing fee"] == D("0.98")
    assert lines["GST"] == D("0.11")


def test_indmoney_brokerage_cap_and_gst():
    lines = by_name(charges("US", "indmoney", "buy", "100", "1000"))
    # value 100000 USD; 0.25% = 250, capped at $25; GST 18% x 25 = 4.50
    assert lines["Brokerage"] == D("25.00")
    assert lines["GST"] == D("4.50")


def test_crypto_has_no_tds_and_gst_on_the_exchange_fee():
    lines = by_name(charges("CRYPTO", "coindcx", "sell", "1", "60000", instrument_type="crypto"))
    # 0.17% x 60000 = 102.00; GST 18% x 102 = 18.36; nothing else (no TDS)
    assert lines == {"Trading fee": D("102.00"), "GST": D("18.36")}


def inr_account(market_code: str, broker_code: str, side: str, qty: str, price: str, **kw):
    """Charges for a USD-priced instrument bought from a rupee account at 1 USD = 83.5 INR."""
    kw.setdefault("account_currency", "INR")
    kw.setdefault("fx_rate", D("83.5"))
    return charges(market_code, broker_code, side, qty, price, **kw)


def test_coinswitch_taker_and_maker_for_a_dollar_coin_in_a_rupee_account():
    # 0.1 BTC at 60000 = 6000 USD.
    # fx markup 1% x 6000 = 60.00 USD (rupees to USDT first); GST is not charged on it
    taker = by_name(inr_account("CRYPTO", "coinswitch", "buy", "0.1", "60000", instrument_type="crypto"))
    # taker: fee 0.1% x 6000 = 6.00 USD; GST 18% x 6.00 = 1.08 USD
    # in INR at 83.5: 6.00 -> 501.00; 1.08 -> 90.18; 60.00 -> 5010.00
    assert taker == {
        "Trading fee": D("501.00"),
        "GST": D("90.18"),
        "Currency conversion markup": D("5010.00"),
    }
    assert total(inr_account("CRYPTO", "coinswitch", "buy", "0.1", "60000", instrument_type="crypto")) == D(
        "5601.18"  # 501.00 + 90.18 + 5010.00
    )
    # maker (a resting limit order): fee 0% so no fee and no GST line; only the conversion cost
    maker = by_name(
        inr_account("CRYPTO", "coinswitch", "buy", "0.1", "60000", instrument_type="crypto", maker=True)
    )
    assert maker == {"Currency conversion markup": D("5010.00")}


def test_wazirx_fee_gst_and_conversion_for_a_dollar_coin():
    lines = inr_account("CRYPTO", "wazirx", "buy", "0.1", "60000", instrument_type="crypto")
    # 6000 USD; fee 0.2% = 12.00 USD; GST 18% x 12.00 = 2.16 USD; fx 1% = 60.00 USD
    # INR at 83.5: 12.00 -> 1002.00; 2.16 -> 180.36; 60.00 -> 5010.00; total 6192.36
    assert by_name(lines) == {
        "Trading fee": D("1002.00"),
        "GST": D("180.36"),
        "Currency conversion markup": D("5010.00"),
    }
    assert total(lines) == D("6192.36")
    # maker pays the same
    maker = inr_account("CRYPTO", "wazirx", "buy", "0.1", "60000", instrument_type="crypto", maker=True)
    assert by_name(maker) == by_name(lines)


def test_a_coin_priced_in_rupees_pays_no_conversion_cost():
    # 0.1 coin at 5,000,000 INR = 500000 INR, rupee account: fee 0.2% = 1000.00, GST 180.00, no fx
    lines = charges(
        "CRYPTO", "wazirx", "buy", "0.1", "5000000",
        instrument_type="crypto", instrument_currency="INR", account_currency="INR",
    )  # fmt: skip
    assert by_name(lines) == {"Trading fee": D("1000.00"), "GST": D("180.00")}


def test_indian_exchanges_charge_the_conversion_binance_does_not():
    for code in ("coindcx", "coinswitch", "wazirx", "mudrex"):
        assert brokers.get_broker(code).fx_markup_percent == D("1"), code
    assert brokers.get_broker("binance").fx_markup_percent == D(0)


def test_indmoney_and_vested_show_the_conversion_markup_on_a_us_buy():
    # 10 AAPL at 230 = 2300 USD; at 83.5 INR per USD
    # INDmoney 0.7% x 2300 = 16.10 USD -> 1344.35 INR; Vested 1% x 2300 = 23.00 USD -> 1920.50 INR
    ind = [c for c in inr_account("US", "indmoney", "buy", "10", "230") if c.category == "fx"]
    ves = [c for c in inr_account("US", "vested", "buy", "10", "230") if c.category == "fx"]
    assert [(c.amount, c.native_amount) for c in ind] == [(D("1344.35"), D("16.10"))]
    assert "0.7%" in ind[0].description
    assert [(c.amount, c.native_amount) for c in ves] == [(D("1920.50"), D("23.00"))]
    assert "1%" in ves[0].description


def test_an_empty_fee_list_means_no_charges():
    free = Broker("b", "B", "crypto", [], markets=("CRYPTO",))
    assert (
        calculate_charges(
            markets.MARKETS["CRYPTO"],
            free,
            "buy",
            D(1),
            D("60000"),
            instrument_type="crypto",
            instrument_currency="USD",
            account_currency="USD",
            fx_rate=D(1),
        )  # fmt: skip
        == []
    )
    assert charges("XETRA", "ibkr", "buy", "10", "200")  # only IBKR's commission
    assert {c.category for c in charges("XETRA", "ibkr", "buy", "10", "200")} == {"brokerage"}


# --- the tables ----------------------------------------------------------------------------


def test_market_lookup_by_symbol():
    assert market_for("AAPL", "equity").code == "US"
    assert market_for("RELIANCE.NS", "equity").code == "NSE"
    assert market_for("reliance.bo", "equity").code == "BSE"
    assert market_for("VOD.L", "equity").code == "LSE"
    assert market_for("0700.HK", "equity").code == "HKEX"
    assert market_for("SAP.DE", "equity").code == "XETRA"
    # crypto is chosen by type, whatever the symbol looks like
    assert market_for("BTC-USD", "crypto").code == "CRYPTO"
    with pytest.raises(UnsupportedMarket, match=r"\.ZZ"):
        market_for("FOO.ZZ", "equity")


def test_tables_are_complete_and_consistent():
    assert len(markets.MARKETS) >= 35
    assert len(brokers.BROKERS) == 13
    assert {b.segment for b in brokers.BROKERS.values()} == set(brokers.SEGMENTS)
    for segment, expected in (("india", 5), ("international", 3), ("crypto", 5)):
        assert len(brokers.brokers_for_segment(segment)) == expected
    for code in brokers.DEFAULT_BROKERS.values():
        assert brokers.get_broker(code)
    # every offered market exists, in the broker's own segment
    for broker in brokers.BROKERS.values():
        for market_code in broker.markets:
            assert markets.MARKETS[market_code].segment == broker.segment, (broker.code, market_code)
    # every market has at least one broker
    for market in markets.MARKETS.values():
        assert any(b.offers(market.code) for b in brokers.BROKERS.values()), market.code
    # suffixes are unique, so a symbol can only mean one market
    suffixes = [s for m in markets.MARKETS.values() for s in m.suffixes]
    assert len(suffixes) == len(set(suffixes))
    # charges are data with provenance: every fee names its source and the date it was checked
    for fee in [f for m in markets.MARKETS.values() for f in m.fees] + [
        f for b in brokers.BROKERS.values() for f in b.fees
    ]:
        assert fee.source and fee.checked and fee.description, fee.name
    for broker in brokers.BROKERS.values():
        assert broker.source and broker.checked and broker.notes, broker.code


def test_fee_rejects_a_misspelled_category():
    with pytest.raises(ValueError, match="category"):
        Fee("x", "brokrage", "d")


# --- break-even ----------------------------------------------------------------------------


def _net_proceeds(market_code, broker_code, qty, price, cost_basis, **kw):
    market = markets.MARKETS[market_code]
    fx = kw.get("fx_rate", D(1))
    sell = calculate_charges(
        market, brokers.get_broker(broker_code), "sell", D(qty), price,
        instrument_type=kw.get("instrument_type", "equity"), instrument_currency=market.currency,
        account_currency=kw.get("account_currency", market.currency), fx_rate=fx,
    )  # fmt: skip
    return money(D(qty) * price * fx) - total(sell) - cost_basis


def test_break_even_is_the_first_tick_that_recovers_everything_paid():
    market = markets.MARKETS["NSE"]
    groww = brokers.get_broker("groww")
    # 12500 paid for the shares + 29.59 of buy charges
    cost = D("12529.59")
    price = break_even_price(
        market, groww, quantity=D(10), cost_basis=cost, instrument_type="equity",
        instrument_currency="INR", account_currency="INR", fx_rate=D(1),
    )  # fmt: skip
    # Exit charges are about 0.222% of the value plus Rs 23.60 (DP 20.00 + GST 3.60 on it), so
    # the value must reach about (12529.59 + 23.60) / 0.99778 = 12581.1, i.e. ~1258.11 a share.
    assert D("1258.05") < price < D("1258.15")
    assert price == price.quantize(D("0.01"))
    # At that price the exit returns everything paid; one tick lower it does not.
    assert _net_proceeds("NSE", "groww", "10", price, cost) >= 0
    assert _net_proceeds("NSE", "groww", "10", price - D("0.01"), cost) < 0


def test_break_even_in_a_foreign_currency_uses_the_exchange_rate():
    market = markets.MARKETS["HKEX"]
    ibkr = brokers.get_broker("ibkr")
    fx = D("0.128")
    # 100 x 380 HKD = 38000 HKD = 4864.00 USD, plus an illustrative 12.00 of buy charges
    cost = D("4876.00")
    price = break_even_price(
        market, ibkr, quantity=D(100), cost_basis=cost, instrument_type="equity",
        instrument_currency="HKD", account_currency="USD", fx_rate=fx,
    )  # fmt: skip
    kw = {"fx_rate": fx, "account_currency": "USD"}
    assert _net_proceeds("HKEX", "ibkr", "100", price, cost, **kw) >= 0
    assert _net_proceeds("HKEX", "ibkr", "100", price - D("0.01"), cost, **kw) < 0
    assert price > D("380")


def test_break_even_for_crypto_uses_an_eight_decimal_tick():
    market = markets.MARKETS["CRYPTO"]
    binance = brokers.get_broker("binance")
    cost = D("6006.00")  # 0.1 BTC at 60000 + 6.00 of fee
    price = break_even_price(
        market, binance, quantity=D("0.1"), cost_basis=cost, instrument_type="crypto",
        instrument_currency="USD", account_currency="USD", fx_rate=D(1),
    )  # fmt: skip
    # 0.1% fee on the way out: price x 0.1 x 0.999 >= 6006 -> price >= 60120.12...
    assert D("60120") < price < D("60121")
    assert _net_proceeds("CRYPTO", "binance", "0.1", price, cost, instrument_type="crypto") >= 0
    assert _net_proceeds("CRYPTO", "binance", "0.1", price - D("1E-8"), cost, instrument_type="crypto") < 0
