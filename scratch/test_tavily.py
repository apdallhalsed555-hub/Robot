import os
import sys

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config.settings as cfg
from brain.tools.web_search_tool import search_web

print("Testing web search with Tavily key...")
print(f"Key configured: {cfg.TAVILY_API_KEY[:10]}...{cfg.TAVILY_API_KEY[-5:]}")
query = "what is the latest news about Mohamed Salah"
print(f"Searching for: '{query}'")
result = search_web(query, max_results=2)
print("=== Result ===")
print(result)
print("==============")
