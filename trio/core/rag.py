"""RAG (Retrieval-Augmented Generation) — lightweight document store with search.

Supports:
    - Text file ingestion (.txt, .md, .py, .json, etc.)
    - PDF ingestion (if PyPDF2 installed)
    - Chunk-based storage with overlap
    - BM25-style keyword search (no external vector DB needed)
    - Optional embedding-based search (if provider supports it)
    - Context injection into LLM prompts
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import hashlib
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from trio.core.config import get_trio_dir

logger = logging.getLogger(__name__)


class Document:
    """A chunk of text from an ingested document."""

    def __init__(self, content: str, metadata: dict[str, Any] | None = None):
        self.content = content
        self.metadata = metadata or {}
        self.doc_id = hashlib.sha256(content[:200].encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {"content": self.content, "metadata": self.metadata, "doc_id": self.doc_id}

    @classmethod
    def from_dict(cls, data: dict) -> "Document":
        doc = cls(content=data["content"], metadata=data.get("metadata", {}))
        doc.doc_id = data.get("doc_id", doc.doc_id)
        return doc


class RAGStore:
    """Lightweight RAG document store with BM25 keyword search.

    No vector database needed — uses term frequency scoring
    for fast, dependency-free retrieval.

    Storage: ~/.trio/rag/<collection>.jsonl
    """

    def __init__(self, collection: str = "default"):
        self._dir = get_trio_dir() / "rag"
        self._dir.mkdir(parents=True, exist_ok=True)
        self.collection = collection
        self._store_path = self._dir / f"{collection}.jsonl"
        self._documents: list[Document] = []
        self._idf_cache: dict[str, float] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        self._documents.clear()
        if self._store_path.exists():
            with open(self._store_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._documents.append(Document.from_dict(json.loads(line)))
                        except json.JSONDecodeError:
                            continue
        self._rebuild_idf()

    def _save_document(self, doc: Document) -> None:
        with open(self._store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")

    def _save_all(self) -> None:
        with open(self._store_path, "w", encoding="utf-8") as f:
            for doc in self._documents:
                f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")

    # ── Ingestion ──────────────────────────────────────

    def ingest_text(
        self,
        text: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Ingest text by splitting into overlapping chunks.

        Returns number of chunks created.
        """
        self._ensure_loaded()
        chunks = self._chunk_text(text, chunk_size, chunk_overlap)
        count = 0
        for chunk in chunks:
            doc = Document(content=chunk, metadata=metadata or {})
            self._documents.append(doc)
            self._save_document(doc)
            count += 1
        self._rebuild_idf()
        return count

    def ingest_file(self, file_path: str | Path, metadata: dict[str, Any] | None = None) -> int:
        """Ingest a file (text, markdown, code, or PDF)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        meta = {"source": str(path), "filename": path.name, **(metadata or {})}

        if path.suffix.lower() == ".pdf":
            text = self._read_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")

        return self.ingest_text(text, metadata=meta)

    def ingest_directory(
        self,
        dir_path: str | Path,
        extensions: list[str] | None = None,
        recursive: bool = True,
    ) -> int:
        """Ingest all matching files in a directory."""
        path = Path(dir_path)
        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        extensions = extensions or [".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml"]
        total = 0
        glob_pattern = "**/*" if recursive else "*"

        for file_path in path.glob(glob_pattern):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                try:
                    total += self.ingest_file(file_path)
                except Exception as e:
                    logger.warning(f"Failed to ingest {file_path}: {e}")
        return total

    # ── Search ─────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[tuple[Document, float]]:
        """BM25-style keyword search. Returns (document, score) pairs."""
        self._ensure_loaded()
        if not self._documents:
            return []

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        scores: list[tuple[Document, float]] = []
        avg_dl = sum(len(self._tokenize(d.content)) for d in self._documents) / len(self._documents)

        k1, b = 1.5, 0.75  # BM25 parameters

        for doc in self._documents:
            doc_terms = self._tokenize(doc.content)
            doc_len = len(doc_terms)
            tf_map = Counter(doc_terms)

            score = 0.0
            for term in query_terms:
                tf = tf_map.get(term, 0)
                idf = self._idf_cache.get(term, 0.0)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * doc_len / avg_dl)
                score += idf * (numerator / denominator) if denominator > 0 else 0.0

            if score > 0:
                scores.append((doc, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def search_text(self, query: str, top_k: int = 5) -> list[str]:
        """Search and return just the text content."""
        results = self.search(query, top_k)
        return [doc.content for doc, _ in results]

    def build_context(self, query: str, top_k: int = 5, max_chars: int = 3000) -> str:
        """Build RAG context string for injection into LLM prompt."""
        results = self.search(query, top_k)
        if not results:
            return ""

        context_parts = []
        total_chars = 0
        for doc, score in results:
            if total_chars + len(doc.content) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 100:
                    context_parts.append(doc.content[:remaining] + "...")
                break
            context_parts.append(doc.content)
            total_chars += len(doc.content)

        return (
            "--- Relevant Context (from knowledge base) ---\n"
            + "\n\n".join(context_parts)
            + "\n--- End Context ---\n"
        )

    # ── Management ─────────────────────────────────────

    def clear(self) -> None:
        """Remove all documents from this collection."""
        self._documents.clear()
        self._idf_cache.clear()
        if self._store_path.exists():
            self._store_path.unlink()

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._documents)

    def list_collections(self) -> list[str]:
        return [p.stem for p in self._dir.glob("*.jsonl")]

    # ── Internal helpers ───────────────────────────────

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split text into overlapping chunks by word count."""
        words = text.split()
        chunks = []
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization: lowercase, split on non-alphanumeric."""
        return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 1]

    def _rebuild_idf(self) -> None:
        """Rebuild IDF (Inverse Document Frequency) cache."""
        self._idf_cache.clear()
        n = len(self._documents)
        if n == 0:
            return

        doc_freq: Counter[str] = Counter()
        for doc in self._documents:
            unique_terms = set(self._tokenize(doc.content))
            for term in unique_terms:
                doc_freq[term] += 1

        for term, df in doc_freq.items():
            self._idf_cache[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)

    def _read_pdf(self, path: Path) -> str:
        """Extract text from PDF."""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
        except ImportError:
            raise ImportError("PyPDF2 is required for PDF ingestion. Install with: pip install PyPDF2")
