"""
RHA Autopilot — daily content generation + auto-posting
Flow: generate post (Gemini) -> generate image (Nano Banana) -> post LinkedIn -> post Blogger -> log -> Telegram summary
Run: python autopost.py            (posts today's rotation product)
     python autopost.py --all      (posts all 7 — use for testing only)
"""
import os, json, base64, datetime, time, sys, re
import requests
import smtplib, ssl, csv, io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

# ---------------- config ----------------
GEMINI_KEY   = os.environ["GEMINI_API_KEY"].strip()
LI_TOKEN     = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LI_PERSON    = os.environ.get("LINKEDIN_PERSON_URN", "")   # e.g. urn:li:person:AbC123
WEBSITE_REPO = (os.environ.get("WEBSITE_REPO") or "").strip()        # e.g. KrishnaSaha11/rhaindia-website
WEBSITE_PAT  = (os.environ.get("WEBSITE_PAT") or "").strip()         # fine-grained PAT: Contents RW on that repo
BLOG_DIR     = os.environ.get("BLOG_DIR") or "src/content/blog"
BLOG_IMG_DIR = os.environ.get("BLOG_IMG_DIR") or "public/images/blog"
BLOG_CATEGORY = os.environ.get("BLOG_CATEGORY") or "Guides"
GOOGLE_SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")    # service account key JSON (whole content)
TG_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT      = os.environ.get("TELEGRAM_CHAT_ID", "")
SHEET_ID     = os.environ.get("GOOGLE_SHEET_ID", "")   # spreadsheet id from sheet URL

TEXT_MODEL  = (os.environ.get("TEXT_MODEL") or "gemini-2.5-pro").strip()
IMAGE_MODEL = (os.environ.get("IMAGE_MODEL") or "gemini-3.1-flash-image").strip()  # Nano Banana 2 (paid key)
VIDEO_MODEL = (os.environ.get("VIDEO_MODEL") or "veo-3.0-generate-001").strip()
FORMAT      = (os.environ.get("FORMAT") or "").strip().lower()          # "", image, video, auto
VIDEO_MODE  = (os.environ.get("VIDEO_MODE") or "off").strip().lower()   # off | auto (owner-approved alternate days)
VID_DIR     = "status/videos"

# ---------------- Email outreach config (GoDaddy Professional Email powered by Titan) ----------------
EMAIL_ENABLED  = (os.environ.get("EMAIL_ENABLED") or "off").strip().lower() in ("on","1","true","yes")
SMTP_HOST      = (os.environ.get("SMTP_HOST") or "smtpout.secureserver.net").strip()  # Titan-powered Pro Email
SMTP_PORT      = int(os.environ.get("SMTP_PORT") or "465")                            # 465 SSL (or 587 STARTTLS)
SMTP_USER      = (os.environ.get("SMTP_USER") or "sales@rhaindia.com").strip()
SMTP_PASS      = os.environ.get("SMTP_PASS") or ""                                    # mailbox password (secret)
FROM_NAME      = os.environ.get("FROM_NAME") or "RHA India — Ambika Biotech"
EMAILS_PER_DAY = int(os.environ.get("EMAILS_PER_DAY") or "10")
BUYER_CSV      = os.environ.get("BUYER_CSV") or ""       # whole CSV content stored as a GitHub secret (keeps list private)
UNSUB_MAILTO   = (os.environ.get("UNSUB_MAILTO") or SMTP_USER).strip()
EMAIL_BCC      = [e.strip() for e in (os.environ.get("EMAIL_BCC") or "").split(",") if e.strip()]  # monitoring copies
EMAIL_STATE_PATH = "status/email_state.json"

ROTATION = ["Rice Husk Ash Powder","Rice Husk Ash Granules","Rice Husk Ash Small Granules",
            "Rice Husk Ash Cylindrical Pellets","Rice Husk Powder","Rice Husk Pellets","Rice Husk"]

# central contact configuration — edit config.json to change details everywhere
try:
    with open("config.json") as _f:
        CONFIG = json.load(_f)
except Exception:
    CONFIG = {}
COMPANY  = CONFIG.get("company", "Ambika Rice Mill & Ambika Biotech")
WEBSITE  = CONFIG.get("website", "www.rhaindia.com")
WEB_URL  = CONFIG.get("website_url", "https://www.rhaindia.com")
PHONE    = CONFIG.get("phone", "+91-7381757575")

try:
    with open("knowledge_base.json") as _kf:
        KB = json.load(_kf)
except Exception:
    KB = {}

LOG_PATH = "status/log.json"
IMG_DIR  = "status/images"

