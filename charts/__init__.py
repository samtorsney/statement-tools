"""Reporting & charts: transfer netting, Sankey/monthly/savings builders.

Pure transform modules (``netting``, ``sankey``, ``monthly``, ``savings``)
take a categorised frame (or the netted result of one) and return another
frame or a ``plotly`` figure -- no file or stdout I/O happens in them. All
I/O and the privacy-sensitive stdout discipline (counts/filenames only,
never transaction text) live in ``charts.cli``.
"""
