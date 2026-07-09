"""Compatibility wrapper for the legacy Streamlit app.

The implementation lives in tools.advisor so the FastAPI backend no longer
depends on the ui package during the React migration.
"""
from tools.advisor import (
    generate_advice,
    is_rag_check_due,
    load_log,
    rag_alert_check,
    save_response,
)

__all__ = [
    "generate_advice",
    "is_rag_check_due",
    "load_log",
    "rag_alert_check",
    "save_response",
]
