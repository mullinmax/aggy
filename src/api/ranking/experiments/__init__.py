"""Prediction experiments: replay a feed's vote history against many methods.

`replay` is the harness (pure numpy, no database), `methods` the candidate
predictors beyond the live model zoo, and `runner` the stored queue that works
experiments one at a time in the background.
"""
