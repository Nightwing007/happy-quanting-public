from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
_EIGHT = Decimal("1E-8")


def money(value: Decimal) -> Decimal:
    """Round to 2 dp, half up. Do this once, at the edge where an amount is produced."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def trim8(value: Decimal) -> Decimal:
    """Quantize to 8 dp (prices, FX rates, average cost) and drop trailing zeros.

    Built from a plain string so 100.00000000 becomes 100, never 1E+2.
    """
    text = f"{value.quantize(_EIGHT, rounding=ROUND_HALF_UP):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text)
