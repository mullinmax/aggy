from db.user import User
from utils import schedule


def score_estimate_training_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            schedule()


# def score_estimate_inference_scheduling_job() -> None:


def score_estimate_trainging_job() -> None:
    pass
    # gather old model, and training data
    # check if there's any new data since the last training
    # if there is enough new data, retrain the model


# def score_estimate_inference_job() -> None:
# check for any un-scored items and score them
# rescore anything that hasn't been scored for some configurable time and has not been read/liked/disliked
