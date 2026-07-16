import zlib
import base64
import urllib.request

def test_kroki():
    code = """graph LR
    A["Microphone"] --> B["STT Engine"]
"""
    data = code.encode('utf-8')
    compressed = zlib.compress(data, 9)
    b64 = base64.urlsafe_b64encode(compressed).decode('ascii')
    url = f"https://kroki.io/mermaid/png/{b64}"
    print(url)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open("x:\\Robot-main\\Robot-main\\scratch\\test_kroki.png", 'wb') as out:
            out.write(response.read())
        print("Success! Downloaded to scratch/test_kroki.png")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_kroki()
