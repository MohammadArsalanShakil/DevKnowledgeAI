import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from devknowledgeai.rag import ABSTAIN, PDFIndex, PDFLibrary, Passage, chunks, validate_answer


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.passages = [Passage(1, 42, 'An interface defines a contract for classes that implement it.', 0.8)]

    def response(self, source_id='S1', quote='An interface defines a contract', answer='An interface defines a contract. [PDF p.42]'):
        return json.dumps(dict(supported=True, answer=answer, evidence=[dict(source_id=source_id, quote=quote)]))

    def test_accepts_real_quote_and_page(self):
        self.assertIn('[PDF p.42]', validate_answer(self.response(), self.passages))

    def test_rejects_fabricated_quote(self):
        self.assertEqual(ABSTAIN, validate_answer(self.response(quote='An interface runs on the moon'), self.passages))

    def test_accepts_pdf_ligatures_and_line_wrapping(self):
        passages = [Passage(1, 42, 'An interface deﬁnes a\ncontract for classes.', 0.8)]
        self.assertIn('[PDF p.42]', validate_answer(self.response(quote='An interface defines a contract'), passages))

    def test_rejects_unretrieved_page(self):
        self.assertEqual(ABSTAIN, validate_answer(self.response(source_id='S99'), self.passages))

    def test_app_adds_citations_from_verified_evidence(self):
        self.assertEqual('An interface defines a contract. [PDF p.42]', validate_answer(self.response(answer='An interface defines a contract.'), self.passages))

    def test_rejects_unverified_inline_citation(self):
        self.assertEqual(ABSTAIN, validate_answer(self.response(answer='A claim. [PDF p.99]'), self.passages))

    def test_rejects_answer_without_evidence(self):
        raw = json.dumps(dict(supported=True, answer='A claim.', evidence=[]))
        self.assertEqual(ABSTAIN, validate_answer(raw, self.passages))

    def test_abstains_on_bad_json_and_unsupported(self):
        for raw in ['not JSON', '[]', '{}', '{"supported":false}']:
            self.assertEqual(ABSTAIN, validate_answer(raw, self.passages))

    def test_same_page_in_two_books_does_not_mix_evidence(self):
        passages = [Passage(1, 42, 'Git branches are separate lines of development.', 0.8, 'Git.pdf'),
                    Passage(1, 42, 'SQL tables contain rows and columns.', 0.8, 'SQL.pdf')]
        self.assertEqual(ABSTAIN, validate_answer(self.response(source_id='S1', quote='SQL tables contain rows and columns.', answer='Tables contain rows.'), passages))
        answer = validate_answer(self.response(source_id='S2', quote='SQL tables contain rows and columns.', answer='Tables contain rows.'), passages)
        self.assertEqual('Tables contain rows. [SQL.pdf p.42]', answer)

    def test_multiple_book_citations(self):
        passages = [Passage(1, 2, 'Git tracks changes to source files.', 0.8, 'Git.pdf'),
                    Passage(1, 2, 'SQL tables contain rows and columns.', 0.8, 'SQL.pdf')]
        raw = json.dumps(dict(supported=True, answer='Two topics.', evidence=[
            dict(source_id='S1', quote=passages[0].text), dict(source_id='S2', quote=passages[1].text)]))
        self.assertEqual('Two topics. [Git.pdf p.2] [SQL.pdf p.2]', validate_answer(raw, passages))

    def test_rejects_command_not_in_retrieved_book(self):
        passages = [Passage(1, 9, 'Use psql -l to list PostgreSQL databases.', 0.8, 'PostgreSQL.pdf')]
        raw = self.response(source_id='S1', quote=passages[0].text, answer='Use `SHOW DATABASES` to list databases.')
        self.assertEqual(ABSTAIN, validate_answer(raw, passages))
        raw = self.response(source_id='S1', quote=passages[0].text, answer='Use `psql -l` to list databases.')
        self.assertIn('[PostgreSQL.pdf p.9]', validate_answer(raw, passages))


