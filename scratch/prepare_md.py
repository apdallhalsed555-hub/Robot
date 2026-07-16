import re
import os
import zlib
import base64
import urllib.request

MD_PATH = r"x:\Robot-main\Robot-main\Mahmoud_Contribution.md"
OUT_MD = r"x:\Robot-main\Robot-main\scratch\temp_Mahmoud_Contribution.md"

def get_kroki_url(mermaid_code):
    data = mermaid_code.encode('utf-8')
    compressed = zlib.compress(data, 9)
    b64 = base64.urlsafe_b64encode(compressed).decode('ascii')
    return f"https://kroki.io/mermaid/png/{b64}"

def prepare_markdown():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    out_lines = []
    i = 0
    in_code_block = False
    code_buffer = []
    code_lang = ""
    img_counter = 0

    while i < len(lines):
        line = lines[i]
        
        # Strip the manual Table of Contents because Pandoc generates it
        if line.startswith("## Table of Contents"):
            i += 1
            while i < len(lines):
                line_text = lines[i].strip()
                if not line_text or re.match(r"^\d+\.", line_text):
                    i += 1
                else:
                    break
            continue

        if line.startswith("```") and not in_code_block:
            code_lang = line[3:].strip()
            in_code_block = True
            code_buffer = []
            i += 1
            continue

        if line.startswith("```") and in_code_block:
            code_text = "".join(code_buffer)
            if code_lang == "mermaid":
                img_counter += 1
                url = get_kroki_url(code_text)
                img_path = f"x:\\Robot-main\\Robot-main\\scratch\\kroki_{img_counter}.png"
                
                print(f"Downloading Kroki image {img_counter}...")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                try:
                    with urllib.request.urlopen(req) as response, open(img_path, 'wb') as out_file:
                        out_file.write(response.read())
                    # Relative path for pandoc
                    out_lines.append(f"\n![Architecture Diagram](scratch/kroki_{img_counter}.png)\n")
                except Exception as e:
                    print(f"Failed to download image: {e}")
                    out_lines.append(f"```mermaid\n{code_text}```\n")
            else:
                out_lines.append(f"```{code_lang}\n{code_text}```\n")
            
            in_code_block = False
            code_buffer = []
            code_lang = ""
            i += 1
            continue

        if in_code_block:
            code_buffer.append(line)
            i += 1
            continue

        out_lines.append(line)
        i += 1

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.writelines(out_lines)
    
    print(f"Prepared markdown at {OUT_MD}")

if __name__ == "__main__":
    prepare_markdown()
