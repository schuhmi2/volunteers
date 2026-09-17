"""
Targeted informational email: task / task category / individual volunteer.

Deliberately lightweight - no persistent delivery audit, retry queue, or
dedupe/cooldown tracking. Each send is synchronous and one-off, matching the
existing mass-mail admin actions this replaces in the normal app.
"""
from django.conf import settings
from django.core.mail import send_mass_mail

from .models import Task, TaskCategory, Volunteer


def audience_for_task(task, include_pending=False):
    """Volunteers assigned to a specific task, approved (+ optionally pending)."""
    statuses = ['approved', 'pending'] if include_pending else ['approved']
    return (
        Volunteer.objects.filter(
            volunteertask__task=task,
            volunteertask__status__in=statuses,
        )
        .distinct()
        .select_related('user')
        .order_by('user__first_name', 'user__last_name')
    )


def audience_for_category(category, edition, include_pending=False):
    """Volunteers assigned to any task in this category for the given edition."""
    statuses = ['approved', 'pending'] if include_pending else ['approved']
    return (
        Volunteer.objects.filter(
            volunteertask__task__template__category=category,
            volunteertask__task__edition=edition,
            volunteertask__status__in=statuses,
        )
        .distinct()
        .select_related('user')
        .order_by('user__first_name', 'user__last_name')
    )


def audience_for_edition(edition, include_pending=False):
    """Every volunteer signed up to any task for the given edition."""
    statuses = ['approved', 'pending'] if include_pending else ['approved']
    return (
        Volunteer.objects.filter(
            volunteertask__task__edition=edition,
            volunteertask__status__in=statuses,
        )
        .distinct()
        .select_related('user')
        .order_by('user__first_name', 'user__last_name')
    )


def send_info_email(subject, message, volunteers):
    """Send one message per recipient (no shared To/CC, for privacy).

    Returns (sent_count, skipped_no_email_count).
    """
    sent = 0
    skipped = 0
    for volunteer in volunteers:
        if not volunteer.user.email:
            skipped += 1
            continue
        send_mass_mail(
            ((subject, message, settings.DEFAULT_FROM_EMAIL, [volunteer.user.email]),),
            fail_silently=False,
        )
        sent += 1
    return sent, skipped
