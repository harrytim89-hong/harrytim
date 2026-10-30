"""Serialize in-process MuPDF access; AI requests may still run concurrently."""
from threading import RLock

PDF_LOCK = RLock()
