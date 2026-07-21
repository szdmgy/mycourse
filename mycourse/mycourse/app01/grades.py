# -*- coding: utf-8 -*-
"""定性批改辅助。"""
from collections import OrderedDict

from app01.models import Homework, HomeworkGrade

LETTER_CHOICES = HomeworkGrade.LETTER_CHOICES
VALID_LETTERS = HomeworkGrade.VALID_LETTERS
LETTER_ORDER = [c[0] for c in LETTER_CHOICES]

# 调用方未传入 score 时保留原值；显式 null/'' 则清空
SCORE_UNSET = object()


def parse_score(score):
    """
    解析可选参考分。
    返回 int 或 None；非法值抛 ValueError。
    None / '' → None（清空）。
    """
    if score is None:
        return None
    if isinstance(score, str):
        s = score.strip()
        if s == '':
            return None
        if not s.isdigit():
            raise ValueError('参考分须为 0–100 的整数')
        value = int(s)
    elif isinstance(score, bool):
        raise ValueError('参考分须为 0–100 的整数')
    elif isinstance(score, int):
        value = score
    elif isinstance(score, float):
        if not score.is_integer():
            raise ValueError('参考分须为 0–100 的整数')
        value = int(score)
    else:
        raise ValueError('参考分须为 0–100 的整数')
    if value < 0 or value > 100:
        raise ValueError('参考分须为 0–100 的整数')
    return value


def serialize_grade(grade, for_student=False):
    if not grade:
        return None
    if for_student and not grade.visible_to_student():
        return None
    data = {
        'letter_grade': grade.letter_grade,
        'is_fail': grade.is_fail,
        'needs_regrade': grade.needs_regrade,
        'updated_at': grade.updated_at.isoformat() if grade.updated_at else None,
    }
    if for_student:
        data['comment'] = grade.comment or ''
        data['label'] = '不合格' if grade.is_fail else grade.letter_grade
    else:
        data['comment'] = grade.comment or ''
        data['score'] = grade.score
        data['graded_at'] = grade.graded_at.isoformat() if grade.graded_at else None
        data['graded_by'] = (
            grade.graded_by.username if grade.graded_by_id else None
        )
    return data


def upsert_grade(homework, letter_grade, comment, graded_by, score=SCORE_UNSET):
    letter = (letter_grade or '').strip()
    if letter not in VALID_LETTERS:
        raise ValueError(f'无效等级：{letter_grade}，允许：{", ".join(sorted(VALID_LETTERS))}')
    comment = (comment or '').strip()
    update_score = score is not SCORE_UNSET
    parsed_score = parse_score(score) if update_score else None
    defaults = {
        'letter_grade': letter,
        'comment': comment,
        'graded_by': graded_by,
        'needs_regrade': False,
    }
    if update_score:
        defaults['score'] = parsed_score
    grade, created = HomeworkGrade.objects.get_or_create(
        homework=homework,
        defaults=defaults,
    )
    if not created:
        grade.letter_grade = letter
        grade.comment = comment
        if update_score:
            grade.score = parsed_score
        grade.graded_by = graded_by
        grade.needs_regrade = False
        grade.save()
    return grade, created


def build_grade_summary(task, students_qs=None):
    """
    构建某作业定性成绩汇总。
    占比分母 = 应交总人数。
    """
    course = task.courseBelongTo
    if students_qs is None:
        students = list(course.members.filter(type='S').select_related('user'))
    else:
        students = list(students_qs)

    student_set = {s.pk for s in students}
    homeworks = list(
        Homework.objects.filter(task=task, user_id__in=student_set)
        .select_related('user', 'user__user', 'grade')
    )

    expected = len(students)
    submitted = len(homeworks)
    not_submitted = expected - submitted

    by_letter = OrderedDict((letter, []) for letter in LETTER_ORDER)
    ungraded = []
    fail_list = []
    needs_regrade_list = []
    graded_count = 0

    for hw in homeworks:
        stu = hw.user
        row = {
            'homework_id': hw.id,
            'number': stu.user.username,
            'name': stu.name,
        }
        try:
            g = hw.grade
        except HomeworkGrade.DoesNotExist:
            g = None
        if g is None:
            ungraded.append(row)
            continue
        graded_count += 1
        row = {
            **row,
            'letter_grade': g.letter_grade,
            'score': g.score,
            'comment': g.comment or '',
            'needs_regrade': g.needs_regrade,
        }
        if g.letter_grade in by_letter:
            by_letter[g.letter_grade].append(row)
        if g.is_fail:
            fail_list.append(row)
        if g.needs_regrade:
            needs_regrade_list.append(row)

    denom = expected or 0

    def _pct(count: int) -> float:
        return round(100.0 * count / denom, 1) if denom else 0.0

    distribution = []
    for letter in LETTER_ORDER:
        count = len(by_letter[letter])
        distribution.append({
            'letter': letter,
            'count': count,
            'percent': _pct(count),
            'students': by_letter[letter],
        })

    # 饼图：各等级 + 未批改（>0 才显示）+ 未提交（>0 才显示）
    pie_colors = {
        'A+': '#0d6efd',
        'A': '#198754',
        'B': '#20c997',
        'C': '#0dcaf0',
        'D': '#ffc107',
        'F': '#dc3545',
        '未批改': '#6c757d',
        '未提交': '#adb5bd',
    }
    pie_slices = []
    for letter in LETTER_ORDER:
        count = len(by_letter[letter])
        if count <= 0:
            continue
        pie_slices.append({
            'label': letter,
            'count': count,
            'percent': _pct(count),
            'color': pie_colors[letter],
        })
    if len(ungraded) > 0:
        pie_slices.append({
            'label': '未批改',
            'count': len(ungraded),
            'percent': _pct(len(ungraded)),
            'color': pie_colors['未批改'],
        })
    if not_submitted > 0:
        pie_slices.append({
            'label': '未提交',
            'count': not_submitted,
            'percent': _pct(not_submitted),
            'color': pie_colors['未提交'],
        })

    return {
        'expected': expected,
        'submitted': submitted,
        'not_submitted': not_submitted,
        'graded': graded_count,
        'ungraded': len(ungraded),
        'fail_count': len(fail_list),
        'needs_regrade_count': len(needs_regrade_list),
        'percent_base': 'expected',
        'distribution': distribution,
        'pie_slices': pie_slices,
        'ungraded_list': ungraded,
        'fail_list': fail_list,
        'needs_regrade_list': needs_regrade_list,
    }
