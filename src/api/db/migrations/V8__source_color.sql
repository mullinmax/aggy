-- Per-source display color (hex, e.g. #e57373), chosen randomly at creation
-- and user-editable in the source settings.
ALTER TABLE sources ADD COLUMN color TEXT;
