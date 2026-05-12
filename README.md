# WitsType ROI — Lead Management System

A local lead management system for tracking LinkedIn outreach cadences.

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Playwright browser (for LinkedIn scraper)
playwright install chromium

# 3. Start the app
python app.py

# 4. Open in browser
open http://localhost:5000
```

## Import Leads

### Option A — LinkedIn Scraper (recommended for initial load)
```bash
python linkedin_scraper.py
```
Logs into LinkedIn in a real browser window, pulls your connections and recent
message threads (up to 1000 connections / 200 conversations), and loads them
into the database. Enter your credentials when prompted — they are never stored.

### Option B — CSV Upload
Go to **http://localhost:5000/import** and upload any CSV.

Supported column names (flexible):
| Data | LinkedIn Export | Custom CSV |
|------|----------------|------------|
| Name | First Name + Last Name | Name |
| Company | Company | company |
| Email | Email Address | email |
| Phone | — | phone |
| Profile | URL | linkedin_url |
| Date | Connected On | connected_at |

## Outreach Cadence

| Step | Action | Timing |
|------|--------|--------|
| 1 | Intro Message | Within 24h of connection |
| 2 | Voice Note 1 | Within 24h of step 1 |
| 3 | Message 2 | ~36h later |
| 4 | Voice Note 2 | ~12h later |
| 5 | Message 3 | ~12h later |
| 6 | Message 4 | ~12h later |
| 7 | Voice Note 3 | ~12h later |

The **Action Queue** (home page) shows who needs what action right now, sorted
by urgency — overdue first, then due within 24h.

## Data

All data is stored in `leads.db` (SQLite) in the project folder. Back it up by
copying that file.
