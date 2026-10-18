"""
Piazza Discussion Board Scraper & Study Guide Generator
======================================================
Scrapes posts, student/instructor answers, and followup discussions from Piazza.
Exports clean Markdown notes (formatted for studying/search), full JSON archive,
and an indexed Master Study Guide grouped by folder/tag.

Features:
  - Multi-method authentication:
      * Browser cookies / Cookie-Editor JSON export (works seamlessly with SSO/UTORid)
      * Raw cookie header (session_id, piazza_session)
      * Standard Email & Password login
  - Incremental Caching:
      * Skips already-downloaded posts that haven't changed, saving bandwidth & API calls
  - Rich Markdown Conversion:
      * Clean code blocks with auto-detected syntax highlighting (C, SQL, Python, etc.)
      * Math / LaTeX support ($...$)
      * Formatted instructor & student responses, endorsements, and threaded discussions
  - Master Study Guide compilation:
      * Generates a single searchable Markdown study guide organized by course folder/tag
  - Structured JSON export for downstream search, embeddings, or RAG pipelines

Usage:
  CLI:
    python3 scraper/piazza_scraper.py --nid <class_network_id_or_url>
    python3 scraper/piazza_scraper.py --nid <nid> --folder a2 --limit 50
    python3 scraper/piazza_scraper.py --nid <nid> --cookie-json cookies.json

  Python:
    from scraper.piazza_scraper import PiazzaScraper
    scraper = PiazzaScraper(nid="m4xxxxxx", session_id="xxxxxx")
    scraper.scrape()
"""

import os
import re
import sys
import time
import json
import random
import argparse
from typing import Dict, List, Optional, Any, Callable
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables (.env in workspace root or scraper/.env)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


# ── Nonce & Base36 Helper ───────────────────────────────────────────────────

_CHARS_36 = "0123456789abcdefghijklmnopqrstuvwxyz"

def _int_to_base36(num: int) -> str:
    """Convert an integer to a base-36 string."""
    if num == 0:
        return "0"
    res = []
    is_neg = num < 0
    num = abs(num)
    while num > 0:
        res.append(_CHARS_36[num % 36])
        num //= 36
    if is_neg:
        res.append("-")
    return "".join(reversed(res))


def generate_piazza_aid() -> str:
    """Generate Piazza's request aid (nonce token)."""
    t_val = int(time.time() * 1000)
    r_val = random.randint(100000, 1679615)
    return _int_to_base36(t_val) + _int_to_base36(r_val)


def extract_nid(url_or_nid: str) -> str:
    """
    Extract network ID from either a raw NID or a Piazza class URL.
    Examples:
      'm4xxxx123' -> 'm4xxxx123'
      'https://piazza.com/class/m4xxxx123' -> 'm4xxxx123'
      'https://piazza.com/class/m4xxxx123?cid=42' -> 'm4xxxx123'
    """
    clean = url_or_nid.strip()
    if not clean:
        return ""
    
    # Check if it's a URL
    if "piazza.com" in clean:
        match = re.search(r"/class/([a-zA-Z0-9_-]+)", clean)
        if match:
            return match.group(1)
        # Check query params for nid
        parsed = urlparse(clean)
        qs = parse_qs(parsed.query)
        if "nid" in qs and qs["nid"]:
            return qs["nid"][0]
            
    # Remove leading/trailing slashes
    clean = clean.strip("/")
    return clean


def slugify(text: str, max_len: int = 50) -> str:
    """Generate filesystem-safe slug from subject text."""
    if not text:
        return "post"
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:max_len].strip("_") or "post"


# ── Markdown Formatter ──────────────────────────────────────────────────────

def detect_code_language(code_text: str) -> str:
    """Guess code language for Markdown syntax highlighting."""
    c = code_text.lower()
    c_indicators = [
        "#include", "printf(", "malloc(", "fork()", "pthread_", "char *",
        "int main", "sigaction", "struct ", "size_t", "null", "stderr", "stdout",
        "stdin", "exit(", "waitpid", "pipe(", "read(", "write(", "close(",
        "#define", "typedef", "errno", "socket(", "bind(", "listen(", "accept("
    ]
    if any(k in c for k in c_indicators):
        return "c"
    if any(k in c for k in ["select ", "from ", "where ", "join ", "create table", "insert into", "group by"]):
        return "sql"
    if any(k in c for k in ["def ", "import ", "elif ", "self.", "__init__"]):
        return "python"
    if any(k in c for k in ["public class", "public static void", "system.out.println"]):
        return "java"
    if any(k in c for k in ["function ", "const ", "let ", "console.log"]):
        return "javascript"
    if any(k in c for k in ["#!/bin/bash", "#!/bin/sh", "chmod ", "grep ", "awk ", "sed "]):
        return "bash"
    return ""


