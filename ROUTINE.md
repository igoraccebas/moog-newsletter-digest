# Cloud routine — "This Week's Picks" (Tuesday & Friday, 8am Toronto)

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

Routine id: trig_01EAWWLniMyjfL52YU9XfiCW — ENABLED 2026-09-03. Schedule: 0 12 * * 2,5 (UTC) =
Tue & Fri 8am Toronto (7am after the November clock change).
End-to-end test 2026-09-03 16:56 UTC: 5 tagged products -> Klaviyo Draft
01M1M3BKBZF0TVZMYA572E5N5K created from the cloud, 5 tags removed, New Releases skipped (test
override). Earlier attempts surfaced and fixed: oversized tool results (split article queries),
egress blocked (env network allowlist), Klaviyo payload shape for revision 2024-10-15.

Network: the cloud environment must allow outbound HTTPS to a.klaviyo.com (draft publish)
and moogaudio.com (blog teasers). Test run 2026-09-03 16:36 UTC rendered fine but publish
failed with "Tunnel connection failed: 403 Forbidden" until egress was opened.

Required environment secret: KLAVIYO_API_KEY (private key, scopes: campaigns read/write,
templates read/write).
