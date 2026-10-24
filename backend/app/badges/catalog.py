"""The badges as data: id, region, display name, order and the "Earned by" sentence.

The conditions live in `evaluate.py`, one small function per id. Official gym-badge names are
trademarks: fine for a local demo, a replacement item before any public launch (see DECISIONS).
"""

from dataclasses import dataclass
from typing import Literal

BadgeKind = Literal["trader", "creator"]


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    group: str | None  # market group: india | us | crypto | global; None for the Elite Four


@dataclass(frozen=True)
class Badge:
    id: str
    region: str
    name: str
    order: int  # position within its region, 1-based
    hint: str  # the "Earned by" sentence
    kind: BadgeKind


REGIONS: dict[str, Region] = {
    "kanto": Region("kanto", "Kanto", "india"),
    "johto": Region("johto", "Johto", "us"),
    "hoenn": Region("hoenn", "Hoenn", "crypto"),
    "sinnoh": Region("sinnoh", "Sinnoh", "global"),
    "elite": Region("elite", "Elite Four", None),
}
MARKET_GROUPS = ("india", "us", "crypto", "global")

CHAMPION = "champion"
ELITE_FOUR = ("debut", "trusted", "consistent", "craftsman")

_ROWS: dict[str, list[tuple[str, str]]] = {
    "kanto": [
        ("boulder", "First filled trade on NSE or BSE"),
        ("cascade", "First stop-loss or target set on an Indian trade"),
        ("thunder", "An intraday short closed by you before the broker's square-off"),
        ("rainbow", "Traded 5 different Indian stocks"),
        ("soul", "10 closed Indian trades, every one protected"),
        ("marsh", "Held a delivery trade 30+ days"),
        ("volcano", "Replayed a full NSE/BSE day in the sim through to the close"),
        ("earth", "20+ closed Indian trades, net profit after charges, drawdown under 10%"),
    ],
    "johto": [
        ("zephyr", "First filled US trade"),
        ("hive", "First stop-loss or target on a US trade"),
        ("plain", "First fractional-share buy"),
        ("fog", "A US short held overnight (borrow paid) and closed by you"),
        ("storm", "Traded 5 different US stocks"),
        ("mineral", "10 closed US trades, every one protected"),
        ("glacier", "Replayed a full US session in the sim through to the close"),
        ("rising", "20+ closed US trades, net profit after charges and currency effects, drawdown under 10%"),
    ],
    "hoenn": [
        ("stone", "First crypto trade"),
        ("knuckle", "First stop-loss or target on crypto"),
        ("dynamo", "A crypto order placed while NSE, NYSE and LSE were all closed"),
        ("heat", "A crypto short closed by you after paying funding"),
        ("balance", "Traded 3 different coins"),
        ("feather", "10 closed crypto trades, every one protected"),
        ("mind", "A crypto backtest that beat buy-and-hold after charges"),
        ("rain", "20+ closed crypto trades, net profit after charges, drawdown under 15%"),
    ],
    "sinnoh": [
        ("coal", "First trade outside India, the US and crypto"),
        ("forest", "First stop-loss or target on a global trade"),
        ("cobble", "Traded in 3 different countries' markets"),
        ("fen", "A trade that paid a transaction tax (UK/HK stamp duty, an FTT, ...)"),
        ("relic", "Held a global trade 30+ days"),
        ("mine", "10 closed global trades, every one protected"),
        ("icicle", "An order placed during Hong Kong's lunch break that waited for the reopen"),
        (
            "beacon",
            "20+ closed global trades, net profit after charges and currency effects, drawdown under 10%",
        ),
    ],
    "elite": [
        ("debut", "First published listing with at least one measured performance window"),
        ("trusted", "10 subscriptions across your listings"),
        ("consistent", "A listing positive after charges in every measured window (at least 2 measured)"),
        ("craftsman", "Shipped version 2+ of a listing, and at least one subscriber upgraded to it"),
    ],
}
_NAMES = {"debut": "Debut", "trusted": "Trusted", "consistent": "Consistent", "craftsman": "Craftsman"}

BADGES: dict[str, Badge] = {}
for _region, _rows in _ROWS.items():
    for _i, (_id, _hint) in enumerate(_rows, start=1):
        BADGES[_id] = Badge(
            _id, _region, _NAMES.get(_id, _id.capitalize()), _i, _hint,
            "creator" if _region == "elite" else "trader",
        )  # fmt: skip
BADGES[CHAMPION] = Badge(
    CHAMPION, "elite", "Champion", 5,
    "All 8 badges of any one region and all four Elite Four", "creator",
)  # fmt: skip


def region_badges(region: str) -> list[str]:
    """The ids of a region's own badges (not the Champion), in order."""
    rows = sorted(BADGES.values(), key=lambda b: b.order)
    return [b.id for b in rows if b.region == region and b.id != CHAMPION]
