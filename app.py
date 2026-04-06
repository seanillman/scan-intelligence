"""
scan-intelligence / app.py
SCAN platform backend — search and scan endpoints
Deploy to Render as a Python web service
"""

import os
import json
import base64
import logging
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

# ── LOGGING ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s · %(levelname)s · %(message)s')
log = logging.getLogger(__name__)

# ── APP ──
app = Flask(__name__)
CORS(app, origins=["*"], supports_credentials=False)  # Allow requests from browser

# ── CLIENT ──
anthropic_client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

# ── EBAY CONFIG ──
EBAY_APP_ID = os.environ.get('EBAY_APP_ID', '')  # Optional — enhances live pricing

# ── HELPERS ──

def extract_json(text):
    """Extract JSON object from Claude response — handles preamble/postamble."""
    text = text.replace('```json', '').replace('```', '').strip()
    s = text.find('{')
    e = text.rfind('}')
    if s != -1 and e != -1:
        return json.loads(text[s:e+1])
    return json.loads(text)


def get_ebay_comps(query, max_results=5):
    """
    Pull recent eBay sold listings for live price comps.
    Returns list of {title, price, date} or empty list if unavailable.
    """
    if not EBAY_APP_ID:
        return []
    try:
        url = "https://svcs.ebay.com/services/search/FindingService/v1"
        params = {
            'OPERATION-NAME': 'findCompletedItems',
            'SERVICE-VERSION': '1.0.0',
            'SECURITY-APPNAME': EBAY_APP_ID,
            'RESPONSE-DATA-FORMAT': 'JSON',
            'keywords': query,
            'itemFilter(0).name': 'SoldItemsOnly',
            'itemFilter(0).value': 'true',
            'sortOrder': 'EndTimeSoonest',
            'paginationInput.entriesPerPage': max_results,
        }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        items = data.get('findCompletedItemsResponse', [{}])[0].get('searchResult', [{}])[0].get('item', [])
        return [{'title': i['title'][0], 'price': i['sellingStatus'][0]['currentPrice'][0]['__value__'], 'date': i['listingInfo'][0]['endTime'][0][:10]} for i in items[:max_results]]
    except Exception as ex:
        log.warning(f"eBay comps failed: {ex}")
        return []


# ── SEARCH ENDPOINT ──

@app.route('/search', methods=['POST', 'OPTIONS'])
def scan_search():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json()
        query = (data or {}).get('query', '').strip()
        if not query:
            return jsonify({'error': 'No query provided'}), 400

        log.info(f"Search: {query}")

        # Pull live eBay comps if available
        comps = get_ebay_comps(query)
        comps_context = ''
        if comps:
            comps_context = f"\n\nRecent eBay sold listings for context:\n" + '\n'.join([f"- {c['title']}: ${c['price']} ({c['date']})" for c in comps])

        system = """You are SCAN Intelligence — the world's most knowledgeable collectibles search engine.
You have complete knowledge of every sports card, memorabilia piece, badge, negative, autograph, and collectible ever made.
You know every market, every price history, every PSA population report, every auction result.
You always respond with pure JSON only. No markdown. No preamble. Start with { end with }.
Generate 4-5 realistic results matching the search query with accurate market prices."""

        user_msg = f"""Search query: "{query}"{comps_context}

Return this exact JSON structure:
{{
  "intelligenceSummary": "2 sentence market intelligence — what the smart move is right now in this category",
  "results": [
    {{
      "id": 1,
      "name": "Full item name",
      "sub": "Year · Set · Condition",
      "thread": "Jordan",
      "price": "$XXX",
      "platform": "eBay",
      "verdict": "BUY",
      "verdictReason": "One sentence — why at this price",
      "intelligence": "One sentence — the deeper insight most buyers miss",
      "emoji": "🏀"
    }}
  ],
  "gapInsight": "The angle they haven't considered — e.g. if searching Jordan cards, mention Jordan negatives trade at $30 vs $500K cards. Always find the gap. Never null."
}}

Sort results by deal quality — best deals first. Mix BUY, NEGOTIATE, WALK verdicts. Price accurately."""

        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user_msg}]
        )

        result = extract_json(response.content[0].text)
        return jsonify(result)

    except Exception as ex:
        log.error(f"Search error: {ex}")
        return jsonify({'error': str(ex)}), 500


# ── SCAN ENDPOINT ──

@app.route('/scan', methods=['POST', 'OPTIONS'])
def scan_identify():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json()
        image_b64 = (data or {}).get('image', '')
        media_type = (data or {}).get('media_type', 'image/jpeg')

        if not image_b64:
            return jsonify({'error': 'No image provided'}), 400

        log.info("Scan request received")

        system = """You are SCAN Intelligence — the world's most knowledgeable collectibles expert.
You identify sports cards, memorabilia, photographs, negatives, badges, autographs from photos.
You know every card ever printed, every PSA grade standard, every market value, every auction result.
You always respond with pure JSON only. No markdown. No preamble. Start with { end with }."""

        user_msg = """Identify this collectible and return market intelligence.

Return this exact JSON structure:
{
  "name": "Full item name",
  "sub": "Year · Set · Condition observed",
  "verdict": "BUY",
  "verdictReason": "One sentence — clear buy/negotiate/walk reason at current asking price",
  "offerPrice": "$XX",
  "marketData": [
    {"label": "Raw Value", "value": "$XX–$XX", "highlight": false},
    {"label": "PSA 9", "value": "$X,XXX", "highlight": true},
    {"label": "PSA 10", "value": "$XX,XXX", "highlight": false},
    {"label": "Last Sale", "value": "$XXX · Xd ago", "highlight": false}
  ],
  "intelligence": "2-3 sentences — the real story. What this object is. Why it matters. What most buyers miss about it.",
  "gradeLadder": [
    {"grade": "PSA 6", "value": "$180", "isCurrent": false},
    {"grade": "PSA 7", "value": "$420", "isCurrent": true},
    {"grade": "PSA 8", "value": "$800", "isCurrent": false},
    {"grade": "PSA 9", "value": "$2,200", "isCurrent": false},
    {"grade": "PSA 10", "value": "$31,000", "isCurrent": false}
  ],
  "flipCalc": {
    "cardCost": "$150",
    "gradingCost": "$75",
    "totalIn": "$225",
    "expectedGrade": "PSA 7",
    "expectedReturn": "$420",
    "netProfit": "$195",
    "roi": "+87%"
  },
  "gapAlert": "The angle they haven't considered — e.g. if this is a card, mention the original negative version. Always find the gap."
}"""

        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": user_msg}
                ]
            }]
        )

        result = extract_json(response.content[0].text)
        return jsonify(result)

    except Exception as ex:
        log.error(f"Scan error: {ex}")
        return jsonify({'error': str(ex)}), 500


# ── HEALTH ──

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'live', 'service': 'scan-intelligence'})


# ── MAIN ──

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    log.info(f"SCAN Intelligence running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

@app.route('/app')
def serve_app():
    return app.send_static_file('scan-app.html')
