import os
import hashlib

# =========== 模式判斷與 persist 目錄 ===========
USE_OLLAMA = os.environ.get("USE_FREE_MODEL", "0") == "1"  # 設1就用 Ollama
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data/clear")

if USE_OLLAMA:
    VECTOR_DB_DIR = os.path.join(BASE_DIR, "data/chroma_db_ollama")
    print("🚩 [core.py] 使用本地 Ollama Llama3，persist 於 chroma_db_ollama", flush=True)
else:
    VECTOR_DB_DIR = os.path.join(BASE_DIR, "data/chroma_db_openai")
    print("🚩 [core.py] 使用 OpenAI 付費模型，persist 於 chroma_db_openai", flush=True)

HASH_FILE = os.path.join(VECTOR_DB_DIR, "last_hash.txt")

# =========== 全域記憶體（由 app 管理） ===========
chat_memories = {}
qa_chain = None

# =========== Embedding & LLM 動態切換 ===========
if USE_OLLAMA:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.llms.ollama import Ollama
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    embedding = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    llm = Ollama(model="llama3", base_url=OLLAMA_BASE_URL)
else:
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    embedding = OpenAIEmbeddings()
    llm = ChatOpenAI(temperature=0)

from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain.chains.history_aware_retriever import create_history_aware_retriever

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
            print(f"⚠️ [build_qa] 資料夾 {DATA_DIR} 底下沒有任何文件，跳過知識庫建置。", flush=True)
            return None
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        docs = splitter.split_documents(documents)
        if not docs:
            print(f"⚠️ [build_qa] 經過拆分後沒有任何 chunk，跳過知識庫建置。", flush=True)
            return None
        vectordb = Chroma.from_documents(
            docs,
            embedding=embedding,
            persist_directory=VECTOR_DB_DIR
        )
        vectordb.persist()
        save_hash(dir_hash)
        print(f"✅ Chroma 向量庫重建完成並已持久化 ({VECTOR_DB_DIR})", flush=True)
    retriever = create_history_aware_retriever(
        llm=llm,
        retriever=vectordb.as_retriever(),
        prompt=ChatPromptTemplate.from_messages([
            ("system", "根據對話歷史與當前問題，請用口語化的方式重新表述：\n{chat_history}"),
            ("human", "{input}")
        ])
    )
    doc_chain = create_stuff_documents_chain(
        llm=llm,
        prompt=ChatPromptTemplate.from_messages([
            ("system", "你是內部AI助理，根據文件回答問題，請將內容精簡後回覆：\n{context}"),
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
