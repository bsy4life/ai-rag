import os
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data/clear")
VECTOR_DB_DIR = os.path.join(BASE_DIR, "data/chroma_db_bge_m3")
HASH_FILE = os.path.join(VECTOR_DB_DIR, "last_hash.txt")

chat_memories = {}
qa_chain = None

from langchain_community.embeddings import HuggingFaceEmbeddings
embedding = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

USE_OLLAMA = os.environ.get("USE_FREE_MODEL", "0") == "1"
if USE_OLLAMA:
    from langchain_community.llms.ollama import Ollama
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    llm = Ollama(model="llama3", base_url=OLLAMA_BASE_URL, temperature=0.2)
else:
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(temperature=0.2)

from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain

from term_mapping import term_mapping

def add_multilingual_notes(text):
    for zh, others in term_mapping.items():
        if zh in text:
            text += " (" + "/".join(others) + ")"
    return text

from transformers import pipeline

ZH2EN_PIPE, ZH2JA_PIPE, EN2ZH_PIPE, JA2ZH_PIPE = None, None, None, None
def get_pipe(src, tgt):
    global ZH2EN_PIPE, EN2ZH_PIPE, ZH2JA_PIPE, JA2ZH_PIPE
    if src == "zh" and tgt == "en":
        if not ZH2EN_PIPE:
            ZH2EN_PIPE = pipeline("translation", model="Helsinki-NLP/opus-mt-zh-en")
        return ZH2EN_PIPE
    if src == "en" and tgt == "zh":
        if not EN2ZH_PIPE:
            EN2ZH_PIPE = pipeline("translation", model="Helsinki-NLP/opus-mt-en-zh")
        return EN2ZH_PIPE
    if src == "zh" and tgt == "ja":
        if not ZH2JA_PIPE:
            ZH2JA_PIPE = pipeline("translation", model="Helsinki-NLP/opus-mt-tc-big-zh-ja")
        return ZH2JA_PIPE
    if src == "ja" and tgt == "zh":
        if not JA2ZH_PIPE:
            JA2ZH_PIPE = pipeline("translation", model="larryvrh/mt5-translation-ja_zh")
        return JA2ZH_PIPE
    return None

def auto_translate_all(query):
    queries = [query]
    def is_zh(s): return any('\u4e00' <= c <= '\u9fff' for c in s)
    def is_ja(s): return any('\u3040' <= c <= '\u30ff' for c in s)
    try:
        if is_zh(query):
            en = get_pipe("zh", "en")(query, max_length=512)[0]["translation_text"]
            ja = get_pipe("zh", "ja")(query, max_length=512)[0]["translation_text"]
            queries.extend([en, ja])
        elif is_ja(query):
            zh = get_pipe("ja", "zh")(query, max_length=512)[0]["translation_text"]
            en = get_pipe("zh", "en")(zh, max_length=512)[0]["translation_text"]
            queries.extend([zh, en])
        else:
            zh = get_pipe("en", "zh")(query, max_length=512)[0]["translation_text"]
            ja = get_pipe("zh", "ja")(zh, max_length=512)[0]["translation_text"]
            queries.extend([zh, ja])
    except Exception as e:
        print(f"[auto_translate_all] 翻譯失敗: {e}", flush=True)
    return list(set([q.strip() for q in queries if q.strip()]))

def expand_query(query):
    queries = [query]
    for zh, others in term_mapping.items():
        if zh in query:
            queries += others
        for o in others:
            if o in query:
                queries.append(zh)
                queries += [oo for oo in others if oo != o]
    queries += auto_translate_all(query)
    return list(set(queries))

def hash_dir(path):
    h = hashlib.md5()
    for dirpath, _, filenames in os.walk(path):
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "rb") as f:
                    h.update(f.read())
            except:
                continue
    return h.hexdigest()

def load_last_hash():
    if not os.path.exists(HASH_FILE):
        return None
    with open(HASH_FILE, "r") as f:
        return f.read().strip()

def save_hash(h):
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    with open(HASH_FILE, "w") as f:
        f.write(h)

from langchain_core.retrievers import BaseRetriever
from typing import Any

