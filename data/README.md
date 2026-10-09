# Local data

Place your PDF books in `documents/`. Run `python setup.py` to index them.
Alternatively, `python setup.py --download-books` fetches the seven reference
books listed in `books.json` from their original websites.

PDFs, indexes, and temporary downloads are ignored by Git. The public repository
contains source code and source links, not redistributed books or user data.

Only readable text is indexed. Scanned PDFs need OCR first. Use unique filenames
so book/page citations remain unambiguous.
