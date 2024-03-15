# Ingestion Service for Blinder

steps:
 - read in users from database
 - read feeds from database
 - check how long ago the feed was last checked
 - update last checked field
 - get rss feed
 - add each item to the feed's item list
 - remove items that already exist
 - get previews for each item
 - create it entry for each item
