import base64
import urllib.request

def test_mermaid():
    code = """graph LR
    A["Microphone"] --> B["STT Engine"]
"""
    b64 = base64.urlsafe_b64encode(code.encode('utf-8')).decode('utf-8')
    url = f"https://mermaid.ink/img/{b64}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response, open("test_mermaid.png", 'wb') as out_file:
            data = response.read()
            out_file.write(data)
        print("Success!")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_mermaid()
