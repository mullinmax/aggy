-- Sources created from a template took the default kind ('rss') instead of the
-- template's, so a video listing was handed to the feed parser as if it were
-- RSS and failed on its first fetch. The creation paths now carry the kind
-- through; this repairs the sources made before they did.
UPDATE sources s
SET kind = t.kind
FROM source_templates t
WHERE s.template_name_hash = t.name_hash
  AND s.kind = 'rss'
  AND t.kind <> 'rss';