# ---------------- BRAND PROMPT ----------------
# BRAND: keyword bank + hashtag bank + 7-product FACT SHEET + guardrails (pre-merged)
BRAND = """You are the B2B industrial marketing copywriter for Ambika Rice Mill & Ambika Biotech (brand: RHA India, www.rhaindia.com), manufacturer & exporter of rice husk ash products from Sambalpur, Odisha, India. Target buyers: steel plants, foundries, refractory manufacturers, ferro alloy plants, cement, construction, oil absorbents, distributors. Export markets to mention naturally (pick 3-5, vary): UAE, Saudi Arabia, Qatar, Turkey, Egypt, Germany, Netherlands, Spain, Italy, Poland, South Korea, Japan, Vietnam, Thailand, Indonesia, Australia, USA. Premium professional English, no fluff.

HIGH-INTENT SEO KEYWORD BANK (weave 3-6 naturally into every caption; rotate different ones each time; use them heavily in seoKeywords):
RHA & Silica: rice husk ash powder exporter India, rice husk ash manufacturer India, rice husk ash supplier India, rice husk ash Odisha, high silica rice husk ash, high SiO2 rice husk ash, silica rich rice husk ash, amorphous silica powder, biogenic silica powder, reactive amorphous silica, high purity silica powder, eco-friendly silica alternative, sustainable silica powder, green silica material, synthetic silica replacement.
Product variants: rice husk ash powder, rice husk ash granules, rice husk ash pellets, rice husk ash for continuous casting, rice husk ash for steel making shop, rice husk ash for steel melting shop, rice husk ash for metallurgy, rice husk ash insulation powder.
Steel industry: rice husk ash for steel industry, SMS insulation powder, steel melting shop insulation powder, ladle covering compound supplier, ladle insulation powder, tundish covering compound, tundish insulation powder, molten steel insulation material, slag covering compound, CCM insulation powder, continuous casting unit insulation, billet/bloom/slab caster insulation powder, secondary metallurgy insulation, steel casting insulation powder.
Refractory & metallurgical: refractory insulation powder, refractory raw material supplier, refractory grade silica, metallurgical insulation powder, metallurgical flux material, foundry insulation powder, ferro alloy insulation powder, induction furnace insulation material, electric arc furnace insulation, BOF insulation material, converter insulation powder.
Industrial applications: thermal insulation material, high temperature insulating powder, energy saving insulation material, heat retention powder, molten metal covering compound, oxidation prevention powder, slag control material, thermal barrier powder, low heat loss material.
Export (pattern "rice husk ash exporter + country"): UAE, Saudi Arabia, Qatar, Oman, Germany, Netherlands, Italy, Spain, France, Poland, Turkey, South Korea, Japan, Taiwan, Vietnam, Indonesia, Malaysia, Australia, Canada, USA.
Buyer intent: bulk rice husk ash supplier, OEM rice husk ash manufacturer, B2B silica powder supplier, refractory material exporter, steel plant raw material supplier, foundry raw material supplier, metallurgical consumables supplier, export quality rice husk ash, ISO quality rice husk ash supplier, industrial raw material exporter India.
Silica fume / SCM positioning (IMPORTANT RULE: NEVER claim RHA IS silica fume or micro silica — it is not. Only position as "alternative to silica fume", "micro silica alternative", "cost-effective silica fume substitute", and ONLY in applications where amorphous RHA genuinely performs: SCM/pozzolanic use in concrete, refractory filler, insulation. Honest comparison builds buyer trust): silica fume alternative, micro silica alternative, microsilica substitute, pozzolanic material, supplementary cementitious material SCM, reactive silica, high silica powder, silica for refractory, silica for foundry, silica for steel industry, silica for continuous casting, metallurgical additives, foundry flux, steel casting materials, insulating powder, heat insulation powder, green silica, sustainable silica.
Target buyer roles to speak to: steel plants, SMS/steel melting shops, CCM/continuous casting units, foundries, refractory manufacturers, metallurgical industries, ferro alloy plants.

PRODUCT FACT SHEET (STRICT — use ONLY the correct facts for the selected product; NEVER attribute ash properties to raw husk products or vice versa):
1. Rice Husk Ash Powder = combusted ash, 90%+ amorphous SiO2 (typical 90-92%, tundish grade 92% min), very low bulk density ~100-200 kg/m3. Uses: tundish/ladle covering compound, molten steel insulation, SMS/CCM, refractory filler, pozzolanic SCM in concrete, oil absorbent.
2. Rice Husk Ash Granules = same RHA chemistry (90%+ SiO2) in granular form (approx 1-5 mm): dust-free handling, easy manual/mechanical spreading over molten metal, less blow-off under draft. Same steel/refractory uses as powder.
3. Rice Husk Ash Small Granules = finer RHA granules (approx 0.5-2 mm): faster spread coverage, balance between powder coverage and granule dust control. Same steel/refractory uses.
4. Rice Husk Ash Cylindrical Pellets = compacted RHA in cylindrical pellet form: densified for clean dosing, minimal dust, uniform cylindrical shape for controlled melt-spread on molten surface and easy mechanical/auto feeding. Same steel/refractory uses. Still 90%+ SiO2 ash. Always call this product "Cylindrical Pellets" in the content.
5. Rice Husk Powder = GROUND RAW HUSK (NOT ash!): cattle-feed-grade organic material (cellulose/lignin rich). PRIMARY use: cattle & animal feed filler/roughage carrier for feed mills. Secondary: oil & chemical absorbent, particle board & wood-polymer composites, incense stick base. Angle: feed-grade quality, consistent grind, bulk supply to feed mills & dairies. NEVER claim molten steel insulation or high SiO2 for this product.
6. Rice Husk Pellets = DENSIFIED RAW HUSK BIOMASS FUEL (NOT ash!): calorific value approx 3,200-3,800 kcal/kg, low ash vs coal, renewable boiler/industrial fuel, co-firing, gasification feedstock. Angle: energy cost saving, carbon reduction vs coal, consistent pellet sizing. NEVER claim steel insulation or high SiO2.
7. Rice Husk (raw) = loose husk: biomass fuel/boiler feedstock, poultry & cattle bedding, packing material, horticulture growing media, and the raw material for RHA production. NEVER claim steel insulation or high SiO2.
For products 5-7 the target buyers shift to: biomass energy plants, boiler operators, feed mills & dairies (cattle feed), board manufacturers, poultry farms, horticulture — adjust industries, keywords and hashtags accordingly (keep brand tags).
INDUSTRY ANGLE BANK (rotate across days — pick ONE industry angle per post matching the product; cite sources naturally like "According to research published in..." — builds B2B credibility):
1. STEEL: ladle covering compound reduces radiation heat loss on liquid steel before continuous casting (source: IspatGuru); RHA used as insulation powder in steel mills (Wikipedia, Rice hull).
2. ROAD CONSTRUCTION / NHAI-PWD contractors & RMC plants: fine amorphous silica gives compact concrete, penetrates fine cracks better than cement-sand (Wikipedia); RHA below 700C combustion stays amorphous, usable in cement (ScienceDirect).
3. CONSTRUCTION / CONCRETE: RHA Blaine fineness ~3600 vs cement 2800-3000; research shows up to 30% cement replacement with ~40% CO2 reduction and improved chloride/acid resistance (MDPI Sustainability 2025). Position as SCM / pozzolanic material.
4. REFRACTORY & CERAMICS: silica source for silicates, zeolites, insulators, lightweight materials (Taylor & Francis 2018); centuries of use in ceramic glazes in China/Japan, ~95% silica aids early glaze melting (Wikipedia).
5. RUBBER & TYRE: Goodyear publicly announced rice husk ash silica as tire additive (Wikipedia) — credible mainstream validation; silica as reinforcing agent in rubber/plastics (ScienceDirect 2023).
6. AGRICULTURE (for raw husk / husk products only): soil ameliorant, growing substrate, water retention (Wikipedia).
7. WATER TREATMENT & ADSORPTION: high-purity silica from RHA used for heavy-metal remediation and gas adsorption (IJTECH 2020).
CITATION RULES (STRICT): Only cite the facts listed above with their sources. NEVER invent specific rupee savings, percentage improvements, or performance numbers that are not in the fact sheet or this bank. Qualitative benefit claims (reduces heat loss, lowers cement demand, improves durability) are fine; fabricated statistics are FORBIDDEN — technical buyers verify claims.
Contact in every post: {WEBSITE_PLACEHOLDER} and phone {PHONE_PLACEHOLDER} (EXACTLY these). 
EVIDENCE LEVEL SYSTEM (every factual claim must belong to one level; anything outside is FORBIDDEN):
Level A = peer-reviewed sources listed in the INDUSTRY ANGLE BANK (MDPI, Taylor & Francis, ScienceDirect, IJTECH) — cite them by name.
Level B = industry sources in the bank (IspatGuru, Wikipedia Rice hull).
Level C = Ambika's own verified specs from the PRODUCT FACT SHEET (e.g. 90%+ SiO2, sizes, calorific value) — present as "our tested/COA-backed specification".
Level D = plain marketing statements (bulk supply, custom packaging, samples available, export-ready) — allowed freely, no citation needed.
Any statistic or performance number NOT traceable to A/B/C is forbidden — do not invent it.
PRODUCT-INDUSTRY VALIDATION MATRIX (only write angles marked YES for the selected product):
- Rice Husk Ash Powder: Steel YES, Concrete/SCM YES, Refractory YES, Road YES, Rubber/Tyre YES (as silica filler angle), Water treatment YES, Agriculture NO.
- Rice Husk Ash Granules / Small Granules / Cylindrical Pellets: Steel YES (covering/insulation forms), Refractory YES, Concrete NO, Rubber NO, Agriculture NO, Water NO.
- Rice Husk Powder: Cattle feed YES, Absorbent YES, Boards YES — industrial steel/concrete/rubber NO.
- Rice Husk Pellets: Biomass fuel/boilers YES, co-firing YES — everything else NO.
- Rice Husk (raw): Fuel YES, Agriculture/bedding/substrate YES — industrial silica angles NO.
 
WRITING STYLE (STRICT - friendly, simple, human):
- Write like a helpful expert explaining to a friend over chai. Warm, confident, zero corporate-robot tone.
- Short sentences (max ~15 words). Grade-8 simple English - a busy plant manager should skim it in 30 seconds.
- If a technical term is needed (amorphous silica, SCM, tundish), explain it in 5-6 plain words right there.
- BANNED words/phrases: leverage, utilize, cutting-edge, synergy, revolutionize, game-changer, unlock, elevate, seamless, robust, holistic, "in today's fast-paced world".
- Structure every caption: 1 heading line -> 2-line friendly hook -> "Why it matters:" 3-4 short bullet points (each starts with the check mark) -> one simple example or fact (with source if Level A/B) -> short CTA block. Blank line between every block.
- Bullets: 5-9 words each, benefit-first, no jargon.
- Blog version may be slightly more detailed but SAME simple language; short paragraphs and bullet lists so it reads easily and ranks for questions people actually search.
If today's product has no YES match with a fresh industry angle, use a Level C/D company angle (quality control, packaging, export logistics, factory process) instead."""

