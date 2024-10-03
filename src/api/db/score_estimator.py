from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, accuracy_score
from datetime import datetime, timedelta
from config import config
from io import BytesIO
import pickle
from typing import Optional


from .base import AggyBaseModel
from .item_state import ItemState
from .feed import Feed


class ScoreEstimator(AggyBaseModel):
    user_hash: str
    feed_hash: str
    training_rows: Optional[int]
    training_date: Optional[datetime]
    training_time: Optional[timedelta]
    inference_time: Optional[timedelta]
    accuracy: Optional[float]
    precision: Optional[float]
    model: Optional[bytes]

    @property
    def key(self):
        return f"USER:{self.user_hash}:FEED:{self.feed_hash}:SCORE_ESTIMATOR"

    def create(self):
        if self.exists():
            raise Exception("ScoreEstimator already exists")

        with self.db_con() as r:
            r.set(self.key, self.model_dump_json())

        return self.key

    @classmethod
    def read(cls, user_hash, feed_hash) -> Optional["ScoreEstimator"]:
        key = f"USER:{user_hash}:FEED:{feed_hash}:SCORE_ESTIMATOR"
        with cls.db_con() as r:
            data = r.hgetall(key)

        if not data:
            return None

        return cls(
            user_hash=user_hash,
            feed_hash=feed_hash,
            training_date=datetime.fromisoformat(data["training_date"]),
            model=data.get("model"),
        )

    def gather_data(self, training: bool) -> tuple[list[list[float]], list[float]]:
        # get all items in the feed
        feed = Feed.read(user_hash=self.user_hash, name_hash=self.feed_hash)
        item_states = []
        items = []
        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL")
        # get all item_states for the items
        for item in feed.items:
            # we can't do anything if we don't have the embeddings
            if item.embeddings is not None and embedding_model in item.embeddings:
                item_state = ItemState.read(
                    user_hash=self.user_hash,
                    feed_hash=self.feed_hash,
                    item_hash=item.item_hash,
                )

                if training:
                    if item_state and item_state.score is not None:
                        item_states.append(item_state)
                        items.append(item)
                else:
                    # only add if the score estimate is stale and the user hasn't already scored it
                    if (
                        not item_state
                        or item_state.score is None
                        or item_state.score_estimate_is_stale
                    ):
                        items.append(item)

        # convert into manageable format for training
        item_data = []
        scores = []

        # make sure we feed inference such that it is estimating the scores for today.
        # TODO maybe we should estimate slightly into the future?
        if not training:
            dummy_item_state = ItemState(
                item_hash=item.url_hash,
                user_hash=self.user_hash,
                feed_hash=self.feed_hash,
                score_date=datetime.now(),
            )
            item_states = [dummy_item_state] * len(items)

        for item, state in zip(items, item_states):
            delta = state.score_date - item.date_published
            item_data.append(
                [
                    item.date_published.year,
                    item.date_published.month,
                    item.date_published.weekday(),
                    item.date_published.hour,
                    state.score_date.year,
                    state.score_date.month,
                    state.score_date.weekday(),
                    state.score_date.hour,
                    delta.days,
                    delta.seconds,
                    *item.embeddings[embedding_model],
                ]
            )
            if training:
                scores.append(state.score)
        return [i.url_hash for i in items], item_data, scores

    def train(self):
        # gather data
        _, item_data, scores = self.gather_training_data(training=True)

        model = LogisticRegression(penalty="l2", solver="lbfgs", C=1.0)

        # train
        training_start_time = datetime.now()
        model.fit(item_data, scores)
        training_end_time = datetime.now()

        # inference
        inference_start_time = datetime.now()
        predictions = model.predict(item_data)
        inference_end_time = datetime.now()

        # evaluate
        self.training_rows = len(item_data)
        self.precision = precision_score(scores, predictions)
        self.accuracy = accuracy_score(scores, predictions)
        self.training_date = datetime.now()
        self.training_time = training_end_time - training_start_time
        self.inference_time = inference_end_time - inference_start_time

        # save model
        model_buffer = BytesIO()
        pickle.dump(model, model_buffer, protocol=5)
        self.model = model_buffer.getvalue()

    def infer(self):
        # TODO get confidence too?
        model = pickle.loads(self.model)

        # gather data
        item_url_hashes, item_data, _ = self.gather_data(training=False)

        # infer
        predictions = model.predict(item_data)

        # save predictions
        for item_url_hash, prediction in zip(item_url_hashes, predictions):
            # ensure we have no out of bounds predictions
            if prediction > 1:
                prediction = 1
            elif prediction < -1:
                prediction = -1

            ItemState.set_state(
                user_hash=self.user_hash,
                feed_hash=self.feed_hash,
                item_url_hash=item_url_hash,
                score=prediction,
            )
