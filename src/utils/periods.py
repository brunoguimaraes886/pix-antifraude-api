from dataclasses import dataclass
from datetime import datetime, time, timedelta

from constants import DAY_PERIOD_START_HOUR, NIGHT_PERIOD_START_HOUR

DAY = "day"
NIGHT = "night"

DAY_LENGTH = timedelta(hours=NIGHT_PERIOD_START_HOUR - DAY_PERIOD_START_HOUR)
NIGHT_LENGTH = timedelta(hours=24) - DAY_LENGTH


@dataclass(frozen=True)
class Period:
    """Um trecho do relógio: o diurno (6h–20h) ou o noturno (20h–6h)."""

    kind: str
    start: datetime
    end: datetime


def current_period(moment: datetime) -> Period:
    """O período em que o momento cai, no fuso do próprio momento.

    O fuso importa: 21h em São Paulo é noite, e é a mesma hora que meia-noite em
    Londres. Por isso as fronteiras são montadas com o `tzinfo` que veio
    na transação, e não com o relógio do servidor.

    A noite atravessa a meia-noite: um Pix às 3h pertence à noite que
    começou às 20h do dia ANTERIOR.
    """
    if moment.tzinfo is None:
        raise ValueError("O momento precisa ter fuso (tzinfo).")

    day = moment.date()

    if DAY_PERIOD_START_HOUR <= moment.hour < NIGHT_PERIOD_START_HOUR:
        return Period(DAY, _at(day, DAY_PERIOD_START_HOUR, moment), _at(day, NIGHT_PERIOD_START_HOUR, moment))

    if moment.hour >= NIGHT_PERIOD_START_HOUR:
        next_day = day + timedelta(days=1)
        return Period(NIGHT, _at(day, NIGHT_PERIOD_START_HOUR, moment), _at(next_day, DAY_PERIOD_START_HOUR, moment))

    previous_day = day - timedelta(days=1)
    return Period(NIGHT, _at(previous_day, NIGHT_PERIOD_START_HOUR, moment), _at(day, DAY_PERIOD_START_HOUR, moment))


def previous_period(period: Period) -> Period:
    """O período imediatamente anterior — sempre do outro tipo."""
    if period.kind == DAY:
        return Period(NIGHT, period.start - NIGHT_LENGTH, period.start)

    return Period(DAY, period.start - DAY_LENGTH, period.start)


def local_day_start(moment: datetime) -> datetime:
    """Meia-noite do dia do momento, no fuso do próprio momento."""
    return _at(moment.date(), 0, moment)


def _at(day, hour: int, reference: datetime) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=reference.tzinfo)
