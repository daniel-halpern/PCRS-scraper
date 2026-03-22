"""
PCRS Diagnostic Tool
=====================
A utility to dump HTML from any PCRS page to aid in development and debugging.

Usage:
    python scraper/diagnostic_tool.py --url https://pcrs.utm.utoronto.ca/209/content/challenges/107/1
"""

import os
import argparse
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

def get_args():
    parser = argparse.ArgumentParser(description="PCRS Diagnostic Tool")
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="Full URL of the PCRS page to dump"
    )
    return parser.parse_args()

def dump_html(url):
    shib_name = os.getenv("SHIB_COOKIE_NAME")
    shib_val = os.getenv("SHIB_COOKIE_VALUE")
    
    if not shib_name or not shib_val:
        print("ERROR: Shibboleth cookies not found in .env")
        return

    cookies = {shib_name: shib_val}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    print(f"Fetching: {url}")
    try:
        r = requests.get(url, cookies=cookies, headers=headers, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Save full HTML
        dump_path = "debug_dump.html"
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"Full HTML dumped to: {os.path.abspath(dump_path)}")

        # Summary of interesting blocks
        print("\n--- Structural Analysis ---")
        print(f"Title: {soup.title.string if soup.title else 'No Title'}")
        
        selectors = [
            ".problem-description", ".question-description", 
            "label.checkbox", "label.radio",
            "[id^='multiple_choice-']", "[id^='problem-']"
        ]
        
        for sel in selectors:
            matches = soup.select(sel)
            print(f"Selector '{sel}': {len(matches)} matches found.")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    args = get_args()
    dump_html(args.url)
