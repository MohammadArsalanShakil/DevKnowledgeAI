"""PDF text extraction, resumable local embeddings, and hybrid retrieval."""
from array import array
from contextlib import closing
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from langchain_ollama import OllamaEmbeddings
import pymupdf

ABSTAIN = "I couldn't find enough information in the books to answer that."
STOP = set("a an the what how why when where who is are was were do does can could would should explain tell me about in on of to for and or with please c sharp".split())
STOP.update("git sql server postgresql postgres mysql mssql csharp entity framework clause work works use using".split())


@dataclass
class Passage:
    id: int
    page: int
    text: str
    similarity: float
    source: str = ""


def chunks(text, size=650, overlap=100):
    """Preserve code newlines and page boundaries, with a short overlap."""
    text = text.replace("\x00", "")
    text = re.sub(r"GoalKicker\.com.*?Notes for Professionals.*?(?=\n|$)", "", text)
    text = text.strip()
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if boundary > start:
                end = boundary
        part = text[start:end].strip()
        if part:
            yield part
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def normalized(vector):
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError("Embedding model returned an invalid vector.")
    return array("f", (x / norm for x in vector))


def source_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_pages(path):
    with pymupdf.open(path) as reader:
        if reader.needs_pass and not reader.authenticate(""):
            raise ValueError("Encrypted PDF requires a password; use an unlocked copy.")
        return [page.get_text("text", sort=True) for page in reader]


class PDFIndex:
    def __init__(self, pdf, index_path, embedding_model, base_url):
        self.pdf = Path(pdf).resolve()
        self.path = Path(index_path)
        if not self.pdf.is_file():
            raise FileNotFoundError(f"PDF not found: {self.pdf}. Set RAG_PDF_DIR or use --pdf.")
        self.model = embedding_model
        self.embedder = OllamaEmbeddings(model=embedding_model, base_url=base_url,
                                         num_ctx=512, num_thread=4, client_kwargs={"timeout": 120})
        self.signature = json.dumps({"sha256": source_hash(self.pdf), "model": self.model,
                                     "chunker": 2, "source": str(self.pdf)})
        self._rows = None

    def build(self, rebuild=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, page INTEGER, text TEXT, vector BLOB)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text)")
            old = dict(db.execute("SELECT key, value FROM metadata"))
            if not rebuild and old.get("signature") == self.signature and old.get("complete") == "1":
                print(f"Using saved PDF index ({old['chunks']} passages, {old['pages']} pages).", flush=True)
                return
            if rebuild or old.get("signature") != self.signature:
                db.execute("DELETE FROM chunks")
                db.execute("DELETE FROM search")
                db.execute("DELETE FROM metadata")
                db.execute("INSERT INTO metadata VALUES ('signature', ?)", (self.signature,))
                db.commit()
            print("Reading PDF text...", flush=True)
            pages = read_pages(self.pdf)
            documents = []
            empty = 0
            for number, text in enumerate(pages, start=1):
                if not text.strip():
                    empty += 1
                # Dense dotted lines indicate a contents page, not substantive evidence.
                if text.count("....") > 8:
                    continue
                documents.extend((number, part) for part in chunks(text))
                if number % 100 == 0:
                    print(f"Read {number}/{len(pages)} PDF pages", flush=True)
            if not documents:
                raise ValueError("No extractable PDF text. Scanned PDFs need OCR before indexing.")
            done = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            print(f"Indexing {len(pages)} PDF pages into {len(documents)} passages; {done} already saved.", flush=True)
            if empty:
                print(f"Note: {empty} pages contain no extractable text (no OCR is performed).", flush=True)
            for start in range(done, len(documents), 32):
                batch = documents[start:start + 32]
                vectors = self.embedder.embed_documents([text for _, text in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Embedding batch was incomplete. Rerun indexing to resume.")
                for offset, ((page, text), vector) in enumerate(zip(batch, vectors)):
                    rowid = start + offset + 1
                    db.execute("INSERT INTO chunks VALUES (?, ?, ?, ?)", (rowid, page, text, normalized(vector).tobytes()))
                    db.execute("INSERT INTO search(rowid, text) VALUES (?, ?)", (rowid, text))
                db.commit()
                if start == done or (start // 32) % 5 == 0 or start + 32 >= len(documents):
                    print(f"Indexed {min(start + 32, len(documents))}/{len(documents)} passages", flush=True)
            for key, value in {"complete": "1", "pages": str(len(pages)), "chunks": str(len(documents))}.items():
                db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, value))
            db.commit()
        self._rows = None

    def load_rows(self):
        if self._rows is None:
            with closing(sqlite3.connect(self.path)) as db:
                metadata = dict(db.execute("SELECT key, value FROM metadata"))
                if metadata.get("complete") != "1" or metadata.get("signature") != self.signature:
                    raise ValueError("PDF index is incomplete or stale. Run --index first.")
                self._rows = []
                for rowid, page, text, blob in db.execute("SELECT id, page, text, vector FROM chunks ORDER BY id"):
                    vector = array("f")
                    vector.frombytes(blob)
                    self._rows.append((rowid, page, text, vector))
        return self._rows

    def retrieve(self, question, count=4):
        return retrieve_from_indexes([self], question, count)


class PDFLibrary:
    """One resumable index per book; retrieval ranks all selected books together."""
    def __init__(self, pdfs, index_directory, embedding_model, base_url):
        pdfs = sorted({Path(p).resolve() for p in pdfs})
        if not pdfs:
            raise ValueError("No PDF books found. Add PDFs to data/documents or use --pdf.")
        if len({p.name.casefold() for p in pdfs}) != len(pdfs):
            raise ValueError("Book filenames must be unique so citations are unambiguous.")
        self.indexes = [PDFIndex(p, Path(index_directory) / (p.name + '.sqlite3'), embedding_model, base_url) for p in pdfs]

    def build(self, rebuild=False):
        for index in self.indexes:
            print(f"Book: {index.pdf.name}", flush=True)
            # Reuse the original single-book index when its source fingerprint matches.
            legacy = index.path.parent.parent / 'index.sqlite3'
            if not rebuild and not index.path.exists() and legacy.is_file():
                index.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(legacy)) as old:
                    metadata = dict(old.execute('SELECT key, value FROM metadata'))
                    if metadata.get('signature') == index.signature and metadata.get('complete') == '1':
                        with closing(sqlite3.connect(index.path)) as target:
                            old.backup(target)
            index.build(rebuild=rebuild)

    def retrieve(self, question, count=4):
        topics = [
            (r'\bentity\s*framework\b', 'entityframework'),
            (r'\bgit\b', 'git'),
            (r'\bpostgres(?:ql)?\b', 'postgresql'),
            (r'\bmysql\b', 'mysql'),
            (r'\bsql\s+server\b|\bmssql\b|\bt-sql\b', 'microsoftsqlserver'),
            (r'\bc\s*#|\bcsharp\b', 'csharp'),
        ]
        named = [prefix for pattern, prefix in topics if re.search(pattern, question, re.IGNORECASE)]
        selected = [index for index in self.indexes if any(index.pdf.stem.casefold().startswith(prefix) for prefix in named)]
        return retrieve_from_indexes(selected or self.indexes, question, count)