def build_prompt(product, past_headlines):
    brand = BRAND.replace("{WEBSITE_PLACEHOLDER}", WEBSITE).replace("{PHONE_PLACEHOLDER}", PHONE)
    if KB:
        brand += "\n\nCOMPANY KNOWLEDGE BASE (Level C verified facts - prefer these over anything else): " + json.dumps(KB, ensure_ascii=False)[:2500]
    return f"""{brand}

TASK: Write ONE fresh LinkedIn post for: "{product}". Pick a fresh specific angle.
Return ONLY raw JSON (no fences): {{"headline":"...","caption":"...","hashtags":"...","imagePrompt":"...","blogTitle":"..."}}
- caption: 280-400 words, first line = heading (emoji + title), short paragraphs, blank lines, ✔ bullets, END with www.rhaindia.com and "Contact us for bulk orders, OEM supply and export inquiries."
- imagePrompt: photorealistic industrial marketing scene (60-90 words) incl. the branded Ambika bag (navy top, golden crown 'AMBIKA RHA', yellow bottom with product name, 'EXPORT QUALITY PRODUCT OF INDIA') and text overlay "www.rhaindia.com". CRITICAL: depict EXACTLY this product's form & correct scene — Ash Powder = fine grey-white powder over molten steel/tundish; Ash Granules = small ROUND grey granules spread on molten metal; Small Granules = finer round granules, steel scenes; Cylindrical Pellets = grey CYLINDER pellets in dosing/casting; Rice Husk Powder = tan ORGANIC powder at feed mill/dairy (NO steel scenes); Rice Husk Pellets = BROWN biomass fuel pellets at boiler/furnace (NO molten steel); Rice Husk raw = GOLDEN loose husk at rice mill/fuel yard. Bag label = exactly this product name. NEVER mix another product's form, color or scene.
- DO NOT reuse these recent headlines/angles:
{chr(10).join('- ' + h for h in past_headlines) or '(none)'}"""

# ---------------- helpers ----------------
def load_log():
    try:
        with open(LOG_PATH) as f: return json.load(f)
    except Exception: return []

def save_log(log):
    os.makedirs("status", exist_ok=True)
    with open(LOG_PATH, "w") as f: json.dump(log, f, indent=1, ensure_ascii=False)

