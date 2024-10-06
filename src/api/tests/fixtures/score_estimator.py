import pytest
from db.score_estimator import ScoreEstimator


@pytest.fixture(scope="function")
def unique_score_estimator(unique_user, unique_feed) -> ScoreEstimator:
    """Generates unique score_estimator data for each test"""
    score_estimator = ScoreEstimator(
        user_hash=unique_user.name_hash,
        feed_hash=unique_feed.name_hash,
        training_rows=100,
        training_date="2021-01-01",
        training_time="00:00:00",
        inference_time="00:00:00",
        model=b"model",
    )

    yield score_estimator

    if score_estimator.exists():
        score_estimator.delete()


@pytest.fixture(scope="function")
def existing_score_estimator(
    unique_score_estimator, existing_user, existing_feed, existing_item_strict
) -> ScoreEstimator:
    """Generates existing score_estimator data for each test"""
    unique_score_estimator.create()
    yield unique_score_estimator
