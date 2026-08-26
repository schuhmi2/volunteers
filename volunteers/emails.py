"""
Email notifications for the task signup approval workflow and task sign-in system.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

logger = logging.getLogger(__name__)


def safe_send_email(email_func, *args, **kwargs):
    """
    Safely call an email-sending function, catching all exceptions.
    Returns True if the email was sent successfully, False otherwise.
    Use this wrapper in views to prevent email failures from crashing the page.
    """
    try:
        email_func(*args, **kwargs)
        return True
    except Exception as e:
        logger.error(f'Failed to send email ({email_func.__name__}): {e}')
        return False


def _build_signin_url(token, action='signout'):
    """Build a full URL for sign-in/sign-out token links."""
    base = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    return f'{base}/{action}/{token}/'


def send_signout_link_email(attendance):
    """Send an email with a sign-out link after a volunteer signs in."""
    volunteer = attendance.volunteer_task.volunteer
    task = attendance.volunteer_task.task
    signout_url = _build_signin_url(attendance.signin_token, action='signout')

    subject = f'[FOSDEM Volunteers] Signed in: {task.name}'
    body = (
        f'Hi {volunteer.user.username},\n\n'
        f'Thanks for signing in to "{task.name}"!\n\n'
        f'If you need to leave before the task ends at {task.end_time.strftime("%H:%M")}, '
        f'please sign out using this link:\n\n'
        f'  {signout_url}\n\n'
        f'Otherwise you will be automatically signed out at the end of the task.\n\n'
        f'Thanks,\nFOSDEM Volunteers System'
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email='volunteer-admin@fosdem.org',
        to=[volunteer.user.email],
    )
    email.send(fail_silently=True)


def send_signin_reminder_email(attendance):
    """Send a reminder email before a task starts with the sign-in link."""
    volunteer = attendance.volunteer_task.volunteer
    task = attendance.volunteer_task.task
    signin_url = _build_signin_url(attendance.signin_token, action='signin')

    subject = f'[FOSDEM Volunteers] Reminder: {task.name} starts soon'
    body = (
        f'Hi {volunteer.user.username},\n\n'
        f'Your task "{task.name}" starts at {task.start_time.strftime("%H:%M")}.\n\n'
        f'Please sign in when you arrive:\n\n'
        f'  {signin_url}\n\n'
        f'Location: {task.location or "N/A"}\n\n'
        f'Thanks,\nFOSDEM Volunteers System'
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email='volunteer-admin@fosdem.org',
        to=[volunteer.user.email],
    )
    email.send(fail_silently=True)


def send_approval_request_email(volunteer, task):
    """
    Notify the task responsible that a volunteer has signed up
    for an approval-required task.
    """
    responsible = task.template.primary
    if not responsible or not responsible.email:
        return

    subject = f'[FOSDEM Volunteers] Approval needed: {volunteer.user.username} → {task.name}'

    body = (
        f'Hi {responsible.first_name or responsible.username},\n\n'
        f'{volunteer.user.username} has signed up for '
        f'"{task.name}" which requires your approval.\n\n'
        f'Task details:\n'
        f'  - Date: {task.date.strftime("%A %d %B %Y")}\n'
        f'  - Time: {task.start_time.strftime("%H:%M")} – {task.end_time.strftime("%H:%M")}\n'
        f'  - Location: {task.location or "N/A"}\n\n'
        f'Please approve or deny this request in the admin panel.\n\n'
        f'Thanks,\n'
        f'FOSDEM Volunteers System'
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email='volunteer-admin@fosdem.org',
        to=[responsible.email],
    )
    email.send(fail_silently=True)


def send_approval_decision_email(volunteer_task, approved):
    """
    Notify the volunteer that their sign-up has been approved or denied.
    """
    volunteer = volunteer_task.volunteer
    task = volunteer_task.task

    if not volunteer.user.email:
        return

    if approved:
        subject = f'[FOSDEM Volunteers] Approved: {task.name}'
        body = (
            f'Hi {volunteer.user.username},\n\n'
            f'Your sign-up for "{task.name}" has been approved!\n\n'
            f'Task details:\n'
            f'  - Date: {task.date.strftime("%A %d %B %Y")}\n'
            f'  - Time: {task.start_time.strftime("%H:%M")} – {task.end_time.strftime("%H:%M")}\n'
            f'  - Location: {task.location or "N/A"}\n\n'
            f'See you there!\n\n'
            f'Thanks,\n'
            f'FOSDEM Volunteers System'
        )
    else:
        subject = f'[FOSDEM Volunteers] Not approved: {task.name}'
        body = (
            f'Hi {volunteer.user.username},\n\n'
            f'Unfortunately, your sign-up for "{task.name}" was not approved.\n\n'
            f'This may be because the task requires specific training or prerequisites. '
            f'If you have questions, please reach out to the task organiser.\n\n'
            f'You are welcome to sign up for other tasks!\n\n'
            f'Thanks,\n'
            f'FOSDEM Volunteers System'
        )

    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email='volunteer-admin@fosdem.org',
        to=[volunteer.user.email],
    )
    email.send(fail_silently=True)
