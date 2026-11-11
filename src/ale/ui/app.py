"""Entry script of the local interface (Ticket U.1): ``streamlit run`` target of ``ale ui``.

Kept to three lines so that the pages live in an importable module, :mod:`ale.ui.render`.
"""

from __future__ import annotations

from ale.ui.render import main

main()
