"""
Convert lecture slide PDFs (and other PDFs such as past exams) into Markdown
notes laid out like the scraped PCRS content, so they drop straight into the
Master Study Guide.

Slides (landscape pages) become one "## Slide title" section per slide, with
bullets, nesting, code blocks and tables reconstructed from font/position
information. Slides containing figures are also rendered to PNG and embedded.
Portrait documents (exams, handouts) are extracted as flowing text.

Output: <dir>/pcrs_<course>_content/week_<N>/slides_<name>/index.md
        (week_<N> is detected from the title slide or filename; otherwise the
        notes go under lecture_notes/ or practice_exams/)
"""
import os
import re
import sys
import glob
import argparse
from collections import Counter

import fitz  # PyMuPDF

MONO_RE = re.compile(r"mono|courier|consol|menlo|inconsolata|cmtt|typewriter|code", re.I)
BOLD_RE = re.compile(r"bold|black|heavy|^cmbx", re.I)
ITALIC_RE = re.compile(r"italic|oblique", re.I)
BULLET_CHARS = "▶►▸•◦▪▫■□●○‣∙·➢➤✓–—"
NUMBERED_RE = re.compile(r"^(\d{1,2}|[a-zA-Z])[.)](\s+|$)")
# Typographic ligatures/accents that break searching and copy-pasting code
GLYPH_FIXES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
                             "ˆ": "^", "˜": "~", "\u00a0": " "})
SYMBOL_FONT_RE = re.compile(r"wingding|symbol|dingbat", re.I)
EXAM_RE = re.compile(r"exam|midterm|quiz|test", re.I)
DOT_LEADER_RE = re.compile(r"(\s*\.\s*){6,}")


def log(msg, callback=None):
    if callback:
        callback(msg)
    else:
        print(msg)


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "_", text).strip("_")


def escape_md(text):
    """Escape characters that would otherwise be interpreted as Markdown/HTML."""
    return re.sub(r"([\\`*<])", r"\\\1", text)


# ---------------------------------------------------------------------------
# Low-level line extraction
# ---------------------------------------------------------------------------

class Line:
    def __init__(self, spans, bbox):
        self.spans = spans  # list of dicts: text, font, size, mono, bold, italic, x0
        self.x0, self.y0, self.x1, self.y1 = bbox
        self.text = "".join(s["text"] for s in spans)
        body = [s for s in spans if s["text"].strip()]
        self.size = max(s["size"] for s in body)
        self.fonts = {s["font"] for s in body}
        self.mono = all(s["mono"] for s in body)
        stripped = self.text.lstrip()
        first = body[0]["text"].strip()
        self.bullet = stripped[:1] in BULLET_CHARS or stripped.startswith(("- ", "* ")) or \
            "\ue000" <= stripped[:1] <= "\uf8ff" or \
            (len(body) > 1 and len(first) == 1 and bool(SYMBOL_FONT_RE.search(body[0]["font"])))
        self.numbered = bool(NUMBERED_RE.match(stripped)) and not self.mono

    @property
    def height(self):
        return max(self.y1 - self.y0, 1)

    def body_text(self):
        """Markdown text of the line with bullet glyph removed and inline styling applied."""
        parts = []
        for s in self.spans:
            parts.append((s["text"], "code" if s["mono"] else "bold" if s["bold"] else "italic" if s["italic"] else None))
        # Strip bullet glyph from the first non-empty span
        if self.bullet:
            for i, (t, style) in enumerate(parts):
                if t.strip():
                    t = t.lstrip()
                    t = t[2:] if t.startswith(("- ", "* ")) else t[1:]
                    parts[i] = (t, style)
                    if not t.strip():  # glyph was its own span; drop leading space of the next one
                        for j in range(i + 1, len(parts)):
                            if parts[j][0].strip():
                                parts[j] = (parts[j][0].lstrip(), parts[j][1])
                                break
                    parts[i] = (t, style)
                    break
        # Merge adjacent runs with the same style
        merged = []
        for t, style in parts:
            if merged and merged[-1][1] == style:
                merged[-1] = (merged[-1][0] + t, style)
            else:
                merged.append((t, style))
        out = []
        for t, style in merged:
            if not t.strip() or style is None:
                out.append(escape_md(t) if style != "code" else t)
                continue
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            core = t.strip()
            if style == "code":
                core = f"`{core}`" if "`" not in core else f"`` {core} ``"
            elif style == "bold":
                core = f"**{escape_md(core)}**"
            else:
                core = f"*{escape_md(core)}*"
            out.append(lead + core + trail)
        return "".join(out).strip()


