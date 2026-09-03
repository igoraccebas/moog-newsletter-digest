# Moog Audio — New Products Digest

Weekly "new arrivals" email per department, built from Shopify and left as a
**draft** in Klaviyo for review. Nothing here ever sends an email.

## Current model — tag-driven, store-wide (Tuesday & Friday)

1. The team tags products in Shopify: `newsletter-hero` = the single "Pick of the Week"
   (coral hero block), `newsletter` = everything else ("Also New This Week" rows).
   If several products carry the hero tag, the most expensive becomes the hero and the
   rest drop into the list.
2. On Tuesday and Friday the run queries Shopify Admin GraphQL for `tag:newsletter`
   (status ACTIVE, published), saves the raw response as JSON, and renders:
   `python3 digest.py store --from-json <products.json> --extras <extras.json>`
   extras.json = {"blog": [...article nodes], "events": [...article nodes]} from the Admin
   `articles` query. Blog = 2 latest posts from the `news` blog. Events = articles from the
   `events` blog whose body contains a full date ("Saturday, April 25, 2026") that is today
   or later; past events are dropped, and the section disappears when nothing is upcoming.
   Layout follows reference-template-igor.html (hero, rows, blog, events, boutique band,
   value props, standard footer).
3. Sold-out products (no purchasable variant) are skipped. Everything else is listed,
   hero items first (by price), as full-width rows: image left, details right
   (vendor, title, short excerpt from the description, price, VIEW PRODUCT). Stock status is
   never shown: emails are static and availability changes.
4. A Klaviyo campaign is created as a **Draft** (never sent automatically) with the
   generated template, subject and preview text. Audience: Newsletter Moog Audio (R5ggT7)
   + Website Form Newsletter List (RmQMN3). Sender: Moog Audio <nouvelles@moogaudio.com>.
5. After the draft exists, two Shopify writes for every product that made it into the email
   (hero included), driven by the manifest:
   - remove its tag (`untag` -> Admin `tagsRemove`); re-tag to re-queue.
   - add it to the manual "New Releases" collection (`add_to_collection` ->
     Admin `collectionAddProducts`, collection gid://shopify/Collection/306490671293).
6. Nothing tagged -> nothing created, one-line notice only.

Department collection mode (`dj`, `modular`, `guitar`) still works as a fallback:
`python3 digest.py dj --days 7`.

## Departments & schedule

| key     | Shopify collection            | digest day |
|---------|-------------------------------|------------|
| dj      | dj-equipment-new              | Monday     |
| modular | new-modular-synthesizers      | Wednesday  |
| guitar  | guitar-gear-new               | Friday     |

Audience for all three: Newsletter Moog Audio (R5ggT7) + Website Form Newsletter List (RmQMN3).
Sender: Moog Audio <nouvelles@moogaudio.com>.

## How a run works

1. `python3 digest.py <key>` reads the public collection JSON (no Shopify auth needed).
2. "New" = published in the last 7 days, OR joined the collection since the last run
   (state/<key>.json remembers members + already-announced products).
3. Sold-out products (no variant purchasable, i.e. the storefront shows "Sold out") are always
   excluded. Noise filter drops product_type "Parts" and titles containing "(Part)". Edit
   `EXCLUDE_TYPES` / `EXCLUDE_TITLE_RE` in digest.py to tune.
4. Colour/finish siblings are grouped into one card ("5 options: Gold, Black, …").
5. Output: `out/<key>-<date>.html` (Klaviyo-ready HTML) and `out/<key>-<date>.json`
   (subject, preview text, campaign name, product list).
6. Klaviyo (via MCP, or Make "Make an API call"):
   create template (CODE, html) → create campaign (audiences, subject, preview, from)
   → assign template to the campaign message. Leave as Draft. Review in Klaviyo, then
   schedule or send manually.

Flags: `--days N` widens the publish window (first run / catch-up), `--dry-run` skips state.

## Design

Follows the Moog Audio design system: black/white, Helvetica, 0px radius, 1px #dcdcdc
hairlines, black ALL-CAPS buttons, prices as `$X,XXX.XX CAD`, red #c1272d sale price +
"Save $X" flag, green #1f8a4c "In Stock". Header/footer blocks (wordmark, black nav strip,
FREE SHIPPING | FLEXITI bar, category links, payment logos, Patch Rewards, socials, address,
Affirm legal) reuse the assets from the live weekly Klaviyo template. A 3px coral/mesh
gradient stripe under the nav is the only promo accent.

## Trial run — 2026-09-03 (tag mode, real tags)
Hero: Teenage Engineering EP-2350 FX (newsletter-hero). Rows: Denon Prime 4 G2, Pittsburgh
SV-2, Death By Audio Amp Crash (newsletter). Blog: 2 latest news posts. Events: none upcoming
(all 5 event articles are recaps of past dates). Draft 01M1KQG0TS7B1106P8BBSM82ZG updated in
place, template XMVi62. Tags NOT removed yet (pending review of the first real draft).

## Trial run — 2026-09-03 (row layout, store mode)
Sample of 5 admin products (1 archived, correctly dropped) -> 4 rows. Klaviyo draft
01M1KQG0TS7B1106P8BBSM82ZG, template XMVi62. No tags were touched in Shopify.

## Trial run — 2026-09-02
DJ Equipment, 14-day window: 9 new products → 5 cards. Klaviyo draft campaign
01M1HPYDJ1W5M0MSYB1YVARPCQ, template SNAgfc (cloned onto the message as Xxr83R).
