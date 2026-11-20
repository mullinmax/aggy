"""A language model as the judge: no training, just reading.

Every other method works from an embedding. This one shows the local analysis
model (the Ollama model the app already uses to analyse pages) a handful of
headlines you upvoted, a handful you did not, and the article in question, and
asks how likely an upvote is.

It is by far the most expensive thing an experiment can do, so it is opt-in and
tightly rationed: only the last blocks of a feed, and only so many articles in
each. Everything stays on the machine the app already talks to. The headlines
go to that model and nowhere else, and none of them are kept in the result.
"""

import json
import re
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from config import config
from ranking.models import ItemFeatures, _embedding_dim, _unit_or_zeros

from . import metrics
from .methods import ExperimentModel

_PROMPT = """You are predicting whether a reader will upvote an article.

Articles this reader UPVOTED:
{liked}

Articles this reader saw and did NOT upvote:
{other}

New article:
{candidate}

How likely is this reader to upvote the new article? Answer with JSON:
{{"upvote_probability": <number between 0 and 1>}}"""

_SCHEMA = {
    "type": "object",
    "properties": {"upvote_probability": {"type": "number"}},
    "required": ["upvote_probability"],
}

_TITLE_CHARS = 140
_EXCERPT_CHARS = 240


def _describe(text: Optional[Tuple[Optional[str], Optional[str]]], full: bool) -> str:
    title, excerpt = text or (None, None)
    line = (title or "(untitled)").strip()[:_TITLE_CHARS]
    if full and excerpt:
        line += "\n" + re.sub(r"\s+", " ", excerpt).strip()[:_EXCERPT_CHARS]
    return line


def ask_ollama(prompt: str) -> float:
    """One judgement from the configured analysis model, as a probability."""
    from utils import get_ollama_connection

    kwargs = {
        "model": config.get("OLLAMA_ANALYSIS_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "format": _SCHEMA,
        "options": {
            "temperature": 0,
            "num_ctx": config.get_int("OLLAMA_ANALYSIS_NUM_CTX"),
        },
    }
    client = get_ollama_connection()
    try:
        response = client.chat(think=False, **kwargs)
    except Exception as e:
        # older servers and non-thinking models reject the parameter
        if "think" not in str(e).lower():
            raise
        response = client.chat(**kwargs)
    content = re.sub(
        r"<think>.*?</think>", "", response["message"]["content"], flags=re.DOTALL
    )
    answer = json.loads(content[content.find("{") : content.rfind("}") + 1])
    return float(np.clip(float(answer["upvote_probability"]), 0.0, 1.0))


class LLMJudgeModel(ExperimentModel):
    name = "llm_judge"
    min_labels = 10
    heavy = True
    # only the newest blocks of a feed are judged (see replay_feed)
    last_blocks = 2

    def __init__(
        self,
        texts: Dict[str, Tuple[Optional[str], Optional[str]]],
        ask=ask_ollama,
        examples: int = 6,
        max_items: int = 20,
    ):
        self.texts = texts
        self.ask = ask
        self.examples = examples
        self.max_items = max_items

    def fit(self, items: Sequence[ItemFeatures]):
        self.items = list(items)
        self.dim = _embedding_dim(items, "embedding")
        self.up = metrics.is_upvote(np.asarray([float(i.label) for i in items]))
        self.matrix = np.asarray(
            [_unit_or_zeros(i.embedding, self.dim)[0] for i in items]
        ).reshape(len(self.items), self.dim)

    def _examples(self, item: ItemFeatures, wanted: np.ndarray) -> str:
        """The voted articles most like this one, so the model is shown the
        part of your taste that bears on it rather than a random sample."""
        candidates = np.flatnonzero(wanted)
        if self.dim and item.embedding is not None:
            vector, _ = _unit_or_zeros(item.embedding, self.dim)
            order = np.argsort(-(self.matrix[candidates] @ vector))
            candidates = candidates[order]
        else:
            candidates = candidates[::-1]  # newest votes first
        lines = [
            "- " + _describe(self.texts.get(self.items[i].url_hash), full=False)
            for i in candidates[: self.examples]
        ]
        return "\n".join(lines) or "- (none yet)"

    def predict(self, items: Sequence[ItemFeatures]):
        scores = np.full(len(items), np.nan)
        for index, item in enumerate(items[: self.max_items]):
            prompt = _PROMPT.format(
                liked=self._examples(item, self.up),
                other=self._examples(item, ~self.up),
                candidate=_describe(self.texts.get(item.url_hash), full=True),
            )
            # a failure here raises, and the replay drops the method for the
            # block: an unreachable model must not be scored as a bad guess
            scores[index] = 2.0 * self.ask(prompt) - 1.0
        return scores, np.full(len(items), 0.5)
