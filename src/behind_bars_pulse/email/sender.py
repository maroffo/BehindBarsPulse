# ABOUTME: Email sender for newsletter distribution via AWS SES SMTP.
# ABOUTME: Handles template rendering, SMTP delivery, and newsletter archival.

import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader

from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import NewsletterContext

log = structlog.get_logger()

HTML_TEMPLATE = "behind_bars_template.html"
TXT_TEMPLATE = "behind_bars_template.txt"


class EmailSender:
    """Sends newsletters via AWS SES SMTP."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._jinja_env: Environment | None = None

    @property
    def jinja_env(self) -> Environment:
        """Lazy-initialized Jinja2 environment."""
        if self._jinja_env is None:
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(self.settings.templates_dir)),
                autoescape=True,
            )
        return self._jinja_env

    def send(
        self,
        context: NewsletterContext,
        recipients: list[str] | None = None,
    ) -> None:
        """Send newsletter email to recipients.

        Args:
            context: Complete newsletter context for rendering.
            recipients: List of email addresses. Defaults to context list or default recipient.
        """
        recipients = recipients or context.notification_address_list
        if not recipients:
            recipients = [self.settings.default_recipient]

        log.info("sending_newsletter", subject=context.subject, recipient_count=len(recipients))

        # Render templates
        template_context = context.model_dump()
        template_context["html_template"] = HTML_TEMPLATE
        template_context["txt_template"] = TXT_TEMPLATE

        html_template = self.jinja_env.get_template(HTML_TEMPLATE)
        txt_template = self.jinja_env.get_template(TXT_TEMPLATE)

        html_content = html_template.render(**template_context)
        txt_content = txt_template.render(**template_context)

        # Archive newsletter
        self._archive_newsletter(txt_content, "txt")
        self._archive_newsletter(html_content, "html")

        # Build email message
        message = EmailMessage()
        message["Subject"] = context.subject
        message["From"] = f"{self.settings.sender_name} <{self.settings.sender_email}>"
        message["To"] = f"iungo <{self.settings.default_recipient}>"
        message.add_header("Return-Path", self.settings.bounce_email)

        message.set_content(txt_content)
        message.add_alternative(html_content, subtype="html")

        # Send via SMTP
        self._send_smtp(message, recipients)

    def _send_smtp(self, message: EmailMessage, recipients: list[str]) -> None:
        """Send email via SMTP."""
        if not self.settings.ses_usr or not self.settings.ses_pwd:
            raise ValueError(
                "SES credentials not configured. Set ses_usr and ses_pwd in .env file."
            )

        log.debug(
            "connecting_smtp",
            host=self.settings.smtp_host,
            port=self.settings.smtp_port,
        )

        server = smtplib.SMTP(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=30,
        )

        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(
                self.settings.ses_usr.get_secret_value(),
                self.settings.ses_pwd.get_secret_value(),
            )

            for recipient in recipients:
                log.info("sending_to", recipient=recipient)
                server.sendmail(
                    message["From"],
                    recipient,
                    message.as_string(),
                )

        finally:
            server.quit()

        log.info("newsletter_sent", recipient_count=len(recipients))

    def _archive_newsletter(
        self, content: str, extension: str, suffix: str = "", issue_date: date | None = None
    ) -> Path:
        """Archive newsletter content to file.

        Args:
            content: Newsletter content to archive.
            extension: File extension (txt or html).
            suffix: Optional suffix before extension (e.g., "_preview").
            issue_date: Date for the filename. Defaults to today.

        Returns:
            Path to the archived file.
        """
        archive_date = issue_date or date.today()
        filename = f"{archive_date.strftime('%Y%m%d')}_issue{suffix}.{extension}"
        archive_dir = Path(self.settings.previous_issues_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)

        file_path = archive_dir / filename
        file_path.write_text(content, encoding="utf-8")

        log.info("newsletter_archived", file=str(file_path))
        return file_path

    def save_preview(self, context: NewsletterContext, issue_date: date | None = None) -> Path:
        """Save newsletter preview without sending.

        Renders templates and saves to previous_issues/ with _preview suffix.

        Args:
            context: Complete newsletter context for rendering.
            issue_date: Date for the filename. Defaults to today.

        Returns:
            Path to the saved HTML preview file.
        """
        log.info("saving_preview", subject=context.subject)

        # Render templates
        template_context = context.model_dump()
        template_context["html_template"] = HTML_TEMPLATE
        template_context["txt_template"] = TXT_TEMPLATE

        html_template = self.jinja_env.get_template(HTML_TEMPLATE)
        txt_template = self.jinja_env.get_template(TXT_TEMPLATE)

        html_content = html_template.render(**template_context)
        txt_content = txt_template.render(**template_context)

        # Save with _preview suffix
        self._archive_newsletter(txt_content, "txt", "_preview", issue_date)
        html_path = self._archive_newsletter(html_content, "html", "_preview", issue_date)

        return html_path
