"""Image-embedding microservice.

Ollama can't embed images, so the recommender's "score the picture itself"
feature needs a real vision model. This is a tiny FastAPI service that wraps a
CLIP model (via sentence-transformers) and turns an image into an L2-normalized
embedding vector. It keeps the heavy torch/CLIP dependency out of the main API
image — the API just POSTs a base64 image here and stores the vector it gets
back in items.image_embeddings.
"""

import base64
import binascii
import io
import logging
import os

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)

# CLIP ViT-B/32 gives 512-dim image embeddings and is small enough to run on
# CPU. The image is baked into the container at build time (see the dockerfile),
# so startup and the first request don't need network access.
MODEL_NAME = os.getenv("IMAGE_EMBED_MODEL", "clip-ViT-B-32")

logging.info(f"Loading image embedding model '{MODEL_NAME}'...")
model = SentenceTransformer(MODEL_NAME)
logging.info("Image embedding model ready.")

app = FastAPI(title="aggy image embedding")


class EmbedRequest(BaseModel):
    image_base64: str


class EmbedResponse(BaseModel):
    model: str
    embedding: list[float]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    try:
        raw = base64.b64decode(request.image_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid base64: {e}")
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not decode image: {e}")

    # normalize so cosine similarity is a plain dot product, matching how the
    # text embeddings are consumed downstream
    vector = model.encode(image, normalize_embeddings=True)
    return EmbedResponse(model=MODEL_NAME, embedding=vector.tolist())
