#!/usr/bin/env python3
"""Pocket → Full‑Article Exporter (robust)

★ 2025‑05‑22 **revision 4** – adds automatic retries & resume‑safe checkpointing
  so long runs (thousands of items) survive Pocket’s occasional time‑outs.

New goodies
===========
1. **Retry + exponential back‑off** on any network hiccup (timeouts, 5xx, etc.).
2. **Checkpointing** – after every page we write `.pocket_checkpoint` with the
   next offset; if you rerun the script it picks up where it left off.
3. Timeout bumped to 90 s, but retries kick in sooner so you aren’t stuck.

Install (if you haven’t already):
```bash
pip install requests readability-lxml beautifulsoup4 tqdm python-slugify
```
Run:
```bash
python pocket_export.py              # JSON export, resumes if interrupted
python pocket_export.py --format md  # Markdown export
```
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path
from textwrap import dedent
from typing import Final, Mapping
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from readability import Document
from requests.adapters import HTTPAdapter, Retry
from slugify import slugify
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuration & constants
# ---------------------------------------------------------------------------
ENV = os.getenv
CONSUMER_KEY: Final[str] = ENV("POCKET_CONSUMER_KEY", "114692-452aa92a814fd6b440742ce")
REDIRECT_URI: Final[str] = ENV("POCKET_REDIRECT_URI", "http://127.0.0.1:51337/finish")
TOKEN_PATH: Final[Path] = Path.home() / ".pocket_access_token"
CHECKPOINT: Final[Path] = Path.cwd() / ".pocket_checkpoint"
HEADERS_FORM: Final[Mapping[str, str]] = {
    "X-Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
REQ_TIMEOUT = 90  # seconds – Pocket can be slow
MAX_BATCH = 30   # Pocket hard limit per docs
USER_AGENT = "PocketExporter/1.2"

# ---------------------------------------------------------------------------
# HTTP session with retries
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    sess = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"User-Agent": USER_AGENT})
    return sess

SESSION = _make_session()

# ---------------------------------------------------------------------------
# Helper – POST with form‑encoded body
# ---------------------------------------------------------------------------

def _post(url: str, data: Mapping[str, str]):
    return SESSION.post(url, data=data, headers=HEADERS_FORM, timeout=REQ_TIMEOUT)

# ---------------------------------------------------------------------------
# OAuth flow (unchanged logic, but uses SESSION)
# ---------------------------------------------------------------------------

def _request_token() -> str:
    r = _post(
        "https://getpocket.com/v3/oauth/request",
        {"consumer_key": CONSUMER_KEY, "redirect_uri": REDIRECT_URI},
    )
    r.raise_for_status()
    return r.json()["code"]


def _authorize_interactively(request_token: str) -> None:
    url = (
        "https://getpocket.com/auth/authorize?request_token="
        f"{request_token}&redirect_uri={quote_plus(REDIRECT_URI)}"
    )
    webbrowser.open(url, new=2)
    input("Press <Enter> after approving access … ")


def _exchange_for_access_token(request_token: str) -> str:
    r = _post(
        "https://getpocket.com/v3/oauth/authorize",
        {"consumer_key": CONSUMER_KEY, "code": request_token},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_access_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()

    tok = _request_token()
    _authorize_interactively(tok)
    access = _exchange_for_access_token(tok)
    TOKEN_PATH.write_text(access)
    return access

# ---------------------------------------------------------------------------
# Pagination with checkpoint & robust retry
# ---------------------------------------------------------------------------

def _read_checkpoint() -> int:
    try:
        return int(CHECKPOINT.read_text())
    except Exception:
        return 0


def _write_checkpoint(offset: int) -> None:
    CHECKPOINT.write_text(str(offset))


def fetch_pocket_items(access_token: str, *, batch_size: int = MAX_BATCH) -> list[dict]:
    if batch_size > MAX_BATCH:
        print(f"Batch size {batch_size} exceeds Pocket's 30‑item cap. Using 30 instead.")
        batch_size = MAX_BATCH

    all_items: list[dict] = []
    offset = _read_checkpoint()
    if offset:
        print(f"Resuming from offset {offset} thanks to checkpoint…")

    pbar = tqdm(desc="Retrieving", unit="item", leave=False, initial=offset)
    while True:
        payload = {
            "consumer_key": CONSUMER_KEY,
            "access_token": access_token,
            "state": "all",
            "detailType": "complete",
            "sort": "newest",
            "count": str(batch_size),
            "offset": str(offset),
            "total": "1",
        }
        try:
            r = _post("https://getpocket.com/v3/get", payload)
            r.raise_for_status()
        except requests.exceptions.RequestException as exc:
            print(f"⚠️  Network hiccup at offset {offset}: {exc}. Retrying in 5 s…")
            time.sleep(5)
            continue

        data = r.json()
        batch = list(data.get("list", {}).values())
        if not batch:
            break
        all_items.extend(batch)
        offset += len(batch)
        _write_checkpoint(offset)
        pbar.update(len(batch))

        total_available = int(data.get("total", offset))
        if offset >= total_available:
            break
    pbar.close()
    CHECKPOINT.unlink(missing_ok=True)  # clean up
    return all_items

# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

def extract_article(url: str) -> tuple[str, str]:
    resp = SESSION.get(url, timeout=REQ_TIMEOUT)
    resp.raise_for_status()
    doc = Document(resp.text)
    html = doc.summary(html_partial=False)
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return html, text

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_json(items: list[dict], outfile: Path):
    outfile.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    print(f"✓ Saved {len(items)} records → {outfile.resolve()}")


def write_markdown(items: list[dict], outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for idx, itm in enumerate(items, 1):
        title = itm.get("resolved_title") or itm.get("given_title") or "untitled"
        slug = slugify(title)[:60] or f"item-{itm['item_id']}"
        name = outdir / f"{idx:05d}_{slug}.md"
        tags = ", ".join(itm.get("tags", {}).keys()) if itm.get("tags") else ""
        md = dedent(f"""---
        pocket_id: {itm['item_id']}
        url: {itm.get('resolved_url') or itm.get('given_url')}
        tags: [{tags}]
        word_count: {itm.get('word_count')}
        ---

        # {title}

        {itm['content_text']}
        """)
        name.write_text(md)
    print(f"✓ Wrote {len(items)} Markdown files → {outdir.resolve()}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export full Pocket articles (robust)")
    p.add_argument("--format", choices=["json", "md"], default="json")
    p.add_argument("--outfile", default="pocket_articles.json")
    p.add_argument("--outdir", default="PocketExport")
    p.add_argument("--batch", type=int, default=30, help="Items per API page (max 30)")
    p.add_argument("--limit", type=int, help="Debug: stop after N items total")
    return p.parse_args()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    print("Pocket → Article Exporter (robust)")
    token = get_access_token()

    print(f"Fetching items in batches of {args.batch}…")
    items = fetch_pocket_items(token, batch_size=args.batch)
    if args.limit:
        items = items[: args.limit]
    print(f"Total items retrieved: {len(items)}")

    enriched: list[dict] = []
    failures: list[str] = []

    for itm in tqdm(items, desc="Extracting", unit="article"):
        url = itm.get("resolved_url") or itm.get("given_url")
        if not url:
            failures.append(f"{itm['item_id']}: no URL")
            continue
        try:
            html, text = extract_article(url)
            itm["content_html"] = html
            itm["content_text"] = text
            enriched.append(itm)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{url}: {e}")

    print(f"\nExtracted {len(enriched)} articles; {len(failures)} failures.")
    if failures:
        print("First few errors:")
        for msg in failures[:10]:
            print("  •", msg)

    if args.format == "json":
        write_json(enriched, Path(args.outfile))
    else:
        write_markdown(enriched, Path(args.outdir))

    print("Done ✔︎")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted — exiting.")
