"""
PCRS CSC209 Scraper
====================
Downloads transcripts, example .c files, and question text from PCRS.

Requirements:
    pip install requests beautifulsoup4

Usage:
    python pcrs_scraper.py
"""

import requests
from bs4 import BeautifulSoup
import os
import re
import time
import argparse
import threading
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Load environment variables
load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────
PCRS_DOMAIN = os.getenv("PCRS_DOMAIN", "pcrs.utm.utoronto.ca")
PCRS_BASE = f"https://{PCRS_DOMAIN}"
MCS_BASE = os.getenv("MCS_BASE", "https://mcs.utm.utoronto.ca")

def get_args():
    parser = argparse.ArgumentParser(description="PCRS Scraper")
    parser.add_argument(
        "--course",
        type=str,
        default=os.getenv("PCRS_COURSE_ID", "209"),
        help="PCRS Course ID (e.g. 209, 108)"
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Specific week number to scrape (e.g. 10)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=PCRS_DOMAIN,
        help=f"PCRS Domain (default: {PCRS_DOMAIN})"
    )
    return parser.parse_args()

args = get_args()
COURSE_ID = args.course
WEEK_FILTER = args.week
REQUEST_DELAY = args.delay
PCRS_DOMAIN = args.domain
PCRS_BASE = f"https://{PCRS_DOMAIN}"
QUESTS_URL = f"{PCRS_BASE}/{COURSE_ID}/content/quests"

SHIB_COOKIE_NAME = os.getenv("SHIB_COOKIE_NAME")
SHIB_COOKIE_VALUE = os.getenv("SHIB_COOKIE_VALUE")

OUTPUT_DIR = f"output/pcrs_{COURSE_ID}_content"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": QUESTS_URL,
}
COOKIES = {
    SHIB_COOKIE_NAME: SHIB_COOKIE_VALUE,
}

sess = requests.Session()
sess.headers.update(HEADERS)
if SHIB_COOKIE_NAME and SHIB_COOKIE_VALUE:
    sess.cookies.update(COOKIES)
else:
    print("[WARN] Shibboleth cookies not found in .env. Scraper might fail.")

# Global set to track challenge IDs for deduplication
seen_challenge_ids = set()
# Track downloaded files to avoid duplicates
seen_files = set()


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]


