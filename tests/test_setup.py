from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import sys
import subprocess
import os
import shutil

from langchain_core.messages import AIMessage
import devknowledgeai.__main__ as app
from devknowledgeai.rag import Passage

spec = importlib.util.spec_from_file_location('project_setup', Path(__file__).resolve().parents[1] / 'setup.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class SetupTests(unittest.TestCase):
    def test_grounded_answer_recovers_after_invalid_evidence(self):
        passages = [Passage(1, 592, 'Threads can simultaneously share data.', 0.8, 'CSharp.pdf')]
        valid = json.dumps({'supported': True, 'answer': 'Threads can share data.', 'evidence': [{'source_id': 'S1', 'quote': passages[0].text}]})
        model = Mock()
        model.invoke.side_effect = [AIMessage(content='{"supported":false}'), AIMessage(content=valid)]
        self.assertIn('[CSharp.pdf p.592]', app.grounded_answer(model, 'Threading in C#', passages))
        self.assertEqual(2, model.invoke.call_count)

    def test_grounded_answer_distinguishes_unverified_answer_from_missing_sources(self):
        passages = [Passage(1, 592, 'Threads can simultaneously share data.', 0.8, 'CSharp.pdf')]
        model = Mock()
        model.invoke.return_value = AIMessage(content='{"supported":false}')
        self.assertEqual(app.UNVERIFIED, app.grounded_answer(model, 'Threading in C#', passages))
        self.assertEqual(2, model.invoke.call_count)

    def test_environment_uses_defaults_when_template_is_missing(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bootstrap, 'ROOT', Path(folder)):
            bootstrap.ensure_environment()
            self.assertEqual(bootstrap.DEFAULT_ENV, (Path(folder) / '.env').read_text())

    def test_environment_preserves_existing_user_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bootstrap, 'ROOT', Path(folder)):
            env = Path(folder) / '.env'
            env.write_text('OLLAMA_MODEL=custom-model\n')
            bootstrap.ensure_environment()
            self.assertEqual('OLLAMA_MODEL=custom-model\n', env.read_text())

    def test_environment_repairs_empty_file_from_failed_setup(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bootstrap, 'ROOT', Path(folder)):
            env = Path(folder) / '.env'
            env.touch()
            bootstrap.ensure_environment()
            self.assertEqual(bootstrap.DEFAULT_ENV, env.read_text())

    def test_ollama_unix_installers_use_official_script(self):
        for platform in ('linux', 'darwin'):
            with self.subTest(platform=platform), patch.object(bootstrap.urllib.request, 'urlopen', return_value=io.BytesIO(b'official installer')), patch.object(bootstrap, 'run') as run:
                bootstrap.install_ollama(platform)
                bootstrap.urllib.request.urlopen.assert_called_once_with('https://ollama.com/install.sh', timeout=60)
                run.assert_called_once_with(['sh'], input=b'official installer')

    def test_ollama_windows_installer_uses_powershell(self):
        with patch.object(bootstrap.shutil, 'which', return_value='powershell'), patch.object(bootstrap, 'run') as run:
            bootstrap.install_ollama('win32')
            self.assertEqual('powershell', run.call_args.args[0][0])
            self.assertEqual('irm https://ollama.com/install.ps1 | iex', run.call_args.args[0][-1])

    def test_explicit_python_precedes_other_candidates(self):
        result = subprocess.CompletedProcess([], 0, stdout='/chosen/python\nTrue\n')
        with patch.dict(os.environ, {'DEVKNOWLEDGEAI_PYTHON': '/chosen/python'}), patch.object(bootstrap.subprocess, 'run', return_value=result) as run:
            self.assertEqual('/chosen/python', bootstrap.choose_python())
            self.assertEqual('/chosen/python', run.call_args.args[0][0])

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Requires native macOS/Linux Bash')
    def test_shell_bootstrap_passes_paths_and_options_without_reinterpreting(self):
        with tempfile.TemporaryDirectory(prefix='project with spaces ') as folder:
            root = Path(folder)
            shutil.copy2(bootstrap.ROOT / 'install.sh', root / 'install.sh')
            (root / 'setup.py').write_text('import json,sys; print(json.dumps(sys.argv[1:]))', encoding='utf-8')
            books = str(root / 'books with spaces; literal')
            env = dict(os.environ, DEVKNOWLEDGEAI_PYTHON=sys.executable)
            result = subprocess.run(['bash', str(root / 'install.sh'), '--skip-models', '--books-dir', books], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(['--skip-models', '--books-dir', books], json.loads(result.stdout))

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Requires native macOS/Linux Bash')
    def test_shell_bootstrap_rejects_unsafe_repository_before_setup(self):
        result = subprocess.run(['bash', str(bootstrap.ROOT / 'install.sh'), '--repository-url', 'https://github.com/owner/repo?token=secret'], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('without credentials or query parameters', result.stderr)

    def test_manifest_contains_unique_official_books(self):
        books = json.loads((bootstrap.ROOT / 'books.json').read_text(encoding='utf-8'))
        self.assertEqual(7, len(books))
        self.assertEqual(7, len({b['filename'] for b in books}))
        self.assertTrue(all(b['url'].startswith('https://goalkicker.com/') for b in books))

    def test_copy_books_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'
            source = Path(folder) / 'input'
            source.mkdir()
            (source / 'Book.PDF').write_bytes(b'%PDF-new')
            target = root / 'data/documents'
            target.mkdir(parents=True)
            (target / 'Book.PDF').write_bytes(b'%PDF-existing')
            with patch.object(bootstrap, 'ROOT', root):
                bootstrap.prepare_books(source)
            self.assertEqual(b'%PDF-existing', (target / 'Book.PDF').read_bytes())

    def test_download_rejects_non_pdf_and_removes_partial_file(self):
        class Response(io.BytesIO):
            url = 'https://goalkicker.com/Book/Book.pdf'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'Book.pdf'
            with patch.object(bootstrap.urllib.request, 'urlopen', return_value=Response(b'not a PDF')):
                with self.assertRaises(ValueError):
                    bootstrap.download_pdf(Response.url, target)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.pdf.part').exists())

    def test_download_rejects_unexpected_host(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                bootstrap.download_pdf('https://example.com/book.pdf', Path(folder) / 'book.pdf')

    def test_empty_library_announces_general_chat(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            args = ['devknowledgeai', '--books-dir', str(Path(folder) / 'books'), '--prompt', 'Hello']
            with patch.object(app, 'ROOT', Path(folder)), patch.object(sys, 'argv', args), patch.object(app, 'ChatOllama') as model, redirect_stdout(output):
                model.return_value.invoke.return_value = AIMessage(content='Hello!')
                self.assertEqual(0, app.main())
            self.assertIn('Starting general chat', output.getvalue())
            self.assertIn('Assistant: Hello!', output.getvalue())

    def test_explicit_index_does_not_silently_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            args = ['devknowledgeai', '--books-dir', str(Path(folder) / 'books'), '--index']
            with patch.object(app, 'ROOT', Path(folder)), patch.object(sys, 'argv', args):
                with self.assertRaises(ValueError):
                    app.main()


if __name__ == '__main__':
    unittest.main()
