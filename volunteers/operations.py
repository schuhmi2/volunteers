"""Aggregation service for the Admin Operations dashboard.

This module only reads data and returns plain dataclasses; it never
replaces the existing Approvals, Task Clashes, or Attendance pages. Every
attention item carries a deep link back to the page that owns the
underlying workflow, so this stays a triage cockpit rather than a
duplicate implementation of those flows.
"""
import datetime as _dt
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional

from django.conf import settings
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import RunnerDeployment, Task, TaskAttendance, VolunteerTask

SEVERITY_CRITICAL = 'critical'
SEVERITY_WARNING = 'warning'
SEVERITY_INFO = 'info'
SEVERITY_OK = 'ok'

_SEVERITY_ORDER = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
    SEVERITY_OK: 3,
}

WINDOW_MINUTES = {
    'now': 0,
    '30m': 30,
    '2h': 120,
    'today': 24 * 60,
    'all': None,
}
DEFAULT_WINDOW = '2h'

CHECKIN_LATE_GRACE_MINUTES = 10
CHECKIN_SOON_MINUTES = 15
APPROVAL_SOON_MINUTES = 120
APPROVAL_STALE_HOURS = 24


@dataclass
class AttentionItem:
    severity: str
    category: str
    title: str
    detail: str
    link: str = ''
    task_id: Optional[int] = None


@dataclass
class ReadinessCheck:
    label: str
    status: str
    detail: str


@dataclass
class RunnerStatus:
    volunteer_task_id: int
    volunteer_name: str
    task_name: str
    checked_in: bool


@dataclass
class DashboardData:
    generated_at: _dt.datetime
    window: str
    attention_items: List[AttentionItem] = field(default_factory=list)
    kpis: dict = field(default_factory=dict)
    runners: List[RunnerStatus] = field(default_factory=list)
    readiness: List[ReadinessCheck] = field(default_factory=list)


def _task_datetime(task, time_obj):
    return timezone.make_aware(
        _dt.datetime.combine(task.date, time_obj),
        timezone.get_current_timezone(),
    )


def _task_start(task):
    return _task_datetime(task, task.start_time)


def _task_end(task):
    return _task_datetime(task, task.end_time)


def _is_active(task, now):
    return _task_start(task) <= now <= _task_end(task)


def _starts_within(task, now, minutes):
    if minutes is None:
        return not _is_active(task, now)
    start = _task_start(task)
    return now < start <= now + timedelta(minutes=minutes)


