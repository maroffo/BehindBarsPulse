# ABOUTME: Email delivery module for newsletter distribution via AWS SES.
# ABOUTME: Handles template rendering, SMTP connection, and archival.

from behind_bars_pulse.email.sender import EmailSender

__all__ = ["EmailSender"]
