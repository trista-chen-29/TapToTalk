-- Local-only request counts. Bind :as_of to an ISO 8601 UTC reference time.
-- The inclusive window is [as_of - 30 days, as_of]; future rows are excluded.
-- julianday compares instants rather than mixed ISO timestamp spellings.
SELECT phrase_id, COUNT(*) AS request_count
FROM selections
WHERE julianday(selected_at) >= julianday(:as_of, '-30 days')
  AND julianday(selected_at) <= julianday(:as_of)
GROUP BY phrase_id
ORDER BY request_count DESC, phrase_id ASC;
