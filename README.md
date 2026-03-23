# PCRS Scraper

Scrapes course content from PCRS (Programming Courses Resource System) used at the University of Toronto (UofT). Downloads video transcripts, example code, and question text.

## Features

- **Desktop GUI**: A user-friendly interface for managing settings and running scrapes.
- **Quick Cookie Import**: Paste JSON exports from browser extensions to auto-configure authentication.
- **Multi-course Support**: Works for CSC209, CSC108, CSC148, etc.
- **Fast**: Parallelized scraping using multiple threads.
- **Efficient**: Skips already downloaded content and deduplicates challenges.
- **Interleaved Output**: Matches the PCRS page layout perfectly, keeping videos, code, and questions in their original order.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   Copy `.env.example` to `.env`. This is where your configuration will be stored.
   ```bash
   cp .env.example .env
   ```

## Authentication & Usage

PCRS requires a valid **Shibboleth SSO** session cookie. The easiest way to get this is via the Desktop GUI.

### 1. Launch the GUI
```bash
python3 scraper/pcrs_gui.py
```

### 2. Import Cookies
1. Install a "Cookie Editor" extension in your browser (e.g., [Cookie-Editor](https://cookie-editor.com/)).
2. Log into PCRS in your browser.
3. Open the extension and click **Export** (JSON format).
4. In the Scraper GUI, click **Quick Import JSON (Cookies)** and paste the JSON blob. It will automatically find and extract the session name and value.
5. Hit **Save Settings**.

### 3. Run Scraper
Select the "Week" you want to scrape and hit **Start Scraper**. You can follow the live log in the terminal or the GUI's log area.

---

### Command Line Usage
If you prefer the terminal, you can still run the scraper directly:
```bash
python3 scraper/pcrs_scraper.py --week 10 --delay 1.0
```

## Repository Structure

- `scraper/`: Main scraping logic, GUI, and auth tools.
- `output/`: Scraped content (gitignored).
- `studyguide/`: Future tools for generating study guides.
- `.env`: Your private credentials (gitignored).