def retrieve_from_indexes(indexes, question, count=4):
        query = normalized(indexes[0].embedder.embed_query(question))
        scores = {}
        lookup = {}
        for number, index in enumerate(indexes):
            for rowid, page, text, vector in index.load_rows():
                if len(vector) != len(query):
                    raise ValueError("Embedding dimensions changed. Rebuild with --index --rebuild.")
                key = (number, rowid)
                scores[key] = sum(a * b for a, b in zip(query, vector))
                lookup[key] = (rowid, page, text, index.pdf.name)
        semantic = heapq.nlargest(24, scores, key=scores.get)
        terms = list(dict.fromkeys(t.lower() for t in re.findall(r"[A-Za-z0-9_]+", question)
                                   if t.lower() not in STOP or t in {'WHERE', 'AND', 'OR', 'ON', 'IN', 'IS', 'USE'}))[:16]
        keyword = []
        if terms:
            expression = " OR ".join('"' + term + '"' for term in terms)
            matches = []
            for number, index in enumerate(indexes):
                with closing(sqlite3.connect(index.path)) as db:
                    matches.extend((score, (number, rowid)) for rowid, score in db.execute("SELECT rowid, bm25(search) FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT 24", (expression,)))
            keyword = [key for score, key in sorted(matches)[:24]]
        if not semantic or (scores[semantic[0]] < 0.28 and not keyword):
            return []
        ranks = {}
        for ranking, weight in ((semantic, 1.0), (keyword, 1.4)):
            for rank, rowid in enumerate(ranking, start=1):
                ranks[rowid] = ranks.get(rowid, 0) + weight / (40 + rank)
        results = []
        per_page = {}
        for rowid in sorted(ranks, key=ranks.get, reverse=True):
            passage_id, page, text, source = lookup[rowid]
            if per_page.get((source, page), 0) >= 2:
                continue
            results.append(Passage(passage_id, page, text, scores[rowid], source))
            per_page[(source, page)] = per_page.get((source, page), 0) + 1
            if len(results) == count:
                break
        return results


def validate_answer(raw, passages):
    """Resolve evidence IDs to exact book/page pairs and verify quoted text."""
    try:
        result = json.loads(raw)
        if result.get("supported") is not True:
            return ABSTAIN
        answer = result["answer"].strip()
        if not answer:
            return ABSTAIN
        evidence = result["evidence"]
        source_text = " ".join(" ".join(unicodedata.normalize("NFKC", p.text).split()) for p in passages)
        code_examples = re.findall(r'(?<!`)`([^`]+)`(?!`)', answer)
        code_examples += re.findall(r'```(?:\w+)?\s*\n(.*?)```', answer, flags=re.DOTALL)
        for code in code_examples:
            if " ".join(unicodedata.normalize("NFKC", code).split()) not in source_text:
                return ABSTAIN
        verified = set()
        for item in evidence:
            source_id, quote = item["source_id"], item["quote"]
            if not isinstance(source_id, str) or not re.fullmatch(r'S[1-9][0-9]*', source_id):
                return ABSTAIN
            position = int(source_id[1:]) - 1
            if position >= len(passages) or not isinstance(quote, str) or len(quote.strip()) < 12:
                return ABSTAIN
            passage = passages[position]
            canonical_quote = " ".join(unicodedata.normalize("NFKC", quote).split())
            if canonical_quote not in " ".join(unicodedata.normalize("NFKC", passage.text).split()):
                return ABSTAIN
            verified.add(f"[{passage.source or 'PDF'} p.{passage.page}]")
        cited = set(re.findall(r"\[(?:PDF|[^\[\]]+\.pdf) p\.\d+\]", answer))
        if not verified or not cited.issubset(verified):
            return ABSTAIN
        if not cited:
            answer += " " + " ".join(sorted(verified))
        return answer
    except (ValueError, KeyError, TypeError, AttributeError):
        return ABSTAIN
