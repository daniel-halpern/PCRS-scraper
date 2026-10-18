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

## Lecture Slides & Past Exams (PDF → Notes)

Click **Import Lecture PDFs...** in the GUI (or use the CLI) to turn slide decks and past exams into Markdown notes in the same format as the scraped content:
```bash
python3 scraper/pdf_notes.py path/to/lecture3.pdf path/to/folder_of_pdfs/
```
- Slides are split into one section per slide, with bullets, code blocks, and tables rebuilt. Slides that contain diagrams are also saved as images.
- Slides are filed under their week (detected from the title slide, e.g. "Week 3: …", or the filename `lecture3.pdf`), so the Master Study Guide places them next to that week's PCRS content.
- Exams and midterms go into a **Practice Exams** section.
- Scanned (image-only) PDFs have no extractable text. Run OCR on them first.

## Repository Structure

- `scraper/`: Main scraping logic, GUI, and auth tools.
- `output/`: Scraped content (gitignored).
- `studyguide/`: Future tools for generating study guides.
- `.env`: Your private credentials (gitignored).

## Piazza Discussion Scraper & Study Guide Generator

Scrapes questions, instructor & student answers, and followup discussions from Piazza:
- **Rich Markdown Formatting**: Preserves code blocks with language highlighting, LaTeX math (`$...$`), images, and quote replies.
- **Incremental Caching**: Skips already downloaded posts that haven't changed.
- **Master Study Guide**: Compiles all discussions grouped by folder/tag (e.g. `a1`, `a2`, `midterm`, `exam`) with a table of contents.
- **Full JSON Archive**: Exports structured JSON for downstream search, RAG, or AI study assistants.

### Quick Usage:

1. **Find your Piazza Network ID**:
   From your course URL: `https://piazza.com/class/<NETWORK_ID>` (e.g. `m4k9...`)

2. **Authenticate**:
   - **Session Cookie (Recommended for UofT SSO / UTORid)**:
     Export cookies from your browser using [Cookie-Editor](https://cookie-editor.com/) as JSON, or copy the `session_id` cookie value.
   - **Or direct email/password**.

3. **Run the Scraper**:
   ```bash
   # Basic run (will prompt for cookie if not in .env)
   python3 scraper/piazza_scraper.py --nid <NETWORK_ID>

   # Using a Cookie-Editor JSON export
   python3 scraper/piazza_scraper.py --nid <NETWORK_ID> --cookie-json cookies.json

   # Filter only Assignment 2 discussions
   python3 scraper/piazza_scraper.py --nid <NETWORK_ID> --folder a2

   # Limit to recent 50 posts with 0.5s polite delay
   python3 scraper/piazza_scraper.py --nid <NETWORK_ID> --limit 50 --delay 0.5
   ```