# Shared data storage (Cloudflare R2)

Bulk data the team shares — corpora, fixtures, anything too big or too
awkward for git — lives in a Cloudflare R2 bucket rather than in the repo.

- **Bucket:** `slopchecker-docs`
- **Account:** Learning Journey AI (`8888d6a39ab3056501fe36f4d43b2ddb`)
- **Region:** ENAM
- **Access:** private. No public URL, no public dev subdomain.

The account ID is an identifier, not a credential — Cloudflare treats it as
non-sensitive and it's normally committed in `wrangler.toml`. It is not
enough on its own to read anything.

## What's in it

| Key | Size | What |
|---|---|---|
| `unimelb/unimelb_training.csv` | 3.6 MB | 8,708 rows × 252 cols, labelled (`Grant.Status`) |
| `unimelb/unimelb_test.csv` | 919 KB | same schema, unlabelled |
| `unimelb/unimelb_example.csv` | 36 KB | sample submission format (`ID,Status`) |
| `unimelb/unimelb.zip` | 462 KB | original archive as received |
| `fixtures/proposal_climate.pdf` | 17 KB | PDF render of `harness/fixtures/proposal_climate.md` (fabricated, planted defects) — round-trip test artifact for the upload pipeline |

Mirrored from the team Drive folder `unimelb_data` on 2026-07-31.
`.DS_Store` was not copied.

The schema follows the University of Melbourne grant-applications layout:
grant metadata (sponsor, category, contract value band, RFCD/SEO research
codes) plus repeating per-investigator blocks (`Person.ID.N`, `Role.N`,
`Year.of.Birth.N`, `Country.of.Birth.N`, `Home.Language.N`, department and
faculty numbers, prior grant success/failure counts) for up to 15
investigators per application.

> **Provenance note.** This data is synthetic — fabricated to match the
> real dataset's schema, per the repo rule that fixtures are fabricated
> documents (#22). It carries applicant-shaped demographic *fields*, so
> treat it with fixture hygiene regardless: don't paste rows into
> third-party APIs casually, and keep the retention question inside the
> #23 data-handling policy rather than deciding it ad hoc.

## Getting access

R2 has no per-user identity. Access is a shared S3-style key pair, so:

1. **Nick mints the token** at Cloudflare dashboard → R2 → *Manage API
   Tokens* → *Create API Token*.
2. **Scope it to `slopchecker-docs` only** — "Apply to specific buckets."
   An account-scoped token would also expose the unrelated production
   buckets in this account (`rubrics`, `success-examples`,
   `webinar-assets`). Object Read is enough for most people; Object
   Read & Write only if you need to upload.
3. **Share it out-of-band** — password manager or DM. Never in the repo,
   never in an issue, never pasted into an AI session (this repo commits
   session transcripts to `ai-log/transcripts/`).

The secret is shown once. If it leaks, roll it in the dashboard; there's
no way to revoke one person's copy without rolling it for everyone.

## Using it

Add to your `.env` (gitignored):

```
R2_ACCOUNT_ID=8888d6a39ab3056501fe36f4d43b2ddb
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=slopchecker-docs
```

The S3 endpoint is `https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com`.

### Python (boto3)

```python
import os, boto3

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
s3.download_file("slopchecker-docs", "unimelb/unimelb_training.csv", "unimelb_training.csv")
```

`region_name="auto"` matters — R2 rejects real AWS region names.

### rclone

```bash
rclone copy r2:slopchecker-docs/unimelb ./data/unimelb --progress
```

with an `r2` remote of `type = s3`, `provider = Cloudflare`, `region = auto`,
and `endpoint = https://<account-id>.r2.cloudflarestorage.com`.

### wrangler (needs Cloudflare account access, not an R2 token)

```bash
wrangler r2 object get slopchecker-docs/unimelb/unimelb_training.csv --remote --pipe > unimelb_training.csv
```

`--remote` is required on wrangler 4.x. Without it you silently read and
write a local simulated bucket instead of the real one.

## Adding data

Keep the repo the source of truth for code and small fixtures; R2 is for
bulk. Use a prefix per dataset (`unimelb/`, not loose keys at the root),
and add a row to the table above in the same PR.

```bash
wrangler r2 object put slopchecker-docs/<prefix>/<file> \
  --file <file> --content-type <mime> --remote
```
