"""DLens Week-0: find the Gemini Flash-Lite model ID and make one test call.

Usage (in WSL, inside any uv venv):
    uv pip install google-genai
    read -s GEMINI_API_KEY && export GEMINI_API_KEY    # paste the dlens-eval key; it is not echoed
    uv run python check_gemini.py

The key is read from the environment and is never printed.
"""
import os
import sys

from google import genai
from google.genai import errors

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("GEMINI_API_KEY is not set. Run: read -s GEMINI_API_KEY && export GEMINI_API_KEY")

client = genai.Client(api_key=key)

# 1. List text models whose name contains "flash"
flash = []
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "flash" in m.name and "generateContent" in actions and "image" not in m.name and "tts" not in m.name:
        flash.append(m.name.removeprefix("models/"))
flash.sort()
print("Flash models with generateContent:")
for name in flash:
    print("  ", name)

lite = [n for n in flash if "lite" in n and "preview" not in n]
if not lite:
    sys.exit("No stable Flash-Lite model found; send me the list above.")
model = lite[-1]  # highest version sorts last
print(f"\nTesting model: {model}")

# 2. One tiny call
try:
    r = client.models.generate_content(model=model, contents="Reply with the single word: ok")
    u = r.usage_metadata
    print("Reply:", (r.text or "").strip())
    print("Tokens in/out:", u.prompt_token_count, u.candidates_token_count)
    print("\nRESULT: call succeeded. Now open https://aistudio.google.com/rate-limit "
          "with project dlens-eval selected and note RPM / TPM / RPD for", model)
except errors.APIError as e:
    print("API error code:", e.code)
    print("Message:", e.message)
    # 429 errors usually name the quota metric and its limit value
    print("Details:", getattr(e, "details", None))
