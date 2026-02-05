import os
import json
import asyncio
import schedule
import time
import nest_asyncio
import requests
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from openai import OpenAI

# --- CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SEARCH PARAMETERS ---
# NOTE: This URL is for Choodasandra. Make sure to update it if you change locations.
SEARCH_URL = "https://www.nobroker.in/property/rent/bangalore/Choodasandra?searchParam=W3sibGF0IjoxMi44ODU2MywibG9uIjo3Ny42ODA1MzI4LCJwbGFjZUlkIjoiQ2hJSk9lZk9XVE1UcmpzUmJidkpBOHFOWkNNIiwicGxhY2VOYW1lIjoiQ2hvb2Rhc2FuZHJhIn1d&radius=2.0&sharedAccomodation=0&type=BHK2&city=bangalore&locality=Choodasandra&orderBy=lastUpdateDate,desc&rent=0,36000&leaseType=FAMILY"

SEARCH_QUERY = "2BHK in Choodasandra under 36k"
DB_FILE = "seen_houses.json"

# --- MEMORY MANAGEMENT ---
def get_seen():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return []

def save_seen(seen_list):
    with open(DB_FILE, 'w') as f: json.dump(seen_list, f)

# --- 1. THE CRAWLER (Optimized for Cloud) ---
async def crawl_listings():
    print("🕷️  Starting Crawler...")
    nest_asyncio.apply()

    # CONFIG: Run headless and block images to save RAM
    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=True
    )

    # RUN CONFIG: Don't wait for network idle (ads), just wait for DOM
    run_cfg = CrawlerRunConfig(
        # This prevents hanging on heavy sites like NoBroker
        wait_for="domcontentloaded", 
        # Blocks images/css to speed up loading
        exclude_external_links=True,
        exclude_social_media_links=True,
        # Fake being a real Mac user to avoid blocks
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=SEARCH_URL, config=run_cfg)
            return result.markdown
    except Exception as e:
        print(f"⚠️  Crawl Failed: {e}")
        return ""

# --- 2. THE BRAIN (GitHub Models) ---
def analyze_data(markdown_text):
    if not markdown_text or len(markdown_text) < 500:
        print("⚠️  Data too short to analyze.")
        return []

    print("🧠 Analyzing with AI...")
    
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN
    )

    seen_houses = get_seen()
    
    prompt = f"""
    You are a Real Estate Filter.
    
    DATA SOURCE:
    {markdown_text[:20000]} 
    
    YOUR GOAL:
    1. Find rental listings that match: "{SEARCH_QUERY}"
    2. Exclude any that match these seen URLs: {json.dumps(seen_houses)}
    3. Return valid JSON only.
    
    OUTPUT FORMAT (JSON List):
    [
        {{"title": "Property Name", "price": "30,000", "url": "Full URL", "reason": "Short reason"}}
    ]
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        content = response.choices[0].message.content
        # Clean markdown wrappers if AI adds them
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return []

# --- 3. THE MOUTH (Telegram) ---
def send_alert(matches):
    seen_houses = get_seen()
    print(f"📤 Sending {len(matches)} alerts...")
    
    for house in matches:
        # Check if URL is valid before sending
        if "http" not in house['url']: continue
        
        msg = f"🏠 *New Match!*\n\n*{house['title']}*\n💰 {house['price']}\n🔗 [View Listing]({house['url']})\n\n_Note: {house['reason']}_"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            seen_houses.append(house['url'])
        except Exception as e:
            print(f"❌ Telegram Error: {e}")
    
    save_seen(seen_houses)

# --- MAIN LOOP ---
def job():
    print("\n⏰ Waking up...")
    
    # Step 1: Crawl
    raw_md = asyncio.run(crawl_listings())
    
    # DEBUG: See if we actually got data
    print(f"👀 Scraped {len(raw_md)} characters.")
    if len(raw_md) > 0:
        print(f"📝 Preview: {raw_md[:200].replace(chr(10), ' ')}...")
    
    # Step 2: Analyze & Alert
    if len(raw_md) > 1000:
        matches = analyze_data(raw_md)
        if matches:
            send_alert(matches)
        else:
            print("💤 AI found no *new* matches.")
    else:
        print("⚠️  Skipping analysis (content empty or blocked).")

if __name__ == "__main__":
    print("🚀 House Agent Started (Cloud Optimized)...")
    
    # Run once immediately
    job()
    
    # Schedule
    schedule.every(30).minutes.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(1)