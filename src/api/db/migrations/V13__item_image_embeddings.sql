-- Store image (thumbnail) embeddings separately from the text embeddings so the
-- recommender can score an article's picture on its own. Same shape as the
-- `embeddings` column: a JSONB dict of {model_name: vector}, keyed by the vision
-- model that produced each vector.
ALTER TABLE items ADD COLUMN image_embeddings JSONB;
