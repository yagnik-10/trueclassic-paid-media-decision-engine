"""Stage 2 — real ingestion.

Reads the raw API-envelope JSON (Meta `data/paging`, Google nested `results`,
Shopify commerce), validates the outer envelope and each record, normalizes valid
records into the canonical model, quarantines the rest, resolves platform product
IDs to canonical SKUs, and detects the planted data-quality defects from the
feeds. No modeling/optimizer/LLM here (Stage 3/5).
"""
