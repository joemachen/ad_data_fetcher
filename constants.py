"""
Shared constants for timeouts and retries.
Used by main.py (GUI timeouts) and referenced by fetchers (retries are per-fetcher).
"""
# Pipeline: max seconds to wait for each platform fetch to complete (batch pipeline)
PIPELINE_FETCH_WAIT_SECONDS = 3600

# Dialogs: max seconds to wait for user to confirm (e.g. token input, funnel stage)
DIALOG_WAIT_SECONDS = 300
