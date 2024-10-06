from sklearn.linear_model import ElasticNet
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
    model: Optional[bytes]

    @property
    def key(self):
        return f"USER:{self.user_hash}:FEED:{self.feed_hash}:SCORE_ESTIMATOR"

    def create(self):
        with self.db_con() as r:
            r.set(self.key, self.model_dump_json())

        return self.key

    @classmethod
    def read(cls, user_hash, feed_hash) -> Optional["ScoreEstimator"]:
        key = f"USER:{user_hash}:FEED:{feed_hash}:SCORE_ESTIMATOR"
        return cls.read_by_key(key)

    @classmethod
    def read_by_key(cls, key):
        with cls.db_con() as r:
            item_json = r.get(key)

        if item_json:
            return cls.model_validate_json(item_json)
        return None

    def gather_data(self, training: bool) -> tuple[list[list[float]], list[float]]:
        feed = Feed.read(user_hash=self.user_hash, name_hash=self.feed_hash)
        item_states = []
        items = []
        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL")

        for item in feed.query_items():
            if item.embeddings is not None and embedding_model in item.embeddings:
                item_state = ItemState.read(
                    user_hash=self.user_hash,
                    feed_hash=self.feed_hash,
                    item_url_hash=item.url_hash,
                )

                if training:
                    if item_state and item_state.score is not None:
                        item_states.append(item_state)
                        items.append(item)
                else:
                    if (
                        not item_state
                        or item_state.score is None
                        or item_state.score_estimate_is_stale
                    ):
                        items.append(item)

        item_data = []
        scores = []

        if not training:
            dummy_item_state = ItemState(
                item_url_hash=item.url_hash,
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
        _, item_data, scores = self.gather_data(training=True)

        # Use ElasticNet instead of LinearRegression
        model = ElasticNet(alpha=1.0, l1_ratio=0.5)

        # train
        training_start_time = datetime.now()
        model.fit(item_data, scores)
        training_end_time = datetime.now()

        # inference (on the training set)
        inference_start_time = datetime.now()
        model.predict(item_data)
        inference_end_time = datetime.now()

        # evaluate
        self.training_rows = len(item_data)
        self.training_date = datetime.now()
        self.training_time = training_end_time - training_start_time
        self.inference_time = inference_end_time - inference_start_time

        # save model as bytes
        model_buffer = BytesIO()
        pickle.dump(model, model_buffer, protocol=5)
        self.model = model_buffer.getvalue()

    def infer(self):
        model = pickle.loads(self.model)

        item_url_hashes, item_data, _ = self.gather_data(training=False)

        predictions = model.predict(item_data)

        for item_url_hash, prediction in zip(item_url_hashes, predictions):
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