def find_task_clashes(volunteer_tasks):
    """Return connected groups of overlapping active sign-ups for one volunteer.

    Shared by the Task Clashes dashboard and the Operations dashboard so
    clash detection is implemented in exactly one place.
    """
    signups = sorted(
        volunteer_tasks,
        key=lambda vt: (
            vt.task.date,
            vt.task.start_time,
            vt.task.end_time,
            vt.task.name,
        ),
    )
    intentional_pairs = {
        frozenset((runner_id, destination_id))
        for runner_id, destination_id in RunnerDeployment.objects.filter(
            runner_assignment_id__in=[signup.pk for signup in signups],
            destination_assignment_id__in=[signup.pk for signup in signups],
            status__in=('active', 'completed'),
        ).values_list('runner_assignment_id', 'destination_assignment_id')
    }
    parents = list(range(len(signups)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first_index, second_index):
        first_root = find(first_index)
        second_root = find(second_index)
        if first_root != second_root:
            parents[second_root] = first_root

    for index, first in enumerate(signups):
        for second_index in range(index + 1, len(signups)):
            second = signups[second_index]
            if second.task.date != first.task.date:
                if second.task.date > first.task.date:
                    break
                continue
            if second.task.start_time >= first.task.end_time:
                break
            if (
                first.task.start_time < second.task.end_time
                and second.task.start_time < first.task.end_time
                and frozenset((first.pk, second.pk)) not in intentional_pairs
                and not (
                    first.task.name == second.task.name
                    and first.task.location == second.task.location
                )
            ):
                union(index, second_index)

    groups = {}
    for index, signup in enumerate(signups):
        groups.setdefault(find(index), []).append(signup)
    return [group for group in groups.values() if len(group) > 1]


def _staffing_items(scoped_tasks, now):
    items = []
    for task in scoped_tasks:
        if task.approved_count < task.nbr_volunteers_min:
            severity = SEVERITY_CRITICAL
        elif task.approved_count < task.nbr_volunteers:
            severity = SEVERITY_WARNING
        else:
            continue
        when = _('now') if _is_active(task, now) else _('soon')
        items.append(AttentionItem(
            severity=severity,
            category=_('Staffing'),
            title=_('%(task)s needs volunteers') % {'task': task.name},
            detail=_('%(approved)d approved of %(min)d minimum (%(target)d target) \u2014 %(when)s') % {
                'approved': task.approved_count,
                'min': task.nbr_volunteers_min,
                'target': task.nbr_volunteers,
                'when': when,
            },
            task_id=task.id,
            link=reverse('task_detailed', args=[task.id]),
        ))
    return items


def _checkin_items(scoped_tasks, now, signin_enabled):
    items = []
    if not signin_enabled:
        return items
    relevant_tasks = [
        task for task in scoped_tasks
        if _is_active(task, now) or _starts_within(task, now, CHECKIN_SOON_MINUTES)
    ]
    task_ids = [task.id for task in relevant_tasks]
    if not task_ids:
        return items
    approved_vts = (
        VolunteerTask.objects.filter(task_id__in=task_ids, status='approved')
        .select_related('volunteer__user', 'task')
        .prefetch_related('attendance')
    )
    for vt in approved_vts:
        task = vt.task
        try:
            attendance = vt.attendance
        except TaskAttendance.DoesNotExist:
            attendance = None
        if attendance and attendance.signed_in_at:
            continue
        active = _is_active(task, now)
        start = _task_start(task)
        volunteer_name = vt.volunteer.user.get_full_name() or vt.volunteer.user.username
        link = reverse('attendance_task_detail', args=[task.id])
        if active and now >= start + timedelta(minutes=CHECKIN_LATE_GRACE_MINUTES):
            items.append(AttentionItem(
                severity=SEVERITY_CRITICAL,
                category=_('Check-in'),
                title=_('%(name)s has not checked in') % {'name': volunteer_name},
                detail=_('%(task)s started %(minutes)d minute(s) ago') % {
                    'task': task.name,
                    'minutes': int((now - start).total_seconds() // 60),
                },
                task_id=task.id,
                link=link,
            ))
        elif not active and _starts_within(task, now, CHECKIN_SOON_MINUTES):
            items.append(AttentionItem(
                severity=SEVERITY_WARNING,
                category=_('Check-in'),
                title=_('%(name)s has not checked in yet') % {'name': volunteer_name},
                detail=_('%(task)s starts soon') % {'task': task.name},
                task_id=task.id,
                link=link,
            ))
    return items


def _available_runner_statuses(edition, now):
    runner_tasks = [
        task for task in Task.objects.filter(
            edition=edition, name__iexact='Runner', date=now.date(),
        )
        if _is_active(task, now)
    ]
    task_ids = [task.id for task in runner_tasks]
    if not task_ids:
        return []
    open_assignments = RunnerDeployment.objects.filter(
        status__in=('pending', 'active'),
    ).values_list('runner_assignment_id', flat=True)
    approved_vts = (
        VolunteerTask.objects.filter(task_id__in=task_ids, status='approved')
        .exclude(id__in=open_assignments)
        .select_related('volunteer__user', 'task')
        .prefetch_related('attendance')
    )
    statuses = []
    for vt in approved_vts:
        try:
            attendance = vt.attendance
        except TaskAttendance.DoesNotExist:
            attendance = None
        statuses.append(RunnerStatus(
            volunteer_task_id=vt.id,
            volunteer_name=vt.volunteer.user.get_full_name() or vt.volunteer.user.username,
            task_name=vt.task.name,
            checked_in=bool(attendance and attendance.signed_in_at and not attendance.signed_out_at),
        ))
    return statuses


def _approval_items(edition, now):
    items = []
    pending = (
        VolunteerTask.objects.filter(task__edition=edition, status='pending')
        .select_related('volunteer__user', 'task')
    )
    for vt in pending:
        task = vt.task
        if _is_active(task, now) and task.assigned_volunteers() < task.nbr_volunteers_min:
            severity = SEVERITY_CRITICAL
        elif _starts_within(task, now, APPROVAL_SOON_MINUTES):
            severity = SEVERITY_WARNING
        elif vt.requested_at and now - vt.requested_at >= timedelta(hours=APPROVAL_STALE_HOURS):
            severity = SEVERITY_WARNING
        else:
            continue
        volunteer_name = vt.volunteer.user.get_full_name() or vt.volunteer.user.username
        items.append(AttentionItem(
            severity=severity,
            category=_('Approvals'),
            title=_('Pending signup: %(name)s for %(task)s') % {
                'name': volunteer_name, 'task': task.name,
            },
            detail=_('Awaiting approval'),
            task_id=task.id,
            link=reverse('approval_dashboard'),
        ))
    return items


def _clash_items(edition, now):
    items = []
    signups = list(
        VolunteerTask.objects.filter(task__edition=edition, status__in=('approved', 'pending'))
        .select_related('volunteer__user', 'task')
    )
    by_volunteer = {}
    for signup in signups:
        by_volunteer.setdefault(signup.volunteer_id, []).append(signup)
    link = reverse('task_clashes_dashboard')
    for volunteer_signups in by_volunteer.values():
        for group in find_task_clashes(volunteer_signups):
            relevant = [
                signup for signup in group
                if _is_active(signup.task, now) or _starts_within(signup.task, now, APPROVAL_SOON_MINUTES)
            ]
            if not relevant:
                continue
            severity = (
                SEVERITY_CRITICAL if any(_is_active(signup.task, now) for signup in relevant)
                else SEVERITY_WARNING
            )
            volunteer_name = group[0].volunteer.user.get_full_name() or group[0].volunteer.user.username
            task_names = ', '.join(sorted({signup.task.name for signup in group}))
            items.append(AttentionItem(
                severity=severity,
                category=_('Clashes'),
                title=_('Task clash: %(name)s') % {'name': volunteer_name},
                detail=task_names,
                link=link,
            ))
    return items


def get_readiness_checks(edition):
    """Cheap exists()/count() checks summarizing edition setup completeness."""
    checks = []
    today = timezone.localdate()

    if not edition:
        checks.append(ReadinessCheck(_('Current edition'), SEVERITY_CRITICAL, _('No current edition configured.')))
        return checks
    if edition.visible_from <= today <= edition.visible_until:
        checks.append(ReadinessCheck(_('Current edition'), SEVERITY_OK, edition.name))
    else:
        checks.append(ReadinessCheck(
            _('Current edition'), SEVERITY_WARNING,
            _('Edition visible window does not include today.'),
        ))

    task_count = Task.objects.filter(edition=edition).count()
    if task_count:
        checks.append(ReadinessCheck(
            _('Tasks imported'), SEVERITY_OK,
            _('%(count)d task(s) for this edition.') % {'count': task_count},
        ))
    else:
        checks.append(ReadinessCheck(_('Tasks imported'), SEVERITY_CRITICAL, _('No tasks found for this edition.')))

    if edition.enable_task_signin:
        checks.append(ReadinessCheck(_('Task sign-in'), SEVERITY_OK, _('Enabled for this edition.')))
        email_enabled = getattr(settings, 'SIGNIN_EMAIL_ENABLED', False)
        matrix_enabled = getattr(settings, 'SIGNIN_MATRIX_ENABLED', False)
        if not email_enabled and not matrix_enabled:
            checks.append(ReadinessCheck(
                _('Sign-in notifications'), SEVERITY_WARNING,
                _('Sign-in is enabled but no reminder channel (email/Matrix) is configured.'),
            ))
        else:
            channels = [name for enabled, name in (
                (email_enabled, _('email')), (matrix_enabled, _('Matrix')),
            ) if enabled]
            checks.append(ReadinessCheck(
                _('Sign-in notifications'), SEVERITY_OK,
                _('Enabled channels: %(channels)s') % {'channels': ', '.join(channels)},
            ))
        if matrix_enabled:
            if getattr(settings, 'MATRIX_BOT_HOMESERVER', '') and getattr(settings, 'MATRIX_BOT_TOKEN', ''):
                checks.append(ReadinessCheck(_('Matrix bot'), SEVERITY_OK, _('Homeserver and token configured.')))
            else:
                checks.append(ReadinessCheck(
                    _('Matrix bot'), SEVERITY_WARNING,
                    _('Matrix sign-in is enabled but bot credentials are incomplete.'),
                ))
    else:
        checks.append(ReadinessCheck(
            _('Task sign-in'), SEVERITY_INFO,
            _('Not enabled for this edition; attendance/check-in widgets are disabled.'),
        ))

    unmapped = Task.objects.filter(edition=edition, location_ref__isnull=True).exclude(location='').count()
    if unmapped:
        checks.append(ReadinessCheck(
            _('Location mapping'), SEVERITY_WARNING,
            _('%(count)d task(s) have an unmapped location.') % {'count': unmapped},
        ))
    else:
        checks.append(ReadinessCheck(_('Location mapping'), SEVERITY_OK, _('All task locations are mapped.')))

    checks.append(ReadinessCheck(
        _('Automation health'), SEVERITY_INFO,
        _('Not yet tracked \u2014 planned for a follow-up phase.'),
    ))
    return checks


def get_operations_dashboard(edition, now=None, window=DEFAULT_WINDOW):
    """Build all data needed to render the Operations dashboard.

    Bounded to a +/-1 day slice of the edition's tasks so this never scans
    the whole event's schedule on every request; annotated counts are
    fetched in one query rather than per-task loops.
    """
    now = now or timezone.now()
    window_minutes = WINDOW_MINUTES.get(window, WINDOW_MINUTES[DEFAULT_WINDOW])
    today = now.date()

    all_tasks = list(
        Task.objects.filter(
            edition=edition,
            date__range=(today - timedelta(days=1), today + timedelta(days=1)),
        ).select_related('template', 'template__category', 'location_ref')
    )

    if window == 'all':
        scoped_tasks = list(all_tasks)
    else:
        scoped_tasks = [
            task for task in all_tasks
            if _is_active(task, now) or _starts_within(task, now, window_minutes)
        ]

    task_ids = [task.id for task in scoped_tasks]
    counts_by_task = {}
    if task_ids:
        rows = (
            VolunteerTask.objects.filter(task_id__in=task_ids)
            .values('task_id', 'status')
            .annotate(count=Count('id'))
        )
        for row in rows:
            counts_by_task.setdefault(row['task_id'], {})[row['status']] = row['count']
    for task in scoped_tasks:
        task.approved_count = counts_by_task.get(task.id, {}).get('approved', 0)
        task.pending_count = counts_by_task.get(task.id, {}).get('pending', 0)

    attention_items = []
    attention_items += _staffing_items(scoped_tasks, now)
    attention_items += _checkin_items(scoped_tasks, now, edition.enable_task_signin)
    attention_items += _approval_items(edition, now)
    attention_items += _clash_items(edition, now)

    runner_statuses = _available_runner_statuses(edition, now)
    has_critical_staffing_gap = any(
        item.category == _('Staffing') and item.severity == SEVERITY_CRITICAL
        for item in attention_items
    )
    if not runner_statuses and has_critical_staffing_gap:
        attention_items.append(AttentionItem(
            severity=SEVERITY_CRITICAL,
            category=_('Runners'),
            title=_('No available runners'),
            detail=_('All runner-task volunteers are already deployed or checked out.'),
            link=reverse('attendance_dashboard'),
        ))

    attention_items.sort(key=lambda item: _SEVERITY_ORDER.get(item.severity, 9))

    active_tasks = [task for task in all_tasks if _is_active(task, now)]
    starting_soon = [
        task for task in all_tasks
        if not _is_active(task, now) and _starts_within(task, now, 60)
    ]
    below_min = [task for task in scoped_tasks if task.approved_count < task.nbr_volunteers_min]
    below_target = [
        task for task in scoped_tasks
        if task.nbr_volunteers_min <= task.approved_count < task.nbr_volunteers
    ]
    pending_approvals_count = VolunteerTask.objects.filter(task__edition=edition, status='pending').count()
    clash_count = sum(1 for item in attention_items if item.category == _('Clashes'))

    kpis = {
        'active_tasks': len(active_tasks),
        'starting_soon': len(starting_soon),
        'below_min': len(below_min),
        'below_target': len(below_target),
        'pending_approvals': pending_approvals_count,
        'clashes': clash_count,
        'available_runners': len(runner_statuses),
        'checked_in_runners': sum(1 for runner in runner_statuses if runner.checked_in),
    }

    return DashboardData(
        generated_at=now,
        window=window,
        attention_items=attention_items,
        kpis=kpis,
        runners=runner_statuses,
        readiness=get_readiness_checks(edition),
    )
