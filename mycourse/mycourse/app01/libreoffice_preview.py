# -*- coding: utf-8 -*-
"""LibreOffice 转 PDF 预览（参考 practice-system）。"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("app01")

PREVIEWABLE_SUFFIXES = {".doc", ".docx", ".pdf"}


def is_previewable_name(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in PREVIEWABLE_SUFFIXES


def find_executable(*names, extra_paths=None):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for candidate in extra_paths or []:
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def bundled_libreoffice_paths():
    base_dir = Path(settings.BASE_DIR)
    return [
        base_dir / "LibreOfficePortable" / "program" / "soffice.com",
        base_dir / "LibreOfficePortable" / "program" / "soffice.exe",
        base_dir / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.com",
        base_dir / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.exe",
        base_dir / "tools" / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.com",
        base_dir / "tools" / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.exe",
    ]


def find_libreoffice_executable():
    return find_executable(
        "soffice.com",
        "soffice",
        "libreoffice",
        extra_paths=[
            *(str(path) for path in bundled_libreoffice_paths()),
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ],
    )


def preview_cache_key(file_path):
    source = Path(file_path)
    stat = source.stat()
    raw = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def preview_root():
    """缓存目录：BASE_DIR/previews/（与上传 file/ 并列，勿提交仓库）。"""
    root = Path(settings.BASE_DIR) / "previews"
    root.mkdir(parents=True, exist_ok=True)
    return root


def homework_preview_cache_path(hw_file, source_path: Path) -> Path:
    username = hw_file.homework.user.user.username
    cache_dir = preview_root() / str(username)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = preview_cache_key(source_path)
    return cache_dir / f"hwfile_{hw_file.id}_{key}.pdf"


def cleanup_old_homework_previews(hw_file, keep_path: Path):
    preview_dir = keep_path.parent
    for old_path in preview_dir.glob(f"hwfile_{hw_file.id}_*.pdf"):
        if old_path != keep_path:
            try:
                old_path.unlink()
            except OSError:
                pass


def convert_office_to_pdf(source_path, hw_file):
    """
    将 .doc/.docx 转为 PDF 并缓存。
    成功返回 Path；找不到 LibreOffice 或转换失败返回 None。
    """
    source = Path(source_path)
    target = homework_preview_cache_path(hw_file, source)
    if target.exists():
        return target

    soffice = find_libreoffice_executable()
    if not soffice:
        logger.warning("未找到 LibreOffice（soffice），无法生成预览 PDF")
        return None

    output_dir = target.parent / f"_convert_{target.stem}"
    profile_dir = target.parent / f"_lo_profile_{target.stem}"
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        soffice,
        "--headless",
        "--norestore",
        "--nofirststartwizard",
        "--nodefault",
        "--nolockcheck",
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        str(output_dir),
        str(source),
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired:
        logger.exception("LibreOffice 转换超时: %s", source)
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
        return None
    except OSError:
        logger.exception("LibreOffice 启动失败: %s", soffice)
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
        return None

    converted = output_dir / f"{source.stem}.pdf"
    if completed.returncode != 0 or not converted.exists():
        logger.warning(
            "LibreOffice 转换失败 rc=%s stderr=%s",
            completed.returncode,
            (completed.stderr or "")[:500],
        )
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
        return None

    shutil.move(str(converted), str(target))
    cleanup_old_homework_previews(hw_file, target)
    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.rmtree(profile_dir, ignore_errors=True)
    return target
