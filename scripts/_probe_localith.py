import json, urllib.request, re, sys
sys.stdout.reconfigure(encoding="utf-8")

# Probe the n8n community node source for endpoint truth
url = "https://raw.githubusercontent.com/localithai/n8n-nodes-localith/main/nodes/Localith/Localith.node.ts"
with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=20) as r:
    src = r.read().decode("utf-8", errors="replace")

print("=== baseURL-style assignments ===")
for m in re.finditer(r"(?:baseURL|baseUrl|apiUrl|api_url|API_URL|API_BASE)\s*[:=]\s*['\"`]([^'\"`]+)['\"`]", src):
    print(" ", m.group(1))

print("\n=== full URLs in backticks ===")
for m in re.finditer(r"`(https?://[^`]+)`", src):
    print(" ", m.group(1)[:160])

print("\n=== full URLs in single/double quotes ===")
for m in re.finditer(r"['\"](https?://[^'\"]+)['\"]", src):
    print(" ", m.group(1)[:160])

print("\n=== endpoint-construction patterns ===")
for m in re.finditer(r"url\s*[:=]\s*['\"`](/[^'\"`]+)['\"`]", src):
    print(" ", m.group(1))

print("\n=== resource names (heuristic) ===")
for word in ("reviews", "locations", "listings", "metrics", "posts", "account", "me"):
    cnt = len(re.findall(rf"\b{word}\b", src, re.IGNORECASE))
    print(f"  {word}: {cnt}")
