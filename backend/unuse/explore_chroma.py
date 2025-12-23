from langchain_community.vectorstores import Chroma

VECTOR_DB_DIR = "data/chroma_db_bge_m3"
keyword = "6500"   # 修改你想查的關鍵字

vectordb = Chroma(persist_directory=VECTOR_DB_DIR)
all_docs = vectordb.get()['documents']
all_metas = vectordb.get()['metadatas']

found = False
for i, doc in enumerate(all_docs):
    text = doc[0] if isinstance(doc, list) else doc
    if keyword in text:
        meta = all_metas[i][0] if isinstance(all_metas[i], list) else all_metas[i]
        print(f"\n--- 來源: {meta.get('source', '未知')}")
        print(text[:300].replace('\n', ''))
        found = True

if not found:
    print(f"❌ 找不到包含「{keyword}」的片段")
