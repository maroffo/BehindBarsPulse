import logging
import smtplib

from bs4.dammit import html_meta
from dateutil.utils import today
from jinja2 import Environment, FileSystemLoader

from email.message import EmailMessage

from core import config

log = logging.getLogger(__name__)

behind_bars_html_template = "behind_bars_template.html"
behind_bars_txt_template = "behind_bars_template.txt"


def send_behind_bars_email(context):
    context['html_template'] = behind_bars_html_template
    context['txt_template'] = behind_bars_txt_template
    log.info(f"Sending email '{context['subject']}'")
    send_email(context)


def archive_newsletter_html(content: str):
    archive_newsletter_content(content, 'html')


def archive_newsletter_txt(content: str):
    archive_newsletter_content(content, 'txt')


def archive_newsletter_content(content: str, file_extension: str):
    filename = f"{today().strftime('%Y%m%d')}_issue.{file_extension}"
    with open(f"previous_issues/{filename}", "w") as text_file:
        text_file.write(content)


def send_email(context):
    environment = Environment(loader=FileSystemLoader("./mail_sender/templates/"))
    html_template = environment.get_template(context.get('html_template'))
    txt_template = environment.get_template(context.get('txt_template'))

    notification_address_list = context.get('notification_address_list')
    message = EmailMessage()

    message["Subject"] = context.get('subject')
    message["From"] = "Behind Bars Pulse <behindbars@iungomail.com>"
    message.add_header('Return-Path', 'bounces@iungomail.com')

    text = txt_template.render(**context)
    archive_newsletter_txt(text)
    message.set_content(text)

    html = html_template.render(**context)
    archive_newsletter_html(html)
    message.add_alternative(html, subtype='html')

    host = "email-smtp.eu-west-1.amazonaws.com"
    port = 587
    use_tls = True
    usr = config.get("ses_usr")
    pwd = config.get("ses_pwd")

    message["To"] = "iungo <maroffo@gmail.com>"
    server = smtplib.SMTP(host, port, timeout=30)
    server.set_debuglevel(0)
    if use_tls is True:
        server.ehlo()
        server.starttls()
        server.ehlo()
    server.login(usr, pwd)
    for mail_address in notification_address_list:
        print("Sending to: {}".format(mail_address))
        server.sendmail(message["From"], mail_address, message.as_string())
    server.quit()
