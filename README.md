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

## How This Was Built (Step-by-Step)

This entire project was built using [Claude Code](https://claude.ai/code) + [DataGen](https://datagen.dev). Here's the exact workflow to reproduce it from scratch.

### Step 1: Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

Requires Node.js 18+ and an Anthropic API key or Claude Pro/Max subscription. See [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code) for details.

### Step 2: Initialize a git repo

```bash
mkdir my-engager-tracker && cd my-engager-tracker
git init
```

### Step 3: Install the DataGen CLI

```bash
curl -fsSL https://cli.datagen.dev/install.sh | sh
```

See [datagendev/datagen-cli](https://github.com/datagendev/datagen-cli) for details.

### Step 4: Log in and add DataGen MCP to Claude Code

```bash
datagen login
datagen mcp
```

This authenticates your DataGen account and registers the DataGen MCP server with Claude Code, giving it access to 1000+ tools (LinkedIn, Google Sheets, Gmail, Slack, etc.).

### Step 5: Install the DataGen Python SDK

Inside Claude Code, run the slash command:

```
/datagen:install-datagen-python-sdk
```

This installs the `datagen-python-sdk` package into your project's virtual environment. The SDK lets you call any DataGen tool from local Python scripts via `client.execute_tool("tool_name", params)`.

This is a **one-time setup** -- after this, you can use any DataGen tool from code.

### Step 6: Describe what you want in Claude Code (plan mode)

Press `Shift+Tab` twice to enter **plan mode**, then describe the task:

```
ok i have a google sheet like https://docs.google.com/spreadsheets/d/15-rdA0CoTX19ZncbBMUteXlFRsBUuNF9V2ztJFgVd40/edit?gid=0#gid=0 .
it contains a company's post they want to track. and we want to send it to clay with this webhook
https://api.clay.com/v3/sources/webhook/pull-in-data-from-a-webhook-d523bf83-f52e-4214-be06-6a17302f3511 .
so idea is every week you would come in and scrape all the engager of these posts. and extract them
as lead list, make sure to not send repetitive lead or lead already sent before. you can use our
datagen linkedin tool for enrichment i think. go look it up. and we'd like to deploy this as an
agent in datagen, so you dont need to worry about the cron job part. just focusing on how to do
the doc pull, enrichment(at scale) and send to webhook part. also list all the unique engager as
a csv file here.
```

Claude Code will:
- Fetch the Google Sheet to understand the data
- Search DataGen for the right LinkedIn tools (`searchTools`, `getToolDetails`)
- Design the pipeline architecture
- Present a plan for your approval

### Step 7: Claude Code writes the script and iterates with you

After approving the plan, Claude Code:
- Writes `engager_tracker.py` with the full pipeline
- Asks clarifying questions (post type, enrichment strategy, etc.)
- You refine together (e.g. "always use `get_linkedin_person_data`, don't use `search_linkedin_person`")

### Step 8: Test with a small batch

```bash
python -u engager_tracker.py 5
```

Review the output, fix any issues (e.g. Clay 413 payload too large -- batch it), and iterate until it works end-to-end.

### Step 9: Create a Claude Code agent

Inside Claude Code, run:

```
/agents
```

This creates an agent definition in `.claude/agents/` that knows how to operate your pipeline -- where to pull posts, how enrichment works, error handling, batch trade-offs, and reporting format. The agent can be invoked by anyone with access to the repo.

### Step 10: Deploy as a DataGen agent

1. Push your repo to GitHub:
   ```bash
   gh repo create your-org/your-repo --public --source=. --push
   ```

2. Go to [datagen.dev/signalgen/agents](https://datagen.dev/signalgen/agents)

3. Connect your GitHub repo (e.g. `https://github.com/datagendev/ravi-demo`)

4. DataGen reads the agent definition and makes it available as a hosted agent.

### Step 11: Schedule weekly runs

In the DataGen agent dashboard, set a **weekly schedule** (e.g. every Monday at 9am). The agent will:
- Pull fresh post URLs from the Google Sheet
- Scrape new engagers since the last run
- Skip anyone already sent (dedup)
- Enrich and deliver new leads to Clay
- No local machine needed

---

That's it -- from `git init` to a production weekly pipeline in one session with Claude Code + DataGen.

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
