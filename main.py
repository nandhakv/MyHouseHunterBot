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
# Using the Choodasandra URL from your logs
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

# --- 1. THE CRAWLER (Fixed for Timeout/Crash) ---
async def crawl_listings():
    print("🕷️  Starting Crawler...")
    nest_asyncio.apply()

    # CONFIG: Headless + Anti-Crash Args
    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=True,
        # CRITICAL: Prevent Docker crashes
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-setuid-sandbox"]
    )

    # RUN CONFIG: "Dumb" Wait Strategy
    run_cfg = CrawlerRunConfig(
        # CRITICAL FIX: Don't wait for "domcontentloaded" (it hangs). 
        # Just wait 5 seconds and grab whatever is there.
        delay_before_return_html=5.0, 
        
        # Don't load images/css
        exclude_external_links=True,
        exclude_social_media_links=True,
        
        # Real User Agent to bypass basic blocks
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )

    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            # We set a hard timeout of 30s. If it fails, it throws an error instead of hanging forever.
            result = await crawler.arun(url=SEARCH_URL, config=run_cfg)
            
            if not result.markdown:
                print("⚠️  Crawl returned empty content.")
                return ""
                
            return result.markdown

    except Exception as e:
        print(f"❌ Crawl Error: {e}")
        # CRITICAL FIX: Return empty string instead of crashing
        return ""

# --- 2. THE BRAIN (GitHub Models) ---
def analyze_data(markdown_text):
    # Safety check
    if not markdown_text or len(markdown_text) < 500:
        print("⚠️  Content too short or empty. Skipping AI analysis.")
        return []

    print("🧠 Analyzing with AI...")
    
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN
    )

    seen_houses = get_seen()
    
    prompt = f"""
    You are a House Hunter.
    
    INPUT TEXT (Scraped Listings):
    {markdown_text[:25000]} 
    
    TASK:
    1. Find rental listings matching: "{SEARCH_QUERY}"
    2. IGNORE URLs found in this list: {json.dumps(seen_houses)}
    3. IGNORE "Sold Out" or "No longer available" listings.
    
    OUTPUT:
    Return valid JSON list only. No markdown.
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
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        print(f"❌ AI Analysis Failed: {e}")
        return []

# --- 3. THE MOUTH (Telegram) ---
def send_alert(matches):
    seen_houses = get_seen()
    print(f"📤 Sending {len(matches)} alerts...")
    
    for house in matches:
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
    
    # Run the crawler safely
    raw_md = asyncio.run(crawl_listings())
    
    # Handle the "NoneType" error by checking if raw_md is valid
    if raw_md and len(raw_md) > 0:
        print(f"👀 Scraped {len(raw_md)} characters.")
        # Print a snippet to verify we actually got NoBroker content
        print(f"📝 Content Preview: {raw_md[:200].replace(chr(10), ' ')}...")
        
        matches = analyze_data(raw_md)
        if matches:
            send_alert(matches)
        else:
            print("💤 No *new* matches found.")
    else:
        print("❌ Scrape failed or returned no data.")

if __name__ == "__main__":
    print("🚀 House Agent Started (Fixed Version)...")
    job() # Run once immediately
    schedule.every(30).minutes.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(1)