import urllib.request
def resolve(url):
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.url
    except Exception as e:
        if hasattr(e, 'url'):
            return e.url
        return url

print(resolve("https://www.facebook.com/share/v/16G9UBiVjDV/?mibextid=wwXIfr"))
