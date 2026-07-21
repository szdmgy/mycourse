# -*- coding: utf-8 -*-
"""报告提交预检：封面预检 + 框架预检（JSON DSL）。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from docx import Document
from django.utils import timezone

from app01.report_template import (
    FIXED_COLLEGE,
    FIXED_MAJOR,
    build_cover_values,
    resolve_task_template,
    task_allows_report_template,
    _COMBO_RE,
    _paragraph_full_text,
    _iter_paragraphs,
)

# 封面日期字段：内置校验；规则包若针对这些字段则跳过内置
COVER_DATE_LABELS = ("实验时间", "实验报告提交时间")
COVER_DATE_LABEL_ALIASES = {
    "实验时间": "实验时间",
    "实验报告提交时间": "实验报告提交时间",
    "提交时间": "实验报告提交时间",
}
_HALF_YEAR_DAYS = 183  # 约半年


@dataclass
class PrecheckIssue:
    code: str
    message: str


@dataclass
class PrecheckPlan:
    do_cover: bool = False
    do_framework: bool = False
    fail_mode: str = "block"  # block | warn
    skip_reason: str = ""


@dataclass
class PrecheckResult:
    ok: bool = True
    fail_mode: str = "block"
    issues: list = field(default_factory=list)

    def as_text(self) -> str:
        lines = [i.message for i in self.issues]
        return "\n".join(lines)


def resolve_precheck_plan(task) -> PrecheckPlan:
    """
    解析某作业是否预检。
    - 继承课程默认封面预检：仅当该作业能解析到报告模板时才做封面预检
    - 作业显式开启预检：即使无模板也可做封面弱校验；框架需有规则包
    """
    course = task.courseBelongTo
    mode = (task.precheck_mode or "inherit").strip()
    has_template = resolve_task_template(task) is not None

    def fail_mode() -> str:
        fm = (task.precheck_fail_mode or "inherit").strip()
        if fm in ("block", "warn"):
            return fm
        return (course.precheck_cover_mode or "block").strip() or "block"

    if mode == "off":
        return PrecheckPlan(skip_reason="作业已关闭预检")

    if mode == "inherit":
        if (course.precheck_master or "off") != "cover_default":
            return PrecheckPlan(skip_reason="课程未开启默认封面预检")
        if not has_template:
            return PrecheckPlan(skip_reason="无报告模板，默认不做预检")
        if not task_allows_report_template(task):
            return PrecheckPlan(skip_reason="本作业不允许 .docx，跳过预检")
        return PrecheckPlan(do_cover=True, do_framework=False, fail_mode=fail_mode())

    # 作业专用
    if not task_allows_report_template(task):
        return PrecheckPlan(skip_reason="本作业不允许 .docx，无法预检")

    do_cover = mode in ("cover", "cover_and_framework")
    do_framework = mode in ("framework", "cover_and_framework")
    if do_framework and not (task.precheck_package_json or "").strip():
        # 允许计划标记需要框架，执行时再报「未配置规则包」
        pass
    if not do_cover and not do_framework:
        return PrecheckPlan(skip_reason="预检模式无效")
    return PrecheckPlan(do_cover=do_cover, do_framework=do_framework, fail_mode=fail_mode())


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _extract_label_value(text: str, label: str) -> str | None:
    pat = re.compile(rf"{re.escape(label)}\s*[：:](.*)$")
    m = pat.search(text)
    if not m:
        return None
    return (m.group(1) or "").strip()


def _normalize_year(y: int) -> int:
    if y < 100:
        return 2000 + y
    return y


@dataclass(frozen=True)
class ParsedCoverDate:
    """封面日期；day 可为 None（仅年月，比较时按当月 1 日）。"""
    year: int
    month: int
    day: int | None = None
    raw: str = ""

    def as_date(self) -> date:
        d = self.day if self.day is not None else 1
        return date(self.year, self.month, d)

    def display(self) -> str:
        if self.day is not None:
            return f"{self.year}年{self.month}月{self.day}日"
        return f"{self.year}年{self.month}月"


# 至少年月；单独年份在解析失败后单独判定
_CN_DATE_RE = re.compile(
    r"(?P<y>\d{2,4})\s*年\s*(?P<m>\d{1,2})\s*月(?:\s*(?P<d>\d{1,2})\s*日?)?"
)
_NUM_DATE_RE = re.compile(
    r"(?P<y>\d{2,4})\s*[./\-_]\s*(?P<m>\d{1,2})(?:\s*[./\-_]\s*(?P<d>\d{1,2}))?"
)


def parse_flexible_date(text: str) -> tuple[ParsedCoverDate | None, str]:
    """
    宽松解析封面日期。
    成功返回 (ParsedCoverDate, "")；失败返回 (None, 原因码)。
    原因码：empty / year_only / unparseable / invalid
    """
    s = (text or "").strip()
    if not s or not re.search(r"\d", s):
        return None, "empty"

    # 优先匹配「年月」或「年月日」
    for cre in (_CN_DATE_RE, _NUM_DATE_RE):
        m = cre.search(s)
        if not m:
            continue
        try:
            y = _normalize_year(int(m.group("y")))
            month = int(m.group("m"))
            day_s = m.groupdict().get("d")
            day = int(day_s) if day_s else None
            if not (1 <= month <= 12):
                return None, "invalid"
            if day is not None:
                date(y, month, day)  # 校验日合法
            else:
                date(y, month, 1)
            return ParsedCoverDate(year=y, month=month, day=day, raw=s), ""
        except (ValueError, TypeError):
            return None, "invalid"

    # 能认出年份但没有月 → 明确拒绝
    if re.search(r"(?<!\d)\d{2,4}\s*年", s) or re.fullmatch(r"\s*\d{2,4}\s*", s):
        return None, "year_only"
    return None, "unparseable"


def package_overrides_cover_dates(package_json: str | None) -> bool:
    """
    规则包若针对封面日期字段，则跳过内置日期校验。
    判定：
    - 根级 skip_builtin_cover_dates / cover_dates=custom
    - 任一条 rule 的 field/target/cover_field/label 命中日期字段名
    """
    raw = (package_json or "").strip()
    if not raw:
        return False
    try:
        pkg = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(pkg, dict):
        return False
    if pkg.get("skip_builtin_cover_dates") is True:
        return True
    if (pkg.get("cover_dates") or "").strip() == "custom":
        return True
    keys = set(COVER_DATE_LABEL_ALIASES.keys())
    for rule in pkg.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for k in ("field", "target", "cover_field", "label"):
            v = (rule.get(k) or "").strip()
            if v in keys:
                return True
    return False


def extract_cover_fields(docx_path: str) -> dict:
    """从已提交 docx 抽取封面字段。"""
    doc = Document(docx_path)
    found = {
        "课程名称": "",
        "实验名称": "",
        "学院": "",
        "专业": "",
        "指导教师": "",
        "姓名": "",
        "学号": "",
        "班级": "",
        "实验时间": "",
        "实验报告提交时间": "",
    }
    present = {k: False for k in ("实验时间", "实验报告提交时间")}
    # 较长标签优先，避免「提交时间」误吃「实验报告提交时间」
    label_keys = (
        ("课程名称", "课程名称"),
        ("实验项目名称", "实验名称"),
        ("实验名称", "实验名称"),
        ("学院", "学院"),
        ("专业", "专业"),
        ("指导教师", "指导教师"),
        ("指导老师", "指导教师"),
        ("报告人", "姓名"),
        ("姓名", "姓名"),
        ("学号", "学号"),
        ("班级", "班级"),
        ("实验报告提交时间", "实验报告提交时间"),
        ("实验时间", "实验时间"),
        ("提交时间", "实验报告提交时间"),
    )
    for para in _iter_paragraphs(doc):
        text = _paragraph_full_text(para)
        if not text.strip():
            continue
        m = _COMBO_RE.match(text)
        if m:
            found["姓名"] = (m.group("a_val") or "").strip() or found["姓名"]
            found["学号"] = (m.group("b_val") or "").strip() or found["学号"]
            found["班级"] = (m.group("c_val") or "").strip() or found["班级"]
            continue
        for label, key in label_keys:
            if label not in text:
                continue
            val = _extract_label_value(text, label)
            if val is None:
                continue
            if key in present:
                present[key] = True
            if not found[key]:
                found[key] = val
    found["_present_实验时间"] = present["实验时间"]
    found["_present_实验报告提交时间"] = present["实验报告提交时间"]
    return found


def _resolve_date_field(
    actual: dict, key: str, label: str, issues: list[PrecheckIssue]
) -> ParsedCoverDate | None:
    """封面存在该标签时解析；空/仅年/无法解析则记 issue。"""
    if not actual.get(f"_present_{key}"):
        return None
    raw = (actual.get(key) or "").strip()
    parsed, reason = parse_flexible_date(raw)
    if parsed:
        return parsed
    if reason == "empty":
        issues.append(PrecheckIssue("cover_date_empty", f"封面「{label}」为空，请填写至少到年月"))
    elif reason == "year_only":
        issues.append(
            PrecheckIssue("cover_date_year_only", f"封面「{label}」仅有年份「{raw}」，须至少填写到年月")
        )
    elif reason == "invalid":
        issues.append(PrecheckIssue("cover_date_invalid", f"封面「{label}」日期无效：「{raw}」"))
    else:
        issues.append(
            PrecheckIssue(
                "cover_date_unparseable",
                f"封面「{label}」无法识别日期「{raw}」，请使用如 2026年5月、2026-5-6、2026/5/6 等格式",
            )
        )
    return None


def run_cover_date_precheck(actual: dict, task) -> list[PrecheckIssue]:
    """内置封面日期逻辑（规则包未覆盖这两项时使用）。"""
    issues: list[PrecheckIssue] = []
    exp_d = _resolve_date_field(actual, "实验时间", "实验时间", issues)
    sub_d = _resolve_date_field(actual, "实验报告提交时间", "实验报告提交时间", issues)

    today = timezone.localdate()
    if exp_d is not None:
        delta = abs((exp_d.as_date() - today).days)
        if delta > _HALF_YEAR_DAYS:
            issues.append(
                PrecheckIssue(
                    "cover_date_exp_range",
                    f"封面「实验时间」{exp_d.display()} 与当前日期相差超过半年（当前 {today.isoformat()}）",
                )
            )

    if exp_d is not None and sub_d is not None:
        if exp_d.as_date() > sub_d.as_date():
            issues.append(
                PrecheckIssue(
                    "cover_date_order",
                    f"封面「实验时间」{exp_d.display()} 不能晚于「实验报告提交时间」{sub_d.display()}",
                )
            )

    if sub_d is not None:
        deadline = getattr(task, "deadline", None)
        if deadline is not None:
            if sub_d.as_date() > deadline:
                issues.append(
                    PrecheckIssue(
                        "cover_date_deadline",
                        f"封面「实验报告提交时间」{sub_d.display()} 不能晚于作业截止日期 {deadline.isoformat()}",
                    )
                )
    return issues


def run_cover_precheck(docx_path: str, task, profile, user) -> list[PrecheckIssue]:
    expected = build_cover_values(task, profile, user)
    actual = extract_cover_fields(docx_path)
    issues: list[PrecheckIssue] = []

    def need(key: str, label: str, exp: str):
        got = actual.get(key) or ""
        if not _norm(got):
            issues.append(PrecheckIssue("cover_empty", f"封面「{label}」为空，应为：{exp}"))
        elif _norm(got) != _norm(exp):
            issues.append(
                PrecheckIssue("cover_mismatch", f"封面「{label}」不匹配：当前「{got}」，应为「{exp}」")
            )

    need("课程名称", "课程名称", expected.get("课程名称") or "")
    need("学院", "学院", FIXED_COLLEGE)
    need("专业", "专业", FIXED_MAJOR)
    # 指导教师：课程可能多人，要求提交中包含系统教师字符串，或规范化后相等/互相包含
    exp_teacher = expected.get("指导教师") or ""
    got_teacher = actual.get("指导教师") or ""
    if not _norm(got_teacher):
        issues.append(PrecheckIssue("cover_empty", f"封面「指导教师」为空，应为：{exp_teacher}"))
    elif _norm(exp_teacher) and _norm(exp_teacher) not in _norm(got_teacher) and _norm(got_teacher) not in _norm(exp_teacher):
        # 允许多教师名单顺序不同：拆分比较
        exp_set = {x.strip() for x in re.split(r"[,，、]", exp_teacher) if x.strip()}
        got_set = {x.strip() for x in re.split(r"[,，、]", got_teacher) if x.strip()}
        if exp_set and not exp_set.issubset(got_set) and not got_set.issubset(exp_set):
            issues.append(
                PrecheckIssue("cover_mismatch", f"封面「指导教师」不匹配：当前「{got_teacher}」，系统为「{exp_teacher}」")
            )

    need("姓名", "报告人", expected.get("姓名") or "")
    need("学号", "学号", expected.get("学号") or "")
    # 班级：01 / 01班 均接受
    exp_class = expected.get("班级") or ""
    got_class = actual.get("班级") or ""
    if not _norm(got_class):
        issues.append(PrecheckIssue("cover_empty", f"封面「班级」为空，应为：{exp_class}"))
    else:
        ec = _norm(exp_class).rstrip("班")
        gc = _norm(got_class).rstrip("班")
        if ec != gc:
            issues.append(
                PrecheckIssue("cover_mismatch", f"封面「班级」不匹配：当前「{got_class}」，应为「{exp_class}」")
            )

    # 实验名称：有期望标题时要求非空且大致匹配
    exp_title = expected.get("实验名称") or ""
    got_title = actual.get("实验名称") or ""
    if exp_title:
        if not _norm(got_title):
            issues.append(PrecheckIssue("cover_empty", f"封面「实验项目名称」为空，应为：{exp_title}"))
        elif _norm(exp_title) not in _norm(got_title) and _norm(got_title) not in _norm(exp_title):
            issues.append(
                PrecheckIssue("cover_mismatch", f"封面「实验项目名称」不匹配：当前「{got_title}」，应为「{exp_title}」")
            )

    # 日期：封面有对应标签时校验；规则包针对这两项则跳过内置
    if not package_overrides_cover_dates(getattr(task, "precheck_package_json", None)):
        issues.extend(run_cover_date_precheck(actual, task))
    return issues


def run_framework_precheck(docx_path: str, package_json: str) -> list[PrecheckIssue]:
    raw = (package_json or "").strip()
    if not raw:
        return [PrecheckIssue("framework_missing", "已启用框架预检，但未配置预检规则包，请联系教师")]
    try:
        pkg = json.loads(raw)
    except json.JSONDecodeError:
        return [PrecheckIssue("framework_invalid", "框架预检规则包不是合法 JSON")]
    if not isinstance(pkg, dict):
        return [PrecheckIssue("framework_invalid", "框架预检规则包格式错误")]
    rules = pkg.get("rules") or []
    if not isinstance(rules, list) or not rules:
        return [PrecheckIssue("framework_invalid", "框架预检规则包中没有 rules")]

    doc = Document(docx_path)
    full_text = "\n".join(_paragraph_full_text(p) for p in _iter_paragraphs(doc))
    issues: list[PrecheckIssue] = []

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            issues.append(PrecheckIssue("framework_rule", f"第 {i+1} 条规则格式错误"))
            continue
        rtype = (rule.get("type") or "").strip()
        msg = (rule.get("message") or "").strip() or f"未通过框架规则 #{i+1}"
        if rtype == "contains":
            text = rule.get("text") or ""
            if text and text not in full_text:
                issues.append(PrecheckIssue("framework_contains", msg))
        elif rtype == "contains_any":
            texts = rule.get("texts") or []
            if texts and not any(t in full_text for t in texts if t):
                issues.append(PrecheckIssue("framework_contains_any", msg))
        elif rtype == "contains_all":
            texts = rule.get("texts") or []
            missing = [t for t in texts if t and t not in full_text]
            if missing:
                issues.append(PrecheckIssue("framework_contains_all", msg + f"（缺少：{'、'.join(missing)}）"))
        elif rtype == "min_chars":
            try:
                n = int(rule.get("value") or 0)
            except (TypeError, ValueError):
                issues.append(PrecheckIssue("framework_rule", f"第 {i+1} 条 min_chars 无效"))
                continue
            if len(re.sub(r"\s+", "", full_text)) < n:
                issues.append(PrecheckIssue("framework_min_chars", msg))
        elif rtype == "regex":
            pat = rule.get("pattern") or ""
            try:
                if pat and not re.search(pat, full_text):
                    issues.append(PrecheckIssue("framework_regex", msg))
            except re.error:
                issues.append(PrecheckIssue("framework_rule", f"第 {i+1} 条正则无效"))
        else:
            issues.append(PrecheckIssue("framework_rule", f"不支持的规则类型：{rtype or '(空)'}"))
    return issues


def run_precheck_on_file(docx_path: str, task, profile, user) -> PrecheckResult:
    plan = resolve_precheck_plan(task)
    result = PrecheckResult(ok=True, fail_mode=plan.fail_mode or "block", issues=[])
    if not plan.do_cover and not plan.do_framework:
        return result
    if plan.do_cover:
        result.issues.extend(run_cover_precheck(docx_path, task, profile, user))
    if plan.do_framework:
        result.issues.extend(run_framework_precheck(docx_path, task.precheck_package_json))
    result.ok = len(result.issues) == 0
    return result


def validate_precheck_package(raw: str) -> tuple[str | None, dict | None]:
    """校验框架预检 JSON，成功返回 (None, pkg)。"""
    try:
        pkg = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"JSON 解析失败：{e}", None
    if not isinstance(pkg, dict):
        return "根节点须为 JSON 对象", None
    rules = pkg.get("rules")
    if not isinstance(rules, list) or not rules:
        return "须包含非空 rules 数组", None
    allowed = {"contains", "contains_any", "contains_all", "min_chars", "regex"}
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or (rule.get("type") or "") not in allowed:
            return f"第 {i+1} 条规则 type 无效（允许：{', '.join(sorted(allowed))}）", None
    return None, pkg


def task_has_reusable_precheck(task) -> bool:
    """作业级是否有可随历史复用带走的预检配置（非纯继承默认）。"""
    mode = (getattr(task, "precheck_mode", None) or "inherit").strip()
    fail = (getattr(task, "precheck_fail_mode", None) or "inherit").strip()
    pkg = (getattr(task, "precheck_package_json", None) or "").strip()
    return mode != "inherit" or fail != "inherit" or bool(pkg)


def copy_precheck_to_task(src_task, dest_task) -> bool:
    """历史复用：同步作业级预检模式、失败策略与框架规则包。"""
    dest_task.precheck_mode = (getattr(src_task, "precheck_mode", None) or "inherit").strip() or "inherit"
    dest_task.precheck_fail_mode = (
        (getattr(src_task, "precheck_fail_mode", None) or "inherit").strip() or "inherit"
    )
    dest_task.precheck_package_json = getattr(src_task, "precheck_package_json", None) or ""
    dest_task.precheck_package_version = getattr(src_task, "precheck_package_version", None) or ""
    dest_task.precheck_package_updated_at = getattr(src_task, "precheck_package_updated_at", None)
    dest_task.save(update_fields=[
        "precheck_mode",
        "precheck_fail_mode",
        "precheck_package_json",
        "precheck_package_version",
        "precheck_package_updated_at",
    ])
    return task_has_reusable_precheck(dest_task)


def precheck_display(task) -> dict:
    """供列表/提交页展示的预检摘要。"""
    plan = resolve_precheck_plan(task)
    mode = (getattr(task, "precheck_mode", None) or "inherit").strip()
    mode_labels = {
        "inherit": "继承课程",
        "off": "作业关闭",
        "cover": "仅封面",
        "framework": "仅框架",
        "cover_and_framework": "封面+框架",
    }
    if plan.do_cover and plan.do_framework:
        label, kind = "封面+框架", "both"
    elif plan.do_cover:
        label, kind = "封面预检", "cover"
    elif plan.do_framework:
        label, kind = "框架预检", "framework"
    else:
        label, kind = "不预检", "off"
    fail = plan.fail_mode or "block"
    return {
        "active": bool(plan.do_cover or plan.do_framework),
        "kind": kind,
        "label": label,
        "fail_mode": fail,
        "fail_label": "硬拦截" if fail == "block" else "仅警告",
        "skip_reason": plan.skip_reason or "",
        "config_mode": mode,
        "config_label": mode_labels.get(mode, mode),
        "do_cover": plan.do_cover,
        "do_framework": plan.do_framework,
        "has_package": bool((getattr(task, "precheck_package_json", None) or "").strip()),
    }
