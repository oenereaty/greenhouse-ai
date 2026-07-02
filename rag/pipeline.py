"""RAG 파이프라인 - 농업 지식베이스 인덱싱 및 검색"""
import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma


KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"


def load_documents() -> list:
    docs = []
    for path in KNOWLEDGE_BASE_DIR.rglob("*.md"):
        loader = TextLoader(str(path), encoding="utf-8")
        docs.extend(loader.load())
    for path in KNOWLEDGE_BASE_DIR.rglob("*.pdf"):
        loader = PyPDFLoader(str(path))
        docs.extend(loader.load())
    print(f"문서 {len(docs)}개 로드 완료")
    return docs


def build_vectorstore() -> Chroma:
    docs = load_documents()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)
    print(f"청크 {len(chunks)}개 생성")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = Chroma.from_documents(
        chunks,
        embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    print(f"벡터 DB 저장 완료: {CHROMA_DIR}")
    return vectorstore


def load_vectorstore() -> Chroma:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )


def retrieve(query: str, k: int = 4) -> list[str]:
    vs = load_vectorstore()
    docs = vs.similarity_search(query, k=k)
    return [d.page_content for d in docs]


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    build_vectorstore()
    results = retrieve("토마토 착과 실패 온도 조건")
    for r in results:
        print("---")
        print(r)
