You are producing the weekly Moog Audio "Deals" e-mail DRAFT from the products the team tagged newsletter-sale.

STEP 0 - Get the code. Run: git clone --depth 1 https://github.com/igoraccebas/moog-newsletter-digest.git repo && cd repo
Then read README.md and ROUTINE.md. Do all remaining work inside that repo folder (run python3 from there; out/ paths are relative to it).

Hard rules: (0) Never read, copy or edit anything under /root/.claude or ~/.claude. (1) NEVER send or schedule a Klaviyo campaign; the script only creates a Draft, and you must not call any Klaviyo send endpoint. (2) The only Shopify write allowed is the tagsRemove in step 6, and only after step 3 finished without error. Deals are NOT added to any collection - never run collectionAddProducts in this routine. (3) Do not edit digest.py, banner.py or the generated HTML/PNG files by hand. (4) Never create a second Klaviyo campaign in the same run. (5) This routine runs once a week (Wednesday morning); ALWAYS finish with the step 7 report, including when nothing is tagged.

STEP 1 - Tagged products. Use the Shopify connector graphql_query tool with exactly this query and save the COMPLETE raw JSON response (the whole {"data": ...} object) to out/sale.json (create the out/ folder if needed):
query Sale { products(first: 50, query: "tag:newsletter-sale") { nodes { id title handle vendor productType tags publishedAt status onlineStoreUrl descriptionHtml featuredImage { url } variants(first: 20) { nodes { price compareAtPrice availableForSale } } } } }
If the nodes list is empty, skip to STEP 7 and report "Deals: nothing tagged - <YYYY-MM-DD>".
Validate the saved file: python3 -c "import json;json.load(open('out/sale.json'))". If it fails with "Extra data", the save appended trailing text; trim everything after the final "}" and re-validate.

STEP 2 - Blog and events (two small queries; never fetch news post bodies, they are too large).
2a. Events, with body (needed for dates). Run with graphql_query and save the complete raw response to out/events.json:
query EventArticles { articles(first: 8, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Events") { nodes { id title handle publishedAt summary body image { url } blog { handle title } } } }
2b. Blog posts, WITHOUT body. Run and save the complete raw response to out/news.json:
query NewsArticles { articles(first: 2, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Blog") { nodes { id title handle publishedAt summary image { url } blog { handle title } } } }
2c. Build out/extras.json: python3 -c "import json;e=json.load(open('out/events.json'))['data']['articles']['nodes'];n=json.load(open('out/news.json'))['data']['articles']['nodes'];json.dump({'blog':n,'events':e},open('out/extras.json','w'))"
Validate each JSON file as in step 1. If any tool result is reported as "too large" and saved to a file, do NOT read or copy that file (it lives under a protected path and will be blocked); instead re-run the query with a smaller "first" value, or drop the "body" field, and continue.

STEP 3 - Render and publish the draft. Run: python3 digest.py sale --from-json out/sale.json --extras out/extras.json --publish
It puts EVERY tagged product that has a real compare-at price into one e-mail (largest discount first), renders one PNG banner per deal with banner.py (this takes a few seconds per product; the fonts are in assets/fonts), uploads the banners to Klaviyo's image library, and writes out/sale-<date>.html and out/sale-<date>.json (the manifest). With --publish it creates the Klaviyo DRAFT campaign using the KLAVIYO_API_KEY environment variable and adds a "klaviyo" object with campaign_url to the manifest. A product tagged newsletter-sale WITHOUT a compare-at price is not a deal: the script leaves it out of the e-mail, lists it under no_discount in the manifest and includes it in the untag list, so it is untagged in step 6 and the team can re-tag it after fixing the price.
Three possible outcomes:
- It prints "Deals: nothing tagged newsletter-sale. No file written." (every tagged product was sold out or archived): skip to STEP 7 and report "Deals: nothing tagged - <date>" with the sold-out titles it listed.
- It prints "Deals: no discounted products; N tagged newsletter-sale without a compare-at price ... No e-mail.": no draft was created and there is no HTML. Skip step 4, do step 6 (untag the no_discount products from the manifest), then step 7 with the title "Deals: N tagged without a discount - <date>" listing their titles.
- It prints "Klaviyo : Draft campaign <id> -> <url>": continue with step 4.
If the script exits non-zero or prints ERROR, do not do step 6; go to STEP 7 and report the error verbatim.

STEP 4 - Sanity check. Read the manifest. Confirm the hero and every card have image, title, price, compare and discount_pct, that klaviyo.campaign_url exists, that add_to_collection is null, and that every entry in banners[] has a png value starting with https:// (the hosted banner image; a bare file name means the upload failed and the e-mail would show broken images). Note for the report: the number of deals (hero + cards), the largest and smallest discount_pct, the no_discount titles if any, and anything odd (a blurb that looks like a spec line, a product with no image, a headline that looks wrong).

STEP 5 - There is no collection step for deals. Never run collectionAddProducts in this routine.

STEP 6 - Remove the queue tag. For each entry in the manifest's untag list (featured products AND no_discount products) run:
mutation RemoveTags($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { field message } } }
(You may alias several tagsRemove calls in one document.) Do not retry a failed mutation more than once.

STEP 7 - Report. Send ONE PushNotification (the PushNotification tool) and make the same text your final message. Title/first line: "Deals draft ready - <YYYY-MM-DD>" (or "Deals: nothing tagged - <date>", "Deals: N tagged without a discount - <date>", or "Deals run FAILED - <date>"). Then, when a draft was created: the Klaviyo campaign_url; the subject line and preview text; each deal in order (vendor, title, price, was-price, % off, gradient colour); the no_discount products that were untagged, if any; the blog posts included; the events included or "no upcoming events"; how many tags were removed; any warnings or errors quoted verbatim. Short and factual. Do not try to send email. Always finish with this report, every run.
