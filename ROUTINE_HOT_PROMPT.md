You are producing the Moog Audio "Product Launch" e-mail DRAFT for ONE hot new product.

STEP 0 - Get the code. Run: git clone --depth 1 https://github.com/igoraccebas/moog-newsletter-digest.git repo && cd repo
Then read README.md and ROUTINE.md. Do all remaining work inside that repo folder (run python3 from there; out/ paths are relative to it).

Hard rules: (0) Never read, copy or edit anything under /root/.claude or ~/.claude. (1) NEVER send or schedule a Klaviyo campaign; the script only creates a Draft, and you must not call any Klaviyo send endpoint. (2) The only Shopify writes allowed are the two in steps 5 and 6, and only after step 3 succeeded. (3) Do not edit digest.py or the generated HTML by hand. (4) Never create a second Klaviyo campaign in the same run. (5) This routine runs every hour; when nothing is tagged, finish QUIETLY (see step 1) - no PushNotification.

STEP 1 - Tagged product(s). Use the Shopify connector graphql_query tool with exactly this query and save the COMPLETE raw JSON response (the whole {"data": ...} object) to out/hot.json (create the out/ folder if needed):
query Hot { products(first: 10, query: "tag:newsletter-hot") { nodes { id title handle vendor productType tags publishedAt status onlineStoreUrl descriptionHtml featuredImage { url } images(first: 4) { nodes { url altText } } variants(first: 20) { nodes { price compareAtPrice availableForSale } } } } }
If the nodes list is empty: do NOT send any notification. End the run with the single final message "Launch: nothing tagged - <YYYY-MM-DD HH:MM UTC>" and stop.
Validate the saved file: python3 -c "import json;json.load(open('out/hot.json'))". If it fails with "Extra data", the save appended trailing text; trim everything after the final "}" and re-validate.

STEP 2 - Blog and events (two small queries; never fetch news post bodies, they are too large).
2a. Events, with body (needed for dates). Run with graphql_query and save the complete raw response to out/events.json:
query EventArticles { articles(first: 8, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Events") { nodes { id title handle publishedAt summary body image { url } blog { handle title } } } }
2b. Blog posts, WITHOUT body. Run and save the complete raw response to out/news.json:
query NewsArticles { articles(first: 2, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published AND blog_title:Blog") { nodes { id title handle publishedAt summary image { url } blog { handle title } } } }
2c. Build out/extras.json: python3 -c "import json;e=json.load(open('out/events.json'))['data']['articles']['nodes'];n=json.load(open('out/news.json'))['data']['articles']['nodes'];json.dump({'blog':n,'events':e},open('out/extras.json','w'))"
Validate each JSON file as in step 1. If any tool result is reported as "too large" and saved to a file, do NOT read or copy that file (it lives under a protected path and will be blocked); instead re-run the query with a smaller "first" value, or drop the "body" field, and continue.

STEP 3 - Render and publish the draft. Run: python3 digest.py hot --from-json out/hot.json --extras out/extras.json --publish
It features exactly ONE product per run (the most recently published one carrying the tag); any other tagged products are listed under queued_for_next_run in the manifest and stay tagged for the next hourly run. It writes out/hot-<date>-<product>.html and out/hot-<date>-<product>.json (the manifest). With --publish it creates the Klaviyo DRAFT campaign using the KLAVIYO_API_KEY environment variable and adds a "klaviyo" object with campaign_url to the manifest. If the script prints "nothing purchasable tagged", treat it like an empty step 1: no notification, final message "Launch: nothing purchasable tagged - <date>" and stop. If the script exits non-zero or prints ERROR, do not do steps 5 and 6; go to STEP 7 and report the error verbatim.

STEP 4 - Sanity check. Read the manifest. Confirm product.images has at least one URL, product.price is present, and klaviyo.campaign_url exists. Note for the report: product.thumbnails (0-3 extra images shown), the number of product.specs rows (0 means the description had no bullet list, so the SPECIFICATIONS box was omitted), and anything odd (a blurb that looks like a spec line, a headline that looks wrong).

STEP 5 - Add the product to New Releases. From the manifest read add_to_collection.id and add_to_collection.product_ids and run this mutation ONCE with graphql_mutation:
mutation AddToNewReleases($id: ID!, $productIds: [ID!]!) { collectionAddProducts(id: $id, productIds: $productIds) { userErrors { field message } } }

STEP 6 - Remove the queue tag from the featured product only. For each entry in the manifest's untag list run:
mutation RemoveTags($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { field message } } }
Do not touch the products listed under queued_for_next_run. Do not retry a failed mutation more than once.

STEP 7 - Report (only when a draft was created, or when something failed). Send ONE PushNotification (the PushNotification tool) and make the same text your final message. Title/first line: "Launch draft ready - <product headline>" (or "Launch run FAILED - <date>"). Then: the Klaviyo campaign_url; the subject line and preview text; product headline, sub-line, vendor, price; how many images are shown (1 main + N thumbnails) and how many spec rows; the blog posts included; the events included or "no upcoming events"; whether the product was added to New Releases and the tag removed; the titles under queued_for_next_run if any; any warnings or errors quoted verbatim. Short and factual. Do not try to send email. Always finish with this report when a draft was created or a step failed.