def safe_get(url, retries=3):
    """Fetch URL with delay and retries."""
    for i in range(retries):
        try:
            # Respect the global delay
            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)
            
            r = sess.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if i < retries - 1:
                wait_time = (i + 1) * 2
                print(f"  [WARN] Failed {url}: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"  [FAIL] Failed {url} after {retries} attempts: {e}")
                return None


def save_file(path, content):
    """Save file if it's new or has different content."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # Check if we've already saved this exact path in this session
    if path in seen_files:
        return False
        
    # Check if file exists on disk and has same content (simple check)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == content:
                # print(f"  [SKIP] File exists and content matches: {os.path.basename(path)}")
                return False

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    seen_files.add(path)
    return True


def scrape_challenge_page(challenge_url, challenge_name, week_dir):
    """
    Scrape a challenge page like /209/content/challenges/5/1
    which lists all videos, questions, and problems.
    """
    thread_info = f"[{threading.current_thread().name}]"
    challenge_slug = slugify(challenge_name)
    challenge_dir = os.path.join(week_dir, challenge_slug)
    out_path = os.path.join(challenge_dir, "index.md")

    # Resume logic: skip if already scraped in this session
    if out_path in seen_files:
         return f"{thread_info} [SKIP] Already scraped: {challenge_name}"

    html = safe_get(challenge_url)
    if not html:
        return f"{thread_info} [FAIL] Could not load: {challenge_name}"

    soup = BeautifulSoup(html, "html.parser")
    os.makedirs(challenge_dir, exist_ok=True)

    all_md = [f"# {challenge_name}\n\nSource: {challenge_url}\n"]

    # 1. Transcripts & .c files
    for link in soup.find_all("a", href=True):
        href = link["href"]
        
        # Transcript .txt files on mcs server
        if href.endswith(".txt") and "mcs.utm.utoronto.ca" in href:
            content = safe_get(href)
            if content:
                fname = slugify(os.path.basename(href)) + ".txt"
                if save_file(os.path.join(challenge_dir, fname), content):
                    # Find nearest heading to use as section title
                    section_title = "Transcript"
                    parent = link.find_parent(["div", "section", "li"])
                    if parent:
                        heading = parent.find_previous(["h1","h2","h3","h4","strong","b"])
                        if heading:
                            section_title = heading.get_text(strip=True)
                    all_md.append(f"## {section_title}\n\n### Transcript\n\n{content.strip()}\n")

        # Example .c files
        elif href.endswith(".c"):
            full_url = href if href.startswith("http") else MCS_BASE + href
            content = safe_get(full_url)
            if content:
                fname = os.path.basename(href)
                if save_file(os.path.join(challenge_dir, fname), content):
                    all_md.append(f"### Example: `{fname}`\n\n```c\n{content.strip()}\n```\n")

    # 2. Question / problem text blocks
    for block in soup.select(".question-text, .problem-text, .pcrs-question, "
                             "[class*='question'], [class*='problem']"):
        text = block.get_text(separator="\n", strip=True)
        if text and len(text) > 20:
            # Avoid duplicating index content if it's already there
            if text[:50] not in "\n".join(all_md):
                all_md.append(f"### Question\n\n{text}\n")

    # 3. Any <pre> code blocks
    for pre in soup.find_all("pre"):
        code = pre.get_text(strip=True)
        if code and len(code) > 10:
            if code[:50] not in "\n".join(all_md):
                all_md.append(f"### Code\n\n```c\n{code}\n```\n")

    save_file(out_path, "\n---\n\n".join(all_md))
    return f"{thread_info} [DONE] {challenge_name}"


def scrape_quests():
    """Parse the quests page, find all challenges, scrape each one."""
    print(f"Fetching: {QUESTS_URL}\n")
    html = safe_get(QUESTS_URL)
    if not html:
        print("ERROR: Could not load quests page.")
        return

    soup = BeautifulSoup(html, "html.parser")

    # Detect login redirect
    title = soup.title.string if soup.title else ""
    if "login" in title.lower() or "sign in" in title.lower():
        print("ERROR: Got login page — session cookie is expired. Grab a fresh one.")
        return

    print(f"Page title: '{title}'")
    print(f"--- First 300 chars ---\n{html[:300]}\n---")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Find all quest (week) accordion panels ────────────────────────────────
    # Structure: div.pcrs-panel-title.quest-expired (or similar) contains "Week N"
    # Sibling div contains the challenge panels

    quest_titles = soup.find_all("div", class_=re.compile(r"pcrs-panel-title"))

    if not quest_titles:
        print("[WARN] No quest panels found. Dumping raw challenge links.")
        quest_titles = [soup]

    # Find all challenge urls first
    challenges_to_scrape = []
    
    challenge_regex = re.compile(fr"/{COURSE_ID}/content/challenges/(\d+)/\d+")

    for quest_div in quest_titles:
        quest_text = quest_div.get_text(strip=True)
        week_match = re.search(r"(week\s*(\d+))", quest_text, re.I)
        
        if week_match:
            week_num = int(week_match.group(2))
            week_name = week_match.group(1).title()
        else:
            week_num = None
            week_name = quest_text[:30]

        # Apply week filter if specified
        if WEEK_FILTER is not None and week_num != WEEK_FILTER:
            continue

        week_dir = os.path.join(OUTPUT_DIR, slugify(week_name))

        # The challenge links are in the collapse div that follows this title
        collapse_id = quest_div.get("href", "").lstrip("#")
        collapse_div = soup.find(id=collapse_id) if collapse_id else quest_div.find_next_sibling("div")

        if not collapse_div:
            collapse_div = quest_div.parent

        if not collapse_div:
            continue

        challenge_links = collapse_div.find_all("a", href=challenge_regex)

        for link in challenge_links:
            href = link["href"]
            match = challenge_regex.search(href)
            if not match:
                continue
            
            challenge_id = match.group(1)
            if challenge_id in seen_challenge_ids:
                continue
            seen_challenge_ids.add(challenge_id)

            # Get challenge name
            name = ""
            # Often challenge name is in a span with class "challenge-name"
            # or just the text of the link
            parent_link = link.find_parent("div")
            if parent_link:
                name_span = parent_link.find(class_="challenge-name")
                if name_span:
                    name = name_span.get_text(strip=True)
            
            if not name:
                name = link.get_text(strip=True) or challenge_id

            full_url = PCRS_BASE + href
            challenges_to_scrape.append((full_url, name, week_dir))

    # Parallelize scraping
    if challenges_to_scrape:
        print(f"Found {len(challenges_to_scrape)} challenges. Scraping with 5 workers...\n")
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(scrape_challenge_page, url, name, week_dir): name 
                       for url, name, week_dir in challenges_to_scrape}
            
            for future in tqdm(as_completed(futures), total=len(challenges_to_scrape), desc="Challenges"):
                result = future.result()
                # Use tqdm.write to avoid breaking the progress bar
                tqdm.write(f"  {result}")
    else:
        print("No new challenges found to scrape.")

    print(f"\n\nDone! Content saved to: {os.path.abspath(OUTPUT_DIR)}/")
    print("\nFolder structure:")
    for root, dirs, files in os.walk(OUTPUT_DIR):
        level = root.replace(OUTPUT_DIR, "").count(os.sep)
        indent = "  " * level
        print(f"{indent}{os.path.basename(root)}/")
        for f in files:
            print(f"{indent}  {f}")


if __name__ == "__main__":
    scrape_quests()