def extract_lines(page):
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for l in block["lines"]:
            spans = []
            for s in l["spans"]:
                if not s["text"]:
                    continue
                spans.append({
                    "text": s["text"].translate(GLYPH_FIXES),
                    "font": s["font"],
                    "size": round(s["size"], 1),
                    "mono": bool(MONO_RE.search(s["font"])),
                    "bold": bool(BOLD_RE.search(s["font"])),
                    "italic": bool(ITALIC_RE.search(s["font"])),
                    "x0": s["bbox"][0],
                })
            if spans and "".join(s["text"] for s in spans).strip():
                lines.append(Line(spans, l["bbox"]))
    lines.sort(key=lambda ln: (round(ln.y0), ln.x0))
    return lines


def group_rows(lines):
    """Group lines sitting on the same baseline (e.g. table cells) into rows."""
    rows = []
    for ln in lines:
        if rows and abs(rows[-1][0].y0 - ln.y0) < 2.5:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for row in rows:
        row.sort(key=lambda ln: ln.x0)
    return rows


def merge_row(row):
    """Combine the pieces of one visual line (e.g. "a." + "(1 pt) ...") into a single Line."""
    if len(row) == 1:
        return row[0]
    spans = list(row[0].spans)
    for prev, ln in zip(row, row[1:]):
        gap = " "
        if prev.mono and ln.mono:
            char_w = (prev.x1 - prev.x0) / max(len(prev.text), 1)
            gap = " " * max(1, int(round((ln.x0 - prev.x1) / char_w)))
        spans.append(dict(ln.spans[0], text=gap, x0=prev.x1))
        spans += ln.spans
    return Line(spans, (row[0].x0, min(l.y0 for l in row), row[-1].x1, max(l.y1 for l in row)))


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Document-level analysis
# ---------------------------------------------------------------------------

class DocInfo:
    """Statistics gathered across the whole PDF to make per-page decisions."""

    def __init__(self, doc, is_slides):
        self.is_slides = is_slides
        self.pages = [extract_lines(p) for p in doc]
        size_counter = Counter()
        for lines in self.pages:
            for ln in lines:
                size_counter[ln.size] += len(ln.text)
        self.body_size = size_counter.most_common(1)[0][0] if size_counter else 11

        # A page is "visual" if it contains images, embedded figures, or lots of vector drawing
        draw_counts = [len(p.get_drawings()) for p in doc]
        baseline = min(draw_counts) if draw_counts else 0
        image_pages = Counter(xref for p in doc for xref in {img[0] for img in p.get_images()})
        repeated = {x for x, c in image_pages.items() if len(doc) >= 3 and c >= 0.5 * len(doc)}
        self.visual = []
        for p, dc in zip(doc, draw_counts):
            area = p.rect.width * p.rect.height
            has_figure = bool(p.get_xobjects()) or any(
                info["xref"] not in repeated and fitz.Rect(info["bbox"]).get_area() > 0.03 * area
                for info in p.get_image_info(xrefs=True))
            if is_slides:
                has_figure = has_figure or dc - baseline >= 8
            self.visual.append(has_figure)

        # Fonts used on plain text pages; anything else on a visual page is figure labelling
        self.main_fonts = set()
        for lines, vis in zip(self.pages, self.visual):
            if not vis:
                for ln in lines:
                    self.main_fonts |= ln.fonts
        if not self.main_fonts:
            self.main_fonts = {f for lines in self.pages for ln in lines for f in ln.fonts}

        # Recurring headers/footers (same text at the page edges on most pages)
        self.boilerplate = set()
        if len(doc) >= 4:
            counter = Counter()
            for p, lines in zip(doc, self.pages):
                h = p.rect.height
                seen = set()
                for ln in lines:
                    if ln.y0 < 0.1 * h or ln.y1 > 0.9 * h:
                        key = re.sub(r"\d+", "#", normalize(ln.text))
                        if key not in seen:
                            counter[key] += 1
                            seen.add(key)
            self.boilerplate = {k for k, c in counter.items() if c >= 0.5 * len(doc)}

        # Indentation levels of bullets/numbered items across the document
        xs = sorted({round(ln.x0) for lines in self.pages for ln in lines if ln.bullet or ln.numbered})
        self.levels = []
        for x in xs:
            if not self.levels or x - self.levels[-1] > 6:
                self.levels.append(x)

    def level_of(self, x):
        if not self.levels:
            return 0
        return min(range(len(self.levels)), key=lambda i: abs(self.levels[i] - x))

    def is_boilerplate(self, ln):
        return re.sub(r"\d+", "#", normalize(ln.text)) in self.boilerplate


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_code(lines):
    x_min = min(ln.x0 for ln in lines)
    out = []
    prev = None
    for ln in lines:
        char_w = (ln.x1 - ln.x0) / max(len(ln.text), 1)
        indent = int(round((ln.x0 - x_min) / char_w)) if char_w > 0 else 0
        if prev is not None and ln.y0 - prev.y1 > 0.9 * prev.height:
            out.append("")
        out.append(" " * indent + ln.text.rstrip())
        prev = ln
    if any(re.search(r"^\s*(def |class |import |from \S+ import |print\()|^\s*(if|elif|else|for|while|try|except|with)\b.*:\s*$", l) for l in out) and \
            not any(l.rstrip().endswith(";") for l in out):
        lang = "python"
    elif any(re.search(r"#include|int main|;\s*$|\{\s*$", l) for l in out):
        lang = "c"
    else:
        lang = ""
    return f"```{lang}\n" + "\n".join(out) + "\n```"


