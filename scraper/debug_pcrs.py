import os
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Load environment variables from .env
load_dotenv()

PCRS_COURSE_ID = os.getenv("PCRS_COURSE_ID", "209")
SHIB_COOKIE_NAME = os.getenv("SHIB_COOKIE_NAME")
SHIB_COOKIE_VALUE = os.getenv("SHIB_COOKIE_VALUE")

PCRS_BASE = "https://pcrs.utm.utoronto.ca"
QUESTS_URL = f"{PCRS_BASE}/{PCRS_COURSE_ID}/content/quests"

def verify_auth():
    if not SHIB_COOKIE_NAME or not SHIB_COOKIE_VALUE:
        print("ERROR: SHIB_COOKIE_NAME or SHIB_COOKIE_VALUE not set in .env")
        return

    cookies = {SHIB_COOKIE_NAME: SHIB_COOKIE_VALUE}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    print(f"Checking URL: {QUESTS_URL}")
    try:
        r = requests.get(QUESTS_URL, cookies=cookies, headers=headers, timeout=15)
        print(f"Status: {r.status_code}")
        print(f"Final URL: {r.url}")
        
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else "No Title"
        print(f"Title: {title}")

        if "idpz.utorauth.utoronto.ca" in r.url:
            print("\nFAILURE: Redirected to login page. Cookie expired or invalid.")
        elif r.status_code == 200 and "PCRS" in title:
            print("\nSUCCESS: Authentication working!")
        else:
            print("\nUNCLEAR: Check the title and URL above.")

    except Exception as e:
        print(f"ERROR: Connection failed: {e}")

if __name__ == "__main__":
    verify_auth()
