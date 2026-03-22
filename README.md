# PCRS Scraper

Scrapes course content from PCRS (Programming Courses Resource System) used at the University of Toronto (UTM). Downloads video transcripts, example code, and question text.

## Features

- **Multi-course Support**: Works for CSC209, CSC108, CSC148, etc.
- **Fast**: Parallelized scraping using multiple threads.
- **Efficient**: Skips already downloaded content and deduplicates challenges.
- **Clean Output**: Organizes everything into Markdown files and raw source files.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   Copy `.env.example` to `.env` and fill in your credentials.
   ```bash
   cp .env.example .env
   ```

## Authentication

PCRS uses **Shibboleth SSO**. You need a valid session cookie to scrape content.

1. Log into PCRS in your browser.
2. Go to your course quests page (e.g., `https://pcrs.utm.utoronto.ca/209/content/quests`).
3. Open DevTools (**F12**) → **Application** tab → **Cookies**.
4. Find the cookie starting with `_shibsession_`.
5. Copy the **Name** and **Value** into your `.env` file:
   ```
   SHIB_COOKIE_NAME=_shibsession_xxxxxxxx
   SHIB_COOKIE_VALUE=_xxxxxxxx
   ```

## Usage

### 1. Verify Authentication
Run the debug tool to confirm your credentials are working:
```bash
python3 scraper/debug_pcrs.py
```

### 2. Run Scraper
By default, it uses the configuration from your `.env`:
```bash
python3 scraper/pcrs_scraper.py
```

### Advanced Usage

**Scrape a specific week (Recommended for testing):**
```bash
python3 scraper/pcrs_scraper.py --week 10
```

**Adjust the request delay (Politeness/Speed):**
```bash
# Faster (0.5s delay)
python3 scraper/pcrs_scraper.py --delay 0.5
# Slower/Safer (2.0s delay)
python3 scraper/pcrs_scraper.py --delay 2.0
```

**Scrape a different course or campus:**
```bash
# Different course
python3 scraper/pcrs_scraper.py --course 108
# Different campus domain
python3 scraper/pcrs_scraper.py --domain pcrs.stg.utoronto.ca
```

## Repository Structure

- `scraper/`: Main scraping logic and auth tools.
- `studyguide/`: Future tools for generating study guides from scraped content.
- `output/`: Scraped content (gitignored).
- `.env`: Your private credentials (gitignored).