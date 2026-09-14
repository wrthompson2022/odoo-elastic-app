"""History window boundary and selection tests, without an Odoo installation."""
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'history_window', Path(__file__).resolve().parents[2] / 'services/history_window.py',
)
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


def matches(domain, values):
    """Evaluate the simple >=, AND and OR subset used here against sample data."""
    tokens = iter(domain)

    def expression(token):
        if token == '|':
            left, right = expression(next(tokens)), expression(next(tokens))
            return left or right
        if token == '&':
            left, right = expression(next(tokens)), expression(next(tokens))
            return left and right
        field, operator, cutoff = token
        if operator != '>=':
            raise AssertionError(operator)
        actual = values.get(field)
        return actual is not None and actual >= cutoff

    results = [expression(token) for token in tokens]
    return all(results)


class TestHistoryWindow(unittest.TestCase):
    NOW = datetime(2026, 9, 14, 16, tzinfo=timezone.utc)

    def domain(self, **kwargs):
        params = dict(date_field='date_order', is_datetime=True, now=self.NOW,
                      update_fields=('write_date', 'order_line.write_date',
                                     'order_line.move_ids.write_date',
                                     'order_line.move_ids.picking_id.write_date'))
        params.update(kwargs)
        return window.history_date_domain(**params)

    def test_three_days_includes_today_and_two_previous_dates(self):
        domain = self.domain(include_updates=False)
        self.assertFalse(matches(domain, {'date_order': datetime(2026, 9, 11, 23, 59, 59)}))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 9, 12)}))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 9, 14, 12)}))

    def test_recent_changes_include_old_documents(self):
        for field in ('write_date', 'order_line.write_date', 'order_line.move_ids.write_date',
                      'order_line.move_ids.picking_id.write_date'):
            with self.subTest(field=field):
                data = {'date_order': datetime(2026, 8, 1), field: datetime(2026, 9, 12)}
                self.assertTrue(matches(self.domain(), data))
                self.assertFalse(matches(self.domain(include_updates=False), data))
        self.assertFalse(matches(self.domain(), {'date_order': datetime(2026, 8, 1),
                                                'write_date': datetime(2026, 9, 11)}))

    def test_fixed_start_is_hard_floor_even_for_updated_orders(self):
        domain = self.domain(start_date=date(2026, 8, 1))
        self.assertFalse(matches(domain, {'date_order': datetime(2026, 7, 31, 23, 59, 59),
                                         'write_date': datetime(2026, 9, 14)}))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 8, 1),
                                        'write_date': datetime(2026, 9, 14)}))

    def test_zero_days_backfills_from_start(self):
        domain = self.domain(lookback_days=0, start_date='2026-01-01')
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 1, 1)}))
        self.assertFalse(matches(domain, {'date_order': datetime(2025, 12, 31),
                                         'write_date': datetime(2026, 9, 14)}))
        self.assertEqual(self.domain(lookback_days=0), [])

    def test_invoice_date_and_update_timestamps_use_different_types(self):
        domain = self.domain(date_field='invoice_date', is_datetime=False,
                             start_date=date(2026, 8, 1))
        self.assertTrue(matches(domain, {'invoice_date': date(2026, 9, 12)}))
        self.assertFalse(matches(domain, {'invoice_date': date(2026, 9, 11)}))
        self.assertTrue(matches(domain, {'invoice_date': date(2026, 8, 1),
                                        'write_date': datetime(2026, 9, 14)}))
        self.assertFalse(matches(domain, {'invoice_date': date(2026, 7, 31),
                                         'write_date': datetime(2026, 9, 14)}))

    def test_local_midnight_is_converted_to_utc(self):
        domain = self.domain(tz='America/New_York', include_updates=False)
        self.assertFalse(matches(domain, {'date_order': datetime(2026, 9, 12, 3, 59, 59)}))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 9, 12, 4)}))

    def test_local_today_differs_from_utc_today_near_midnight(self):
        domain = self.domain(tz='America/Los_Angeles', lookback_days=1,
                             now=datetime(2026, 9, 14, 1, tzinfo=timezone.utc))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 9, 13, 7)}))
        self.assertFalse(matches(domain, {'date_order': datetime(2026, 9, 13, 6, 59, 59)}))

    def test_window_spanning_dst_uses_offset_at_cutoff(self):
        domain = self.domain(tz='America/New_York', lookback_days=3,
                             now=datetime(2026, 3, 9, 16, tzinfo=timezone.utc))
        self.assertTrue(matches(domain, {'date_order': datetime(2026, 3, 7, 5)}))
        self.assertFalse(matches(domain, {'date_order': datetime(2026, 3, 7, 4, 59, 59)}))

    def test_negative_days_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'zero or greater'):
            self.domain(lookback_days=-1)


if __name__ == '__main__':
    unittest.main()