def html_to_markdown(html_content: Optional[str]) -> str:
    """
    Converts Piazza rich-text HTML into clean GitHub-Flavored Markdown.
    Handles math/latex, pre/code blocks, lists, links, images, blockquotes, and tables.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    # 1. LaTeX math tags
    for lt in soup.find_all(["latex", "tex"]):
        tex = lt.get_text().strip()
        lt.replace_with(f" ${tex}$ ")

    # 2. MathJax / KaTeX spans
    for span in soup.find_all("span", class_=re.compile(r"katex|math", re.I)):
        tex = span.get_text().strip()
        span.replace_with(f" ${tex}$ ")

    # 3. Code blocks (<pre>)
    for pre in soup.find_all("pre"):
        code = pre.get_text()
        lang = detect_code_language(code)
        pre.replace_with(f"\n\n```{lang}\n{code.strip()}\n```\n\n")

    # 4. Inline code
    for code in soup.find_all(["code", "tt"]):
        code.replace_with(f"`{code.get_text().strip()}`")

    # 5. Bold & Italic
    for b in soup.find_all(["b", "strong"]):
        b.replace_with(f"**{b.get_text().strip()}**")
    for i in soup.find_all(["i", "em"]):
        i.replace_with(f"*{i.get_text().strip()}*")

    # 6. Links & Anchor tags
    for a in soup.find_all("a"):
        href = a.get("href", "").strip()
        text = a.get_text().strip() or href
        if href:
            a.replace_with(f"[{text}]({href})")
        else:
            a.replace_with(text)

    # 7. Images
    for img in soup.find_all("img"):
        src = img.get("src", "").strip()
        alt = img.get("alt", "Piazza Attachment").strip()
        if src:
            img.replace_with(f"\n\n![{alt}]({src})\n\n")

    # 8. Blockquotes
    for bq in soup.find_all("blockquote"):
        bq_text = bq.get_text().strip()
        quoted = "\n".join(f"> {line}" for line in bq_text.splitlines())
        bq.replace_with(f"\n\n{quoted}\n\n")

    # 9. List items
    for li in soup.find_all("li"):
        li.replace_with(f"\n- {li.get_text().strip()}")

    # 10. Paragraphs & Line breaks
    for p in soup.find_all(["p", "div"]):
        p.replace_with(f"\n\n{p.get_text().strip()}\n\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    text = soup.get_text()

    # Clean up whitespace and punctuation
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Fix spacing around punctuation following code tags
    text = re.sub(r" ` +([.,!?;:)])", r"`\1", text)
    return text.strip()


# ── Piazza Client ───────────────────────────────────────────────────────────

class PiazzaClient:
    """
    Communicates with Piazza's internal RPC web API (https://piazza.com/logic/api).
    Supports session cookie authentication (Cookie-Editor JSON or raw header)
    and standard email/password authentication.
    """

    BASE_URL = "https://piazza.com/logic/api"
    MAIN_URL = "https://piazza.com/main/api"

    def __init__(
        self,
        nid: Optional[str] = None,
        session_id: Optional[str] = None,
        piazza_session: Optional[str] = None,
        cookies_dict: Optional[Dict[str, str]] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        delay: float = 0.5,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.nid = extract_nid(nid) if nid else None
        self.delay = delay
        self.log_callback = log_callback
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/json; charset=utf-8",
            "Referer": "https://piazza.com/",
            "Origin": "https://piazza.com",
            "Accept": "application/json, text/plain, */*",
        })

        # Set cookies if supplied
        if cookies_dict:
            for k, v in cookies_dict.items():
                self.session.cookies.set(k, v, domain="piazza.com")
        if session_id:
            self.session.cookies.set("session_id", session_id, domain="piazza.com")
        if piazza_session:
            self.session.cookies.set("piazza_session", piazza_session, domain="piazza.com")

        # Fallback to email/password login if no session cookies provided
        if not self._has_session_cookie() and email and password:
            self.login_with_credentials(email, password)

    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def _has_session_cookie(self) -> bool:
        return "session_id" in self.session.cookies

    def set_cookie_from_json(self, json_data: Any) -> bool:
        """
        Accepts cookie JSON export (from Cookie-Editor extension)
        and loads `session_id`, `piazza_session`, and any other cookies.
        """
        if isinstance(json_data, str):
            try:
                json_data = json.loads(json_data)
            except Exception as e:
                self.log(f"  [ERROR] Invalid Cookie JSON: {e}")
                return False

        if not isinstance(json_data, list):
            json_data = [json_data]

        loaded = 0
        for item in json_data:
            name = item.get("name")
            val = item.get("value")
            if name and val:
                self.session.cookies.set(name, val, domain="piazza.com")
                loaded += 1

        if self._has_session_cookie():
            self.log("  [INFO] Successfully loaded Piazza session cookies.")
            return True
        else:
            self.log("  [WARN] Cookie JSON loaded, but 'session_id' was not found.")
            return False

    def set_cookie_from_string(self, cookie_str: str) -> bool:
        """Parse 'cookie1=val1; cookie2=val2' header string."""
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip(), domain="piazza.com")
        return self._has_session_cookie()

    def login_with_credentials(self, email: str, password: str) -> bool:
        """Standard email/password login to Piazza."""
        self.log(f"  [INFO] Authenticating as {email}...")
        try:
            # 1. Fetch CSRF token
            csrf_resp = self.session.get("https://piazza.com/main/csrf_token", timeout=15)
            if "CSRF_TOKEN" not in csrf_resp.text:
                raise ValueError("Could not retrieve initial CSRF token from Piazza.")
            csrf_token = csrf_resp.text.replace('"', "").replace(";", "").split("=")[1].strip()

            # 2. POST to /class login endpoint
            login_resp = self.session.post(
                "https://piazza.com/class",
                data={
                    "from": "/signup",
                    "email": email,
                    "password": password,
                    "remember": "on",
                    "csrf_token": csrf_token,
                },
                timeout=20
            )

            if "ERROR_MSG" in login_resp.text:
                match = re.search(r'VAR ERROR_MSG\s*=\s*["\']([^"\']+)["\']', login_resp.text, re.I)
                err = match.group(1) if match else "Invalid email or password"
                raise ValueError(f"Piazza authentication error: {err}")

            if not self._has_session_cookie():
                raise ValueError("Login completed but session_id cookie was not returned.")

            self.log("  [SUCCESS] Successfully logged into Piazza via email/password.")
            return True

        except Exception as e:
            self.log(f"  [ERROR] Login failed: {e}")
            return False

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, nid: Optional[str] = None) -> Any:
        """
        Executes a Piazza RPC request against logic/api endpoint.
        """
        target_nid = nid or self.nid
        payload_params = dict(params or {})
        if target_nid and "nid" not in payload_params:
            payload_params["nid"] = target_nid

        max_retries = 4
        for attempt in range(max_retries):
            aid = generate_piazza_aid()
            url = f"{self.BASE_URL}?method={method}&aid={aid}"

            headers = {}
            if "session_id" in self.session.cookies:
                headers["CSRF-Token"] = self.session.cookies["session_id"]

            body = {
                "method": method,
                "params": payload_params
            }

            if self.delay > 0:
                time.sleep(self.delay)

            resp = self.session.post(url, json=body, headers=headers, timeout=25)
            if resp.status_code != 200:
                raise requests.HTTPError(f"HTTP {resp.status_code} for method {method}: {resp.text[:200]}")

            data = resp.json()
            if data.get("error"):
                err_msg = str(data.get("error", ""))
                err_codes = data.get("error_codes", [])

                # Handle rate limiting: "Sorry, too fast"
                if "too fast" in err_msg.lower() and attempt < max_retries - 1:
                    backoff = 2.0 * (attempt + 1)
                    self.log(f"    [PAUSE] Piazza rate limit reached ('too fast'). Cooling down for {backoff:.1f}s (retry {attempt+1}/{max_retries-1})...")
                    time.sleep(backoff)
                    continue

                raise RuntimeError(f"Piazza API Error ({method}): {err_msg} (codes: {err_codes})")

            return data.get("result")

    def get_feed(self, limit: int = 100, offset: int = 0, sort: str = "updated", nid: Optional[str] = None) -> Dict[str, Any]:
        """Fetch a page of feed posts."""
        return self.request(
            "network.get_my_feed",
            params={"limit": limit, "offset": offset, "sort": sort},
            nid=nid
        )

    def get_all_feed_items(self, nid: Optional[str] = None, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Paginates through network.get_my_feed to collect all visible posts.
        Returns list of summary items from the feed.
        """
        all_items: List[Dict[str, Any]] = []
        offset = 0
        page_size = 100
        seen_ids = set()

        self.log(f"  [INFO] Fetching feed for network {nid or self.nid}...")

        while True:
            result = self.get_feed(limit=page_size, offset=offset, nid=nid)
            feed_page = result.get("feed", []) if result else []
            if not feed_page:
                break

            new_count = 0
            for item in feed_page:
                cid = item.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_items.append(item)
                    new_count += 1
                    if max_items and len(all_items) >= max_items:
                        return all_items

            if new_count == 0 or len(feed_page) < page_size:
                # Reached end of feed
                break

            offset += len(feed_page)

        self.log(f"  [INFO] Found total {len(all_items)} posts in course feed.")
        return all_items

    def get_post(self, cid: Any, nid: Optional[str] = None) -> Dict[str, Any]:
        """Fetch full details and responses for a post by CID or post number."""
        return self.request(
            "content.get",
            params={"cid": cid, "student_view": None},
            nid=nid
        )


