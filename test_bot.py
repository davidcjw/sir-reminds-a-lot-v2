import os
import sys
import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from db import Card, SpendEntry
from logic.billing import billing_period, find_due_reminders
from logic.formatting import (
    aggregate_category_totals,
    build_due_reminder_messages,
    build_recent_transactions_message,
    build_spend_summary_message,
    find_matching_rules,
    is_one_off,
    parse_spend_amount,
    update_spend_amount,
)
from logic.chart import build_category_pie_image
from handlers.reminders import _next_run


# ── Billing period ────────────────────────────────────────────────────────────

class BillingPeriodTests(unittest.TestCase):
    def test_calendar_month_returns_first_to_last_day(self):
        start, end = billing_period(1, date(2026, 5, 17))
        self.assertEqual(start, date(2026, 5, 1))
        self.assertEqual(end, date(2026, 5, 31))

    def test_calendar_month_february(self):
        start, end = billing_period(1, date(2026, 2, 10))
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_custom_cycle_today_after_start(self):
        # today=May 17, cycle=13 → 13 May – 12 Jun
        start, end = billing_period(13, date(2026, 5, 17))
        self.assertEqual(start, date(2026, 5, 13))
        self.assertEqual(end, date(2026, 6, 12))

    def test_custom_cycle_today_on_start_day(self):
        start, end = billing_period(13, date(2026, 5, 13))
        self.assertEqual(start, date(2026, 5, 13))
        self.assertEqual(end, date(2026, 6, 12))

    def test_custom_cycle_today_before_start(self):
        # today=May 5, cycle=13 → 13 Apr – 12 May
        start, end = billing_period(13, date(2026, 5, 5))
        self.assertEqual(start, date(2026, 4, 13))
        self.assertEqual(end, date(2026, 5, 12))

    def test_custom_cycle_january_wraps_to_december(self):
        start, end = billing_period(13, date(2026, 1, 5))
        self.assertEqual(start, date(2025, 12, 13))
        self.assertEqual(end, date(2026, 1, 12))

    def test_custom_cycle_december_today_after_start(self):
        start, end = billing_period(13, date(2026, 12, 15))
        self.assertEqual(start, date(2026, 12, 13))
        self.assertEqual(end, date(2027, 1, 12))

    def test_custom_cycle_start_day_beyond_short_month(self):
        # cycle=31, today=Mar 5 → start clamps to Feb 28, end clamps to Mar 30
        start, end = billing_period(31, date(2026, 3, 5))
        self.assertEqual(start, date(2026, 2, 28))
        self.assertEqual(end, date(2026, 3, 30))


# ── Due date reminders ────────────────────────────────────────────────────────

