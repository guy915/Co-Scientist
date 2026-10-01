"""PDF heading recovery for uploaded documents.

The cascade (bookmarks, then numbering, then font style) is assembled in
``app.pdf.headings``; document_ingest imports it lazily.
"""
