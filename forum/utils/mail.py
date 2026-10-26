import email
import socket
import ssl
import os
import logging

try:
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.header import Header
except:
    from email.MIMEMultipart import MIMEMultipart
    from email.MIMEText import MIMEText
    from email.MIMEImage import MIMEImage
    from email.Header import Header

from email.utils import formataddr
from django.core.mail import DNS_NAME
from smtplib import SMTP
from smtplib import SMTPRecipientsRefused
from forum import settings
from django.template import loader, Context, Template
from forum.utils.html import sanitize_html
from forum.utils import metrics
from forum.context import application_settings
from threading import Thread

def send_template_email(recipients, template, context, sender=None, reply_to = None):
    """Returns the sending errors (empty list when the SMTP server took every message)."""
    t = loader.get_template(template)
    errors = []
    context.update(dict(recipients=recipients, settings=settings, sender=sender, reply_to=reply_to,
                        mail_errors=errors))
    t.render(context)
    return errors


def render_template_email(recipient, template, context):
    """Renders an email template for one recipient without sending it (the
    admin's email previews). Returns a dict: subject, html, text, headers."""
    t = loader.get_template(template)
    captured = []
    context = dict(context, recipients=[recipient], settings=settings, sender=None, reply_to=None,
                   mail_errors=[], email_capture=captured)
    t.render(context)
    to, subject, html, text, media, headers = captured[0]
    return {'subject': subject, 'html': html, 'text': text, 'headers': headers}

def create_connection():
    connection = SMTP(str(settings.EMAIL_HOST), str(settings.EMAIL_PORT),
                          local_hostname=DNS_NAME.get_fqdn(), timeout=30)

    if bool(settings.EMAIL_USE_TLS):
        connection.ehlo()
        connection.starttls()
        connection.ehlo()

    if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
        connection.login(str(settings.EMAIL_HOST_USER), str(settings.EMAIL_HOST_PASSWORD))

    return connection


def create_and_send_mail_messages(messages, sender_data=None, reply_to=None):
    """Sends the messages; returns a list of error descriptions (also logged)."""
    errors = []

    def error(text):
        logging.error(text)
        errors.append(text)
        metrics.count('osqa_emails_failed_total')

    if not settings.EMAIL_HOST:
        errors.append('No email server is set (Email host is empty), so no email was sent.')
        return errors

    if sender_data == None:
        sender_name, sender_email = str(settings.APP_SHORT_NAME), str(settings.DEFAULT_FROM_EMAIL)
    else:
        sender_name, sender_email = str(sender_data['name']), str(sender_data['email'])
    # formataddr encodes only the name: a header encoded as a whole hides the
    # address, and Amazon SES refuses it ("Missing final '@domain'").
    sender = formataddr((sender_name, sender_email))

    if reply_to == None:
        reply_to = str(settings.DEFAULT_REPLY_TO_EMAIL)
    else:
        reply_to = str(reply_to)

    try:
        connection = None

        for message in messages:
            recipient, subject, html, text, media = message[:5]
            headers = message[5] if len(message) > 5 else {}
            if connection is None:
                connection = create_connection()

            msgRoot = MIMEMultipart('related')

            msgRoot['Subject'] = Header(subject, 'utf-8')
            msgRoot['From'] = sender

            msgRoot['To'] = formataddr((recipient.username, recipient.email))

            if reply_to:
                msgRoot['Reply-To'] = reply_to

            for name, value in headers.items():
                msgRoot[name] = value

            msgRoot.preamble = 'This is a multi-part message from %s.' % str(settings.APP_SHORT_NAME)

            msgAlternative = MIMEMultipart('alternative')
            msgRoot.attach(msgAlternative)

            msgAlternative.attach(MIMEText(text, 'plain', 'utf-8'))
            msgAlternative.attach(MIMEText(html, 'html', 'utf-8'))

            for alias, location in media.items():
                fp = open(location, 'rb')
                msgImage = MIMEImage(fp.read())
                fp.close()
                msgImage.add_header('Content-ID', '<'+alias+'>')
                msgRoot.attach(msgImage)

            try:
                connection.sendmail(sender_email, [recipient.email], msgRoot.as_string())
                metrics.count('osqa_emails_sent_total')
            except SMTPRecipientsRefused as e:
                error("Email address not accepted.  Exception: %s" % e)
            except Exception as e:
                error("Couldn't send mail using the sendmail method: %s" % e)
                try:
                    connection.quit()
                except Exception as e:
                    logging.error(e)
                finally:
                    connection = None

        try:
            connection.quit()
        except AttributeError:
            pass
        except ssl.SSLError:
            connection.close()
    except Exception as e:
        error('Email sending has failed: %s: %s' % (type(e).__name__, e))

    return errors
