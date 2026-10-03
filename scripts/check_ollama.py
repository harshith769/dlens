"""DLens Week-0: does qwen3:8b fit 100% on the GPU at num_ctx 4096? How fast is qwen3:4b?

Usage (in WSL, inside any uv venv, with the Ollama server already running):
    uv pip install ollama
    uv run python check_ollama.py
"""
import subprocess

import ollama

PROMPT = "In two sentences, explain what a SQL JOIN does."

for model, ctx in [("qwen3:4b", 8192), ("qwen3:8b", 4096)]:
    # Unload everything so each test starts clean
    for m in ollama.ps().models:
        ollama.generate(model=m.model, prompt="", keep_alive=0)
    r = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        options={"num_ctx": ctx, "temperature": 0},
        think=False,
    )
    tok_s = r.eval_count / (r.eval_duration / 1e9)
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.strip()
    print(f"=== {model} @ num_ctx {ctx} ===")
    print(f"generation speed: {tok_s:.1f} tok/s ({r.eval_count} tokens)")
    print(ps)
    print()

print("Send me both blocks. Look at the PROCESSOR column: '100% GPU' is what we want.")