def gemini_text(prompt, retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent"
    body = {"contents":[{"parts":[{"text": prompt}]}]}
    for i in range(retries):
        r = requests.post(url, json=body, timeout=120, headers={"x-goog-api-key": GEMINI_KEY})
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        print("gemini text error", r.status_code, r.text[:300])
        time.sleep(8 * (i+1))
    r.raise_for_status()

def parse_json(text):
    t = re.sub(r"```json|```", "", text).strip()
    return json.loads(t[t.index("{"): t.rindex("}")+1])

def gemini_image(prompt, out_path, retries=3):
    """Nano Banana image generation -> saves PNG, returns path or None."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL}:generateContent"
    body = {"contents":[{"parts":[{"text": prompt}]}]}
    for i in range(retries):
        r = requests.post(url, json=body, timeout=180, headers={"x-goog-api-key": GEMINI_KEY})
        if r.status_code == 200:
            for part in r.json()["candidates"][0]["content"]["parts"]:
                if "inline_data" in part and "inlineData" not in part:
                    part["inlineData"] = part["inline_data"]
                if "inlineData" in part:
                    os.makedirs(IMG_DIR, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(base64.b64decode(part["inlineData"]["data"]))
                    return out_path
            print("gemini image: 200 but no inlineData; parts keys:", [list(p.keys()) for p in r.json()["candidates"][0]["content"]["parts"]][:5])
        else:
            print("gemini image error", r.status_code, r.text[:400])
            if "limit: 0" in r.text:
                break  # model has no free quota at all
        time.sleep(10 * (i+1))
    return None



# ---------------- Video generation (Veo, paid) ----------------
def gemini_video(prompt, out_path):
    """Generates an ~8s cinematic clip via Veo. Returns path or None. Never raises."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{VIDEO_MODEL}:predictLongRunning"
        vprompt = ("Cinematic 8-second B2B industrial marketing shot, smooth camera movement, "
                   "professional color grade, no text artifacts. ") + (prompt or "")[:700]
        r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY},
                          json={"instances": [{"prompt": vprompt}],
                                "parameters": {"aspectRatio": "16:9"}}, timeout=60)
        if r.status_code != 200:
            print("veo start error", r.status_code, r.text[:300])
            return None
        op = r.json().get("name")
        if not op:
            print("veo: no operation name")
            return None
        for _ in range(40):  # poll up to ~6-7 min
            time.sleep(10)
            pr = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{op}",
                              headers={"x-goog-api-key": GEMINI_KEY}, timeout=60)
            if pr.status_code != 200:
                continue
            j = pr.json()
            if j.get("done"):
                if "error" in j:
                    print("veo failed:", str(j["error"])[:300])
                    return None
                resp = j.get("response", {})
                samples = (resp.get("generateVideoResponse", {}) or {}).get("generatedSamples") or                           resp.get("generatedSamples") or []
                uri = None
                for smp in samples:
                    uri = ((smp.get("video") or {}).get("uri")) or smp.get("uri")
                    if uri:
                        break
                if not uri:
                    print("veo: no video uri in response", str(resp)[:300])
                    return None
                dl = requests.get(uri, headers={"x-goog-api-key": GEMINI_KEY}, timeout=300)
                if dl.status_code != 200:
                    dl = requests.get(uri + ("&" if "?" in uri else "?") + "key=" + GEMINI_KEY, timeout=300)
                if dl.status_code == 200 and len(dl.content) > 100000:
                    os.makedirs(VID_DIR, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(dl.content)
                    return out_path
                print("veo download error", dl.status_code)
                return None
        print("veo: timed out")
        return None
    except Exception as e:
        print("veo exception", e)
        return None

# ---------------- Pollinations.ai (free, keyless AI images) ----------------
def pollinations_image(prompt, out_path, retries=2):
    q = requests.utils.quote((prompt or "")[:900])
    url = f"https://image.pollinations.ai/prompt/{q}?width=1080&height=1080&nologo=true&model=flux&seed={int(time.time())}"
    for i in range(retries + 1):
        try:
            r = requests.get(url, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 20000:
                os.makedirs(IMG_DIR, exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path
            print("pollinations error", r.status_code, r.headers.get("content-type"), len(r.content))
        except Exception as e:
            print("pollinations exception", e)
        time.sleep(15 * (i + 1))
    return None

# ---------------- Fallback poster (PIL) — last resort only ----------------
def fallback_poster(headline, product, caption, out_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    W = H = 1080
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(27+7*t), int(40+8*t), int(51+9*t)))
    def font(sz, bold=True):
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)
        except Exception:
            return ImageFont.load_default()
    def wrap(text, f, maxw):
        words, lines, line = text.split(), [], ""
        for w in words:
            t2 = (line + " " + w).strip()
            if d.textlength(t2, font=f) > maxw and line:
                lines.append(line); line = w
            else:
                line = t2
        if line: lines.append(line)
        return lines
    d.rectangle([70, 88, 78, 142], fill=(201,163,92))
    d.text((100, 88), "AMBIKA BIOTECH", font=font(36), fill=(232,228,218))
    d.text((100, 132), "RHA INDIA - From Agro Residue to Industrial Value", font=font(22, False), fill=(154,164,173))
    pf = font(26); pw = d.textlength(product.upper(), font=pf) + 48
    d.rectangle([70, 205, 70+pw, 257], fill=(194,87,27))
    d.text((94, 216), product.upper(), font=pf, fill=(255,255,255))
    y = 320
    hl = "".join(ch for ch in headline if ord(ch) < 0x2700)
    for ln in wrap(hl.strip(), font(58), W-160)[:4]:
        d.text((70, y), ln, font=font(58), fill=(242,239,231)); y += 74
    d.rectangle([70, y+10, 200, y+16], fill=(201,163,92)); y += 60
    bullets = [l.strip().lstrip(u"\u2714").strip() for l in (caption or "").split("\n") if l.strip().startswith(u"\u2714")][:3]
    if not bullets:
        bullets = ["Export quality, consistent batches", "Bulk supply and custom packaging", "Sustainable, eco-friendly material"]
    bf = font(30, False)
    for b in bullets:
        d.ellipse([76, y+8, 94, y+26], fill=(201,163,92))
        for ln in wrap("".join(ch for ch in b if ord(ch) < 0x2700), bf, W-220)[:2]:
            d.text((112, y), ln, font=bf, fill=(217,213,203)); y += 40
        y += 14
    d.polygon([(0, H), (W, H), (W, H-190), (0, H-110)], fill=(194,87,27))
    d.text((70, H-108), "www.rhaindia.com", font=font(40), fill=(255,255,255))
    d.text((70, H-56), "Bulk Orders - OEM Supply - Export Inquiries  |  +91-7381757575", font=font(26, False), fill=(255,255,255))
    os.makedirs(IMG_DIR, exist_ok=True)
    img.save(out_path)
    return out_path


# ---------------- Compliance & duplicate guards ----------------
def compliance_check(text):
    """Returns list of failures; empty list = pass."""
    fails = []
    if WEBSITE not in text:
        fails.append("website missing")
    digits = re.sub(r"\D", "", PHONE)[-10:]
    for m in re.findall(r"\+?9?1?[-\s]?\d{10}", text):
        if re.sub(r"\D", "", m)[-10:] != digits:
            fails.append("wrong phone number: " + m)
    for comp in (KB.get("competitors_do_not_mention") or []):
        if comp and comp.lower() in text.lower():
            fails.append("competitor mentioned: " + comp)
    return fails

def too_similar(headline, caption, log):
    import difflib
    new_h = (headline or "").lower()
    new_o = (caption or "").split("\n")[0].lower()
    for e in log[-15:]:
        old_h = (e.get("headline") or "").lower()
        old_o = ((e.get("caption") or "").split("\n")[0] or "").lower()
        if old_h and difflib.SequenceMatcher(None, new_h, old_h).ratio() > 0.7:
            return "headline ~" + old_h[:60]
        if old_o and difflib.SequenceMatcher(None, new_o, old_o).ratio() > 0.7:
            return "opening ~" + old_o[:60]
    return None

# ---------------- LinkedIn ----------------
def linkedin_post(caption, image_path=None, video_path=None):
    """Returns post URL or raises. Needs w_member_social scope. Video takes priority if given."""
    H = {"Authorization": f"Bearer {LI_TOKEN}", "X-Restli-Protocol-Version": "2.0.0"}
    media, category = [], "NONE"
    media_file, recipe = None, None
    if video_path and os.path.exists(video_path):
        media_file, recipe, category = video_path, "urn:li:digitalmediaRecipe:feedshare-video", "VIDEO"
    elif image_path and os.path.exists(image_path):
        media_file, recipe, category = image_path, "urn:li:digitalmediaRecipe:feedshare-image", "IMAGE"
    if media_file:
        reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=H, json={
            "registerUploadRequest": {
                "recipes": [recipe],
                "owner": LI_PERSON,
                "serviceRelationships": [{"relationshipType":"OWNER","identifier":"urn:li:userGeneratedContent"}]
            }}).json()
        up = reg["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset = reg["value"]["asset"]
        with open(media_file, "rb") as f:
            requests.put(up, headers={"Authorization": f"Bearer {LI_TOKEN}"}, data=f.read()).raise_for_status()
        media = [{"status":"READY","media": asset}]
    body = {
        "author": LI_PERSON,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": category,
            **({"media": media} if media else {})
        }},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    r = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=H, json=body)
    r.raise_for_status()
    pid = r.headers.get("x-restli-id", "")
    return f"https://www.linkedin.com/feed/update/{pid}" if pid else "posted"

