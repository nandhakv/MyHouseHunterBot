import os
import json
import asyncio
import schedule
import time
import nest_asyncio
import requests # Imported at top level for safety
from crawl4ai import AsyncWebCrawler
from openai import OpenAI

# --- CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SEARCH PARAMETERS ---
# URL: Searches for 2BHK in Choodasandra, Family, Rent < 36k
SEARCH_URL = "https://www.nobroker.in/property/rent/bangalore/Choodasandra?searchParam=W3sibGF0IjoxMi44ODU2MywibG9uIjo3Ny42ODA1MzI4LCJwbGFjZUlkIjoiQ2hJSk9lZk9XVE1UcmpzUmJidkpBOHFOWkNNIiwicGxhY2VOYW1lIjoiQ2hvb2Rhc2FuZHJhIn1d&radius=2.0&sharedAccomodation=0&type=BHK2&city=bangalore&locality=Choodasandra&orderBy=lastUpdateDate,desc&rent=0,36000&leaseType=FAMILY"

# QUERY: Updated to match the URL (Choodasandra) so the AI doesn't ignore the results
SEARCH_QUERY = "2BHK in Choodasandra under 36k"

# --- DATABASE (Simple JSON) ---
DB_FILE = "seen_houses.json"

def get_seen():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return []

def save_seen(seen_list):
    with open(DB_FILE, 'w') as f: json.dump(seen_list, f)

# --- 1. THE CRAWLER (Crawl4AI) ---
async def crawl_listings():
    print("🕷️ Crawling URL...")
    nest_asyncio.apply()
    
    async with AsyncWebCrawler(verbose=True) as crawler:
        result = await crawler.arun(url=SEARCH_URL)
        return result.markdown  # Returns clean markdown text

# --- 2. THE BRAIN (GitHub Models / Azure AI) ---
def analyze_data(markdown_text):
    print("🧠 Analyzing with GitHub Models...")
    
    # We use the OpenAI Client but point it to GitHub's Model Endpoint
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN
    )

    seen_houses = get_seen()
    
    prompt = f"""
    You are a House Hunter Agent. 
    Here is the raw markdown content of a property listing page:
    
    --- START OF CONTENT ---
    {markdown_text[:20000]} 
    --- END OF CONTENT ---
    
    Task:
    1. Extract valid property listings matching: "{SEARCH_QUERY}"
    2. IGNORE any listing that contains these URLs: {json.dumps(seen_houses)}
    3. Return a JSON list of NEW matches only. 
    
    Return ONLY raw JSON. No markdown formatting (no ```json).
    Format:
    [
        {{"title": "...", "price": "...", "url": "...", "reason": "Why it's good"}}
    ]
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    
    content = response.choices[0].message.content
    # Clean up potential markdown formatting from LLM
    content = content.replace("```json", "").replace("```", "").strip()
    
    try:
        return json.loads(content)
    except Exception as e:
        print(f"❌ LLM JSON Error: {e}")
        print(f"Raw Output: {content}")
        return []

# --- 3. THE MOUTH (Telegram) ---
def send_alert(matches):
    seen_houses = get_seen()
    
    print(f"📤 Attempting to send {len(matches)} alerts...")
    
    for house in matches:
        msg = f"🏠 *New Match found!*\n\n*{house['title']}*\n💰 {house['price']}\n🔗 [View Listing]({house['url']})\n\n_Agent Note: {house['reason']}_"
        
        # FIXED: Removed the accidental markdown link syntax from the URL variable
        url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
        
        try:
            resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            if resp.status_code == 200:
                print(f"✅ Sent alert for {house['title']}")
                seen_houses.append(house['url'])
            else:
                print(f"❌ Telegram Error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"❌ Connection Error: {e}")
    
    save_seen(seen_houses)

# --- MAIN LOOP (DEBUG MODE) ---
def job():
    print("\n⏰ Waking up...")
    try:
        # 1. Crawl
        raw_md = asyncio.run(crawl_listings())
        
        # --- DEBUGGING START ---
        print(f"👀 Scraped Data Length: {len(raw_md)} chars")
        print(f"🔍 PREVIEW (First 500 chars):\n{'-'*20}\n{raw_md[:500]}\n{'-'*20}")
        
        if len(raw_md) < 500:
            print("⚠️ WARNING: Scraped data seems too short. Possibly blocked or CAPTCHA?")
        # --- DEBUGGING END ---

        # 2. Analyze
        matches = analyze_data(raw_md)
        
        # 3. Alert
        if matches:
            print(f"🎉 Found {len(matches)} NEW matches! Sending alerts...")
            send_alert(matches)
        else:
            print("💤 No new matches found (either filtered by LLM or already seen).")
            
    except Exception as e:
        print(f"❌ Critical Job Error: {e}")

if __name__ == "__main__":
    print("🚀 Agent Started...")
    
    # Run once immediately to test
    job() 
    
    # Schedule every 30 mins
    schedule.every(30).minutes.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(1)