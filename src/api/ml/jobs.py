import logging

from db.user import User
from db.score_estimator import ScoreEstimator
from utils import schedule, next_scheduled_key
from constants import (
    SCORE_ESTIMATORS_TO_TRAIN_QUE,
    SCORE_ESTIMATORS_TO_INFER_QUE,
    SCORE_ESTIMATE_TRAINING_INTERVAL_TIMEDELTA,
    SCORE_ESTIMATE_INFERENCE_INTERVAL_TIMEDELTA,
)


def score_estimate_training_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            schedule(
                que=SCORE_ESTIMATORS_TO_TRAIN_QUE,
                key=feed.key,
                interval=SCORE_ESTIMATE_TRAINING_INTERVAL_TIMEDELTA,
            )


def score_estimate_inference_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            score_estimator = ScoreEstimator(
                user_hash=feed.user_hash, feed_hash=feed.name_hash
            )
            schedule(
                que=SCORE_ESTIMATORS_TO_INFER_QUE,
                key=score_estimator.key,
                interval=SCORE_ESTIMATE_INFERENCE_INTERVAL_TIMEDELTA,
            )


def score_estimate_trainging_job() -> None:
    with next_scheduled_key(
        que=SCORE_ESTIMATORS_TO_TRAIN_QUE,
        interval=SCORE_ESTIMATE_TRAINING_INTERVAL_TIMEDELTA,
    ) as score_estimator_key:
        try:
            logging.info(f"Training score estimator for {score_estimator_key}")
            score_estimator = ScoreEstimator.read_by_key(score_estimator_key)
            if score_estimator is None:
                score_estimator = ScoreEstimator(
                    user_hash=score_estimator.user_hash,
                    feed_hash=score_estimator.name_hash,
                )

            score_estimator.train()
            score_estimator.create()

            # schedule the next inference for now, since we have a new model
            schedule(
                que=SCORE_ESTIMATORS_TO_INFER_QUE,
                key=score_estimator_key,
                interval=SCORE_ESTIMATE_TRAINING_INTERVAL_TIMEDELTA,
                now=True,
            )
        except Exception as e:
            logging.error(
                f"Training of score estimator {score_estimator_key} failed: {e}"
            )
            return


def score_estimate_inference_job() -> None:
    with next_scheduled_key(
        que=SCORE_ESTIMATORS_TO_INFER_QUE,
        interval=SCORE_ESTIMATE_INFERENCE_INTERVAL_TIMEDELTA,
    ) as score_estimator_key:
        try:
            logging.info(f"Inferencing score estimator for {score_estimator_key}")
            score_estimator = ScoreEstimator.read_by_key(score_estimator_key)
            if score_estimator is None:
                logging.error(f"Score estimator {score_estimator_key} not found")
                return

            score_estimator.infer()
        except Exception as e:
            logging.error(
                f"Inferencing of score estimator {score_estimator_key} failed: {e}"
            )
            return
