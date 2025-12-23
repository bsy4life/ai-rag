import re
import pandas as pd

# === 1. 讀取 Big5 中文報表 ===
with open("data/114年02月地區營業額.TXT", "r", encoding="big5-hkscs") as f:
    lines = f.readlines()

# === 2. 移除空白/無意義區段 ===
data_lines = []
for line in lines:
    if re.match(r'^[-=_\s]*$', line): continue
    if any(x in line for x in ["資料日期", "產品類別", "貢獻比", "總合計"]): continue
    if line.strip() == "": continue
    data_lines.append(line.strip())

# === 3. 最穩定的解析方法 ===
def parse_line_flexible(line):
    match = re.match(r'^(\d{2})\s+(.*?)\s+([\d,\. %]+)$', line)
    if not match:
        return None

    index = match.group(1).strip()
    product = match.group(2).strip()
    numbers_text = match.group(3)

    # 從尾部擷取 8 個數字
    numbers = re.findall(r'[\d,\.]+', numbers_text)
    if len(numbers) != 8:
        return None

    numbers = [n.replace(",", "") for n in numbers]
    return [index, product] + numbers

# === 4. 處理所有資料行 ===
rows = []
for line in data_lines:
    parsed = parse_line_flexible(line)
    if parsed and len(parsed) == 10:
        rows.append(parsed)
    else:
        print(f"⚠️ 無法解析：{line}")

# === 5. 建立 DataFrame ===
columns = ["項次", "產品類別", "台南", "高雄", "台北", "台中", "湖內", "貿易課", "總合計", "貢獻比"]
df = pd.DataFrame(rows, columns=columns)

# 數值欄轉換
for col in df.columns[2:-1]:
    df[col] = df[col].astype(float)
df["貢獻比"] = df["貢獻比"].astype(float)

# === 6. 儲存乾淨 CSV ===
df.to_csv("data/clear/cleaned_營業額.csv", index=False, encoding="utf-8-sig")
print("✅ 已輸出 cleaned_營業額.csv")

# === 7. 語意化段落 ===
paragraphs = []
for _, row in df.iterrows():
    text = (
        f"114 年 2 月，產品類別 {row['產品類別']} 的銷售狀況如下："
        f"台南 {int(row['台南'])} 元，高雄 {int(row['高雄'])} 元，台北 {int(row['台北'])} 元，"
        f"台中 {int(row['台中'])} 元，湖內 {int(row['湖內'])} 元，貿易課 {int(row['貿易課'])} 元。"
        f"總合計為 {int(row['總合計'])} 元，貢獻比為 {row['貢獻比']}%。"
    )
    paragraphs.append(text)

with open("data/clear/vector_input.txt", "w", encoding="utf-8") as f:
    for p in paragraphs:
        f.write(p + "\n\n")

print("✅ 已輸出語意段落檔案 vector_input.txt")
