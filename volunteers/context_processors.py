from django.contrib import admin
from django.db.models import Q

from .models import TaskTemplate
from .permissions import has_permission


def operational_navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {'operational_nav': {}}

    is_responsible = user.is_staff and TaskTemplate.objects.filter(
        Q(primary=user) | Q(secondary=user)
    ).exists()
    flags = {
        'schedules': (
            has_permission(user, 'export_task_schedules')
            or is_responsible
        ),
        'approvals': has_permission(user, 'manage_approvals') or is_responsible,
        'clashes': has_permission(user, 'manage_task_clashes') or is_responsible,
        'attendance': has_permission(user, 'manage_attendance') or is_responsible,
        'labels': has_permission(user, 'manage_labels'),
        'tshirts': has_permission(user, 'view_tshirt_report'),
        'matrix_ids': has_permission(user, 'export_matrix_ids'),
        'django_admin': (
            user.is_staff
            and bool(admin.site.get_app_list(request))
        ),
    }
    flags['admin_any'] = any(
        value
        for name, value in flags.items()
        if name != 'schedules'
    )
    return {'operational_nav': flags}
