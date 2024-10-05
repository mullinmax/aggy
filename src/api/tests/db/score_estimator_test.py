def test_create_score_estimator(unique_score_estimator):
    """Tests creating a score_estimator"""
    assert unique_score_estimator.create()
    assert unique_score_estimator.exists()


def test_read_score_estimator(existing_score_estimator):
    """Tests reading a score_estimator"""
    actual = existing_score_estimator.read(
        existing_score_estimator.user_hash, existing_score_estimator.feed_hash
    )

    assert actual
    assert actual.user_hash == existing_score_estimator.user_hash
    assert actual.feed_hash == existing_score_estimator.feed_hash
    assert actual.training_rows == existing_score_estimator.training_rows
    assert actual.training_date == existing_score_estimator.training_date
    assert actual.training_time == existing_score_estimator.training_time
    assert actual.inference_time == existing_score_estimator.inference_time
    assert actual.accuracy == existing_score_estimator.accuracy
    assert actual.precision == existing_score_estimator.precision
    assert actual.model == existing_score_estimator.model


def test_read_non_existent_score_estimator(existing_score_estimator):
    """Tests reading a non-existent score_estimator"""
    actual = existing_score_estimator.read("non_existent", "non_existent")
    assert not actual


def test_gather_data(existing_score_estimator, existing_item_strict):
    """Tests gathering data for a score_estimator"""
    item_keys, item_data, scores = existing_score_estimator.gather_data(training=True)
    assert item_keys
    assert item_data
    assert scores
    assert isinstance(item_keys, list)
    assert isinstance(item_data, list)
    assert isinstance(scores, list)
    assert len(item_keys) == 1


def test_gather_data_inference(existing_score_estimator, existing_item_strict):
    """Tests gathering data for a score_estimator"""
    # remove score estimate from item
    existing_item_strict.score_estimate = None
    existing_item_strict.score_estimate_date = None
    existing_item_strict.update()

    item_keys, item_data, scores = existing_score_estimator.gather_data(training=False)
    assert item_keys
    assert item_data
    assert len(item_keys) == 1