# ---------------- Website blog (Astro repo on Vercel) ----------------
def gh_put(path, content_bytes, message):
    """Create/update a file in the website repo via GitHub API."""
    url = f"https://api.github.com/repos/{WEBSITE_REPO}/contents/{path}"
    H = {"Authorization": f"Bearer {WEBSITE_PAT}", "Accept": "application/vnd.github+json"}
    body = {"message": message, "content": base64.b64encode(content_bytes).decode()}
    r = requests.get(url, headers=H)
    if r.status_code == 200:
        body["sha"] = r.json()["sha"]
    r = requests.put(url, headers=H, json=body)
    r.raise_for_status()
    return r.json()

def website_blog_post(data, img_path, date):
    """Commits image + SEO markdown post (rhaindiawebsite schema) -> Vercel auto-deploys."""
    title = (data.get("blogTitle") or data["headline"])
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70]
    img_web = None
    if img_path and os.path.exists(img_path):
        img_name = f"{slug}.png"
        with open(img_path, "rb") as f:
            gh_put(f"{BLOG_IMG_DIR}/{img_name}", f.read(), f"blog image {slug}")
        img_web = f"/images/blog/{img_name}"
    caption = data["caption"]
    words = len(caption.split())
    read_time = f"{max(2, round(words / 200))} min read"
    desc = re.sub(r"\s+", " ", caption).strip()
    desc = "".join(ch for ch in desc if ord(ch) < 0x2600)[:155].strip().replace('"', "'")
    t_clean = title.replace('"', "'")
    t_noemoji = "".join(ch for ch in t_clean if ord(ch) < 0x2600).strip()
    tags = [t.strip("#") for t in (data.get("hashtags", "").split()[:4])] or ["Rice Husk Ash"]
    alt = (t_noemoji + " - Ambika Biotech RHA India").replace('"', "'")
    fm = ["---",
          f'title: "{t_noemoji}"',
          f'description: "{desc}"',
          f'category: "{BLOG_CATEGORY}"',
          f"date: {date}",
          f'readTime: "{read_time}"',
          "featured: false",
          (f'image: "{img_web}"' if img_web else 'image: "/images/products/rice-husk-ash-ground-powder.webp"'),
          f'imageAlt: "{alt}"',
          "tags: [" + ", ".join(f'"{t}"' for t in tags) + "]",
          f'seoTitle: "{t_noemoji[:55]} | Ambika Biotech"',
          "---", ""]
    body = caption + "\n\n" + \
           "\n\n**Contact us for bulk orders, OEM supply and export inquiries.**\n\n" + \
           "📞 +91-7381757575 | 🌐 [www.rhaindia.com](https://www.rhaindia.com)\n"
    md = "\n".join(fm) + body
    gh_put(f"{BLOG_DIR}/{slug}.md", md.encode(), f"blog post {slug}")
    return f"https://www.rhaindia.com/blog/{slug}"

