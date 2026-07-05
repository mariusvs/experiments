"""Minimal, dependency-free PDF writer for monospaced text reports.

Generates a valid multi-page PDF using the built-in Courier font (no font
embedding needed). Good enough for tabular text reports; it is deliberately not a
general layout engine. Keeping it stdlib-only means the whole tool installs with
just psutil + pynput and still produces a shareable PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

# US Letter, points.
PAGE_W, PAGE_H = 612, 792
MARGIN = 40


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _sanitize(text: str) -> str:
    """PDF standard fonts are Latin-1; drop anything else to keep files valid."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _paginate(lines: List[str], font_size: int, leading: float) -> List[List[str]]:
    usable = PAGE_H - 2 * MARGIN
    per_page = max(1, int(usable // leading))
    return [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[]]


def text_to_pdf(lines: List[str], path: str, font_size: int = 9,
                title: str = "") -> str:
    """Write ``lines`` to a PDF at ``path`` and return the path."""
    leading = font_size * 1.35
    if title:
        lines = [title, "=" * len(title), ""] + list(lines)
    pages = _paginate([_sanitize(l) for l in lines], font_size, leading)

    objects: List[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)  # 1-based object number

    # Reserve: 1=catalog, 2=pages, 3=font, then page+content pairs.
    catalog_num = 1
    pages_num = 2
    font_num = 3
    objects.extend([b"", b"", b""])  # placeholders for 1..3

    kids = []
    for page_lines in pages:
        start_y = PAGE_H - MARGIN - font_size
        stream = ["BT", f"/F1 {font_size} Tf", f"{leading:.2f} TL",
                  f"{MARGIN} {start_y:.2f} Td"]
        for ln in page_lines:
            stream.append(f"({_esc(ln)}) Tj")
            stream.append("T*")
        stream.append("ET")
        content = "\n".join(stream).encode("latin-1")
        content_obj = (b"<< /Length %d >>\nstream\n" % len(content)) + content + b"\nendstream"
        content_num = add(content_obj)
        page_obj = (
            f"<< /Type /Page /Parent {pages_num} 0 R "
            f"/MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode("latin-1")
        page_num = add(page_obj)
        kids.append(page_num)

    objects[catalog_num - 1] = (
        f"<< /Type /Catalog /Pages {pages_num} 0 R >>").encode("latin-1")
    kids_str = " ".join(f"{k} 0 R" for k in kids)
    objects[pages_num - 1] = (
        f"<< /Type /Pages /Kids [{kids_str}] /Count {len(kids)} >>").encode("latin-1")
    objects[font_num - 1] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    # Assemble file with a cross-reference table.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for i, obj in enumerate(objects, start=1):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for i in range(1, len(objects) + 1):
        out += f"{offsets[i]:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_num} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode("latin-1")

    Path(path).write_bytes(out)
    return path
