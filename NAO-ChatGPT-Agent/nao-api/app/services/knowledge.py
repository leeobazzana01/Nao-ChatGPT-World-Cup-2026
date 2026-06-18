#services/knowledge.py —> simple RAG with TF-IDF cosine similarity
#loads .txt/.md files from KNOWLEDGE_DIR and retrieves relevant snippets
#zero external dependencies.

import re
import math
import pathlib
import threading
from typing import Optional
from app.utils import logger as log_module

_log = log_module.get("knowledge")

#chunking                                                          

def _split_chunks(text: str, size: int = 800) -> list[str]:
    """Splits text into chunks while respecting paragraphs."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            
            #if the paragraph alone is larger than size, split by sentences
            if len(para) > size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for sent in sentences:
                    if len(buf) + len(sent) + 1 <= size:
                        buf = (buf + " " + sent).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = sent
                if buf:
                    chunks.append(buf)
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks

#TF-IDF              

def _tokenize(text: str) -> list[str]:
    #keeps accented characters so Portuguese knowledge files tokenize correctly
    return re.findall(r"[a-záàâãéèêíïóôõöúüçñ]+", text.lower())


def _tf(tokens: list[str]) -> dict[str, float]:
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    total = len(tokens) or 1
    return {t: c / total for t, c in freq.items()}


def _cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    dot = sum(vec_a.get(t, 0) * v for t, v in vec_b.items())
    norm_a = math.sqrt(sum(v * v for v in vec_a.values())) or 1e-9
    norm_b = math.sqrt(sum(v * v for v in vec_b.values())) or 1e-9
    return dot / (norm_a * norm_b)


#knowledge base
class KnowledgeBase:
    #load() —> reads .txt/.md files from the directory and indexes them
    #search(query, top_k) —> returns the most relevant chunks
    #format_context(chunks) —> formats them for insertion into the prompt

    def __init__(self, knowledge_dir: pathlib.Path, chunk_size: int = 800) -> None:
        self._dir = knowledge_dir
        self._chunk_size = chunk_size
        self._chunks: list[str] = []
        self._chunk_tfs: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._lock = threading.Lock()
        self._loaded = False

    #loading
    def load(self) -> int:
        #loads and indexes the knowledge base, returns the number of chunks
        
        with self._lock:
            return self._load_locked()

    def reload(self) -> int:
        #reloads (useful if the files changed at runtime)

        with self._lock:
            self._chunks = []
            self._chunk_tfs = []
            self._idf = {}
            self._loaded = False
            return self._load_locked()

    def _load_locked(self) -> int:
        if self._loaded:
            return len(self._chunks)

        files = sorted(
            list(self._dir.glob("*.txt")) + list(self._dir.glob("*.md"))
        )
        if not files:
            _log.warning(f"No knowledge files in {self._dir}")
            self._loaded = True
            return 0

        raw_chunks: list[str] = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                chunks = _split_chunks(text, self._chunk_size)
                raw_chunks.extend(chunks)
                _log.info(f"  Loaded: {path.name} -> {len(chunks)} chunks")
            except Exception as exc:
                _log.error(f"Error reading {path}: {exc}")

        if not raw_chunks:
            self._loaded = True
            return 0

        #compute TF per chunk
        tfs = [_tf(_tokenize(c)) for c in raw_chunks]

        #compute global IDF
        df: dict[str, int] = {}
        N = len(raw_chunks)
        for tf in tfs:
            for term in tf:
                df[term] = df.get(term, 0) + 1
        idf = {
            term: math.log((N + 1) / (cnt + 1)) + 1
            for term, cnt in df.items()
        }

        #build TF IDF vectors
        self._chunks = raw_chunks
        self._chunk_tfs = [
            {t: v * idf.get(t, 1) for t, v in tf.items()}
            for tf in tfs
        ]
        self._idf = idf
        self._loaded = True

        _log.info(f"KnowledgeBase ready: {len(raw_chunks)} chunks from {len(files)} file(s)")
        return len(raw_chunks)

    #search
    def search(self, query: str, top_k: int = 5) -> list[tuple[float, str]]:
        #returns a list of (score, chunk) sorted by decreasing relevance.
        
        with self._lock:
            if not self._loaded:
                self._load_locked()

        if not self._chunks:
            return []

        q_tf = _tf(_tokenize(query))
        q_tfidf = {t: v * self._idf.get(t, 1) for t, v in q_tf.items()}

        scored = [
            (_cosine(q_tfidf, chunk_vec), chunk)
            for chunk_vec, chunk in zip(self._chunk_tfs, self._chunks)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(s, c) for s, c in scored[:top_k] if s > 0.01]

    def format_context(self, query: str, top_k: int = 5) -> str:
        #returns a formatted string to inject into the system prompt as RAG context
        
        results = self.search(query, top_k)
        if not results:
            return ""

        parts = ["### Relevant Knowledge\n"]
        for i, (score, chunk) in enumerate(results, 1):
            parts.append(f"[Excerpt {i} — relevance {score:.2f}]\n{chunk}\n")

        return "\n".join(parts)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def is_loaded(self) -> bool:
        return self._loaded
