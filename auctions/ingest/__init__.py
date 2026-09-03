"""Ingest pipeline for the izsoles.ta.gov.lv open-data feed.

:mod:`auctions.ingest.parse` turns a local ``izsoles.csv`` into record dicts
keyed by :class:`auctions.models.Listing` field names. :mod:`auctions.ingest.fetch`
is a best-effort helper that refreshes that local file over HTTP.
"""
