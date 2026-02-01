# LinkedIn Post Engager Tracker

Scrapes all engagers (reactions, comments, reposts) from LinkedIn posts listed in a Google Sheet, enriches them with full profile data, sends new leads to a Clay webhook, and saves a local CSV.

## What It Does

1. **Fetches a public Google Sheet** containing LinkedIn post URLs (via CSV export)
2. **Scrapes engagers** for each post using DataGen's LinkedIn tools -- reactions, comments, and reposts
3. **Deduplicates** within the current batch and against previously sent leads (`sent_leads.json`)
4. **Enriches** each new lead with full LinkedIn profile data (name, headline, company, title, location, etc.) using parallel workers
5. **Sends enriched leads to Clay** via webhook in batches of 50
6. **Saves a CSV** of all unique engagers to `engagers.csv`
7. **Tracks sent leads** in `sent_leads.json` so subsequent runs skip already-processed leads

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install datagen-python-sdk httpx tqdm
```

### 2. Set your DataGen API key

Get your API key from the [DataGen dashboard](https://datagen.dev).

```bash
export DATAGEN_API_KEY=<your-key>
```

### 3. Configure the script

Edit the constants at the top of `engager_tracker.py`:

```python
SPREADSHEET_ID = "15-rdA0CoTX19ZncbBMUteXlFRsBUuNF9V2ztJFgVd40"  # your Google Sheet ID
CLAY_WEBHOOK_URL = "https://api.clay.com/v3/sources/webhook/..."     # your Clay webhook
MAX_ENRICHMENT_WORKERS = 5                                           # parallel enrichment threads (1-15)
```

The Google Sheet must be **publicly accessible** (Share > Anyone with the link). The script reads it via the public CSV export URL.

### Google Sheet Format

The sheet should have LinkedIn post URLs in any cell. The script scans all cells and extracts any URL containing `linkedin.com` with a recognizable activity ID. Both formats work:

```
https://www.linkedin.com/posts/username_text-activity-7421960208622493696-hash
https://www.linkedin.com/feed/update/urn:li:activity:7421960208622493696/
```

## Usage

```bash
# Run on all posts in the sheet
python -u engager_tracker.py

# Run on only the first N posts (useful for testing)
python -u engager_tracker.py 5
```

The `-u` flag ensures unbuffered output so progress bars display in real time.

### Example output

```
Fetching Google Sheet ...
  Found 30 LinkedIn URLs
  Unique activity IDs: 26
  Limiting to first 5 posts
Scraping posts: 100%|##########| 5/5 [00:11<00:00, 2.26s/post]
Deduplicating (previously sent: 0) ...
  Total engagers: 366
  Unique engagers: 283
  Previously sent: 0
  New leads: 283
Enriching leads: 100%|##########| 283/283 [05:31<00:00, 1.17s/lead]
Sending 283 leads to Clay in 6 batches ...
Clay batches: 100%|##########| 6/6 [00:03<00:00, 1.80batch/s]
Updated sent_leads.json (+283 IDs)
CSV saved to engagers.csv (283 rows)

--- Summary ---
Posts processed:     5
Total engagers:      366
New leads enriched:  283
Sent to Clay:        283
CSV:                 engagers.csv
```

## Output Files

| File | Purpose |
|------|---------|
| `engagers.csv` | All unique enriched engagers. Columns: authorId, authorName, authorUrl, engagement_type, reaction_type, comment_text, source_activity_id, enriched, firstName, lastName, headline, location, linkedInUrl, summary, followerCount, openToWork, currentTitle, currentCompany |
| `sent_leads.json` | Tracks which authorIds have been sent to Clay. Prevents duplicates across runs. Delete this file to reset and re-send all leads. |

## How Deduplication Works

**Within a single run:** Engagers are grouped by `authorId`. If the same person reacted and commented on the same or different posts, they merge into one record (engagement types combined, e.g. `reaction+comment`).

**Across runs:** `sent_leads.json` stores all previously sent `authorId` values. On each run, anyone already in that file is filtered out before enrichment and sending. To start fresh, delete `sent_leads.json`.

## How Enrichment Works

Each engager's `authorUrl` (returned by LinkedIn's API) is passed to `get_linkedin_person_data` for full profile enrichment. This runs in parallel with 5 workers by default.

Company/brand pages (e.g. "Fulcrum", "CRV") will log a warning and be included without enrichment since they don't have personal profiles.

## DataGen SDK

This script uses the [DataGen Python SDK](https://pypi.org/project/datagen-python-sdk/) to call LinkedIn tools. The SDK requires:

- A DataGen account with a valid API key
- LinkedIn tools accessible through your DataGen workspace

Tool aliases used:
- `get_linkedin_person_post_reactions` -- get all reactions on a post
- `get_linkedin_person_post_comments` -- get all comments (auto-paginates up to 10 pages)
- `get_linkedin_person_post_repost` -- get all reposts (manual pagination)
- `get_linkedin_person_data` -- enrich a profile by LinkedIn URL

## Deploying to DataGen

To run this on a schedule without a local machine, deploy as a DataGen custom tool. The script is designed to be portable -- the only local-only piece is `sent_leads.json`. For the deployed version, swap the local JSON file for a Google Sheet "Sent Leads" tab or a database table for persistent dedup tracking.
