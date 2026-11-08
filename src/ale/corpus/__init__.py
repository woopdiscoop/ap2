"""Corpus ingestion and classification (Ticket 1.1): ``corpus.sqlite`` units of work.

Entry points: :func:`ale.corpus.ingest.ingest` and :func:`ale.corpus.db.read_status`.
(The function is deliberately not re-exported here: it would shadow the submodule.)
"""

from __future__ import annotations
