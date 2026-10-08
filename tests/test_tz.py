import unittest
from datetime import datetime, timezone, timedelta, date, time
from zoneinfo import ZoneInfo
from tradingbot.utils.tz import (
    CHILE_TZ,
    UTC_TZ,
    now_chile,
    now_utc,
    parse_datetime,
    utc_to_chile,
    chile_to_utc,
    format_chile,
    format_chile_human,
    format_dual_tz,
    get_chile_offset_str,
    get_chile_day_range_in_utc,
    get_active_hours_info,
    explain_schedule_message
)


class TestTimezoneHelper(unittest.TestCase):

    def test_now_functions(self):
        cl = now_chile()
        utc = now_utc()
        self.assertIsNotNone(cl.tzinfo)
        self.assertIsNotNone(utc.tzinfo)
        # Difference in time should be within 1 second
        diff = abs((utc - cl).total_seconds())
        self.assertLess(diff, 2.0)

    def test_parse_datetime_various_inputs(self):
        # String ISO
        dt1 = parse_datetime("2026-10-08T14:30:00Z")
        self.assertEqual(dt1.tzinfo, timezone.utc)
        self.assertEqual(dt1.hour, 14)

        # String SQL format
        dt2 = parse_datetime("2026-10-08 14:30:00")
        self.assertEqual(dt2.hour, 14)

        # Float timestamp
        ts = 1791469800.0
        dt3 = parse_datetime(ts)
        self.assertIsNotNone(dt3)

        # None or invalid
        self.assertIsNone(parse_datetime(None))
        self.assertIsNone(parse_datetime("invalid_date_string"))

    def test_utc_to_chile_conversion(self):
        # 14:00 UTC should be 11:00 in Chile (UTC-3 in October)
        utc_dt = datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc)
        cl_dt = utc_to_chile(utc_dt)
        self.assertEqual(cl_dt.hour, 11)
        self.assertEqual(cl_dt.minute, 0)

        # From string
        cl_dt_str = utc_to_chile("2026-10-08 14:00:00")
        self.assertEqual(cl_dt_str.hour, 11)

    def test_chile_to_utc_conversion(self):
        # 11:00 Chile should be 14:00 in UTC (UTC-3 in October)
        cl_dt = datetime(2026, 10, 8, 11, 0, 0, tzinfo=CHILE_TZ)
        utc_dt = chile_to_utc(cl_dt)
        self.assertEqual(utc_dt.hour, 14)
        self.assertEqual(utc_dt.minute, 0)

    def test_format_chile(self):
        utc_dt = datetime(2026, 10, 8, 14, 30, 45, tzinfo=timezone.utc)
        formatted = format_chile(utc_dt)
        self.assertEqual(formatted, "2026-10-08 11:30:45")

        formatted_tz = format_chile(utc_dt, include_tz=True)
        self.assertTrue("UTC-3" in formatted_tz or "-03" in formatted_tz)

    def test_format_dual_tz(self):
        utc_dt = datetime(2026, 10, 8, 14, 30, 0, tzinfo=timezone.utc)
        dual = format_dual_tz(utc_dt)
        self.assertIn("11:30:00", dual)
        self.assertIn("14:30:00", dual)

    def test_day_range_in_utc(self):
        target = date(2026, 10, 8)
        start_utc, end_utc = get_chile_day_range_in_utc(target)
        # 00:00 Chile (UTC-3) -> 03:00 UTC same day
        self.assertEqual(start_utc.hour, 3)
        self.assertEqual(start_utc.minute, 0)
        self.assertEqual(start_utc.day, 8)

    def test_get_active_hours_info(self):
        info = get_active_hours_info(start_utc=13, end_utc=17)
        self.assertEqual(info["start_utc"], 13)
        self.assertEqual(info["end_utc"], 17)
        # In UTC-3, 13 UTC is 10 CL, 17 UTC is 14 CL
        self.assertEqual(info["start_chile"], 10)
        self.assertEqual(info["end_chile"], 14)
        self.assertIn("10:00 - 14:00 (Chile)", info["active_range_chile"])

    def test_explain_schedule_message(self):
        msg = explain_schedule_message(13, 17)
        self.assertIn("Conversor y Monitor de Horarios", msg)
        self.assertIn("Chile", msg)
        self.assertIn("UTC", msg)


if __name__ == "__main__":
    unittest.main()
