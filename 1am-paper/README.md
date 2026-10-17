# The 1 A.M. Paper

A nightly two-story science digest, written by NVIDIA Nemotron 3 (free on OpenRouter) and published to a phone-friendly web page by GitHub Actions. It continues the issue numbering, move playbook and spaced-repetition quiz from the Claude version (issues No. 1 and 2 are already in `docs/log.json`).

## How a night works

| Step | Done by | Model requests |
|---|---|---|
| 1. Search Europe PMC for open-access papers from the last 14 days in your 5 categories (widens to 30 days if too few) | code | 0 |
| 2. Rank candidates (journal tier, recency) and drop reviews, corrections and papers already covered | code | 0 |
| 3. Pick the lead and second story from ~25 to 40 candidates | Nemotron | 1 |
| 4. Download each paper's **full text**; skip any paper without it | code | 0 |
| 5. Write each story as structured JSON (problem, guess, trick, methods, figure data, stats, move, quiz) | Nemotron | 2 |
| 6. **Number check**: every number in the story must appear in the paper's text. Misses go back to the model once for a fix; anything still unmatched is removed from stat tiles and figures and listed at the bottom of the issue | code + Nemotron | 0 to 2 |
| 7. Write the linking "thread", intro and one-liner | Nemotron | 1 |
| 8. Build the page from your original template, update the log and archive, publish, notify your phone | code | 0 |

A normal night uses **4 to 9** of your 1,000 free daily requests (hard cap: 30, set in `config.json`). Runs take about 5 to 20 minutes.

The rules from the old prompt carry over: lead rotation by least-covered category, a wildcard lead every 4th issue, a "Classic" second story on Sundays, a different category for the second story, no repeated DOIs, Q3 from 7 days back (odd issues) or 30 days back (even issues).

## Setup (about 15 minutes, all in a web browser)

**1. Create the repository.**
On github.com, click **New repository**. Name it `1am-paper`, set it to **Public** (free GitHub Pages needs a public repo), and create it.

**2. Upload the files.**
Unzip `1am-paper.zip` on your computer. On the new repo page, click **uploading an existing file**, drag in everything inside the unzipped folder, and click **Commit changes**.
Then check that the file `.github/workflows/nightly.yml` is in the repo. If it is missing (some browsers skip folders that start with a dot): click **Add file → Create new file**, type `.github/workflows/nightly.yml` as the name, paste the contents of that file from the zip, and commit.

**3. Turn on GitHub Pages.**
Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

**4. Add your secrets.**
Repo **Settings → Secrets and variables → Actions → New repository secret**, twice:

| Name | Value |
|---|---|
| `OPENROUTER_API_KEY` | Your OpenRouter key from openrouter.ai/keys. You can reuse the one in AnythingLLM or make a new one named "1am-paper". |
| `NTFY_TOPIC` | A long random name only you know, e.g. `devan-1am-k7q2v9xr`. Anyone who knows it can read the notifications, so don't use something guessable. |

**5. Set up the phone notification.**
Install the free **ntfy** app (Android or iPhone). Tap **+**, enter the same topic name as `NTFY_TOPIC`, keep the server as `ntfy.sh`, and subscribe.

**6. Test the paper search (no model calls).**
Repo **Actions** tab → enable workflows if asked → **Nightly 1 A.M. Paper** → **Run workflow** → mode **check** → **Run workflow**. Open the run and expand "Make tonight's issue". You should see a candidate count per category and `OK` with a word count for most categories.

**7. Make a real issue.**
Same button, mode **full**. When it finishes, your phone gets a notification; tap it to read. Manual runs always make a new issue, even if one already exists today.

From then on it runs every night at 12:52 AM Eastern. GitHub sometimes starts scheduled runs 5 to 30 minutes late.

**Your links**
- Archive and move playbook: `https://<your-github-username>.github.io/1am-paper/`
- Each issue: `https://<your-github-username>.github.io/1am-paper/issues/issue-003.html`, and so on.
- Issues No. 1 and 2 link to their original Claude pages, which only you can open.

## Things to know

- **The site and repo are public.** The reader profile in `prompts/reader_profile.md` describes your work in general terms and never names your employer. To keep even that private, paste your own profile into a repository secret named `READER_PROFILE`; it overrides the file.
- **Only open-access papers qualify.** The code needs the full text, so paywalled papers are never candidates. Open-access journal articles can take days to weeks to appear in Europe PMC, which is why the window widens to 30 days when the 14-day pool is thin.
- **Expect rougher writing than the Claude version.** Nemotron 3 Super has 120 billion parameters but only 12 billion active per token. The code compensates where it can: fixed page layout, figures drawn from data in code, and the number check. Story choice and prose quality will still vary night to night.
- **If a night fails** your phone gets "1 A.M. Paper failed tonight"; tap it to see the log. The usual causes are below.

## Troubleshooting

| Symptom in the run log | Fix |
|---|---|
| `OPENROUTER_API_KEY is not set` | Add the secret (setup step 4). The name must match exactly. |
| `OpenRouter refused the request (401)` | The key is wrong or was deleted. Make a new one and update the secret. |
| `(402)` | Your OpenRouter balance is negative. Add credit; free models stop working below zero. |
| `No endpoints found matching your data policy` | In OpenRouter **Settings → Privacy**, allow the providers that free models use. |
| `(429)` many times | You hit the 20 requests/minute or daily free limit. The code waits and retries; if it keeps happening, check what else uses your key. |
| `no lead candidate had usable open-access full text` | A thin night. Run again manually, or raise `recent_days` in `config.json`. |
| Error in "Find the site address" | GitHub Pages isn't on yet (setup step 3). |

## Changing things

| To change | Edit |
|---|---|
| The time | `cron: "52 0 * * *"` in `.github/workflows/nightly.yml` (minute, hour; Eastern time) |
| The model | `"model"` in `config.json`, e.g. `nvidia/nemotron-3-nano-30b-a3b:free` |
| Topics and search phrases | `"categories"` in `config.json` (`any` = title/abstract phrases; `and_any` = at least one must also appear) |
| Journal preference | `"journal_tiers"` in `config.json` |
| Writing style, word limits, story fields | `prompts/reader.md`, `prompts/story.md` |
| Page look | `template/issue-template.html` (its `<style>` and `<script>` are copied into every issue) |

## Files

| Path | What it is |
|---|---|
| `run.py` | Runs the whole night, start to finish |
| `amp/europepmc.py` | Paper search, full-text download, JATS (journal XML) to text |
| `amp/llm.py` | OpenRouter client; extracts and repairs JSON replies |
| `amp/numcheck.py` | The number check |
| `amp/state.py` | Issue numbering, topic rotation, spaced repetition, moves |
| `amp/render.py` | Builds the issue and archive pages |
| `docs/` | The published site: `index.html` (archive), `issues/`, `log.json` |
| `tests/run_offline.py` | Offline test with a fictional paper and a fake model: `python tests/run_offline.py` |

## Running it on your Windows PC (optional)

Install Python 3.11 or newer from python.org, open a terminal in the unzipped folder, then:

```
py run.py --mode check
$env:OPENROUTER_API_KEY = "sk-or-..."
py run.py --force
```

(The middle line is for PowerShell; in Command Prompt use `set OPENROUTER_API_KEY=sk-or-...`.) The last command writes a new issue into `docs/` on your computer only; it is not published.
