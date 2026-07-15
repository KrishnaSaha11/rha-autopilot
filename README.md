# RHA Autopilot v2 — GitHub Actions (Krishna's repo)

Daily 11:00 IST: Gemini post -> Nano Banana image -> LinkedIn -> **rhaindia.com blog (website repo commit -> Vercel auto-deploy)** -> Google Sheet log -> Telegram.

BRAND block (fact sheet + keywords + rules) is ALREADY MERGED in autopost.py. ✓

## Secrets needed (repo Settings -> Secrets -> Actions)

| Secret | What | Where from |
|---|---|---|
| GEMINI_API_KEY | text + image AI | aistudio.google.com (Rohit's account best) |
| LINKEDIN_ACCESS_TOKEN | posting to Rohit's profile | LinkedIn app OAuth (see below) |
| LINKEDIN_PERSON_URN | urn:li:person:XXX | GET /v2/userinfo -> sub |
| WEBSITE_REPO | e.g. KrishnaSaha11/rhaindia-website | your website repo path |
| WEBSITE_PAT | fine-grained PAT, Contents Read+Write on WEBSITE_REPO only | github.com/settings/personal-access-tokens |
| BLOG_DIR | Astro blog content folder (e.g. src/content/blog) | your repo structure |
| BLOG_IMG_DIR | public images folder (e.g. public/blog-images) | your repo structure |
| GOOGLE_SA_JSON | full service-account key JSON | see Sheet step |
| SHEET_ID (env GOOGLE_SHEET_ID)* | post history sheet | sheet URL |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | daily summary to Rohit | @BotFather |

*Note: code reads GOOGLE_SHEET_ID — add secret with that exact name.

## Setup order (~2.5-3 hr)

1. **(10 min)** This repo -> push files -> Actions tab shows workflow.
2. **(15 min)** Gemini key -> secret. Verify image model name `gemini-2.5-flash-image` in AI Studio.
3. **(20 min)** Website blog wiring:
   - Confirm your Astro blog collection path + frontmatter schema (title/description/pubDate/heroImage/tags). **Edit the `fm` list in `website_blog_post()` if your field names differ** (e.g. `date:` instead of `pubDate:`).
   - Create fine-grained PAT (only WEBSITE_REPO, Contents RW). Secrets: WEBSITE_REPO, WEBSITE_PAT, BLOG_DIR, BLOG_IMG_DIR.
4. **(25 min)** Google Sheet via service account (NO OAuth pain):
   - console.cloud.google.com -> project -> enable **Google Sheets API** -> IAM -> Service Accounts -> create -> Keys -> new JSON key -> download.
   - Whole JSON content -> secret GOOGLE_SA_JSON.
   - Create sheet "RHA Post History" (headers: Date|Product|Headline|LinkedIn|Blog|Image|Status) -> **Share the sheet with the service account email** (xxx@yyy.iam.gserviceaccount.com) as Editor. -> SHEET id -> secret GOOGLE_SHEET_ID.
5. **(60-90 min)** LinkedIn (with Rohit on call for his login):
   - developer.linkedin.com -> create app -> Products: "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect".
   - OAuth (scope `w_member_social openid profile`) with ROHIT's LinkedIn -> access token.
   - GET https://api.linkedin.com/v2/userinfo -> `sub` -> URN = `urn:li:person:<sub>`.
   - Token expires ~60 days: set calendar reminder.
6. **(15 min)** Telegram: @BotFather bot -> token; Rohit sends /start -> chat id via getUpdates.
7. **(20 min)** TEST: Actions -> Run workflow (manual). Verify: LinkedIn post, blog live on rhaindia.com (check Vercel deploy), sheet row, Telegram, status/log.json. Fix -> rerun.
8. Status page: Vercel/GitHub Pages from /status (optional day-2).

## SEO notes for the blog
- Each post gets slug `YYYY-MM-DD-headline`, meta description (155 chars), hero image, tags from hashtags — all auto.
- Krishna: make sure blog collection renders title as H1 and description as meta description in your Astro layout; submit /blog to GSC sitemap if not already.

## Daily behavior
- 1 product/day by weekday rotation (Mon=Powder ... Sun=Rice Husk). `python autopost.py --all` for testing only.
- Duplicate prevention via log.json history.
- Failures isolated per platform; Telegram shows exactly what failed.

## Daily Email Outreach (NEW — GoDaddy Professional Email powered by Titan)

After the blog post is published, the system emails the blog link to the next **10 buyers** from a rotating list. Fully isolated — if email fails, posting is unaffected.

**How it works**
- Buyer list lives in the `BUYER_CSV` **secret** (NOT committed — keeps the lead database private even though this repo is public). Script auto-picks the best email per row (Primary → Sales → Export → Procurement → General → Technical), cleans junk/placeholder addresses, and de-dupes.
- Rotation pointer stored in `status/email_state.json` (only an offset + counts — no emails, safe to commit). Next day continues from where it stopped; wraps around at the end.
- Each email: friendly B2B copy + blog link + company intro + phone/website signature + **unsubscribe** line and `List-Unsubscribe` header (protects sender reputation of the primary mailbox).
- Full recipient list (who got it, sent/failed) goes to **Telegram** and the **Google Sheet** (both private). The public mission-control page shows **counts only**.
- Guards: won't double-send the same day; skips entirely on `--all` test runs.

**Secrets to add (Settings → Secrets → Actions)**

| Secret | Value | Notes |
|---|---|---|
| EMAIL_ENABLED | `on` | leave unset/`off` to keep email disabled |
| SMTP_USER | `sales@rhaindia.com` | the sending mailbox |
| SMTP_PASS | mailbox password | Titan mailbox password |
| BUYER_CSV | *(paste whole CSV)* | keeps buyer list private |
| FROM_NAME | e.g. `RHA India — Ambika Biotech` | optional display name |
| SMTP_HOST | *(optional)* | default `smtpout.secureserver.net` |
| SMTP_PORT | *(optional)* | default `465` (SSL). Use `587` if 465 blocked |
| EMAILS_PER_DAY | *(optional)* | default `10` |
| UNSUB_MAILTO | *(optional)* | default = SMTP_USER |

**One-time Titan setup (in `sales@rhaindia.com` Titan webmail):**
1. Settings (gear) → **Enable Titan on other apps** (turn ON third-party access).
2. **Turn OFF 2FA** on this mailbox — Titan blocks third-party SMTP while 2FA is on.
3. SMTP: `smtpout.secureserver.net`, port 465, SSL, username = full email, password = mailbox password.

**Test:** add secrets → Actions → Run workflow (manual, blank product) → check: 10 emails delivered, Telegram shows recipient list, Google Sheet email column filled, `status/email_state.json` offset advanced.