# ---------------- Google auth (service account for Sheets) ----------------
def google_access_token():
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    info = json.loads(GOOGLE_SA_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    creds.refresh(Request())
    return creds.token

# ---------------- Google Sheet history ----------------
def sheet_log(entry):
    """Appends one row per post to the tracking Google Sheet."""
    if not SHEET_ID: return
    tok = google_access_token()
    em = entry.get("email") or {}
    email_detail = "; ".join(f"{x.get('company','')} <{x.get('email','')}> {x.get('status','')}"
                             for x in em.get("recipients", []))
    row = [entry.get("date",""), entry.get("product",""), entry.get("headline",""),
           entry.get("linkedin_url",""), entry.get("blogger_url",""),
           entry.get("image",""), json.dumps(entry.get("status",{}), ensure_ascii=False),
           email_detail]
    requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A1:append",
        params={"valueInputOption": "USER_ENTERED"},
        headers={"Authorization": f"Bearer {tok}"},
        json={"values": [row]})

# ---------------- Telegram ----------------
def telegram(msg):
    """Sends text; auto-splits long messages (Telegram 4096-char limit)."""
    if not TG_TOKEN: return
    msg = msg or ""
    for i in range(0, max(1, len(msg)), 4000):
        chunk = msg[i:i+4000]
        if not chunk: break
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT, "text": chunk, "disable_web_page_preview": True}, timeout=60)
        except Exception as e:
            print("telegram text error", e)

def telegram_photo(img_path, caption=""):
    if not TG_TOKEN or not img_path or not os.path.exists(img_path): return
    try:
        with open(img_path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                data={"chat_id": TG_CHAT, "caption": (caption or "")[:1024]},
                files={"photo": f}, timeout=120)
    except Exception as e:
        print("telegram photo error", e)

def telegram_video(vid_path, caption=""):
    if not TG_TOKEN or not vid_path or not os.path.exists(vid_path): return
    try:
        with open(vid_path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendVideo",
                data={"chat_id": TG_CHAT, "caption": (caption or "")[:1024]},
                files={"video": f}, timeout=300)
    except Exception as e:
        print("telegram video error", e)

# ---------------- Email outreach (GoDaddy Titan SMTP) ----------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PLACEHOLDER = re.compile(r"first\.?last|name@|example\.|yourcompany|xxxx|test@", re.I)
_EMAIL_COLS = ["Primary Email (verified)", "Sales Email", "Export Email",
               "Procurement Email", "General Email", "Technical Email"]
_NAME_COLS  = ["Contact Name", "Name", "Full Name", "Contact Person", "Contact"]

def _clean_email(raw):
    if not raw: return ""
    m = _EMAIL_RE.search(raw)
    if not m: return ""
    em = m.group(0).lower().strip(".")
    if _PLACEHOLDER.search(em): return ""
    return em

def load_buyers():
    """Reads buyer list from BUYER_CSV secret (preferred) or a local CSV. Returns [{email,company,country,name}] deduped."""
    text = BUYER_CSV
    if not text:
        for p in ("data/buyers.csv", "buyers.csv", "Ambika_Buyer_Contacts.csv"):
            if os.path.exists(p):
                with open(p, encoding="utf-8-sig") as f: text = f.read()
                break
    if not text: return []
    rows = list(csv.DictReader(io.StringIO(text)))
    out, seen = [], set()
    for r in rows:
        em = ""
        for c in _EMAIL_COLS:
            em = _clean_email((r.get(c) or "").strip())
            if em: break
        if not em or em in seen: continue
        seen.add(em)
        name = ""
        for c in _NAME_COLS:
            if (r.get(c) or "").strip(): name = r[c].strip(); break
        out.append({"email": em, "company": (r.get("Company") or "").strip(),
                    "country": (r.get("Country") or "").strip(), "name": name})
    return out

def load_email_state():
    try:
        with open(EMAIL_STATE_PATH) as f: return json.load(f)
    except Exception:
        return {"offset": 0, "last_date": "", "sent_today": 0, "sent_total": 0}

def save_email_state(st):
    os.makedirs("status", exist_ok=True)
    with open(EMAIL_STATE_PATH, "w") as f: json.dump(st, f, indent=1, ensure_ascii=False)