def render_table(rows):
    cols = []  # left edges of the columns, from the widest row
    for ln in max(rows, key=len):
        cols.append(ln.x0)
    ncols = len(cols)
    md = []
    for i, row in enumerate(rows):
        cells = [""] * ncols
        for ln in row:
            j = min(range(ncols), key=lambda c: abs(cols[c] - ln.x0) if ln.x0 >= cols[c] - 4 else 1e9)
            cells[j] = (cells[j] + " " + ln.body_text().replace("|", "\\|")).strip()
        md.append("| " + " | ".join(cells) + " |")
        if i == 0:
            md.append("|" + " --- |" * ncols)
    return "\n".join(md)


def join_text(a, b):
    if re.search(r"[A-Za-z]-$", a) and b[:1].islower():
        return a[:-1] + b
    for mark in ("**", "*"):  # keep emphasis that wraps across lines as one run
        if a.endswith(mark) and b.startswith(mark) and not b.startswith(mark + "*"):
            return a[: -len(mark)] + " " + b[len(mark):]
    return a + " " + b


def render_body(lines, info):
    """Turn a sequence of positioned lines into Markdown blocks."""
    blocks = []      # finished markdown strings
    item = None      # current paragraph/list item: dict(kind, level, text, x0, last)
    list_level = None  # level of the numbered list we're inside, for nesting bullets under it
    code = []        # pending code lines
    table = []       # pending table rows

    def flush_item():
        nonlocal item
        if item:
            if item["kind"] == "bullet":
                blocks.append("  " * item["level"] + "- " + item["text"])
            elif item["kind"] == "numbered":
                blocks.append("  " * item["level"] + item["text"])
            elif item["kind"] == "lettered":
                label, _, rest = item["text"].partition(" ")
                blocks.append(f"**{label}** {rest}".strip())
            elif item["kind"] == "heading":
                blocks.append("### " + item["text"])
            else:
                blocks.append(item["text"])
            item = None

    def flush_code():
        if code:
            blocks.append(render_code(code))
            code.clear()

    def flush_table():
        if len(table) >= 2:
            blocks.append(render_table(table))
        elif table:
            blocks.append(" ".join(ln.body_text() for ln in table[0]))
        table.clear()

    for row in group_rows(lines):
        # Multi-cell rows with wide gaps (or matching an open table's columns) are table rows
        wide_gaps = any(row[i + 1].x0 - row[i].x1 > 2 * row[i].size for i in range(len(row) - 1))
        aligned = bool(table) and len(row) == len(table[-1]) and \
            all(abs(a.x0 - b.x0) < 4 for a, b in zip(row, table[-1]))
        if len(row) >= 2 and not all(ln.mono for ln in row) and (wide_gaps or aligned):
            flush_item(); flush_code()
            table.append(row)
            continue
        flush_table()

        ln = merge_row(row)
        if ln.mono and not ln.bullet:
            flush_item()
            code.append(ln)
            continue
        flush_code()
        text = ln.body_text()
        if not text:
            continue
        if not info.is_slides and re.match(r"^\d+\.\s*\(\d+\s*pts?\)", normalize(ln.text)):
            flush_item()
            blocks.append("### " + escape_md(normalize(ln.text)))
            list_level = None
            continue
        if ln.bullet or ln.numbered:
            flush_item()
            level = info.level_of(ln.x0)
            if ln.bullet:
                kind = "bullet"
                if list_level is not None and level <= list_level:
                    level = list_level + 1
            elif re.match(r"^\d", text):
                kind = "numbered"
                list_level = level
            else:
                kind = "lettered"
            item = {"kind": kind, "level": level, "text": text, "x0": ln.x0, "last": ln}
            continue
        close = item and ln.y0 - item["last"].y1 < 0.9 * ln.height
        if close and (item["kind"] == "para" and abs(ln.x0 - item["x0"]) < 4 or
                      item["kind"] != "para" and ln.x0 >= item["x0"] - 3):
            item["text"] = join_text(item["text"], text)
            item["last"] = ln
            continue
        flush_item()
        list_level = None
        item = {"kind": "para", "level": 0, "text": text, "x0": ln.x0, "last": ln}

    flush_item(); flush_code(); flush_table()

    # Tighten list spacing: consecutive list items shouldn't be separated by blank lines
    out = []
    for b in blocks:
        is_list = re.match(r"^\s*(- |\d+[.)] )", b) is not None
        if out and is_list and out[-1][1]:
            out[-1] = (out[-1][0] + "\n" + b, True)
        else:
            out.append((b, is_list))
    return "\n\n".join(b for b, _ in out)


