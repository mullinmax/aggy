"""The nearest-neighbour graph over a feed's articles.

``search`` is the walk itself, with no database in it. ``graph`` builds and
reads the stored graph, and is what duplicate detection, the ranking models and
the reader's related-articles rail all go through.
"""
