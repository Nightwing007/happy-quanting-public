from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas import BrokerOut, MarketRefOut, SegmentBrokersOut, SettingsIn, SettingsOut
from app.trading import engine
from app.trading.brokers import SEGMENT_LABELS, SEGMENTS, brokers_for_segment
from app.trading.markets import MARKETS

router = APIRouter(prefix="/api", tags=["settings"])


def _settings_out(account) -> SettingsOut:
    return SettingsOut(
        broker_india=account.broker_india,
        broker_international=account.broker_international,
        broker_crypto=account.broker_crypto,
    )


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: DbSession):
    return _settings_out(engine.get_account(db))


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsIn, db: DbSession):
    account = engine.update_brokers(
        db,
        {
            "india": body.broker_india,
            "international": body.broker_international,
            "crypto": body.broker_crypto,
        },
    )
    return _settings_out(account)


@router.get("/brokers", response_model=list[SegmentBrokersOut])
def list_brokers():
    return [
        SegmentBrokersOut(
            segment=segment,
            label=SEGMENT_LABELS[segment],
            brokers=[
                BrokerOut(
                    code=b.code,
                    name=b.name,
                    segment=b.segment,
                    notes=b.notes,
                    fx_markup_percent=b.fx_markup_percent,
                    markets=[
                        MarketRefOut(code=m.code, name=m.name, currency=m.currency)
                        for m in (MARKETS[c] for c in b.markets)
                    ],
                    source=b.source,
                    checked=b.checked,
                )
                for b in brokers_for_segment(segment)
            ],
        )
        for segment in SEGMENTS
    ]
