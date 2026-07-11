"""
RHA Autopilot — daily content generation + auto-posting
Flow: generate post (Gemini) -> generate image (Nano Banana) -> post LinkedIn -> post Blogger -> log -> Telegram summary
Run: python autopost.py            (posts today's rotation product)
     python autopost.py --all      (posts all 7 — use for testing only)
"""
import os, json, base64, datetime, time, sys, re
import requests

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

TEXT_MODEL  = "gemini-flash-latest"
IMAGE_MODEL = "gemini-2.5-flash-image"   # Nano Banana (free tier)

ROTATION = ["Rice Husk Ash Powder","Rice Husk Ash Granules","Rice Husk Ash Small Granules",
            "Rice Husk Ash Cylindrical Pellets","Rice Husk Powder","Rice Husk Pellets","Rice Husk"]

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
For products 5-7 the target buyers shift to: biomass energy plants, boiler operators, feed mills & dairies (cattle feed), board manufacturers, poultry farms, horticulture — adjust industries, keywords and hashtags accordingly (keep brand tags)."""

def build_prompt(product, past_headlines):
    return f"""{BRAND}

TASK: Write ONE fresh LinkedIn post for: "{product}". Pick a fresh specific angle.
Return ONLY raw JSON (no fences): {{"headline":"...","caption":"...","hashtags":"...","imagePrompt":"...","blogTitle":"..."}}
- caption: 280-400 words, first line = heading (emoji + title), short paragraphs, blank lines, ✔ bullets, END with www.rhaindia.com and "Contact us for bulk orders, OEM supply and export inquiries."
- imagePrompt: photorealistic industrial marketing scene for this product, include text overlay "www.rhaindia.com", 60-90 words.
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


# ---------------- Fallback poster (PIL) — guarantees every post has an image ----------------
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

# ---------------- LinkedIn ----------------
def linkedin_post(caption, image_path=None):
    """Returns post URL or raises. Needs w_member_social scope."""
    H = {"Authorization": f"Bearer {LI_TOKEN}", "X-Restli-Protocol-Version": "2.0.0"}
    media = []
    if image_path:
        reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=H, json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": LI_PERSON,
                "serviceRelationships": [{"relationshipType":"OWNER","identifier":"urn:li:userGeneratedContent"}]
            }}).json()
        up = reg["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset = reg["value"]["asset"]
        with open(image_path, "rb") as f:
            requests.put(up, headers={"Authorization": f"Bearer {LI_TOKEN}"}, data=f.read()).raise_for_status()
        media = [{"status":"READY","media": asset}]
    body = {
        "author": LI_PERSON,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": "IMAGE" if media else "NONE",
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
    row = [entry.get("date",""), entry.get("product",""), entry.get("headline",""),
           entry.get("linkedin_url",""), entry.get("blogger_url",""),
           entry.get("image",""), json.dumps(entry.get("status",{}), ensure_ascii=False)]
    requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A1:append",
        params={"valueInputOption": "USER_ENTERED"},
        headers={"Authorization": f"Bearer {tok}"},
        json={"values": [row]})

# ---------------- Telegram ----------------
def telegram(msg):
    if not TG_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": msg, "disable_web_page_preview": True})

# ---------------- main ----------------
def run_product(product, log):
    today = datetime.date.today().isoformat()
    past = [e["headline"] for e in log if e.get("product") == product][-8:] \
         + [e["headline"] for e in log[-12:]]
    entry = {"date": today, "product": product, "status": {}, "headline": ""}
    try:
        data = parse_json(gemini_text(build_prompt(product, past)))
        entry["headline"] = data["headline"]
        full_post = data["caption"] + "\n\n" + data["hashtags"]

        # image (nano banana)
        img_name = f"{today}-{product.lower().replace(' ', '-')}.png"
        img_path = os.path.join(IMG_DIR, img_name)
        img_ok = gemini_image(data["imagePrompt"], img_path)
        if img_ok:
            entry["status"]["image"] = "ok (nano banana)"
        else:
            img_ok = fallback_poster(data.get("headline",""), product, data.get("caption",""), img_path)
            entry["status"]["image"] = "ok (fallback poster)" if img_ok else "failed"
        entry["image"] = f"images/{img_name}" if img_ok else None

        # LinkedIn
        try:
            entry["linkedin_url"] = linkedin_post(full_post, img_path if img_ok else None)
            entry["status"]["linkedin"] = "ok"
        except Exception as e:
            entry["status"]["linkedin"] = f"failed: {e}"

        # Website blog (rhaindia.com)
        try:
            entry["blogger_url"] = website_blog_post(data, img_path if img_ok else None, today)
            entry["status"]["blogger"] = "ok"
        except Exception as e:
            entry["status"]["blogger"] = f"failed: {e}"

    except Exception as e:
        entry["status"]["generation"] = f"failed: {e}"
    log.append(entry)
    try: sheet_log(entry)
    except Exception as e: entry["status"]["sheet"] = f"failed: {e}"
    return entry

if __name__ == "__main__":
    log = load_log()
    if "--all" in sys.argv:
        products = ROTATION
    else:
        products = [ROTATION[datetime.date.today().weekday() % 7]]  # Mon=Powder ... Sun=Rice Husk
    results = [run_product(p, log) for p in products]
    save_log(log)
    lines = [f"🏭 RHA Autopilot — {datetime.date.today()}"]
    for r in results:
        s = r["status"]
        lines.append(f"\n{r['product']}\n📝 {r.get('headline','—')}"
                     f"\nin: {s.get('linkedin','—')} | blog: {s.get('blogger','—')} | img: {s.get('image','—')}"
                     + (f"\n🔗 {r.get('linkedin_url','')}" if r.get('linkedin_url') else ""))
    telegram("\n".join(lines))
    print(json.dumps(results, indent=1, ensure_ascii=False))
