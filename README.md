# Pocket‑Archive Exporter

I made a simple Python script to grab your Pocket saves before the service shuts down. This includes metadata and the full, reader‑view article text, which is more than just the links you get from an official Pocket export request.

*The exporter works from the command line, is resumable, robust against Pocket’s time‑outs, and comes with a consumer key so it is ready to use.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Command‑Line Options](#command-line-options)
6. [Troubleshooting](#troubleshooting)
7. [What We Learned Building It](#what-we-learned-building-it)
8. [Next Steps](#next-steps)
9. [License](#license)

---

## Features

|  ✅                           | Description                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| **Full OAuth flow**          | Opens your browser the first run, then caches a token at `~/.pocket_access_token`.    |
| **Fetches *all* items**      | Loops through `/v3/get` in 30‑item pages—Pocket’s documented cap.                     |
| **Clean article extraction** | Downloads every URL and runs *readability‑lxml* to strip ads & chrome.                |
| **Checkpointing**            | Writes `.pocket_checkpoint` after each page—restart any time without losing progress. |
| **Robust retries**           | Exponential back‑off for Pocket’s occasional 5xx/timeout errors.                      |
| **Two output formats**       | One big **JSON** file (default) *or* a Markdown vault (`--format md`).                |

---

## Prerequisites

* Python **3.9 or newer**
* A Pocket **consumer key** with *Retrieve* permission
  *The repo ships with a working key baked into `pocket_export.py` with *Retrieve* permission only, so you can test immediately.*
* A Pocket account logged in on your default web browser (tested on Chrome and Firefox on MacOS)

---

## Installation

```bash
git clone https://github.com/mkdir-markpettyjohn/PocketRetriever.gitcd pocket‑archive‑exporter

# (optional) python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## Quick Start

```bash
python3 pocket_export.py                # JSON export in cwd
python3 pocket_export.py --format md    # Markdown vault
```

Interaction on first run:

```
Opening browser for Pocket authorization…
Press <Enter> after approving access …
Fetching items in batches of 30…
Retrieving: 5010item [03:02, 27.4item/s]
Extracting: 100%|█████████████████| 5010/5010 [1:02:18<00:00,  1.34article/s]
✓ Saved 5010 records → ./pocket_articles.json
Done ✔︎
```

---

## Command‑Line Options

| Flag                 | Default                | Purpose                                  |
| -------------------- | ---------------------- | ---------------------------------------- |
| `--format {json,md}` | `json`                 | Output as JSON file or Markdown folder.  |
| `--outfile PATH`     | `pocket_articles.json` | Where to place the JSON file.            |
| `--outdir DIR`       | `PocketExport`         | Destination folder for Markdown.         |
| `--batch N`          | `30`                   | Items per API page (Pocket refuses >30). |
| `--limit N`          | –                      | Debug: stop after *N* items.             |

Examples:

```bash
# Markdown vault for Obsidian / Logseq
python pocket_export.py --format md --outdir PocketExport

# First 100 items only (debug)
python pocket_export.py --limit 100
```

---

## Troubleshooting

| Symptom                                         | Fix                                                                                                      |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **`ReadTimeout` / `HTTP 500`** during retrieval | The script retries automatically. If it stalls forever, check connectivity and rerun—checkpoint resumes. |
| **Extraction stuck at 0 %**                     | Corporate network may block sites. Try a VPN or narrow with `--limit` to isolate offenders.              |
| **Zero items retrieved**                        | Ensure your consumer key has **Retrieve** access and `POCKET_CONSUMER_KEY` is set in the same shell.     |

---

## What We Learned Building It

*Docs we leaned on: [Pocket OAuth](https://getpocket.com/developer/docs/authentication) · [Retrieve v3](https://getpocket.com/developer/docs/v3/retrieve)*

1. **`count` + `offset` require form‑encoded bodies** …

2. **`count` + `offset` require form‑encoded bodies**
   Sending them in JSON quietly returns an **empty list**—Pocket quirk #1.

3. **`offset = 0` on the very first call can fail**
   Better to omit `offset` until page 2.

4. **Batch size is hard‑capped at 30** despite some docs hinting at 500. Anything bigger is simply ignored.

5. **Pocket’s API sometimes hangs for 45‑60 s**
   We added a 90 s timeout *plus* up‑to‑5 retries with exponential back‑off.

6. **Extraction latency dominates**
   Even with fast internet, third‑party sites average \~1 s each. Baseline ≈ 1.3 articles/s serially. Parallelism (thread pool) is the future improvement.

7. **Checkpoint early, checkpoint often**
   Writing a tiny file after each 30‑item page means a laptop sleep or CTRL‑C never loses more than a minute of work.

These lessons are baked into the current script—no more empty downloads, silent limits, or lost progress.

8. **Export take a lot of time**
  If rates are similar, expect an overnight job if you have thousands of saves in Pocket.

9. **It's not perfect**
   Total items retrieved: 5010
   Extracted 3958 articles; 1052 failures
   Error examples:
  • https://archive.is/B1Tcp: 429 Client Error: Too Many Requests for url: https://archive.is/B1Tcp
  • https://ohiocapitaljournal.com/briefs/as-teacher-burnout-deepens-states-scramble-to-fill-school-job-vacancies/: 403 Client Error: Forbidden for url: https://ohiocapitaljournal.com/briefs/as-teacher-burnout-deepens-states-scramble-to-fill-school-job-vacancies/
  • https://www.science.org/doi/10.1126/sciadv.aaw9569: 403 Client Error: Forbidden for url: https://www.science.org/doi/10.1126/sciadv.aaw9569

I have not repeated the process or tried to troubleshoot any further. Someone else may be able to improve upon the process and ultimately extract more of their saves.

---

## Next Steps

### Explore the JSON in pandas

```python
import pandas as pd, json, pathlib
df = pd.json_normalize(json.load(open('pocket_articles.json')))
print(df['tags'].explode().value_counts().head(20))
```

### Make an EPUB

```bash
pip install ebooklib
python tools/json_to_epub.py pocket_articles.json pocket_archive.epub
```

### Drop the Markdown vault into Obsidian

1. **Open‑folder‑as‑vault** and you’re done—tags, backlinks, full‑text search.

---

## License

MIT © 2025 Your Name