class MultilingualExpandingRetriever(BaseRetriever):
    vectordb: Any

    def get_relevant_documents(self, query, *, run_manager=None, **kwargs):
        all_hits = []
        expanded = expand_query(query)
        for q in expanded:
            hits = self.vectordb.similarity_search(q, k=5)
            all_hits.extend(hits)
        # 去重
        seen = set()
        final = []
        for d in all_hits:
            key = hash(d.page_content)
            if key not in seen:
                seen.add(key)
                final.append(d)
        return final

    async def aget_relevant_documents(self, query, *, run_manager=None, **kwargs):
        return self.get_relevant_documents(query)

def build_qa():
    dir_hash = hash_dir(DATA_DIR)
    last_hash = load_last_hash()
    if os.path.exists(VECTOR_DB_DIR) and last_hash == dir_hash:
        print(f"✅ 檔案未異動，直接載入 Chroma 向量庫 ({VECTOR_DB_DIR})", flush=True)
        vectordb = Chroma(persist_directory=VECTOR_DB_DIR, embedding_function=embedding)
    else:
        print(f"🔄 檔案有異動或首次啟動，重建 Chroma 向量庫 ({VECTOR_DB_DIR})", flush=True)
        loader = DirectoryLoader(DATA_DIR, loader_cls=UnstructuredFileLoader)
        documents = loader.load()
        if not documents:
            print(f"⚠️ [build_qa] 資料夾 {DATA_DIR} 沒有文件，跳過知識庫建置。", flush=True)
            return None
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        docs = splitter.split_documents(documents)
        if not docs:
            print(f"⚠️ [build_qa] 經過拆分後沒有 chunk，跳過知識庫建置。", flush=True)
            return None
        for d in docs:
            d.page_content = add_multilingual_notes(d.page_content)
        vectordb = Chroma.from_documents(
            docs,
            embedding=embedding,
            persist_directory=VECTOR_DB_DIR
        )
        vectordb.persist()
        save_hash(dir_hash)
        print(f"✅ Chroma 向量庫重建完成並已持久化 ({VECTOR_DB_DIR})", flush=True)

    retriever = MultilingualExpandingRetriever(vectordb=vectordb)
    doc_chain = create_stuff_documents_chain(
        llm=llm,
        prompt=ChatPromptTemplate.from_messages([
        ("system",
         "你是多語技術助理，根據下方文件內容回答問題。\n"
         "如果找不到完全吻合的內容，請合理推測或彙整文件中最相關的資訊作為答案；\n"
         "如完全無關線索再回「查無資料」。\n"
         "務必用中文精要回覆。\n"
         "相關文件如下：\n{context}"
        ),
        ("human", "{input}")
    ])
    )
    return create_retrieval_chain(retriever=retriever, combine_docs_chain=doc_chain)

def reload_qa_chain():
    global qa_chain
    try:
        print("📂 偵測到資料更新，準備重建知識庫…", flush=True)
        new_chain = build_qa()
        if new_chain is None:
            print("⚠️ reload_qa_chain: build_qa() 回傳 None，資料夾可能尚無文件，跳過重建。", flush=True)
            return
        qa_chain = new_chain
        chat_memories.clear()
        print("✅ 知識庫重建完成", flush=True)
    except Exception as e:
        print(f"❌ 知識庫重建失敗：{e}", flush=True)

# ----【加這個保證全部回應中文】----
def ensure_chinese(text):
    from re import split
    sentences = split('([。！？\n])', text)
    result = []
    for s in sentences:
        if any('\u3040' <= c <= '\u30ff' for c in s):  # 有日文就翻
            try:
                result.append(get_pipe("ja", "zh")(s, max_length=512)[0]["translation_text"])
            except Exception as e:
                print(f"[ensure_chinese] 日翻中失敗: {e}", flush=True)
                result.append(s)
        else:
            result.append(s)
    merged = "".join(result)
    # 全文沒中文再整段翻
    if not any('\u4e00' <= c <= '\u9fff' for c in merged):
        try:
            merged = get_pipe("en", "zh")(merged, max_length=512)[0]["translation_text"]
        except Exception as e:
            print(f"[ensure_chinese] 英翻中失敗: {e}", flush=True)
    return merged


