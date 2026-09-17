"""Near-duplicate article detection.

The same article reaches a user through several sources, under a different URL
from each, so it is stored several times and shown several times. This package
works out which items are the same content, and the feed then shows one member
of each group -- whichever the current model scores highest.

A sibling of ``ranking`` rather than part of it: which items are the same
content is a fact about the items, not about anyone's preferences. Only
choosing the member to show involves the model, and that happens at query time
in ``Feed.query_items_with_sources``.
"""