# ---------------------------------------------------------------------------
# Slide / document converters
# ---------------------------------------------------------------------------

def split_title(lines, page, info):
    """Return (title, remaining_lines, title_bottom_y) for a slide."""
    top = [ln for ln in lines if ln.y0 < 0.25 * page.rect.height and ln.size >= info.body_size + 1.5]
    if not top:
        return None, lines, 0
    biggest = max(ln.size for ln in top)
    title_lines = [ln for ln in top if abs(ln.size - biggest) < 0.6]
    rest = [ln for ln in lines if ln not in title_lines]
    title = normalize(" ".join(ln.text for ln in title_lines))
    return title, rest, max(ln.y1 for ln in title_lines)


def convert_slides(doc, info, out_dir, images=True):
    sections = []
    doc_title = None
    prev_title = None
    page_texts = [normalize(" ".join(ln.text for ln in lines)) for lines in info.pages]

    for i, page in enumerate(doc):
        # Skip incremental "build" slides whose content is repeated on the next page
        if i + 1 < len(doc) and page_texts[i] and page_texts[i + 1].startswith(page_texts[i]):
            continue

        lines = [ln for ln in info.pages[i] if not info.is_boilerplate(ln)]
        if info.visual[i]:
            lines = [ln for ln in lines if ln.fonts <= info.main_fonts]
        title, rest, title_bottom = split_title(lines, page, info)

        if i == 0:
            # Title slide: the prominent text below the banner is the document title
            big = [ln for ln in rest if ln.size >= info.body_size + 0.5]
            big = [ln for ln in big if ln.size >= max(l.size for l in big) - 0.6] if big else big
            if big:
                doc_title = normalize(" ".join(ln.text for ln in big))
                rest = [ln for ln in rest if ln not in big]
            elif title:
                doc_title, title = title, None
            body = render_body(rest, info)
            if body:
                sections.append(f"*{body}*" if "\n" not in body else body)
            prev_title = title
            continue

        parts = []
        clean_title = re.sub(r"\s*\((cont(inued|'d|’d|\.)?|\d+/\d+)\)\s*$", "", title or "", flags=re.I)
        if clean_title and clean_title != prev_title:
            parts.append(f"## {escape_md(clean_title)}")
        if clean_title:
            prev_title = clean_title

        body = render_body(rest, info)
        if body:
            parts.append(body)

        if images and info.visual[i]:
            clip = fitz.Rect(page.rect.x0, title_bottom + 2, page.rect.x1, page.rect.y1) if title_bottom else page.rect
            fname = f"slide_{i + 1:02d}.png"
            page.get_pixmap(dpi=150, clip=clip).save(os.path.join(out_dir, fname))
            parts.append(f"![Slide {i + 1}]({fname})")

        if parts:
            sections.append("\n\n".join(parts))

    return doc_title, sections


