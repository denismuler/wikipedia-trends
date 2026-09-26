"""Copy report files to a convenient location and print paths for chat/UI."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import date
from pathlib import Path


def downloads_dir() -> Path:
    custom = os.environ.get("WIKI_SKILL_DOWNLOADS_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / "Downloads"


def copy_to_downloads(src: Path, stem: str) -> Path:
    """Copy ``src`` to Downloads as ``wikipedia-trends_{stem}{suffix}`` (unique if needed)."""
    dest_dir = downloads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix
    base = f"wikipedia-trends_{stem}"
    dest = dest_dir / f"{base}{suffix}"
    if dest.exists():
        dest = dest_dir / f"{base}_{date.today().strftime('%Y%m%d')}{suffix}"
    shutil.copy2(src, dest)
    return dest.resolve()


def open_in_system_viewer(*paths: Path) -> None:
    if not paths:
        return
    system = platform.system()
    files = [str(p) for p in paths if p.is_file()]
    if not files:
        return
    if system == "Darwin":
        subprocess.run(["open", *files], check=False)
    elif system == "Linux":
        subprocess.run(["xdg-open", *files], check=False)
    elif system == "Windows":
        for f in files:
            os.startfile(f)  # type: ignore[attr-defined]


def print_deliverables(
    chart_png: Path,
    report_pdf: Path,
    *,
    copy_downloads: bool = True,
    open_files: bool = False,
    title: str = "",
) -> dict[str, str]:
    """Print a machine- and human-friendly block; return path map."""
    chart_png = chart_png.resolve()
    report_pdf = report_pdf.resolve()
    stem = chart_png.stem

    dl_png = dl_pdf = ""
    if copy_downloads and not os.environ.get("WIKI_SKILL_SKIP_DOWNLOADS"):
        try:
            dl_png = str(copy_to_downloads(chart_png, stem))
            dl_pdf = str(copy_to_downloads(report_pdf, stem))
        except OSError as exc:
            print(f"WARNING: could not copy to Downloads: {exc}", flush=True)

    if open_files:
        open_in_system_viewer(chart_png, report_pdf)
        if dl_png and dl_pdf:
            open_in_system_viewer(Path(dl_png), Path(dl_pdf))

    chart_md = f"![{title or 'Wikipedia trends chart'}]({chart_png})"
    payload = {
        "chart_png": str(chart_png),
        "report_pdf": str(report_pdf),
        "chart_markdown": chart_md,
        "downloads_chart_png": dl_png,
        "downloads_report_pdf": dl_pdf,
    }

    print("-" * 70)
    print("DELIVERABLES (show chart in chat + open locally)")
    print(f"  Chart (PNG):     {chart_png}")
    print(f"  Report (PDF):    {report_pdf}")
    if dl_png:
        print(f"  Downloads PNG:   {dl_png}")
        print(f"  Downloads PDF:   {dl_pdf}")
    print()
    print("  Paste in chat (markdown image):")
    print(f"  {chart_md}")
    print()
    print(f"WIKI_TRENDS_DELIVERABLES={json.dumps(payload, ensure_ascii=False)}")
    print("=" * 70)

    return payload