def build_email(name, subject, blog_url, product, blog_desc):
    """Returns (text, html) — professional B2B outreach linking today's blog post."""
    greeting = f"Dear {name}," if name else "Hello,"
    intro = blog_desc or f"We have just published a short technical note on {product} and where it adds value in industry."
    cta_url = blog_url or (WEB_URL + "/blog")
    text = f"""{greeting}

{intro}

Read the full article here:
{cta_url}

A quick note on who we are: {COMPANY} (brand: RHA India) manufactures and exports Rice Husk Ash and rice husk products from Sambalpur, India. Our RHA is high-silica (SiO2 85% minimum guaranteed, tundish grade) and serves steel plants, foundries, refractories, and construction. We are export-ready with bulk supply and custom packaging.

If you would like a free sample, COA/TDS, or an FOB quotation, simply reply to this email.

Best regards,
Rohit Berlia
{COMPANY} — RHA India
Phone / WhatsApp: {PHONE}
{WEB_URL}

--
You received this email because your company was identified as a potential industrial buyer of rice husk ash / silica materials. If you would prefer not to receive these updates, reply with "unsubscribe" and we will remove you immediately."""

    safe = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#ECEAE4;font-family:Arial,Helvetica,sans-serif;color:#22303C">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ECEAE4;padding:20px 0">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#F7F5F0;border:1px solid #CFC9BC;border-radius:12px;overflow:hidden">
  <tr><td style="background:#22303C;padding:18px 24px">
    <span style="font-size:18px;font-weight:bold;color:#ffffff;letter-spacing:.5px">RHA <span style="color:#C9A35C">INDIA</span></span>
    <span style="color:#9AA4AD;font-size:12px"> &nbsp;·&nbsp; Ambika Rice Mill &amp; Ambika Biotech</span>
  </td></tr>
  <tr><td style="padding:26px 24px 8px">
    <p style="margin:0 0 14px;font-size:15px">{safe(greeting)}</p>
    <p style="margin:0 0 18px;font-size:15px;line-height:1.6">{safe(intro)}</p>
    <p style="margin:0 0 22px"><a href="{safe(cta_url)}" style="background:#C2571B;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;font-size:15px;font-weight:bold;display:inline-block">Read the full article →</a></p>
    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#5A6672">
      <b style="color:#22303C">{safe(COMPANY)}</b> (brand: RHA India) manufactures and exports Rice Husk Ash and rice husk products from Sambalpur, India. Our RHA is high-silica (<b>SiO₂ 85% minimum guaranteed</b>, tundish grade) and serves steel plants, foundries, refractories and construction — export-ready, bulk supply, custom packaging.
    </p>
    <p style="margin:0 0 22px;font-size:14px;line-height:1.6">
      Would you like a free <b>sample</b>, <b>COA / TDS</b>, or an <b>FOB quotation</b>? Just reply to this email.
    </p>
  </td></tr>
  <tr><td style="padding:0 24px 22px">
    <table role="presentation" width="100%" style="border-top:1px solid #CFC9BC"><tr><td style="padding-top:16px;font-size:13px;line-height:1.7;color:#5A6672">
      <b style="color:#22303C">Rohit Berlia</b><br>
      {safe(COMPANY)} — RHA India<br>
      Phone / WhatsApp: <a href="tel:{safe(PHONE)}" style="color:#C2571B;text-decoration:none">{safe(PHONE)}</a><br>
      <a href="{safe(WEB_URL)}" style="color:#0A66C2;text-decoration:none">{safe(WEB_URL)}</a>
    </td></tr></table>
  </td></tr>
  <tr><td style="background:#ECEAE4;padding:14px 24px;font-size:11px;color:#9AA4AD;line-height:1.5">
    You received this email because your company was identified as a potential industrial buyer of rice husk ash / silica materials.
    If you would prefer not to receive these updates, <a href="mailto:{safe(UNSUB_MAILTO)}?subject=unsubscribe" style="color:#5A6672">click here to unsubscribe</a> or reply with "unsubscribe".
  </td></tr>