class IndexTests(unittest.TestCase):
    def test_explicit_database_topics_select_correct_books(self):
        from types import SimpleNamespace
        library = PDFLibrary.__new__(PDFLibrary)
        library.indexes = [SimpleNamespace(pdf=Path(name)) for name in ['PostgreSQLNotesForProfessionals.pdf', 'MySQLNotesForProfessionals.pdf', 'MicrosoftSQLServerNotesForProfessionals.pdf']]
        with patch('devknowledgeai.rag.retrieve_from_indexes', return_value=[]) as retrieve:
            library.retrieve('PostgreSQL RETURNING')
            self.assertEqual([library.indexes[0]], retrieve.call_args.args[0])
            library.retrieve('Compare PostgreSQL and MySQL transactions')
            self.assertEqual(library.indexes[:2], retrieve.call_args.args[0])
            library.retrieve('SQL joins')
            self.assertEqual(library.indexes, retrieve.call_args.args[0])

    def test_library_reuses_unchanged_books_and_embeds_query_once(self):
        class Embeddings:
            document_calls = 0
            query_calls = 0
            def embed_documents(self, texts):
                self.document_calls += 1
                return [[1.0, 0.0] if 'Git' in text else [0.0, 1.0] for text in texts]
            def embed_query(self, question):
                self.query_calls += 1
                return [1.0, 0.0]
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / 'Git.pdf', Path(folder) / 'SQL.pdf']
            for path in paths:
                path.write_text('mock source', encoding='utf-8')
            library = PDFLibrary(paths, Path(folder) / 'indexes', 'all-minilm', 'http://localhost:11434')
            embedder = Embeddings()
            for index in library.indexes:
                index.embedder = embedder
            def pages(path):
                return ['Git branches track development.' if path.name == 'Git.pdf' else 'SQL tables store records.']
            with patch('devknowledgeai.rag.read_pages', side_effect=pages):
                library.build()
                self.assertEqual(2, embedder.document_calls)
                library.build()
                self.assertEqual(2, embedder.document_calls)
            result = library.retrieve('Git branches')
            self.assertEqual('Git.pdf', result[0].source)
            self.assertEqual(1, embedder.query_calls)
            # Changing only SQL leaves Git's saved embeddings intact.
            paths[1].write_text('changed mock source', encoding='utf-8')
            changed = PDFLibrary(paths, Path(folder) / 'indexes', 'all-minilm', 'http://localhost:11434')
            for index in changed.indexes:
                index.embedder = embedder
            with patch('devknowledgeai.rag.read_pages', side_effect=pages):
                changed.build()
            self.assertEqual(3, embedder.document_calls)

    def test_resume_after_failed_embedding_batch(self):
        class Embeddings:
            calls = 0
            def embed_documents(self, texts):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError('simulated interruption')
                return [[1.0, 0.0] for _ in texts]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.txt'
            source.write_text('mock source', encoding='utf-8')
            index = PDFIndex(source, Path(folder) / 'index.sqlite3', 'all-minilm', 'http://localhost:11434')
            index.embedder = Embeddings()
            with patch('devknowledgeai.rag.read_pages', return_value=['An interface defines a contract.'] * 40):
                with self.assertRaises(RuntimeError):
                    index.build()
                with closing(sqlite3.connect(index.path)) as db:
                    self.assertEqual(32, db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0])
                index.build()
            with closing(sqlite3.connect(index.path)) as db:
                self.assertEqual(40, db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0])
                self.assertEqual('1', dict(db.execute('SELECT * FROM metadata'))['complete'])
            # Unrelated query, low semantic similarity, and no keyword matches.
            index.embedder.embed_query = lambda _: [0.0, 1.0]
            self.assertEqual([], index.retrieve('banana spaceship'))
            index.embedder.embed_query = lambda _: [1.0, 0.0]
            self.assertTrue(index.retrieve('interface " contract OR NOT'))
            index.signature = 'modified source'
            index._rows = None
            with self.assertRaises(ValueError):
                index.retrieve('interface')

    def test_chunks_keep_text_boundaries_and_overlap(self):
        text = ('Interfaces define contracts.\n' * 50).strip()
        parts = list(chunks(text))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(0 < len(p) <= 650 for p in parts))
        self.assertTrue(parts[-1].endswith('Interfaces define contracts.'))


if __name__ == '__main__':
    unittest.main()