# ── Piazza Scraper Orchestrator ─────────────────────────────────────────────

class PiazzaScraper:
    """
    High-level orchestrator for scraping Piazza discussions, caching results,
    writing individual Markdown notes, full JSON archive, and compiled study guides.
    """

    def __init__(
        self,
        nid: str,
        session_id: Optional[str] = None,
        piazza_session: Optional[str] = None,
        cookies_dict: Optional[Dict[str, str]] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        output_dir: Optional[str] = None,
        folder_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
        delay: float = 0.5,
        force: bool = False,
        compile_guide: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.nid = extract_nid(nid)
        if not self.nid:
            raise ValueError("Course Network ID (nid) is required. e.g. 'm4xxxxxx' or 'https://piazza.com/class/m4xxxxxx'")

        self.output_dir = output_dir or os.path.join("output", f"piazza_{self.nid}")
        self.folder_filter = folder_filter.lower().strip() if folder_filter else None
        self.type_filter = type_filter.lower().strip() if type_filter else None
        self.limit = limit
        self.delay = delay
        self.force = force
        self.compile_guide = compile_guide
        self.log_callback = log_callback

        # Initialize client
        self.client = PiazzaClient(
            nid=self.nid,
            session_id=session_id,
            piazza_session=piazza_session,
            cookies_dict=cookies_dict,
            email=email,
            password=password,
            delay=delay,
            log_callback=log_callback
        )

        self.cache_file = os.path.join(self.output_dir, ".piazza_cache.json")
        self.posts_dir = os.path.join(self.output_dir, "posts")
        self.cache: Dict[str, Any] = {}

    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def _load_cache(self):
        if not self.force and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception as e:
                self.log(f"  [WARN] Could not load cache: {e}. Starting fresh.")
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"  [WARN] Could not save cache: {e}")

    def format_post_markdown(self, post: Dict[str, Any]) -> str:
        """Generate formatted Markdown for an individual Piazza post and its answers."""
        nr = post.get("nr", "?")
        history = post.get("history", [{}])
        latest = history[0] if history else {}
        subject = latest.get("subject", "No Subject").strip()
        body_html = latest.get("content", "")
        post_type = post.get("type", "note").capitalize()
        folders = post.get("folders", [])
        created = post.get("created", "")
        views = post.get("unique_views", "N/A")
        post_id = post.get("id", "")
        piazza_url = f"https://piazza.com/class/{self.nid}?cid={nr}"

        lines = [
            f"# @{nr}: {subject}",
            "",
            f"- **Type**: {post_type}",
            f"- **Folders / Tags**: {', '.join(f'`{f}`' for f in folders) if folders else 'None'}",
            f"- **Date**: {created}",
            f"- **Unique Views**: {views}",
            f"- **Piazza Link**: [View on Piazza]({piazza_url})",
            "",
            "---",
            "",
            "## ❓ " + ("Question" if post_type.lower() == "question" else "Note / Announcement"),
            "",
            html_to_markdown(body_html),
            ""
        ]

        children = post.get("children", [])
        s_answers = [c for c in children if c.get("type") == "s_answer"]
        i_answers = [c for c in children if c.get("type") == "i_answer"]
        followups = [c for c in children if c.get("type") == "followup"]

        # Instructor Answer
        if i_answers:
            lines.extend(["---", "", "## 💡 Instructor Answer", ""])
            for ans in i_answers:
                ans_hist = ans.get("history", [{}])
                ans_latest = ans_hist[0] if ans_hist else {}
                ans_content = ans_latest.get("content", "")
                is_endorsed = bool(ans.get("tag_endorse"))
                badge = " *(Endorsed)*" if is_endorsed else ""
                lines.append(f"### Answer{badge}")
                lines.append("")
                lines.append(html_to_markdown(ans_content))
                lines.append("")

        # Student Answer
        if s_answers:
            lines.extend(["---", "", "## 🎓 Student Collective Answer", ""])
            for ans in s_answers:
                ans_hist = ans.get("history", [{}])
                ans_latest = ans_hist[0] if ans_hist else {}
                ans_content = ans_latest.get("content", "")
                is_endorsed = bool(ans.get("tag_endorse"))
                badge = " *(Endorsed by Instructor)*" if is_endorsed else ""
                lines.append(f"### Answer{badge}")
                lines.append("")
                lines.append(html_to_markdown(ans_content))
                lines.append("")

        # Followups and discussions
        if followups:
            lines.extend(["---", "", "## 💬 Discussions & Follow-ups", ""])
            for idx, fu in enumerate(followups, 1):
                fu_text = fu.get("subject", "")
                fu_created = fu.get("created", "")
                lines.append(f"### Follow-up #{idx} ({fu_created})")
                lines.append("")
                lines.append(html_to_markdown(fu_text))
                lines.append("")

                # Feedbacks (replies to this followup)
                feedbacks = fu.get("children", [])
                for fb in feedbacks:
                    fb_text = fb.get("subject", "")
                    fb_created = fb.get("created", "")
                    clean_fb = html_to_markdown(fb_text)
                    quoted = "\n".join(f"> {line}" for line in clean_fb.splitlines())
                    lines.append(f"> **Reply ({fb_created}):**\n{quoted}\n")

        return "\n".join(lines).strip() + "\n"

    def compile_master_guide(self, all_posts: List[Dict[str, Any]]):
        """
        Compiles all scraped posts into a single organized Master Study Guide
        grouped by folders/tags (e.g., 'a1', 'a2', 'exam', 'lectures').
        """
        guide_file = os.path.join(self.output_dir, f"piazza_{self.nid}_master_study_guide.md")
        self.log(f"  [INFO] Compiling Master Study Guide to {guide_file}...")

        # Group posts by primary folder
        folder_groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in all_posts:
            folders = p.get("folders", [])
            primary_folder = folders[0] if folders else "general"
            folder_groups.setdefault(primary_folder, []).append(p)

        lines = [
            f"# Piazza Master Study Guide ({self.nid})",
            "",
            f"*Total Posts*: {len(all_posts)}  |  *Generated*: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Table of Contents",
            ""
        ]

        sorted_folders = sorted(folder_groups.keys(), key=lambda f: f.lower())
        for folder in sorted_folders:
            folder_slug = slugify(folder)
            count = len(folder_groups[folder])
            lines.append(f"- [📁 Folder: {folder} ({count} posts)](#folder-{folder_slug})")

        lines.append("\n---\n")

        for folder in sorted_folders:
            folder_slug = slugify(folder)
            posts_in_folder = folder_groups[folder]
            # Sort posts by post number ascending
            posts_in_folder.sort(key=lambda x: int(x.get("nr", 0)))

            lines.append(f"# Folder: {folder}")
            lines.append(f"<a id=\"folder-{folder_slug}\"></a>\n")

            for post in posts_in_folder:
                nr = post.get("nr", "?")
                hist = post.get("history", [{}])
                subj = hist[0].get("subject", "No Subject").strip() if hist else "No Subject"
                lines.append(f"## [@{nr}] {subj}")
                lines.append(f"[Individual Post File](posts/@{nr}_{slugify(subj)}.md)  |  [View on Piazza](https://piazza.com/class/{self.nid}?cid={nr})\n")
                
                # Question body snippet / content
                content = hist[0].get("content", "") if hist else ""
                lines.append("### Question / Note")
                lines.append(html_to_markdown(content))
                lines.append("")

                # Answers summary
                for child in post.get("children", []):
                    c_type = child.get("type")
                    if c_type in ("i_answer", "s_answer"):
                        label = "💡 Instructor Answer" if c_type == "i_answer" else "🎓 Student Answer"
                        c_hist = child.get("history", [{}])
                        c_body = c_hist[0].get("content", "") if c_hist else ""
                        if c_body.strip():
                            lines.append(f"### {label}")
                            lines.append(html_to_markdown(c_body))
                            lines.append("")

                lines.append("\n---\n")

        with open(guide_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self.log(f"  [SUCCESS] Master Study Guide written to {guide_file}")

    def scrape(self) -> List[Dict[str, Any]]:
        """
        Executes full scrape workflow:
          1. Fetches feed
          2. Applies filters (folder, type, limit)
          3. Downloads full post contents (using cache)
          4. Writes individual Markdown files and full JSON
          5. Compiles Master Study Guide
        """
        os.makedirs(self.posts_dir, exist_ok=True)
        self._load_cache()

        # Step 1: Get all feed summaries
        feed_items = self.client.get_all_feed_items(nid=self.nid)
        if not feed_items:
            self.log("  [WARN] No posts found or authentication issue. Aborting.")
            return []

        # Step 2: Apply filters
        filtered_items = []
        for item in feed_items:
            # Filter by folder
            if self.folder_filter:
                item_folders = [f.lower() for f in item.get("folders", [])]
                if self.folder_filter not in item_folders:
                    continue

            # Filter by type (question vs note)
            if self.type_filter:
                item_type = item.get("type", "").lower()
                if self.type_filter != item_type:
                    continue

            filtered_items.append(item)

        if self.limit:
            filtered_items = filtered_items[:self.limit]

        self.log(f"  [INFO] Processing {len(filtered_items)} posts matching criteria...")

        all_full_posts: List[Dict[str, Any]] = []
        downloaded_count = 0
        cached_count = 0

        # Step 3: Fetch post content
        for idx, item in enumerate(filtered_items, 1):
            cid = item.get("id")
            nr = item.get("nr", idx)
            last_modified = item.get("m")  # modified timestamp from feed

            # Check cache
            cached_post = self.cache.get(cid)
            if (
                cached_post
                and not self.force
                and cached_post.get("m") == last_modified
                and cached_post.get("post_data")
            ):
                post_data = cached_post["post_data"]
                cached_count += 1
            else:
                try:
                    self.log(f"  [{idx}/{len(filtered_items)}] Fetching @{nr} (ID: {cid})...")
                    post_data = self.client.get_post(cid=cid, nid=self.nid)
                    if not post_data:
                        self.log(f"    [WARN] Post @{nr} returned empty data (may be deleted or restricted).")
                        continue

                    # Update cache
                    self.cache[cid] = {
                        "m": last_modified,
                        "post_data": post_data
                    }
                    downloaded_count += 1
                except Exception as e:
                    self.log(f"    [ERROR] Failed to fetch post @{nr}: {e}")
                    continue

            all_full_posts.append(post_data)

            # Write individual Markdown file
            try:
                hist = post_data.get("history", [{}])
                subj = hist[0].get("subject", "post") if hist else "post"
                filename = f"@{nr}_{slugify(subj)}.md"
                md_path = os.path.join(self.posts_dir, filename)
                md_text = self.format_post_markdown(post_data)
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_text)
            except Exception as e:
                self.log(f"    [WARN] Could not write Markdown for @{nr}: {e}")

        # Save cache
        self._save_cache()

        # Step 4: Write consolidated JSON archive
        json_file = os.path.join(self.output_dir, "piazza_posts.json")
        try:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(all_full_posts, f, indent=2, ensure_ascii=False)
            self.log(f"  [SUCCESS] Saved full JSON archive to {json_file}")
        except Exception as e:
            self.log(f"  [WARN] Failed to write JSON archive: {e}")

        # Step 5: Compile Master Study Guide
        if self.compile_guide and all_full_posts:
            self.compile_master_guide(all_full_posts)

        self.log(f"\n[COMPLETE] Done! {downloaded_count} downloaded, {cached_count} loaded from cache.")
        self.log(f"Output files stored in: {os.path.abspath(self.output_dir)}")
        return all_full_posts


