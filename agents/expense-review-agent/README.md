# Expense Review Agent

> Turn read-only Gmail messages and personal Keep exports into evidence-backed financial proposals for human review.

## Overview

This local Python agent is for people whose transaction records are scattered
across emails and notes. It collects source text, asks local Ollama to extract
structured transactions, applies deterministic guardrails, and stages a review
queue. Nothing enters the monthly ledger until explicitly approved by a person.

It separates spending, lending, borrowing, repayments received, repayments paid,
income, and transfers. The monthly dashboard counts only approved INR entries;
loan proceeds are not treated as earnings and lending is not treated as spending.
Monthly cashflow includes borrowing, lending, and repayments with their proper
cash directions; transfers between the user's own accounts are excluded.

## Technical Stack

- Python 3.11+, Pydantic validation, HTTPX, and SQLite.
- Read-only Gmail through Google's official OAuth and Gmail clients.
- Personal Google Keep through exported Takeout JSON, not password scraping.
- Ollama's local structured-output chat API; default model `qwen3:4b`.
- No ADK dependency or model-controlled write tools. This is a bounded
  collection/extraction/review workflow, not an unrestricted autonomous agent.

## Architecture & Data Flow

```text
Gmail (read-only) / Keep JSON -> raw source notes -> local Ollama extraction
  -> schema validation -> evidence/amount/currency checks -> pending candidates
  -> human correction + approval/rejection -> audited ledger -> monthly totals
```

Raw notes and original proposals are retained alongside the current proposal,
evidence, classification reason, confidence, review flags, and decision audit.
Reimporting identical source notes is idempotent. Low-confidence proposals remain
flagged; unsupported currencies, unknown direction, and unsupported evidence or
amount block approval. Same date/amount/currency as an approved entry requires
explicit confirmation that the candidate is a distinct transaction.

## Prerequisites

Python 3.11+ with pip and venv. For real extraction, install and start Ollama from
https://ollama.com/download and download an appropriate local model. For Gmail,
enable Gmail API in a Google Cloud project, configure OAuth consent (add your
account as a test user if applicable), and create a Desktop OAuth client.
Download its credentials JSON outside this repository. Personal Keep requires
an export from https://takeout.google.com with Keep selected.

## Installation & Setup

From the repository root:

```bash
cd agents/expense-review-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
expense-review --help
ollama pull qwen3:4b
```

Open the Ollama desktop app or run `ollama serve` in a separate terminal.
On Windows, use `.venv\Scripts\Activate.ps1` for activation. Verified on macOS
with Python 3.14; other platforms and the minimum runtime are not verified.

## Configuration & Environment Variables

`EXPENSE_DATA_DIR` optionally selects the private data directory; otherwise data
lives at `~/.local/share/expense-review`. The CLI's global `--data-dir` overrides
it. The directory contains `ledger.sqlite3` and, after OAuth, `gmail-token.json`.
The model is selected with the reasoning command's `--model` flag. No hosted
model key is needed and `.env` files are not automatically loaded.

## How to Run

Authorize Gmail locally once using the downloaded Desktop client credentials:

```bash
expense-review auth-gmail --credentials /absolute/private/path/client.json
expense-review fetch-gmail --limit 20
expense-review import-keep /absolute/path/to/Takeout/Keep/example.json
expense-review reason --model qwen3:4b
expense-review list
```

The browser consent requests `gmail.readonly`; no email is modified or sent.
Google Keep's official API targets enterprise administration; this project does
not claim live personal Keep sync. Import one exported note JSON at a time, or
a JSON array / `{"notes": [...]}` containing up to 100 note objects. A note can
have `title`, `textContent`, and `listContent` checklist entries.

Inspect a candidate's source, amount, date, direction, and classification. Use
its ID from `list` to explicitly review it:

```bash
expense-review review CANDIDATE_ID --action approved --note "Matched to the original transaction source."
expense-review monthly 2026-10
```

Use `--action rejected` to exclude a candidate permanently. If a duplicate warning
is raised, verify the source and supply `--confirm-distinct` only for genuinely
different transactions. Corrections are available through the Python `Ledger.review`
API; the CLI only reviews existing proposals. The optional companion dashboard
and its Python backend are deliberately outside this repository.

## Example Input & Output

Offline checks use this explicitly synthetic note, not private financial data:

```text
On 2026-10-20 I paid INR 250 for lunch.
```

A fixture proposes an INR 250 spending entry with category Food and verbatim
evidence. The verified ledger behavior is zero approved entries before review,
one approved entry after review, spending total `250`, and cashflow `-250`.
This verifies bookkeeping, not actual Ollama extraction quality; no live-model
financial result is presented as verified.

## How to Test

```bash
python -m unittest discover -s tests -v
python -m pip check
```

Offline checks cover approval gating, source/amount guardrails, duplicate review,
idempotent imports, loan-direction totals, source parsing, and schema failures.
Real Gmail access and live Ollama extraction require local setup and consent;
they are not exercised by the offline checks.

## Known Limitations

- INR only; no FX conversion, bank reconciliation, payment initiation, or loan
  account balances. Repayments are classified but not matched to specific loans.
- Dates, counterparties, categories, completeness, and factual meaning still
  require human verification. Verbatim evidence is not proof a note is truthful.
- Takeout JSON only for Keep; no attachments, PDF parsing, or continuous sync.
- Imports are capped at 100 notes, Gmail at 50 fetched messages, and reasoning
  at 20 notes with a 90-second HTTP timeout and 3,000-token output cap per note.
- Gmail queries can miss relevant messages; model output can be incomplete or
  wrong. Schema failures remain visible as note errors and may be retried.
- Dependencies are range-constrained, not fully locked; one-user local storage
  is not a multi-user finance service. There is no encryption-at-rest layer.

## Security & Privacy Considerations

Emails and notes are sensitive. The ledger stores original text in plaintext;
protect its directory, disk, and backups. Gmail OAuth tokens are written with
owner-only file permissions. Never commit credentials, tokens, exports, local
databases, or actual financial examples. Gmail uses Google's API; source text
goes only to the fixed local Ollama endpoint for model inference. Review your
local model/service configuration separately.

Source text is untrusted and can include prompt injection. Instructions and
structured output reduce risk but are not a security boundary. The model cannot
approve entries, send mail, access arbitrary files, or execute commands. Human
review and deterministic approval checks are the authoritative write gate.
This is organizational tooling, not financial advice or a certified accounting system.

## Future Improvements

Stronger duplicate matching, configurable evidence checks, review reversal with
audit trails, encrypted storage, loan matching, and optional enterprise Keep integration.

## License

Contributed under the parent repository's MIT license.