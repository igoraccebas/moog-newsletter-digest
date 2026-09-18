# Cloud routine — "This Week's Picks" (Tuesday & Friday, 9am Toronto)

The routine (claude.ai/code → Routines) has no linked repository; its first step clones this
public repo with plain git, then follows the prompt stored in the routine config (copy in
ROUTINE_PROMPT.md). Summary of what it does each run:

1. Shopify connector → Admin GraphQL: products tagged `newsletter` or `newsletter-hero`
   → save raw response to out/tagged.json. Nothing tagged → report and stop.
2. Shopify connector → latest 12 published articles → out/extras.json
   (blog = 2 newest from blog `news`; events = all from blog `events`).
3. `python3 digest.py store --from-json out/tagged.json --extras out/extras.json --publish`
   → renders the email and creates a Klaviyo DRAFT (KLAVIYO_API_KEY from env). Never sends.
4. Shopify connector → `collectionAddProducts` (New Releases) for manifest.add_to_collection.
5. Shopify connector → `tagsRemove` for each manifest.untag entry.
6. Report: push notification (Claude app) + final run message, visible at
   https://claude.ai/code/routines. The Microsoft 365 connector is read-only inside routines,
   so no email is sent from the run.

Routine id: trig_01EAWWLniMyjfL52YU9XfiCW — ENABLED 2026-09-03. Schedule: 0 13 * * 2,5 (UTC) =
Tue & Fri 9am Toronto (8am after the November clock change). The cron is UTC: saving the
routine from the claude.ai web form can rewrite it (on 2026-09-03 it became 0 09 UTC = 5am
Toronto), so after any UI edit re-check the cron here or via the API.
End-to-end test 2026-09-03 16:56 UTC: 5 tagged products -> Klaviyo Draft
01M1M3BKBZF0TVZMYA572E5N5K created from the cloud, 5 tags removed, New Releases skipped (test
override). Earlier attempts surfaced and fixed: oversized tool results (split article queries),
egress blocked (env network allowlist), Klaviyo payload shape for revision 2024-10-15.

Network: the cloud environment must allow outbound HTTPS to a.klaviyo.com (draft publish)
and moogaudio.com (blog teasers). Test run 2026-09-03 16:36 UTC rendered fine but publish
failed with "Tunnel connection failed: 403 Forbidden" until egress was opened.

Required environment secret: KLAVIYO_API_KEY (private key, scopes: campaigns read/write,
templates read/write).

---

# Cloud routine — "Product Launch" (hourly, tag `newsletter-hot`)

Second routine, same environment, connectors and Klaviyo secret as the weekly one. Prompt:
ROUTINE_HOT_PROMPT.md. Routine id: trig_01FrnmCwsoSL853JYYmxJ1hk — ENABLED 2026-09-08 20:06 UTC.
Cron `5 * * * *` (every hour at :05 UTC; the server moved it off :00). Runs around the clock, so no
DST issue; narrow it to business hours by editing the cron, e.g. `5 11-23,0-2 * * *` for 7am–10pm
Toronto in summer. Cost note: each run is a short cloud session even when nothing is tagged.

- Runs ~24 times a day; when nothing is tagged it ends quietly with no notification.
- When a product is tagged: Draft in Klaviyo → added to New Releases → tag removed →
  ONE PushNotification "Launch draft ready - <product>". Igor reviews and sends by hand.
- One product per run; extra tagged products wait for the following hours
  (manifest field `queued_for_next_run`).
- Cloud routines cannot run more often than hourly, so the delay between tagging and the
  draft is 0–60 minutes (Igor accepted this on 2026-09-08 over a 10–30 min GitHub Actions /
  Make.com alternative that would have needed a Shopify Admin API token).

---

# Cloud routine — "Deals" (weekly, Wednesday 10am Toronto, tag `newsletter-sale`)

Third routine, same environment and Klaviyo secret as the other two, Shopify connector only. Prompt:
ROUTINE_SALE_PROMPT.md. Schedule: `0 14 * * 3` (UTC) = Wednesday 10am Toronto (9am after the November
clock change, like the picks routine). Igor chose weekly over hourly on 2026-09-18. Routine id: see the
line added when it was created (below). The cron is UTC and saving from the web form can rewrite it —
re-check after any UI edit.

- Everything tagged `newsletter-sale` by Wednesday morning goes out together in ONE draft; the tags are
  removed afterwards (`digest.py sale`, added 2026-09-16). Nothing tagged → one "nothing tagged" report.
- A tagged product without a compare-at price is not a deal: it is left out, listed under `no_discount`
  in the manifest and untagged too; the run reports it ("Deals: N tagged without a discount - <date>").
  Sold-out tagged products keep their tag and go out once purchasable again.
- No New Releases step: `add_to_collection` is null in the manifest and the prompt never runs
  collectionAddProducts. The only Shopify write is tagsRemove.
- Banners (since 2026-09-17): the run renders one 900×675 PNG per deal with `banner.py` (stdlib only,
  ~1.5–3 s each plus ~4 s once for the backdrop) and uploads each to Klaviyo's image library before the
  campaign is created. Needs `assets/fonts/Helvetica.ttf` in the repo (hard error otherwise — the run
  reports `ERROR: Deals banners need a font…`), and egress to `moogaudio.com` (brand-collection logos via
  `/collections/<handle>.json`) and `cdn.shopify.com` (`format=png` conversions) — both already allowed.
  The manifest lists the hosted URLs under `banners[]`; step 4 of the prompt checks they are https.
- Report: ONE PushNotification every run — "Deals draft ready - <date>", "Deals: nothing tagged - <date>",
  "Deals: N tagged without a discount - <date>" or "Deals run FAILED - <date>".
