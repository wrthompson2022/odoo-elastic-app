"""Dependency-free, cumulative availability calculation shared with the brief."""


def availability_timeline(starting_qty, dated_events, today):
    """Return (date, projected_stock, ATS) at today and each future event.

    Carry deficits forward before looking backward for the lowest remaining
    balance. Selling more than that minimum would consume stock required by an
    existing commitment. Clamp only the published ATS, never the net balance.
    Values are cumulative quantities available by a date, not receipt deltas.
    """
    balance = starting_qty + sum(
        qty for event_date, qty in dated_events.items() if event_date <= today
    )
    balances = [(today, balance)]
    for event_date in sorted(day for day in dated_events if day > today):
        balance += dated_events[event_date]
        balances.append((event_date, balance))

    minimum = balance
    timeline = []
    for event_date, projected in reversed(balances):
        minimum = min(minimum, projected)
        timeline.append((event_date, projected, max(minimum, 0)))
    return list(reversed(timeline))
