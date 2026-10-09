# Dependencies and reference sources

The project installs dependencies from PyPI; it does not bundle their source or binaries.

| Direct dependency | Version | Published license |
| --- | --- | --- |
| langchain-ollama | 1.1.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PyMuPDF | 1.28.2 | GNU AGPL v3 or Artifex commercial license |

See [LangChain](https://github.com/langchain-ai/langchain),
[python-dotenv](https://github.com/theskumar/python-dotenv), and
[PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).
Transitive dependencies have their own licenses; `requirements.lock.txt` records
the tested dependency versions. A project license has not yet been selected.

The optional reference PDFs are fetched directly from GoalKicker when requested.
They are not included in this repository. Source pages and download URLs appear
in `books.json`. GoalKicker credits Stack Overflow Documentation contributors and
describes text content as Creative Commons BY-SA; individual images may carry
different rights. Refer to each source page and the book's credits for details.
Downloading a book does not change its ownership or license.
