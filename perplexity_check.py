import os, json, requests

api_key = os.getenv("PERPLEXITY_API_KEY")
payload = {"query": "sftw", "max_results": 10, "include_answer": True}
resp = requests.post(
    "https://api.perplexity.ai/search",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json=payload,
    timeout=10,
)

if resp.ok:
    data = resp.json()
    results = data.get("results", [])
    print(f"status {resp.status_code}, {len(results)} results")
    for idx, item in enumerate(results[:10], 1):
        title = item.get("title") or item.get("url")
        print(f"{idx}. {title}")
else:
    print(resp.status_code, resp.text)
