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

## Product Launch e-mail — `hot` mode (hourly, since 2026-09-08)

One product, one e-mail, whenever the team wants it out. Tag a product `newsletter-hot` in Shopify;
the hourly cloud routine (see ROUTINE.md, prompt in ROUTINE_HOT_PROMPT.md) picks it up on the next
run, creates a Klaviyo **draft**, adds the product to New Releases and removes the tag. Nothing is
ever sent automatically. If several products carry the tag, the most recently published one goes
out and the others stay tagged for the following runs (one per hour).

Design: claude.ai/design "Product Launch Email" (Igor, 2026-09-08). Layout, top to bottom:
coral gradient body (hosted PNG `assets/launch-coral.png`, generated with `make_gradient.py`),
black header bar (MOOG AUDIO / PRODUCT LAUNCH), eyebrow "It's finally here", headline + sub-line,
main product image on a white card, **up to three gallery thumbnails** (row omitted when the
product has a single image; 1–3 tiles adapt in width), description, **SPECIFICATIONS** box,
price + "Financing available at checkout · Free shipping" (free shipping only from 199$),
SHOP NOW, a one-line note, the Boutique band, then the standard white footer (blog, events,
value props, payments, rewards, socials, legal).

Where the content comes from — all from the Shopify product, nothing hand-written per e-mail:
- headline / sub-line: `split_title()` — split on " - " if the title has one, else right after the
  first model-number token ("Morphor Echon 6" | "Analog Polyphonic BBD Synthesizer"); otherwise the
  whole title with the product type as sub-line.
- images: `featuredImage` first, then the next three of `images(first: 4)`; thumbnails are
  centre-cropped by the Shopify CDN so the tiles line up.
- description: `long_blurb()` — the first paragraphs of the description (no headings, no lists,
  no repeated title line), cut at a sentence end near 480 characters.
- specifications: `spec_rows()` — the first bullet list in the description, max six items.
  "Label: value" bullets render as two columns and the box is titled SPECIFICATIONS; plain bullets
  render full-width under KEY FEATURES; no list at all → no box.
- static copy lines live in `LAUNCH_NOTE` and `LAUNCH_BAND` in digest.py.

Run by hand: `python3 digest.py hot --from-json out/hot.json --extras out/extras.json [--publish] [--dry-run]`
(`out/hot-test.json` is a saved sample). Output: `out/hot-<date>-<slug>.html/.json`.
Subject: "It's here: <headline> — <sub-line>"; the manifest also lists `queued_for_next_run`.

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

## Dark mode (since 2026-09-08)
Two layers, because no single trick covers every client. `DARK_MODE` in digest.py picks layer 1:

1. **`lock-light` (default).** The email stays light wherever the client lets us decide:
   `<meta name="color-scheme" content="light">` for Apple Mail / iOS Mail, and `LIGHT_LOCK_RULES`
   (`[data-ogsc]`/`[data-ogsb]`) re-assert every colour in Outlook.com / new Outlook dark mode.
   Every element that carries a colour has a class (`.txt-*`, `.bg-*`, `.btn`, `.hl`) so nothing
   is left for Outlook to recolour on its own.
   **`themed`** is the alternative: `DARK_RULES` emitted inside `@media (prefers-color-scheme: dark)`
   and under `[data-ogsc]` give dark-mode users a designed dark theme (dark page/body, white text,
   `.btn` inverted to white-on-black, dimmed hairlines) while `LOCK_RULES` keep the hero text,
   white tiles, nav band and sale flag as designed. Igor tried it on 2026-09-08 and preferred
   light-by-default, so it is off.
2. **Survive inversion everywhere else.** Gmail ignores layer 1 and inverts by itself (iOS flips
   light *and* dark blocks, so buttons invert there too; Android flips only light ones, so black
   buttons stay black with their white hairline border). The layout is built so inverting it still
   looks intentional:
   - the MOOG AUDIO wordmark is live text, not a white JPEG, so it flips with its background;
   - image-only cells (hero product card, product shots, payment logos, Patch Rewards, social
     icons) are locked white with `WHITE_LOCK` (`background-image: linear-gradient(#fff,#fff)`,
     which Gmail does not recolour). Never put text inside a WHITE_LOCK cell — Gmail would still
     lighten it;
   - black buttons carry a 1px white border: invisible on white, keeps them visible after a
     partial invert;
   - category links are `#9a9a9a` (the old `#c1c1c1` became unreadable once inverted).

Known limit: Gmail turns the black hero text on the gradient white (it did before too). Kept by
decision on 2026-09-08 — the hero layout stays as designed.

Previews: out/today-light.jpeg, out/today-dark-*.jpeg (local only).

## Hero background rotation
The "Pick of the Week" block rotates through five gradients (peach-coral, gold-amber,
blush-rose, sage-mint, slate-ice), chosen from the run date so consecutive Tuesday/Friday runs
never repeat and the cycle restarts every five runs. Each has a solid fallback for Outlook.
Force one with `--hero-style <name>`; the manifest records `hero_style`.

## Design

Follows the Moog Audio design system: black/white, Helvetica, 0px radius, 1px #dcdcdc
hairlines, black ALL-CAPS buttons, prices as `$X,XXX.XX CAD`, red #c1272d sale price +
"Save $X" flag, green #1f8a4c "In Stock". Header/footer blocks (wordmark, black nav strip,
FREE SHIPPING | FLEXITI bar, category links, payment logos, Patch Rewards, socials, address,
Affirm legal) reuse the assets from the live weekly Klaviyo template. A 3px coral/mesh
gradient stripe under the nav is the only promo accent.

## Automation live — 2026-09-03
Cloud routine enabled (see ROUTINE.md). First scheduled run 2026-09-04 succeeded (draft 01M1NV126ZW3YPWHP13HTAFTBH). Schedule moved to 13:00 UTC = 9am Toronto.

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
