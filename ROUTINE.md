# Cloud routine — "This Week's Picks" (Tuesday & Friday, 8am Toronto)

The routine (claude.ai/code → Routines) clones this repo and follows the prompt stored in
the routine config. Summary of what it does each run:

1. Shopify connector → Admin GraphQL: products tagged `newsletter` or `newsletter-hero`
   → save raw response to out/tagged.json. Nothing tagged → report and stop.
2. Shopify connector → latest 12 published articles → out/extras.json
   (blog = 2 newest from blog `news`; events = all from blog `events`).
3. `python3 digest.py store --from-json out/tagged.json --extras out/extras.json --publish`
   → renders the email and creates a Klaviyo DRAFT (KLAVIYO_API_KEY from env). Never sends.
4. Shopify connector → `collectionAddProducts` (New Releases) for manifest.add_to_collection.
5. Shopify connector → `tagsRemove` for each manifest.untag entry.
6. Microsoft 365 connector → email the campaign link + summary to Igor.

Required environment secret: KLAVIYO_API_KEY (private key, scopes: campaigns read/write,
templates read/write).