class DueDateReminderTests(unittest.TestCase):
    def test_matches_within_window(self):
        reminders = find_due_reminders(
            [("Amex", "8th"), ("DBS", "11th"), ("SCB", "12th")],
            today=date(2026, 5, 8),
            days_ahead=3,
        )
        self.assertEqual(reminders, [
            ("Amex", "8th", date(2026, 5, 8)),
            ("DBS", "11th", date(2026, 5, 11)),
        ])

    def test_handles_next_month_rollover(self):
        reminders = find_due_reminders(
            [("Trust Bank", "1st")],
            today=date(2026, 4, 28),
            days_ahead=3,
        )
        self.assertEqual(reminders, [("Trust Bank", "1st", date(2026, 5, 1))])

    def test_handles_last_day_of_month(self):
        reminders = find_due_reminders(
            [("UOB", "last day of month")],
            today=date(2026, 5, 28),
            days_ahead=3,
        )
        self.assertEqual(reminders, [("UOB", "last day of month", date(2026, 5, 31))])

    def test_empty_window_message(self):
        messages = build_due_reminder_messages([], today=date(2026, 5, 8), days_ahead=3)
        self.assertEqual(messages, ["No credit card payments are due in the next 3 days."])

    def test_reminder_message_contains_card_and_timing(self):
        messages = build_due_reminder_messages(
            [("DBS", "11th", date(2026, 5, 11)), ("Amex", "8th", date(2026, 5, 8))],
            today=date(2026, 5, 8),
            days_ahead=3,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("DBS", messages[0])
        self.assertIn("Amex", messages[0])
        self.assertIn("in 3 days", messages[0])
        self.assertIn("today", messages[0])


# ── Reminder scheduling ─────────────────────────────────────────────────────────

class NextRunTests(unittest.TestCase):
    def test_same_day_when_time_not_yet_passed(self):
        now = datetime(2026, 5, 15, 8, 0)
        self.assertEqual(_next_run(now, time(9, 0)), datetime(2026, 5, 15, 9, 0))

    def test_rolls_to_next_day_when_time_passed(self):
        now = datetime(2026, 5, 15, 10, 0)
        self.assertEqual(_next_run(now, time(9, 0)), datetime(2026, 5, 16, 9, 0))

    def test_rolls_over_last_day_of_month(self):
        # Regression: day+1 used to raise ValueError on month-end, killing the loop.
        now = datetime(2026, 5, 31, 10, 0)
        self.assertEqual(_next_run(now, time(9, 0)), datetime(2026, 6, 1, 9, 0))

    def test_rolls_over_year_end(self):
        now = datetime(2026, 12, 31, 10, 0)
        self.assertEqual(_next_run(now, time(9, 0)), datetime(2027, 1, 1, 9, 0))


# ── Spend amount ──────────────────────────────────────────────────────────────

class SpendAmountTests(unittest.TestCase):
    def test_builds_decimal_amount(self):
        amount = ""
        for action in ["1", "2", "dot", "3", "4", "5"]:
            amount = update_spend_amount(amount, action)
        self.assertEqual(amount, "12.34")

    def test_backspace_removes_last_char(self):
        self.assertEqual(update_spend_amount("12.3", "backspace"), "12.")

    def test_clear_resets_to_empty(self):
        self.assertEqual(update_spend_amount("12.3", "clear"), "")

    def test_dot_is_ignored_if_already_present(self):
        self.assertEqual(update_spend_amount("12.", "dot"), "12.")

    def test_parse_formats_to_two_decimals(self):
        self.assertEqual(parse_spend_amount("12.3"), Decimal("12.30"))

    def test_parse_accepts_dollar_sign_and_commas(self):
        self.assertEqual(parse_spend_amount("$1,234.5"), Decimal("1234.50"))

    def test_parse_rejects_zero(self):
        with self.assertRaises(ValueError):
            parse_spend_amount("0")

    def test_parse_rejects_negative(self):
        with self.assertRaises(ValueError):
            parse_spend_amount("-5")

    def test_parse_rejects_non_numeric(self):
        with self.assertRaises(ValueError):
            parse_spend_amount("abc")


# ── Spend summary ─────────────────────────────────────────────────────────────

class SpendSummaryTests(unittest.TestCase):
    def _rows(self, entries):
        return [SpendEntry(*e) for e in entries]

    def test_groups_by_card_and_sums(self):
        cards = [Card("HSBC", "15th", 1), Card("DBS", "10th", 1)]
        rows = self._rows([
            ("2026-05-10 10:00:00", "50.00", "HSBC", "Groceries"),
            ("2026-05-12 11:00:00", "30.00", "HSBC", "Transport"),
            ("2026-05-15 09:00:00", "100.00", "DBS", "Food"),
        ])
        msg = build_spend_summary_message(cards, rows, date(2026, 5, 17))
        self.assertIn("HSBC: $80.00", msg)
        self.assertIn("DBS: $100.00", msg)

    def test_applies_custom_billing_cycle(self):
        cards = [Card("UOB Visa", "last", 13)]
        rows = self._rows([
            ("2026-05-14 10:00:00", "200.00", "UOB Visa", "Shopping"),  # in cycle
            ("2026-05-12 10:00:00", "999.00", "UOB Visa", "Shopping"),  # before cycle
        ])
        msg = build_spend_summary_message(cards, rows, date(2026, 5, 17))
        self.assertIn("$200.00", msg)
        self.assertNotIn("999", msg)

    def test_empty_rows_returns_no_spend_message(self):
        cards = [Card("DBS", "10th", 1)]
        msg = build_spend_summary_message(cards, [], date(2026, 5, 17))
        self.assertEqual(msg, "No spend logged in the current billing period.")

    def test_no_cards_configured_returns_setup_prompt(self):
        msg = build_spend_summary_message([], [], date(2026, 5, 17))
        self.assertIn("/admin", msg)

    def test_skips_rows_outside_billing_period(self):
        cards = [Card("DBS", "10th", 1)]
        rows = self._rows([("2026-04-15 10:00:00", "50.00", "DBS", "Food")])
        msg = build_spend_summary_message(cards, rows, date(2026, 5, 17))
        self.assertEqual(msg, "No spend logged in the current billing period.")


class RecentTransactionsTests(unittest.TestCase):
    def _rows(self, entries):
        return [SpendEntry(*e) for e in entries]

    def test_lists_entries_with_details(self):
        rows = self._rows([
            ("2026-05-12 11:00:00", "30.00", "HSBC", "Transport", None),
            ("2026-05-10 10:00:00", "50.50", "DBS", "Groceries", "weekly run"),
        ])
        msg = build_recent_transactions_message(rows, 5)
        self.assertIn("Last 2 transactions:", msg)
        self.assertIn("$30.00 on HSBC (Transport)", msg)
        self.assertIn("$50.50 on DBS (Groceries) — weekly run", msg)

    def test_singular_label_for_one_entry(self):
        rows = self._rows([("2026-05-12 11:00:00", "5.00", "DBS", "Food", None)])
        msg = build_recent_transactions_message(rows, 5)
        self.assertIn("Last 1 transaction:", msg)

    def test_empty_returns_friendly_message(self):
        self.assertEqual(build_recent_transactions_message([], 5), "No transactions logged yet.")


# ── Category chart ────────────────────────────────────────────────────────────

class CategoryChartTests(unittest.TestCase):
    def _rows(self, entries):
        return [SpendEntry(*e) for e in entries]

    def test_groups_by_category(self):
        rows = self._rows([
            ("2026-05-10 10:00:00", "50.00", "DBS", "Groceries"),
            ("2026-05-11 10:00:00", "30.00", "DBS", "Groceries"),
            ("2026-05-12 10:00:00", "100.00", "UOB", "Food & Dining"),
        ])
        totals = aggregate_category_totals(rows, date(2026, 5, 17))
        self.assertEqual(totals["Groceries"], Decimal("80.00"))
        self.assertEqual(totals["Food & Dining"], Decimal("100.00"))

    def test_filters_to_current_month_only(self):
        rows = self._rows([
            ("2026-04-15 10:00:00", "999.00", "DBS", "Transport"),
            ("2026-05-10 10:00:00", "42.00", "DBS", "Transport"),
        ])
        totals = aggregate_category_totals(rows, date(2026, 5, 17))
        self.assertEqual(totals.get("Transport"), Decimal("42.00"))

    def test_falls_back_to_uncategorized_for_empty_category(self):
        rows = self._rows([("2026-05-10 10:00:00", "25.00", "DBS", "")])
        totals = aggregate_category_totals(rows, date(2026, 5, 17))
        self.assertIn("Uncategorized", totals)

    def test_returns_empty_dict_when_no_spend_this_month(self):
        rows = self._rows([("2026-04-10 10:00:00", "50.00", "DBS", "Groceries")])
        totals = aggregate_category_totals(rows, date(2026, 5, 17))
        self.assertEqual(totals, {})

    def test_pie_image_returns_png_bytes(self):
        rows = self._rows([
            ("2026-05-10 10:00:00", "100.00", "DBS", "Groceries"),
            ("2026-05-11 10:00:00", "50.00", "UOB", "Transport"),
        ])
        result = build_category_pie_image(rows, date(2026, 5, 17))
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_pie_image_returns_none_when_no_spend_this_month(self):
        rows = self._rows([("2026-04-10 10:00:00", "50.00", "DBS", "Groceries")])
        result = build_category_pie_image(rows, date(2026, 5, 17))
        self.assertIsNone(result)

    def test_excludes_one_off_by_category(self):
        rows = self._rows([
            ("2026-05-10 10:00:00", "50.00", "DBS", "Groceries"),
            ("2026-05-11 10:00:00", "2000.00", "DBS", "One-off"),
        ])
        totals = aggregate_category_totals(rows, date(2026, 5, 17), exclude_one_off=True)
        self.assertEqual(totals, {"Groceries": Decimal("50.00")})

    def test_excludes_one_off_by_remark(self):
        rows = self._rows([
            ("2026-05-10 10:00:00", "50.00", "DBS", "Groceries", None),
            ("2026-05-11 10:00:00", "1200.00", "DBS", "Electronics", "one-off laptop"),
        ])
        totals = aggregate_category_totals(rows, date(2026, 5, 17), exclude_one_off=True)
        self.assertEqual(totals, {"Groceries": Decimal("50.00")})

    def test_keeps_one_off_when_not_excluded(self):
        rows = self._rows([
            ("2026-05-10 10:00:00", "50.00", "DBS", "Groceries"),
            ("2026-05-11 10:00:00", "2000.00", "DBS", "One-off"),
        ])
        totals = aggregate_category_totals(rows, date(2026, 5, 17))
        self.assertEqual(totals["One-off"], Decimal("2000.00"))

    def test_pie_image_returns_none_when_only_one_off_excluded(self):
        rows = self._rows([("2026-05-11 10:00:00", "2000.00", "DBS", "One-off")])
        result = build_category_pie_image(rows, date(2026, 5, 17), exclude_one_off=True)
        self.assertIsNone(result)

    def _rendered_title(self, exclude_one_off=False):
        rows = self._rows([("2026-05-10 10:00:00", "100.00", "DBS", "Groceries")])
        with patch("matplotlib.axes.Axes.set_title") as set_title:
            build_category_pie_image(rows, date(2026, 5, 17), exclude_one_off=exclude_one_off)
        set_title.assert_called_once()
        return set_title.call_args.args[0]

    def test_pie_image_title_uses_computed_month(self):
        title = self._rendered_title()
        self.assertIn("Spend by Category — May 2026", title)
        self.assertNotIn("excl. one-off", title)

    def test_pie_image_title_marks_excluded_one_off(self):
        title = self._rendered_title(exclude_one_off=True)
        self.assertIn("Spend by Category — May 2026 (excl. one-off)", title)


class OneOffDetectionTests(unittest.TestCase):
    def test_detects_one_off_variants_in_category(self):
        for cat in ("One-off", "one off", "ONEOFF", "Big One-Off Buys"):
            self.assertTrue(is_one_off(SpendEntry("2026-05-10 10:00:00", "1", "DBS", cat)))

    def test_detects_one_off_in_remark(self):
        entry = SpendEntry("2026-05-10 10:00:00", "1", "DBS", "Electronics", "one-off TV")
        self.assertTrue(is_one_off(entry))

    def test_regular_entry_is_not_one_off(self):
        entry = SpendEntry("2026-05-10 10:00:00", "1", "DBS", "Groceries", "weekly run")
        self.assertFalse(is_one_off(entry))


# ── Card rule lookup ──────────────────────────────────────────────────────────

class CardRuleLookupTests(unittest.TestCase):
    RULES = [
        ("Groceries", "UOB Ladies"),
        ("Food & Dining", "Maybank XL / UOB Ladies"),
        ("Transport", "UOB PPV"),
        ("Online Shopping", "DBS WWMC"),
    ]

    def test_exact_match(self):
        matches = find_matching_rules(self.RULES, "Groceries")
        self.assertTrue(any(cat == "Groceries" for cat, _ in matches))

    def test_partial_match(self):
        matches = find_matching_rules(self.RULES, "food")
        self.assertTrue(any("Food" in cat for cat, _ in matches))

    def test_no_match_returns_empty(self):
        matches = find_matching_rules(self.RULES, "xyzzy")
        self.assertEqual(matches, [])


# ── Database CRUD ─────────────────────────────────────────────────────────────

class DBTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init(Path(self._tmp.name))

    def tearDown(self):
        if db._conn:
            db._conn.close()
            db._conn = None
        os.unlink(self._tmp.name)

    def test_add_and_get_card(self):
        db.add_card("DBS WWMC", "15th", 1)
        cards = db.get_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].name, "DBS WWMC")
        self.assertEqual(cards[0].due_day, "15th")
        self.assertEqual(cards[0].cycle_start, 1)

    def test_remove_card(self):
        db.add_card("DBS WWMC", "15th", 1)
        db.remove_card("DBS WWMC")
        self.assertEqual(db.get_cards(), [])

    def test_add_card_replace_on_duplicate_name(self):
        db.add_card("DBS WWMC", "15th", 1)
        db.add_card("DBS WWMC", "20th", 13)
        cards = db.get_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].due_day, "20th")

    def test_add_and_get_category(self):
        db.add_category("Groceries")
        self.assertIn("Groceries", db.get_categories())

    def test_remove_category(self):
        db.add_category("Groceries")
        db.remove_category("Groceries")
        self.assertNotIn("Groceries", db.get_categories())

    def test_add_duplicate_category_is_idempotent(self):
        db.add_category("Groceries")
        db.add_category("Groceries")
        self.assertEqual(db.get_categories().count("Groceries"), 1)

    def test_set_and_get_card_rule(self):
        db.set_card_rule("Groceries", "UOB Ladies")
        rules = dict(db.get_card_rules())
        self.assertEqual(rules["Groceries"], "UOB Ladies")

    def test_set_card_rule_updates_existing(self):
        db.set_card_rule("Groceries", "UOB Ladies")
        db.set_card_rule("Groceries", "DBS WWMC")
        rules = dict(db.get_card_rules())
        self.assertEqual(rules["Groceries"], "DBS WWMC")

    def test_remove_card_rule(self):
        db.set_card_rule("Groceries", "UOB Ladies")
        db.remove_card_rule("Groceries")
        self.assertEqual(db.get_card_rules(), [])

    def test_add_and_get_merchant_alias(self):
        db.add_merchant_alias("NTUC", "Groceries")
        aliases = dict(db.get_merchant_aliases())
        self.assertEqual(aliases["NTUC"], "Groceries")

    def test_remove_merchant_alias(self):
        db.add_merchant_alias("NTUC", "Groceries")
        db.remove_merchant_alias("NTUC")
        self.assertEqual(db.get_merchant_aliases(), [])

    def test_append_and_read_spend_rows(self):
        ts = datetime(2026, 5, 10, 10, 0, 0)
        db.append_spend(ts, Decimal("42.50"), "DBS WWMC", "Groceries")
        rows = db.get_all_spend_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].card, "DBS WWMC")
        self.assertEqual(rows[0].amount, "42.50")
        self.assertEqual(rows[0].category, "Groceries")

    def test_get_spend_rows_in_range_filters_by_date(self):
        db.append_spend(datetime(2026, 4, 15, 10, 0), Decimal("99.00"), "DBS", "Food")
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("42.00"), "DBS", "Food")
        rows = db.get_spend_rows_in_range(date(2026, 5, 1), date(2026, 5, 31))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, "42.00")

    def test_get_last_spend_returns_most_recent(self):
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("10.00"), "DBS", "Food")
        db.append_spend(datetime(2026, 5, 11, 10, 0), Decimal("99.00"), "UOB", "Transport")
        last = db.get_last_spend()
        self.assertIsNotNone(last)
        self.assertEqual(last.amount, "99.00")
        self.assertEqual(last.card, "UOB")

    def test_get_last_spend_returns_none_when_empty(self):
        self.assertIsNone(db.get_last_spend())

    def test_get_recent_spend_rows_returns_newest_first(self):
        for day, amt in [(10, "10.00"), (11, "20.00"), (12, "30.00")]:
            db.append_spend(datetime(2026, 5, day, 10, 0), Decimal(amt), "DBS", "Food")
        rows = db.get_recent_spend_rows(5)
        self.assertEqual([r.amount for r in rows], ["30.00", "20.00", "10.00"])

    def test_get_recent_spend_rows_respects_limit(self):
        for day in range(1, 9):
            db.append_spend(datetime(2026, 5, day, 10, 0), Decimal("1.00"), "DBS", "Food")
        self.assertEqual(len(db.get_recent_spend_rows(5)), 5)

    def test_get_recent_spend_rows_empty(self):
        self.assertEqual(db.get_recent_spend_rows(5), [])

    def test_delete_last_spend_removes_most_recent(self):
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("10.00"), "DBS", "Food")
        db.append_spend(datetime(2026, 5, 11, 10, 0), Decimal("99.00"), "UOB", "Transport")
        deleted = db.delete_last_spend()
        self.assertEqual(deleted.amount, "99.00")
        remaining = db.get_all_spend_rows()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].amount, "10.00")

    def test_delete_last_spend_returns_none_when_empty(self):
        self.assertIsNone(db.delete_last_spend())

    def test_append_spend_with_remarks(self):
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("42.00"), "DBS", "Food", remarks="birthday dinner")
        row = db.get_last_spend()
        self.assertEqual(row.remarks, "birthday dinner")

    def test_append_spend_without_remarks_defaults_to_none(self):
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("10.00"), "DBS", "Food")
        row = db.get_last_spend()
        self.assertIsNone(row.remarks)

    def test_remarks_included_in_range_query(self):
        db.append_spend(datetime(2026, 5, 10, 10, 0), Decimal("20.00"), "DBS", "Food", remarks="note")
        rows = db.get_spend_rows_in_range(date(2026, 5, 1), date(2026, 5, 31))
        self.assertEqual(rows[0].remarks, "note")

    def test_migration_adds_remarks_column_to_existing_db(self):
        # Simulate a pre-remarks DB by dropping and recreating without the column
        _db = db._conn
        _db.execute("DROP TABLE IF EXISTS spend_entries_old")
        _db.execute("ALTER TABLE spend_entries RENAME TO spend_entries_old")
        _db.execute(
            "CREATE TABLE spend_entries "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
            "amount TEXT NOT NULL, card TEXT NOT NULL, category TEXT NOT NULL)"
        )
        _db.commit()
        # Migration should add the remarks column
        db._migrate(_db)
        cols = {row[1] for row in _db.execute("PRAGMA table_info(spend_entries)")}
        self.assertIn("remarks", cols)
        # Cleanup
        _db.execute("DROP TABLE spend_entries")
        _db.execute("ALTER TABLE spend_entries_old RENAME TO spend_entries")
        _db.commit()

    def test_init_rejects_unwritable_database_file(self):
        db_path = Path(self._tmp.name)

        def fake_access(path, mode):
            return Path(path) != db_path

        with patch("db.os.access", side_effect=fake_access):
            with self.assertRaisesRegex(db.DatabasePermissionError, "Database file exists but is not writable"):
                db.init(db_path)


# ── Config ────────────────────────────────────────────────────────────────────

@patch('config.load_dotenv')
class ConfigTests(unittest.TestCase):
    def test_load_config_requires_token(self, _dotenv):
        from config import load_config
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                load_config()

    def test_load_config_returns_botconfig(self, _dotenv):
        from config import load_config, BotConfig
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=True):
            cfg = load_config()
        self.assertIsInstance(cfg, BotConfig)
        self.assertEqual(cfg.token, "test-token")
        self.assertIsNone(cfg.reminder_chat_id)

    def test_load_config_parses_reminder_chat_id(self, _dotenv):
        from config import load_config
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "tok",
            "TELEGRAM_REMINDER_CHAT_ID": "123456",
        }, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.reminder_chat_id, 123456)


if __name__ == "__main__":
    unittest.main()
