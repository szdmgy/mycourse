# -*- coding: utf-8 -*-
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from app01.grades import parse_score, serialize_grade, SCORE_UNSET
from app01.precheck import (
    copy_precheck_to_task,
    parse_flexible_date,
    package_overrides_cover_dates,
    run_cover_date_precheck,
    task_has_reusable_precheck,
)


class ParseScoreTests(SimpleTestCase):
    def test_none_and_blank(self):
        self.assertIsNone(parse_score(None))
        self.assertIsNone(parse_score(''))
        self.assertIsNone(parse_score('  '))

    def test_valid_int(self):
        self.assertEqual(parse_score(0), 0)
        self.assertEqual(parse_score(100), 100)
        self.assertEqual(parse_score('85'), 85)
        self.assertEqual(parse_score(90.0), 90)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_score(-1)
        with self.assertRaises(ValueError):
            parse_score(101)
        with self.assertRaises(ValueError):
            parse_score('8.5')
        with self.assertRaises(ValueError):
            parse_score(True)

    def test_serialize_hides_score_for_student(self):
        grade = SimpleNamespace(
            letter_grade='F',
            is_fail=True,
            needs_regrade=False,
            updated_at=None,
            comment='重交',
            score=60,
            graded_at=None,
            graded_by_id=None,
            visible_to_student=lambda: True,
        )
        student = serialize_grade(grade, for_student=True)
        teacher = serialize_grade(grade, for_student=False)
        self.assertNotIn('score', student)
        self.assertEqual(teacher['score'], 60)
        self.assertIs(SCORE_UNSET, SCORE_UNSET)


class ParseFlexibleDateTests(SimpleTestCase):
    def test_chinese_full(self):
        d, err = parse_flexible_date("2026年5月6日")
        self.assertEqual(err, "")
        self.assertEqual((d.year, d.month, d.day), (2026, 5, 6))

    def test_chinese_year_month(self):
        d, err = parse_flexible_date("2026年5月")
        self.assertEqual(err, "")
        self.assertEqual((d.year, d.month, d.day), (2026, 5, None))
        self.assertEqual(d.as_date(), date(2026, 5, 1))

    def test_two_digit_year(self):
        d, err = parse_flexible_date("26年5月6日")
        self.assertEqual(err, "")
        self.assertEqual(d.year, 2026)

    def test_separators(self):
        for s in ("2026-5-6", "2026/5/6", "2026.5.6", "26-05-06"):
            d, err = parse_flexible_date(s)
            self.assertEqual(err, "", s)
            self.assertEqual((d.year, d.month, d.day), (2026, 5, 6), s)

    def test_year_only_rejected(self):
        for s in ("2026年", "2026", "26年"):
            d, err = parse_flexible_date(s)
            self.assertIsNone(d, s)
            self.assertEqual(err, "year_only", s)

    def test_empty(self):
        d, err = parse_flexible_date("   ")
        self.assertIsNone(d)
        self.assertEqual(err, "empty")


class PackageOverrideTests(SimpleTestCase):
    def test_flag(self):
        self.assertTrue(package_overrides_cover_dates('{"skip_builtin_cover_dates": true, "rules":[{"type":"contains","text":"x"}]}'))
        self.assertTrue(package_overrides_cover_dates('{"cover_dates":"custom","rules":[{"type":"contains","text":"x"}]}'))

    def test_field_on_rule(self):
        raw = '{"rules":[{"type":"regex","pattern":".+","field":"实验时间","message":"x"}]}'
        self.assertTrue(package_overrides_cover_dates(raw))

    def test_plain_contains_not_override(self):
        raw = '{"rules":[{"type":"contains","text":"实验目的","message":"x"}]}'
        self.assertFalse(package_overrides_cover_dates(raw))


class CoverDateLogicTests(SimpleTestCase):
    def _actual(self, exp="", sub="", has_exp=True, has_sub=True):
        return {
            "实验时间": exp,
            "实验报告提交时间": sub,
            "_present_实验时间": has_exp,
            "_present_实验报告提交时间": has_sub,
        }

    @override_settings(USE_TZ=True)
    def test_ok_within_half_year(self):
        today = timezone.localdate()
        exp = f"{today.year}年{today.month}月"
        sub = f"{today.year}-{today.month}-{min(today.day, 28)}"
        task = SimpleNamespace(deadline=date(today.year + 1, 12, 31))
        issues = run_cover_date_precheck(self._actual(exp, sub), task)
        self.assertEqual(issues, [])

    def test_exp_after_submit(self):
        task = SimpleNamespace(deadline=date(2026, 12, 31))
        issues = run_cover_date_precheck(
            self._actual("2026年6月", "2026年5月1日"), task
        )
        codes = [i.code for i in issues]
        self.assertIn("cover_date_order", codes)

    def test_submit_after_deadline(self):
        task = SimpleNamespace(deadline=date(2026, 5, 1))
        issues = run_cover_date_precheck(
            self._actual("2026年4月", "2026年6月1日"), task
        )
        codes = [i.code for i in issues]
        self.assertIn("cover_date_deadline", codes)

    def test_absent_labels_skipped(self):
        task = SimpleNamespace(deadline=date(2026, 12, 31))
        issues = run_cover_date_precheck(
            self._actual("", "", has_exp=False, has_sub=False), task
        )
        self.assertEqual(issues, [])


class CopyPrecheckTests(SimpleTestCase):
    class _FakeTask:
        def __init__(self, **kw):
            self.precheck_mode = kw.get("precheck_mode", "inherit")
            self.precheck_fail_mode = kw.get("precheck_fail_mode", "inherit")
            self.precheck_package_json = kw.get("precheck_package_json", "")
            self.precheck_package_version = kw.get("precheck_package_version", "")
            self.precheck_package_updated_at = kw.get("precheck_package_updated_at")
            self.saved_fields = None

        def save(self, update_fields=None):
            self.saved_fields = update_fields

    def test_has_reusable_detects_package_and_mode(self):
        self.assertFalse(task_has_reusable_precheck(self._FakeTask()))
        self.assertTrue(task_has_reusable_precheck(self._FakeTask(precheck_mode="cover")))
        self.assertTrue(task_has_reusable_precheck(
            self._FakeTask(precheck_package_json='{"rules":[]}')
        ))

    def test_copy_precheck_fields(self):
        src = self._FakeTask(
            precheck_mode="cover_and_framework",
            precheck_fail_mode="warn",
            precheck_package_json='{"rules":[{"type":"contains","text":"实验目的"}]}',
            precheck_package_version="v1",
        )
        dest = self._FakeTask()
        self.assertTrue(copy_precheck_to_task(src, dest))
        self.assertEqual(dest.precheck_mode, "cover_and_framework")
        self.assertEqual(dest.precheck_fail_mode, "warn")
        self.assertIn("实验目的", dest.precheck_package_json)
        self.assertEqual(dest.precheck_package_version, "v1")
        self.assertIn("precheck_mode", dest.saved_fields)
