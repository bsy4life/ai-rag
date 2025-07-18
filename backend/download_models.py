from transformers import pipeline
#pl = pipeline("translation", model="Helsinki-NLP/opus-mt-zh-ja", token="REDACTED_HF_TOKEN")
models = [
    "Helsinki-NLP/opus-mt-zh-en",
    "Helsinki-NLP/opus-mt-en-zh",
    "larryvrh/mt5-translation-ja_zh",
    "Helsinki-NLP/opus-mt-tc-big-zh-ja"
]

for model in models:
    print(f"Downloading {model} ...")
    pl = pipeline("translation", model=model)
    print(pl("翻譯測試：", pl("這是一個自動翻譯測試。")))