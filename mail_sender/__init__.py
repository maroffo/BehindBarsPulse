import logging
import smtplib

from dateutil.utils import today
from jinja2 import Environment, FileSystemLoader

from email.message import EmailMessage

from core import config

log = logging.getLogger(__name__)

behind_bars_template = "behind_bars_template.html"


def send_behind_bars_email(context):
    context['template'] = behind_bars_template
    today_str = today().strftime('%d.%m.%Y')
    context['today_str'] = today_str
    context['subject'] = f"⚖️⛓️BehindBars - Notizie dal mondo della giustizia e delle carceri italiane - {today_str}"
    log.info(f"Sending email '{context['subject']}'")
    send_email(context)


def save_email_body(content):
    with open("newsletter.html", "w") as text_file:
        text_file.write(content)


def send_email(context):
    environment = Environment(loader=FileSystemLoader("./mail_sender/templates/"))
    template = environment.get_template(context.get('template'))
    content = template.render(**context)

    notification_address_list = context.get('notification_address_list')
    message = EmailMessage()

    message["Subject"] = context.get('subject')
    message["From"] = "Behind Bars Pulse <behindbars@iungomail.com>"

    html = content
    save_email_body(content)

    # text = """
    # Designed and Developed with ❤️ in Bologna
    # """
    #  message.set_content(text)

    message.add_alternative(html, subtype='html')
    message.add_header('Return-Path', 'bounces@iungomail.com')

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
