"""
Deep API inspection:
1. Get CSRF token from advance-search page
2. POST to /search-bids with DELHI state  
3. Inspect full JSON response structure
4. Check if all data is available via API (no browser scraping needed)
"""
import asyncio, re, json
from playwright.async_api import async_playwright

BASE_URL = "https://bidplus.gem.gov.in/advance-search"

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        responses = {}
        async def on_response(resp):
            if "search-bids" in resp.url:
                try:
                    responses["search_bids"] = {
                        "url": resp.url,
                        "status": resp.status,
                        "headers": dict(resp.headers),
                        "body": await resp.json()
                    }
                except:
                    responses["search_bids"] = {"error": "parse failed"}
        page.on("response", on_response)

        req_data = {}
        async def on_request(req):
            if "search-bids" in req.url:
                req_data["url"] = req.url
                req_data["method"] = req.method
                req_data["post_data"] = req.post_data
                req_data["headers"] = dict(req.headers)
        page.on("request", on_request)

        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
        await page.click("text=Search by Consignee Location", timeout=30000)
        await page.wait_for_selector("select#state_name_con", timeout=30000)
        await page.select_option("select#state_name_con", value="DELHI", timeout=30000)
        await page.click("a[onclick=\"searchBid('con')\"]", timeout=30000)
        await asyncio.sleep(8)

        print("=== REQUEST TO /search-bids ===")
        print(f"URL: {req_data.get('url')}")
        print(f"Method: {req_data.get('method')}")
        print(f"Post data: {req_data.get('post_data')}")
        print(f"Headers (important ones):")
        for k in ["x-csrf-token", "x-requested-with", "content-type", "referer", "origin", "cookie"]:
            if k in req_data.get("headers", {}):
                print(f"  {k}: {req_data['headers'][k][:100]}")

        print("\n=== RESPONSE FROM /search-bids ===")
        if "search_bids" in responses:
            resp = responses["search_bids"]
            body = resp.get("body", {})
            print(f"Status: {resp.get('status')}")
            resp_data = body.get("response", {}).get("response", {})
            print(f"numFound: {resp_data.get('numFound')}")
            docs = resp_data.get("docs", [])
            print(f"Docs count: {len(docs)}")
            if docs:
                print(f"\nFirst doc keys: {list(docs[0].keys())}")
                print(f"\nFirst doc sample:")
                for k, v in list(docs[0].items())[:20]:
                    print(f"  {k}: {v}")

        # Also check the bidCard div structure
        bid_card_html = await page.evaluate("() => document.getElementById('bidCard') ? document.getElementById('bidCard').innerHTML.slice(0, 2000) : 'not found'")
        print(f"\n=== #bidCard HTML (first 2000 chars) ===")
        print(bid_card_html)

        # Check pagination
        pag = await page.evaluate("() => { const p = document.getElementById('light-pagination'); return p ? p.innerHTML.slice(0,800) : 'not found'; }")
        print(f"\n=== #light-pagination HTML ===")
        print(pag)

        await browser.close()

asyncio.run(inspect())
