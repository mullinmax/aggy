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

    def gather_training_data(self):
        # get all items in the feed
        feed = Feed.read(user_hash=self.user_hash, name_hash=self.feed_hash)
        items = feed.items
        item_states = []
        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL")
        # get all item_states for the items
        for item in items:
            item_state = ItemState.read(
                user_hash=self.user_hash,
                feed_hash=self.feed_hash,
                item_hash=item.item_hash,
            )

            # throw away any with no score or without the relevant embeddings
            if (
                item_state.score is None
                or item.embeddings is None
                or embedding_model not in item.embeddings
            ):
                item_states.remove(item_state)

            item_states.append(item_state)

        # convert into manageable format for training
        item_data = []
        scores = []

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
            scores.append(state.score)

    def train(self):
        # gather data
        item_data, scores = self.gather_training_data()

        initial_model = LogisticRegression(penalty="l2", solver="lbfgs", C=1.0)

        # train
        training_start_time = datetime.now()
        initial_model.fit(item_data, scores)
        training_end_time = datetime.now()

        # inference
        inference_start_time = datetime.now()
        predictions = initial_model.predict(item_data)
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
        pickle.dump(initial_model, model_buffer, protocol=5)
        self.model = model_buffer.getvalue()

    def infer(self):
        pass