def convert_document(doc, info, out_dir, images=True):
    # Render page by page so y-positions stay meaningful, but join into one flow
    sections = []
    doc_title = doc.metadata.get("title") or None
    for i, page in enumerate(doc):
        # Drop headers/footers and form fields like "Last name . . . . ."
        page_lines = [ln for ln in info.pages[i]
                      if not info.is_boilerplate(ln) and not DOT_LEADER_RE.search(ln.text)]
        if i == 0 and not doc_title:
            lead = []
            for ln in page_lines[:3]:
                if not all(s["bold"] for s in ln.spans if s["text"].strip()):
                    break
                lead.append(ln)
            if lead:
                doc_title = normalize(" ".join(ln.text for ln in lead))
                page_lines = page_lines[len(lead):]
        body = render_body(page_lines, info)
        if body:
            sections.append(body)
        if images and page.get_images():
            fname = f"page_{i + 1:02d}.png"
            page.get_pixmap(dpi=110).save(os.path.join(out_dir, fname))
            sections.append(f"![Page {i + 1}]({fname})")
    return doc_title, sections


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def detect_week(title, filename):
    """Week number from "Week 3" in the title/filename, else the lecture number ("Lecture 3", "L03", "lec_3")."""
    patterns = [
        (title or "", r"(?<![a-z])week[\s_-]*(\d{1,2})(?!\d)"),
        (filename, r"(?<![a-z])(?:week|wk|w)[\s_-]*(\d{1,2})(?!\d)"),
        (title or "", r"(?<![a-z])lecture[\s_-]*(\d{1,2})(?!\d)"),
        (filename, r"(?<![a-z])(?:lecture|lect|lec|l)[\s_-]*(\d{1,2})(?!\d)"),
    ]
    for text, pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return int(m.group(1))
    return None


def convert_pdf(pdf_path, course_id="209", output_base="output", images=True, log_callback=None):
    """Convert one PDF. Returns the path of the written index.md."""
    filename = os.path.basename(pdf_path)
    stem = os.path.splitext(filename)[0]
    doc = fitz.open(pdf_path)
    if doc.page_count == 0:
        raise ValueError("PDF has no pages")
    first = doc[0].rect
    is_slides = first.width > first.height
    info = DocInfo(doc, is_slides)

    if sum(len(p) for p in info.pages) == 0:
        raise ValueError("no extractable text (scanned PDF? try OCR first)")

    content_dir = os.path.join(output_base, f"pcrs_{course_id}_content")
    # Decide destination before rendering so images land next to index.md
    tmp_title = None
    if is_slides:
        tmp_title, _, _ = split_title(info.pages[0], doc[0], info)
        big = [ln for ln in info.pages[0] if ln.size >= info.body_size + 0.5]
        big = [ln for ln in big if ln.size >= max(l.size for l in big) - 0.6] if big else big
        tmp_title = " ".join(ln.text for ln in big) or tmp_title
    week = detect_week(tmp_title, stem) if is_slides else None

    if week is not None:
        out_dir = os.path.join(content_dir, f"week_{week}", f"slides_{slugify(stem)}")
    elif EXAM_RE.search(stem):
        out_dir = os.path.join(content_dir, "practice_exams", slugify(stem))
    else:
        out_dir = os.path.join(content_dir, "lecture_notes", slugify(stem))
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.png")):
        os.remove(old)

    if is_slides:
        doc_title, sections = convert_slides(doc, info, out_dir, images)
    else:
        doc_title, sections = convert_document(doc, info, out_dir, images)
    doc.close()

    title = doc_title or stem
    md = [f"# {escape_md(title)}", f"Source: {filename}"] + sections
    out_path = os.path.join(out_dir, "index.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(md).strip() + "\n")
    log(f"[DONE] {filename} -> {out_path}", log_callback)
    return out_path


def convert_many(paths, course_id="209", output_base="output", images=True, log_callback=None):
    pdfs = []
    for p in paths:
        if os.path.isdir(p):
            pdfs += sorted(glob.glob(os.path.join(p, "*.pdf")))
        else:
            pdfs.append(p)
    done = 0
    for pdf in pdfs:
        try:
            convert_pdf(pdf, course_id, output_base, images, log_callback)
            done += 1
        except Exception as e:
            log(f"[FAIL] {os.path.basename(pdf)}: {e}", log_callback)
    log(f"\nConverted {done}/{len(pdfs)} PDFs into {os.path.abspath(os.path.join(output_base, f'pcrs_{course_id}_content'))}/", log_callback)
    return done


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert lecture slide PDFs into Markdown notes.")
    parser.add_argument("paths", nargs="+", help="PDF files and/or folders containing PDFs")
    parser.add_argument("--course", default=os.getenv("PCRS_COURSE_ID", "209"))
    parser.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"),
                        help="Output base directory (default: scraper/output, same as the GUI)")
    parser.add_argument("--no-images", action="store_true", help="Don't render figure slides to PNG")
    args = parser.parse_args()
    ok = convert_many(args.paths, args.course, args.dir, not args.no_images)
    sys.exit(0 if ok else 1)
