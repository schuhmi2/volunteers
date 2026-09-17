from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import TaskTemplate


ROLE_PERMISSIONS = {
    'Coordinator': {
        'manage_approvals',
        'manage_task_clashes',
        'manage_attendance',
        'assign_volunteers',
        'event_signon',
        'view_other_schedules',
        'export_task_schedules',
    },
    'Logistics': {
        'manage_labels',
        'view_tshirt_report',
        'export_matrix_ids',
    },
    'Communications': {
        'send_mass_mail',
    },
}


def has_permission(user, codename):
    return bool(
        user.is_authenticated
        and user.has_perm(f'volunteers.{codename}')
    )


def is_template_responsible(user, template):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    return user.pk in {
        template.primary_id,
        template.secondary_id,
    }


def is_task_responsible(user, task):
    return is_template_responsible(user, task.template)


def has_responsible_templates(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    return TaskTemplate.objects.filter(
        Q(primary=user) | Q(secondary=user)
    ).exists()


def can_manage_task(user, task):
    return has_permission(user, 'assign_volunteers') or is_task_responsible(user, task)


def can_approve_task(user, task):
    return has_permission(user, 'manage_approvals') or is_task_responsible(user, task)


def can_manage_task_attendance(user, task):
    return has_permission(user, 'manage_attendance') or is_task_responsible(user, task)


def can_view_template_schedule(user, template):
    return (
        has_permission(user, 'export_task_schedules')
        or is_template_responsible(user, template)
    )


def can_message_task(user, task):
    return has_permission(user, 'send_mass_mail') or is_task_responsible(user, task)


def can_message_category(user, category):
    if has_permission(user, 'send_mass_mail'):
        return True
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    return TaskTemplate.objects.filter(category=category).filter(
        Q(primary=user) | Q(secondary=user)
    ).exists()


def can_message_edition(user):
    """Coordinators and superusers may email everyone signed up for the current edition."""
    return has_permission(user, 'send_mass_mail') or has_permission(user, 'manage_approvals')


def can_view_operations_dashboard(user):
    """Superusers and Coordinators may view the aggregated Operations dashboard.

    ``has_permission`` already returns True for superusers via Django's
    built-in ``user.has_perm`` short-circuit, so checking the Coordinator-only
    'manage_approvals' permission covers both roles.
    """
    return has_permission(user, 'manage_approvals')


def messageable_categories(user):
    """Task categories this user may compose an informational email to."""
    from .models import TaskCategory
    if has_permission(user, 'send_mass_mail'):
        return TaskCategory.objects.filter(active=True)
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return TaskCategory.objects.none()
    return TaskCategory.objects.filter(
        active=True,
        tasktemplate__in=TaskTemplate.objects.filter(
            Q(primary=user) | Q(secondary=user)
        ),
    ).distinct()


def permission_required(codename):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_permission(request.user, codename):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def log_operational_action(request, obj, message):
    LogEntry.objects.log_action(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.get_for_model(
            obj,
            for_concrete_model=False,
        ).pk,
        object_id=str(obj.pk),
        object_repr=str(obj)[:200],
        action_flag=CHANGE,
        change_message=message,
    )