# ── CLI Interface ───────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Piazza Scraper & Study Guide Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--nid",
        type=str,
        default=os.getenv("PIAZZA_NID"),
        help="Piazza Course Network ID (e.g., 'm4k9... ' or full URL 'https://piazza.com/class/m4k9...')"
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=os.getenv("PIAZZA_SESSION_ID"),
        help="Piazza session_id cookie value"
    )
    parser.add_argument(
        "--cookie",
        type=str,
        default=os.getenv("PIAZZA_COOKIE"),
        help="Raw Cookie header string (e.g., 'session_id=...; piazza_session=...')"
    )
    parser.add_argument(
        "--cookie-json",
        type=str,
        help="Path to JSON file exported from Cookie-Editor extension or JSON string"
    )
    parser.add_argument(
        "--email",
        type=str,
        default=os.getenv("PIAZZA_EMAIL"),
        help="Piazza account email (if using password login)"
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("PIAZZA_PASSWORD"),
        help="Piazza account password (if using password login)"
    )
    parser.add_argument(
        "--out",
        type=str,
        help="Output directory path (defaults to 'output/piazza_<nid>')"
    )
    parser.add_argument(
        "--folder",
        type=str,
        help="Filter posts by folder/tag (e.g. 'a1', 'a2', 'exam', 'lectures')"
    )
    parser.add_argument(
        "--type",
        choices=["question", "note"],
        help="Filter posts by type ('question' or 'note')"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of posts to scrape"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between requests to prevent rate limiting"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache and re-download all posts"
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Skip generating the compiled Master Study Guide"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 1. Resolve NID
    nid = args.nid
    if not nid:
        print("=" * 60)
        print("Piazza Scraper Setup")
        print("=" * 60)
        nid = input("Enter Piazza Course Network ID or Course URL: ").strip()

    if not nid:
        print("[ERROR] Course Network ID is required. Exiting.")
        sys.exit(1)

    cookies_dict = {}
    session_id = args.session_id
    piazza_session = os.getenv("PIAZZA_SESSION")

    # Auto-detect piazza_cookies.json if not explicitly specified via --cookie-json
    if not args.cookie_json:
        for candidate in ["piazza_cookies.json", "scraper/piazza_cookies.json"]:
            if os.path.exists(candidate):
                args.cookie_json = candidate
                break

    if args.cookie_json:
        try:
            if os.path.exists(args.cookie_json):
                with open(args.cookie_json, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = args.cookie_json
            data = json.loads(content)
            if not isinstance(data, list):
                data = [data]
            for c in data:
                name = c.get("name")
                val = c.get("value")
                if name and val:
                    cookies_dict[name] = val
                    if name == "session_id":
                        session_id = val
                    elif name == "piazza_session":
                        piazza_session = val
            print(f"[INFO] Loaded {len(cookies_dict)} cookies from Cookie JSON.")
        except Exception as e:
            print(f"[ERROR] Failed to parse cookie JSON: {e}")

    if args.cookie and not cookies_dict:
        for part in args.cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies_dict[k.strip()] = v.strip()
                if k.strip() == "session_id":
                    session_id = v.strip()

    # Prompt if no credentials found
    if not session_id and not cookies_dict and not (args.email and args.password):
        print("\nNo authentication credentials found.")
        print("Choose an option:")
        print("1. Enter session_id cookie value (Recommended for SSO/UTORid)")
        print("2. Enter Email and Password")
        choice = input("Choice (1/2): ").strip()

        if choice == "2":
            args.email = input("Piazza Email: ").strip()
            import getpass
            args.password = getpass.getpass("Piazza Password: ")
        else:
            session_id = input("Paste your session_id cookie value: ").strip()

    scraper = PiazzaScraper(
        nid=nid,
        session_id=session_id,
        piazza_session=piazza_session,
        cookies_dict=cookies_dict,
        email=args.email,
        password=args.password,
        output_dir=args.out,
        folder_filter=args.folder,
        type_filter=args.type,
        limit=args.limit,
        delay=args.delay,
        force=args.force,
        compile_guide=not args.no_compile
    )

    scraper.scrape()


if __name__ == "__main__":
    main()
