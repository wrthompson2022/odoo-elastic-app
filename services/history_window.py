"""Date bounds shared by order and invoice history domains."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def history_date_domain(date_field, *, start_date=None, lookback_days=3,
                        include_updates=True, update_fields=(), is_datetime=False,
                        now=None, tz='UTC'):
    """Use inclusive local calendar dates; zero days disables the rolling limit.

    The fixed start date is a hard document-date floor, even for recent updates.
    Datetime fields in Odoo are stored as naive UTC; Date fields stay local dates.
    """
    if lookback_days < 0:
        raise ValueError('Order history lookback days must be zero or greater.')
    zone = ZoneInfo(tz or 'UTC')
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(zone).date()

    def midnight(day):
        return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)

    def bound(day):
        return midnight(day) if is_datetime else day

    domain = []
    if start_date:
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        elif not isinstance(start_date, date):
            start_date = date.fromisoformat(start_date)
        domain.append((date_field, '>=', bound(start_date)))
    if lookback_days:
        # 3 days means today and the preceding two calendar dates.
        cutoff = today - timedelta(days=lookback_days - 1)
        alternatives = [(date_field, '>=', bound(cutoff))]
        if include_updates:
            alternatives.extend((field, '>=', midnight(cutoff)) for field in update_fields)
        domain += ['|'] * (len(alternatives) - 1) + alternatives
    return domain