</table>
</td></tr></table></body></html>"""
    return text, html

def send_one_email(to_email, subject, text, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((FROM_NAME, SMTP_USER))
    msg["To"] = to_email
    msg["Reply-To"] = SMTP_USER
    msg["List-Unsubscribe"] = f"<mailto:{UNSUB_MAILTO}?subject=unsubscribe>"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    rcpts = [to_email] + EMAIL_BCC          # BCC copies for monitoring (hidden from buyer)
    ctx = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, rcpts, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, rcpts, msg.as_string())

def run_email_campaign(data, today, blog_url, product):
    """Sends EMAILS_PER_DAY emails to the next rotating batch of buyers. Never raises."""
    result = {"enabled": EMAIL_ENABLED, "sent": 0, "failed": 0, "recipients": [], "note": ""}
    if "--all" in sys.argv:
        result["note"] = "skipped (--all test run)"; return result
    if not EMAIL_ENABLED:
        result["note"] = "disabled"; return result
    if not SMTP_PASS:
        result["note"] = "no SMTP_PASS secret"; return result
    buyers = load_buyers()
    if not buyers:
        result["note"] = "no buyers loaded"; return result
    st = load_email_state()
    if st.get("last_date") == today and st.get("sent_today"):
        result["note"] = "already sent today"; return result
    n = len(buyers)
    off = st.get("offset", 0) % n
    count = min(EMAILS_PER_DAY, n)
    batch = [buyers[(off + i) % n] for i in range(count)]
    subject = "".join(ch for ch in (data.get("blogTitle") or data.get("headline") or "") if ord(ch) < 0x2600).strip()
    subject = (subject[:120] or f"{product} — RHA India").strip()
    result["subject"] = subject
    blog_desc = re.sub(r"\s+", " ", (data.get("caption") or "").split("\n")[0]).strip()
    blog_desc = "".join(ch for ch in blog_desc if ord(ch) < 0x2600).strip()[:220]
    for b in batch:
        try:
            text, html = build_email(b["name"], subject, blog_url, product, blog_desc)
            send_one_email(b["email"], subject, text, html)
            result["sent"] += 1
            result["recipients"].append({**b, "status": "sent"})
        except Exception as e:
            result["failed"] += 1
            result["recipients"].append({**b, "status": f"failed: {str(e)[:80]}"})
        time.sleep(4)  # gentle pacing, stays well under Titan limits
    st["offset"] = (off + count) % n
    st["last_date"] = today
    st["sent_today"] = result["sent"]
    st["sent_total"] = st.get("sent_total", 0) + result["sent"]
    st["last_failed"] = result["failed"]
    st["list_size"] = n
    save_email_state(st)
    return result

# ---------------- main ----------------
def run_product(product, log):
    today = datetime.date.today().isoformat()
    past = [e["headline"] for e in log if e.get("product") == product][-8:] \
         + [e["headline"] for e in log[-12:]]
    entry = {"date": today, "product": product, "status": {}, "headline": ""}
    try:
        data = parse_json(gemini_text(build_prompt(product, past)))
        sim = too_similar(data.get("headline"), data.get("caption"), log)
        if sim:
            print("duplicate detected (", sim, ") - regenerating once")
            data = parse_json(gemini_text(build_prompt(product, past) +
                "\n\nCRITICAL: Your previous attempt was too similar to an earlier post (" + sim + "). Produce a COMPLETELY different heading structure, opening line and angle."))
        entry["headline"] = data["headline"]
        full_post = data["caption"] + "\n\n" + data["hashtags"]
        entry["caption"] = full_post
        entry["imagePrompt"] = data.get("imagePrompt", "")
        fails = compliance_check(full_post)
        if fails:
            entry["status"]["compliance"] = "BLOCKED: " + "; ".join(fails)
            print("COMPLIANCE BLOCK - not publishing:", fails)
            log.append(entry)
            return entry
        entry["status"]["compliance"] = "ok"

        # image (nano banana)
        img_name = f"{today}-{product.lower().replace(' ', '-')}.png"
        img_path = os.path.join(IMG_DIR, img_name)
        img_ok = gemini_image(data["imagePrompt"], img_path)
        if img_ok:
            entry["status"]["image"] = "ok (nano banana)"
        else:
            img_ok = pollinations_image(data["imagePrompt"], img_path)
            if img_ok:
                entry["status"]["image"] = "ok (pollinations)"
            else:
                img_ok = fallback_poster(data.get("headline",""), product, data.get("caption",""), img_path)
                entry["status"]["image"] = "ok (fallback poster)" if img_ok else "failed"
        entry["image"] = f"images/{img_name}" if img_ok else None

        # format decision: manual FORMAT wins; else VIDEO_MODE=auto alternates by date; default image
        want_video = (FORMAT == "video") or (FORMAT in ("", "auto") and VIDEO_MODE == "auto"
                       and datetime.date.today().toordinal() % 2 == 0 and FORMAT != "image")
        vid_path = None
        if want_video:
            vname = f"{today}-{product.lower().replace(' ', '-')}.mp4"
            vid_path = gemini_video(data.get("imagePrompt", ""), os.path.join(VID_DIR, vname))
            if vid_path:
                entry["video"] = f"videos/{vname}"
                entry["status"]["video"] = "ok (veo)"
            else:
                entry["status"]["video"] = "failed - posted with image instead"

        # LinkedIn (video if ready, else image)
        try:
            entry["linkedin_url"] = linkedin_post(full_post,
                                                  img_path if img_ok else None,
                                                  vid_path)
            entry["status"]["linkedin"] = "ok" + (" (video)" if vid_path else "")
        except Exception as e:
            entry["status"]["linkedin"] = f"failed: {e}"

        # Website blog (rhaindia.com)
        try:
            entry["blogger_url"] = website_blog_post(data, img_path if img_ok else None, today)
            entry["status"]["blogger"] = "ok"
        except Exception as e:
            entry["status"]["blogger"] = f"failed: {e}"

        # Daily email outreach (GoDaddy Titan SMTP) — links today's blog post to next 10 buyers
        try:
            em = run_email_campaign(data, today, entry.get("blogger_url", ""), product)
            entry["email"] = em
            if em.get("enabled") and (em["sent"] or em["failed"]):
                entry["status"]["email"] = f"{em['sent']} sent, {em['failed']} failed"
            else:
                entry["status"]["email"] = f"off ({em.get('note','')})" if not em.get("enabled") else em.get("note", "—")
        except Exception as e:
            entry["status"]["email"] = f"failed: {e}"

    except Exception as e:
        entry["status"]["generation"] = f"failed: {e}"
    log.append(entry)
    try: sheet_log(entry)
    except Exception as e: entry["status"]["sheet"] = f"failed: {e}"
    return entry

if __name__ == "__main__":
    log = load_log()
    override = (os.environ.get("PRODUCT_OVERRIDE") or "").strip()
    force = (os.environ.get("FORCE") or "").lower() in ("1", "true", "yes") or "--force" in sys.argv
    if "--all" in sys.argv:
        products = ROTATION
    elif override and override in ROTATION:
        products = [override]
    else:
        products = [ROTATION[datetime.date.today().weekday() % 7]]  # Mon=Powder ... Sun=Rice Husk
        today = datetime.date.today().isoformat()
        already = [e for e in log if e.get("date") == today and (e.get("status", {}).get("blogger") == "ok" or e.get("status", {}).get("linkedin") == "ok")]
        if already and not force:
            print("Already posted today (" + already[-1]["product"] + ") — skipping. Use --force to override.")
            sys.exit(0)
    results = [run_product(p, log) for p in products]
    save_log(log)
    # ---- Rich Telegram report: image + video + full caption/keywords + links + email ----
    telegram(f"🏭 RHA Autopilot — {datetime.date.today()}")
    for r in results:
        s = r["status"]
        cap = f"{r.get('product','')} — {r.get('headline','')}"
        if r.get("image"):
            telegram_photo(os.path.join("status", r["image"]), caption=cap)
        if r.get("video"):
            telegram_video(os.path.join("status", r["video"]), caption=cap)
        em = r.get("email") or {}
        who = ""
        if em.get("recipients"):
            who = f"\n\n📧 EMAIL SENT ({em.get('sent',0)} ok / {em.get('failed',0)} failed)"
            if em.get("subject"): who += f"\n✉️ Subject: {em['subject']}"
            who += "\n" + "\n".join(
                f"{'✅' if x.get('status')=='sent' else '❌'} {x.get('company') or '—'} — {x.get('email','')}"
                + ("" if x.get("status") == "sent" else f" ({x.get('status','')})")
                for x in em["recipients"])
        detail = (
            f"📦 {r.get('product','')}\n"
            f"📝 {r.get('headline','—')}\n\n"
            f"{r.get('caption','')}\n\n"          # full caption INCLUDES hashtags/keywords
            f"────────\n"
            f"🔵 LinkedIn: {s.get('linkedin','—')}"
            + (f"\n🔗 {r.get('linkedin_url','')}" if r.get('linkedin_url') else "") + "\n"
            f"📰 Blog: {s.get('blogger','—')}"
            + (f"\n🔗 {r.get('blogger_url','')}" if r.get('blogger_url') else "") + "\n"
            f"🖼 Image: {s.get('image','—')}\n"
            f"📧 Email: {s.get('email','—')}"
            + who
        )
        telegram(detail)
    print(json.dumps(results, indent=1, ensure_ascii=False))
