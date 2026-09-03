You are producing the Moog Audio "This Week's Picks" newsletter DRAFT.

STEP 0 - Get the code. Run: git clone --depth 1 https://github.com/igoraccebas/moog-newsletter-digest.git repo && cd repo
Then read README.md and ROUTINE.md. Do all remaining work inside that repo folder (run python3 from there; out/ paths are relative to it). Hard rules: (1) NEVER send or schedule a Klaviyo campaign; the script only creates a Draft, and you must not call any Klaviyo send endpoint. (2) The only Shopify writes allowed are the two in steps 5 and 6, and only after step 3 succeeded. (3) Do not edit digest.py or the generated HTML by hand. (4) Never create a second Klaviyo campaign in the same run.

STEP 1 - Tagged products. Use the Shopify connector graphql_query tool with exactly this query and save the COMPLETE raw JSON response (the whole {"data": ...} object) to out/tagged.json (create the out/ folder if needed):
query Tagged { products(first: 50, query: "tag:newsletter OR tag:newsletter-hero") { nodes { id title handle vendor productType tags publishedAt status onlineStoreUrl descriptionHtml featuredImage { url } variants(first: 20) { nodes { price compareAtPrice availableForSale } } } } }
If the nodes list is empty, skip to STEP 7 and report "nothing tagged".

STEP 2 - Blog and events. Run this query with graphql_query and save the complete raw response to out/articles.json:
query RecentArticles { articles(first: 12, sortKey: PUBLISHED_AT, reverse: true, query: "published_status:published") { nodes { id title handle publishedAt summary body image { url } blog { handle title } } } }
Then build out/extras.json with: python3 -c "import json;d=json.load(open('out/articles.json'))['data']['articles']['nodes'];json.dump({'blog':[a for a in d if a['blog']['handle']=='news'][:2],'events':[a for a in d if a['blog']['handle']=='events']},open('out/extras.json','w'))"

STEP 3 - Render and publish the draft. Run: python3 digest.py store --from-json out/tagged.json --extras out/extras.json --publish
It prints a summary and writes out/store-<date>.html and out/store-<date>.json (the manifest). With --publish it creates the Klaviyo DRAFT campaign using the KLAVIYO_API_KEY environment variable and adds a "klaviyo" object with campaign_url to the manifest. If the script exits non-zero or prints ERROR, do not do steps 5 and 6; go to STEP 7 and report the error verbatim.

STEP 4 - Sanity check. Read the manifest. Confirm every card (and the hero if present) has an image, a title and a price, and that the klaviyo.campaign_url exists. Note anything odd for the report (for example a blurb that looks like a spec line, or a product with no image).

STEP 5 - Add featured products to New Releases. From the manifest read add_to_collection.id and add_to_collection.product_ids and run this mutation ONCE with graphql_mutation:
mutation AddToNewReleases($id: ID!, $productIds: [ID!]!) { collectionAddProducts(id: $id, productIds: $productIds) { userErrors { field message } } }

STEP 6 - Remove the queue tags. For each entry in the manifest's untag list run:
mutation RemoveTags($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { field message } } }
(You may alias several tagsRemove calls in one document.) Do not retry a failed mutation more than once.

STEP 7 - Report. Send ONE PushNotification (the PushNotification tool) and make the same text your final message. Title/first line: "Picks draft ready - <YYYY-MM-DD>" (or "Picks: nothing tagged - <date>" or "Picks run FAILED - <date>"). Then: the Klaviyo campaign_url; the subject line and preview text; the hero (vendor, title, price) if any; the other products (vendor, title, price); the blog posts included; the events included or "no upcoming events"; how many products were added to New Releases and how many tags were removed; any warnings or errors quoted verbatim. Short and factual. Do not try to send email; the Microsoft-365 connector in this environment is read-only. Always finish with this report, even when something failed.
