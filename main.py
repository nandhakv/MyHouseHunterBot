import os
import json
import asyncio
import schedule
import time
import nest_asyncio
from crawl4ai import AsyncWebCrawler
from openai import OpenAI

# --- CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# What are we looking for?
SEARCH_URL = "https://www.nobroker.in/property/rent/bangalore/Indiranagar?searchParam=..." # REPLACE THIS with your actual search result URL
SEARCH_QUERY = "2BHK in Indiranagar under 45k"

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
    print("🕷️ Crawling...")
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
    
    {markdown_text[:15000]}  # Truncate to avoid token limits if page is huge
    
    Task:
    1. Extract valid property listings matching: {SEARCH_QUERY}
    2. IGNORE any listing that contains these URLs: {json.dumps(seen_houses)}
    3. Return a JSON list of NEW matches only. Format:
    [
        {{"title": "...", "price": "...", "url": "...", "reason": "Why it's good"}}
    ]
    If no new matches, return empty JSON [].
    """

    response = client.chat.completions.create(
        model="gpt-4o",  # or "Meta-Llama-3.1-70B-Instruct"
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    
    # Parse the LLM's response (It might wrap it in ```json, so be careful)
    content = response.choices[0].message.content
    content = content.replace("```json", "").replace("```", "").strip()
    
    try:
        return json.loads(content)
    except:
        print("❌ LLM did not return valid JSON:", content)
        return []

# --- 3. THE MOUTH (Telegram) ---
def send_alert(matches):
    import requests
    seen_houses = get_seen()
    
    for house in matches:
        msg = f"🏠 *New Match found!*\n\n*{house['title']}*\n💰 {house['price']}\n🔗 [Link]({house['url']})\n\n_Agent Note: {house['reason']}_"
        
        url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        
        seen_houses.append(house['url'])
    
    save_seen(seen_houses)

# --- MAIN LOOP ---
def job():
    print("⏰ Waking up...")
    try:
        raw_md = asyncio.run(crawl_listings())
        matches = analyze_data(raw_md)
        if matches:
            send_alert(matches)
        else:
            print("💤 No new matches.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🚀 Agent Started...")
    job() # Run once on start
    schedule.every(30).minutes.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(1)