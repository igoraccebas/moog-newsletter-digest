You are producing the Moog Audio "This Week's Picks" newsletter DRAFT.

STEP 0 - Get the code. Run: git clone --depth 1 https://github.com/igoraccebas/moog-newsletter-digest.git repo && cd repo
Then read README.md and ROUTINE.md. Do all remaining work inside that repo folder (run python3 from there; out/ paths are relative to it). Hard rules: (0) Never read, copy or edit anything under /root/.claude or ~/.claude. (1) NEVER send or schedule a Klaviyo campaign; the script only creates a Draft, and you must not call any Klaviyo send endpoint. (2) The only Shopify writes allowed are the two in steps 5 and 6, and only after step 3 succeeded. (3) Do not edit digest.py or the generated HTML by hand. (4) Never create a second Klaviyo campaign in the same run.

STEP 1 - Tagged products. Use the Shopify connector graphql_query tool with exactly this query and save the COMPLETE raw JSON response (the whole {"data": ...} object) to out/tagged.json (create the out/ folder if needed):
query Tagged { products(first: 50, query: "tag:newsletter OR tag:newsletter-hero") { nodes { id title handle vendor productType tags publishedAt status onlineStoreUrl descriptionHtml featuredImage { url } variants(first: 20) { nodes { price compareAtPrice availableForSale } } } } }
If the nodes list is empty, skip to STEP 7 and report "nothing tagged".

STEP 2 - Blog and events (two small queries; never fetch news post bodies, they are too large).
2a. Events, with body (needed for dates). Run with graphql_query and save the complete raw response to out/events.json:
query EventArticles { articles(first: 8, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Events") { nodes { id title handle publishedAt summary body image { url } blog { handle title } } } }
2b. Blog posts, WITHOUT body. Run and save the complete raw response to out/news.json:
query NewsArticles { articles(first: 2, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Blog") { nodes { id title handle publishedAt summary image { url } blog { handle title } } } }
2c. Build out/extras.json: python3 -c "import json;e=json.load(open('out/events.json'))['data']['articles']['nodes'];n=json.load(open('out/news.json'))['data']['articles']['nodes'];json.dump({'blog':n,'events':e},open('out/extras.json','w'))"
(The script fetches blog teasers from the public article pages itself.)
After saving each JSON file, validate it: python3 -c "import json;json.load(open('out/<file>.json'))". If it fails with "Extra data", the save appended trailing text; trim everything after the final "}" and re-validate.
If any tool result is reported as "too large" and saved to a file, do NOT read or copy that file (it lives under a protected path and will be blocked); instead re-run the query with a smaller "first" value, or drop the "body" field, and continue.

STEP 3 - Render and publish the draft. Run: python3 digest.py store --from-json out/tagged.json --extras out/extras.json --publish
It prints a summary and writes out/store-<date>.html and out/store-<date>.json (the manifest). With --publish it creates the Klaviyo DRAFT campaign using the KLAVIYO_API_KEY environment variable and adds a "klaviyo" object with campaign_url to the manifest. If the script exits non-zero or prints ERROR, do not do steps 5 and 6; go to STEP 7 and report the error verbatim.

STEP 4 - Sanity check. Read the manifest. Confirm every card (and the hero if present) has an image, a title and a price, and that the klaviyo.campaign_url exists. Note anything odd for the report (for example a blurb that looks like a spec line, or a product with no image).

STEP 5 - Add featured products to New Releases. From the manifest read add_to_collection.id and add_to_collection.product_ids and run this mutation ONCE with graphql_mutation:
mutation AddToNewReleases($id: ID!, $productIds: [ID!]!) { collectionAddProducts(id: $id, productIds: $productIds) { userErrors { field message } } }

STEP 6 - Remove the queue tags. For each entry in the manifest's untag list run:
mutation RemoveTags($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { field message } } }
(You may alias several tagsRemove calls in one document.) Do not retry a failed mutation more than once.

STEP 7 - Report. Send ONE PushNotification (the PushNotification tool) and make the same text your final message. Title/first line: "Picks draft ready - <YYYY-MM-DD>" (or "Picks: nothing tagged - <date>" or "Picks run FAILED - <date>"). Then: the Klaviyo campaign_url; the subject line and preview text; the hero (vendor, title, price) if any; the other products (vendor, title, price); the blog posts included; the events included or "no upcoming events"; how many products were added to New Releases and how many tags were removed; any warnings or errors quoted verbatim. Short and factual. Do not try to send email; the Microsoft-365 connector in this environment is read-only. Always finish with this report, even when something failed.
