"""
LinkedIn Post Engager Tracker -> Clay Webhook

Reads LinkedIn post URLs from a public Google Sheet, scrapes all engagers
(reactions, comments, reposts), deduplicates against previously sent leads,
enriches with LinkedIn profile data, sends to Clay webhook, and saves CSV.

Requirements:
    pip install datagen-python-sdk httpx tqdm
    export DATAGEN_API_KEY=<your-key>
"""

import csv
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx
from datagen_sdk import DatagenClient
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SPREADSHEET_ID = "15-rdA0CoTX19ZncbBMUteXlFRsBUuNF9V2ztJFgVd40"
CLAY_WEBHOOK_URL = (
    "https://api.clay.com/v3/sources/webhook/"
    "pull-in-data-from-a-webhook-d523bf83-f52e-4214-be06-6a17302f3511"
)
SENT_LEADS_FILE = os.path.join(os.path.dirname(__file__), "sent_leads.json")
CSV_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "engagers.csv")
MAX_ENRICHMENT_WORKERS = 5
ACTIVITY_ID_RE = re.compile(r"(?:activity|ugcPost)[:\-](\d+)")

# ---------------------------------------------------------------------------
# Google Sheet fetch (public CSV export, no MCP needed)
# ---------------------------------------------------------------------------

def fetch_post_urls(spreadsheet_id: str) -> list[str]:
    """Fetch the public Google Sheet as CSV and extract all LinkedIn URLs."""
    export_url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/export?format=csv&gid=0"
    )
    resp = httpx.get(export_url, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    urls = []
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        for cell in row:
            cell = cell.strip()
            if "linkedin.com" in cell and ACTIVITY_ID_RE.search(cell):
                urls.append(cell)
    return urls


def extract_activity_id(url: str) -> str | None:
    m = ACTIVITY_ID_RE.search(url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Scraping engagers
# ---------------------------------------------------------------------------

def scrape_reactions(client: DatagenClient, activity_id: str) -> list[dict]:
    """Get all reactions for a person post."""
    try:
        result = client.execute_tool(
            "get_linkedin_person_post_reactions",
            {"activity_id": activity_id},
        )
    except Exception as e:
        print(f"  [warn] reactions failed for {activity_id}: {e}")
        return []

    reactions = result.get("reactions", []) if isinstance(result, dict) else []
    out = []
    for r in reactions:
        author = r.get("author", {})
        out.append({
            "authorId": author.get("authorId", ""),
            "authorName": author.get("authorName", ""),
            "authorUrl": author.get("authorUrl", ""),
            "engagement_type": "reaction",
            "reaction_type": r.get("type", ""),
            "comment_text": "",
            "source_activity_id": activity_id,
        })
    return out


def scrape_comments(client: DatagenClient, activity_id: str) -> list[dict]:
    """Get all comments (auto-paginates up to 10 pages)."""
    try:
        result = client.execute_tool(
            "get_linkedin_person_post_comments",
            {"activity_id": activity_id},
        )
    except Exception as e:
        print(f"  [warn] comments failed for {activity_id}: {e}")
        return []

    comments = result.get("comments", []) if isinstance(result, dict) else []
    out = []
    for c in comments:
        author = c.get("author", {})
        identifier = author.get("authorPublicIdentifier", "")
        author_url = f"https://www.linkedin.com/in/{identifier}" if identifier else ""
        out.append({
            "authorId": author.get("authorId", ""),
            "authorName": author.get("authorName", ""),
            "authorUrl": author_url,
            "engagement_type": "comment",
            "reaction_type": "",
            "comment_text": c.get("text", ""),
            "source_activity_id": activity_id,
        })
    return out


def scrape_reposts(client: DatagenClient, activity_id: str) -> list[dict]:
    """Get all reposts with manual pagination."""
    all_reposts: list[dict] = []
    page = 1
    while True:
        try:
            result = client.execute_tool(
                "get_linkedin_person_post_repost",
                {"activity_id": activity_id, "page": page},
            )
        except Exception as e:
            print(f"  [warn] reposts failed for {activity_id} page {page}: {e}")
            break

        if not isinstance(result, dict):
            break
        batch = result.get("reposts", [])
        if not batch:
            break

        for rp in batch:
            author = rp.get("author", {})
            identifier = author.get("authorPublicIdentifier", "")
            author_url = f"https://www.linkedin.com/in/{identifier}" if identifier else ""
            all_reposts.append({
                "authorId": author.get("authorId", ""),
                "authorName": author.get("authorName", ""),
                "authorUrl": author_url,
                "engagement_type": "repost",
                "reaction_type": "",
                "comment_text": "",
                "source_activity_id": activity_id,
            })

        meta = result.get("metadata", {})
        total = meta.get("total", 0)
        per_page = meta.get("perPage", 10)
        if page * per_page >= total:
            break
        page += 1
        if page > 50:
            break

    return all_reposts


def scrape_all_engagers(client: DatagenClient, activity_ids: list[str]) -> list[dict]:
    """Scrape reactions, comments, and reposts for every activity ID."""
    all_engagers = []
    for aid in tqdm(activity_ids, desc="Scraping posts", unit="post"):
        all_engagers.extend(scrape_reactions(client, aid))
        all_engagers.extend(scrape_comments(client, aid))
        all_engagers.extend(scrape_reposts(client, aid))
        time.sleep(1)  # rate-limit courtesy
    return all_engagers


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def load_sent_leads() -> set[str]:
    if not os.path.exists(SENT_LEADS_FILE):
        return set()
    with open(SENT_LEADS_FILE, "r") as f:
        data = json.load(f)
    return set(data.get("sent_author_ids", []))


def save_sent_leads(existing: set[str], new_ids: set[str]):
    merged = sorted(existing | new_ids)
    with open(SENT_LEADS_FILE, "w") as f:
        json.dump({"sent_author_ids": merged, "last_updated": datetime.now(timezone.utc).isoformat()}, f, indent=2)


def deduplicate(engagers: list[dict], sent_ids: set[str]) -> list[dict]:
    """Deduplicate within batch by authorId, then filter out already-sent."""
    seen: dict[str, dict] = {}
    for eng in engagers:
        aid = eng.get("authorId", "")
        if not aid:
            continue
        if aid not in seen:
            seen[aid] = eng
        else:
            # merge engagement types for the same person
            existing = seen[aid]
            existing_type = existing.get("engagement_type", "")
            new_type = eng.get("engagement_type", "")
            if new_type and new_type not in existing_type:
                existing["engagement_type"] = f"{existing_type}+{new_type}"
            # keep authorUrl if we get it from another engagement type
            if not existing.get("authorUrl") and eng.get("authorUrl"):
                existing["authorUrl"] = eng["authorUrl"]

    unique = list(seen.values())
    new_only = [e for e in unique if e["authorId"] not in sent_ids]
    print(f"  Total engagers: {len(engagers)}")
    print(f"  Unique engagers: {len(unique)}")
    print(f"  Previously sent: {len(unique) - len(new_only)}")
    print(f"  New leads: {len(new_only)}")
    return new_only


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_single(client: DatagenClient, engager: dict) -> dict:
    """Enrich one engager with full LinkedIn profile data via get_linkedin_person_data."""
    author_url = engager.get("authorUrl", "")
    author_name = engager.get("authorName", "")
    profile = None

    if author_url and "/in/" in author_url:
        try:
            result = client.execute_tool(
                "get_linkedin_person_data",
                {"linkedin_url": author_url},
            )
            if isinstance(result, dict):
                profile = result.get("person", result)
        except Exception as e:
            print(f"    [warn] enrich failed for {author_name}: {e}")
    else:
        print(f"    [skip] no profile URL for {author_name} -- cannot enrich")

    enriched = {
        "authorId": engager.get("authorId", ""),
        "authorName": author_name,
        "authorUrl": author_url,
        "engagement_type": engager.get("engagement_type", ""),
        "reaction_type": engager.get("reaction_type", ""),
        "comment_text": engager.get("comment_text", ""),
        "source_activity_id": engager.get("source_activity_id", ""),
        "enriched": bool(profile),
    }

    if profile:
        enriched.update({
            "firstName": profile.get("firstName", ""),
            "lastName": profile.get("lastName", ""),
            "headline": profile.get("headline", ""),
            "location": profile.get("location", ""),
            "linkedInUrl": profile.get("linkedInUrl", ""),
            "summary": profile.get("summary", ""),
            "followerCount": profile.get("followerCount", 0),
            "openToWork": profile.get("openToWork", False),
            "currentTitle": "",
            "currentCompany": "",
        })
        positions = profile.get("positions", {})
        history = positions.get("positionHistory", [])
        if history:
            enriched["currentTitle"] = history[0].get("title", "")
            enriched["currentCompany"] = history[0].get("companyName", "")

    return enriched


def enrich_leads(client: DatagenClient, new_engagers: list[dict]) -> list[dict]:
    """Enrich all new engagers in parallel using ThreadPoolExecutor."""
    if not new_engagers:
        return []

    enriched = []
    with ThreadPoolExecutor(max_workers=MAX_ENRICHMENT_WORKERS) as executor:
        futures = {
            executor.submit(enrich_single, client, eng): eng
            for eng in new_engagers
        }
        with tqdm(total=len(futures), desc="Enriching leads", unit="lead") as pbar:
            for future in as_completed(futures):
                try:
                    enriched.append(future.result())
                except Exception as e:
                    original = futures[future]
                    print(f"  [error] enrichment failed for {original.get('authorName')}: {e}")
                    original["enriched"] = False
                    enriched.append(original)
                pbar.update(1)

    return enriched


# ---------------------------------------------------------------------------
# Clay webhook
# ---------------------------------------------------------------------------

CLAY_BATCH_SIZE = 50


def send_to_clay(leads: list[dict], webhook_url: str):
    if not leads:
        print("No leads to send to Clay.")
        return
    batches = [leads[i:i + CLAY_BATCH_SIZE] for i in range(0, len(leads), CLAY_BATCH_SIZE)]
    print(f"Sending {len(leads)} leads to Clay in {len(batches)} batches ...")
    for idx, batch in enumerate(tqdm(batches, desc="Clay batches", unit="batch"), 1):
        try:
            resp = httpx.post(webhook_url, json=batch, timeout=60)
            if resp.status_code >= 400:
                print(f"  Batch {idx} failed ({resp.status_code}): {resp.text[:300]}")
            else:
                print(f"  Batch {idx}: {resp.status_code} ({len(batch)} leads)")
        except Exception as e:
            print(f"  [error] Batch {idx} failed: {e}")


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "authorId", "authorName", "authorUrl",
    "engagement_type", "reaction_type", "comment_text",
    "source_activity_id", "enriched",
    "firstName", "lastName", "headline", "location",
    "linkedInUrl", "summary", "followerCount", "openToWork",
    "currentTitle", "currentCompany",
]


def save_csv(leads: list[dict], path: str):
    if not leads:
        print("No leads to write to CSV.")
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)
    print(f"CSV saved to {path} ({len(leads)} rows)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(limit: int = 0):
    if not os.getenv("DATAGEN_API_KEY"):
        raise RuntimeError("DATAGEN_API_KEY not set")

    client = DatagenClient()

    # 1. Fetch post URLs from Google Sheet
    print("Fetching Google Sheet ...")
    all_urls = fetch_post_urls(SPREADSHEET_ID)
    print(f"  Found {len(all_urls)} LinkedIn URLs")

    # 2. Extract unique activity IDs
    seen_aids = set()
    activity_ids = []
    for url in all_urls:
        aid = extract_activity_id(url)
        if aid and aid not in seen_aids:
            seen_aids.add(aid)
            activity_ids.append(aid)
    print(f"  Unique activity IDs: {len(activity_ids)}")

    if limit > 0:
        activity_ids = activity_ids[:limit]
        print(f"  Limiting to first {limit} posts")

    # 3. Scrape engagers from all posts
    all_engagers = scrape_all_engagers(client, activity_ids)

    # 4. Deduplicate
    sent_ids = load_sent_leads()
    print(f"Deduplicating (previously sent: {len(sent_ids)}) ...")
    new_engagers = deduplicate(all_engagers, sent_ids)

    # 5. Enrich new leads
    enriched = enrich_leads(client, new_engagers)

    # 6. Send to Clay
    send_to_clay(enriched, CLAY_WEBHOOK_URL)

    # 7. Update sent-leads tracker
    new_ids = {e["authorId"] for e in enriched if e.get("authorId")}
    if new_ids:
        save_sent_leads(sent_ids, new_ids)
        print(f"Updated {SENT_LEADS_FILE} (+{len(new_ids)} IDs)")

    # 8. Save CSV of all unique engagers
    save_csv(enriched, CSV_OUTPUT_FILE)

    # Summary
    print("\n--- Summary ---")
    print(f"Posts processed:     {len(activity_ids)}")
    print(f"Total engagers:      {len(all_engagers)}")
    print(f"New leads enriched:  {len(enriched)}")
    print(f"Sent to Clay:        {len(enriched)}")
    print(f"CSV:                 {CSV_OUTPUT_FILE}")


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    main(limit=lim)
