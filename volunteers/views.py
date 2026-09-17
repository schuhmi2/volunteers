from django.utils import timezone
from datetime import timedelta
import datetime as _dt

from .models import Volunteer, VolunteerTask, VolunteerTalk, TaskCategory, TaskTemplate, Task, Track, \
    Talk, Edition, EmailConfirmation, LabelPrintLog, RunnerDeployment, TaskAttendance, \
    CURRENT_PRIVACY_POLICY_VERSION
from .forms import EditProfileForm, SignupForm, EventSignupForm, EmailChangeForm, ResendActivationForm, \
    ComposeInfoEmailForm
from .runner_deployments import (
    approve_runner_deployment,
    complete_runner_deployment,
    deny_runner_deployment,
    request_runner_deployment,
)
from .communications import audience_for_category, audience_for_edition, audience_for_task, send_info_email

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.generic.list import ListView
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from collections import OrderedDict as SortedDict
from django.utils.translation import gettext as _
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.contrib.auth import get_user_model

from django.http import Http404
import csv
import uuid

# PDF generation (optional for local development)
try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None
from django.template.loader import get_template
from django.template import Context
from django.utils.html import escape

from .permissions import (
    can_approve_task,
    can_manage_task,
    can_manage_task_attendance,
    can_message_category,
    can_message_edition,
    can_message_task,
    can_view_template_schedule,
    has_permission,
    has_responsible_templates,
    is_task_responsible,
    log_operational_action,
    messageable_categories,
    permission_required,
)

from django.views.generic import TemplateView


def check_profile_completeness(request, volunteer):
    if request.user != volunteer.user:
        return True

    if not volunteer.mobile_nbr:
        messages.warning(request, _(
            "Hey there! It seems you didn't give us a phone number. Please update your profile, to make sure we can contact you if the network fails..."),
                         fail_silently=True)
    if not volunteer.check_mugshot():
        messages.warning(request, _(
            "Looks like we don't have your beautiful smile in our system. Be so kind to upload a mugshot in your profile page. :)"),
                         fail_silently=True)


def faq(request):
    return render(request, 'static/faq.html')


def privacy_policy(request):
    return render(request, 'static/privacy_policy.html')


def _attach_prior_task_experience(signups):
    for signup in signups:
        previous = VolunteerTask.objects.filter(
            volunteer=signup.volunteer,
            task__template=signup.task.template,
            task__edition__start_date__lt=signup.task.edition.start_date,
            status='approved',
        ).select_related('task__edition')
        signup.prior_assignment_count = previous.count()
        signup.prior_edition_names = list(
            previous.order_by('-task__edition__start_date')
            .values_list('task__edition__name', flat=True)
            .distinct()
        )
        signup.prior_attendance_count = TaskAttendance.objects.filter(
            volunteer_task__in=previous,
            signed_in_at__isnull=False,
        ).count()


def promo(request):
    return render(request, 'static/promo.html')


@login_required
def talk_detailed(request, talk_id):
    talk = get_object_or_404(Talk, id=talk_id)
    context = {'talk': talk}
    return render(request, 'volunteers/talk_detailed.html', context)


def task_detailed(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    context = {'task': task}
    # Only admins can see the named list of volunteers on this task; everyone
    # else only sees a count (see template). This matches the privacy policy's
    # "current-edition tasks visible only to self + admin" rule.
    can_view_volunteer_names = can_manage_task(request.user, task)
    context['can_view_volunteer_names'] = can_view_volunteer_names
    context['can_message_this_task'] = can_message_task(request.user, task)
    # Let the volunteer know their own signup status for this task.
    context['own_signup_status'] = None
    if request.user.is_authenticated:
        volunteer = getattr(request.user, 'volunteer', None)
        if volunteer:
            own_vt = VolunteerTask.objects.filter(task=task, volunteer=volunteer).first()
            if own_vt:
                context['own_signup_status'] = own_vt.status
    if can_view_volunteer_names:
        # Provide list of all volunteers for admin assignment dropdown
        assigned_volunteer_ids = task.volunteers.values_list('id', flat=True)
        context['assignable_volunteers'] = (
            Volunteer.objects.select_related('user')
            .exclude(id__in=assigned_volunteer_ids)
            .order_by('user__first_name', 'user__last_name')
        )
        # Pending approval signups
        context['pending_signups'] = list(
            VolunteerTask.objects.filter(task=task, status='pending')
            .select_related('volunteer__user')
        )
        _attach_prior_task_experience(context['pending_signups'])
    return render(request, 'volunteers/task_detailed.html', context)


@login_required
def admin_assign_volunteer(request, task_id):
    """Assign or remove a volunteer when the actor manages this task."""
    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task(request.user, task):
        raise PermissionDenied

    if request.method == 'POST':
        volunteer_id = request.POST.get('volunteer_id')
        action = request.POST.get('action', 'assign')

        if action == 'assign' and volunteer_id:
            volunteer = get_object_or_404(Volunteer, id=volunteer_id)
            signup, created = VolunteerTask.objects.get_or_create(
                task=task,
                volunteer=volunteer,
                defaults={'status': 'approved'},
            )
            if not created and signup.status != 'approved':
                signup.status = 'approved'
                signup.reviewed_at = timezone.now()
                signup.reviewed_by = request.user
                signup.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])
            log_operational_action(
                request,
                signup,
                f'Assigned {volunteer.user.username} to task {task.pk}',
            )
            messages.success(
                request,
                _('%(name)s has been assigned to this task.') % {
                    'name': f'{volunteer.user.first_name} {volunteer.user.last_name}'
                }
            )
        elif action == 'unassign' and volunteer_id:
            volunteer = get_object_or_404(Volunteer, id=volunteer_id)
            signup = get_object_or_404(
                VolunteerTask,
                task=task,
                volunteer=volunteer,
            )
            if (
                signup.runner_deployments.exists()
                or signup.destination_deployments.exists()
            ):
                messages.error(
                    request,
                    _('This assignment is part of a recorded runner deployment and cannot be removed.'),
                )
            else:
                log_operational_action(
                    request,
                    signup,
                    f'Removed {volunteer.user.username} from task {task.pk}',
                )
                signup.delete()
                messages.success(
                    request,
                    _('%(name)s has been removed from this task.') % {
                        'name': f'{volunteer.user.first_name} {volunteer.user.last_name}'
                    }
                )

    return redirect('task_detailed', task_id=task.id)


@login_required
def talk_list(request):
    # get the signed in volunteer
    volunteer = Volunteer.objects.get(user=request.user)

    # when the user submitted the form
    if request.method == 'POST':
        # get the checked tasks
        talk_ids = request.POST.getlist('talk')

        # go trough all the talks that were checked
        for talk in Talk.objects.filter(id__in=talk_ids):
            # add the volunteer to the talk when he/she is not added
            VolunteerTalk.objects.get_or_create(talk=talk, volunteer=volunteer)

        # delete all the not checked talks
        VolunteerTalk.objects.filter(volunteer=volunteer).exclude(talk_id__in=talk_ids).delete()

        messages.success(request, _('Your talks have been updated.'), fail_silently=True)

        # redirect to prevent repost
        return redirect('talk_list')

    # group the talks according to tracks
    context = {'talks': [], 'checked': {}}

    talks = Talk.objects.select_related('track').filter(track__edition=Edition.get_current()).order_by('track__title', 'date', 'start_time')

    context['talks'] = talks

    # mark checked, attending talks
    for talk in Talk.objects.filter(volunteers=volunteer):
        context['checked'][talk.id] = 'checked'

    return render(request, 'volunteers/talks.html', context)


@login_required
def category_schedule_list(request):
    templates = TaskTemplate.objects.filter(category__active=True)
    if not has_permission(request.user, 'export_task_schedules'):
        templates = templates.filter(
            Q(primary=request.user) | Q(secondary=request.user)
        )
    if not templates.exists():
        raise PermissionDenied

    categories = TaskCategory.objects.filter(
        active=True,
        tasktemplate__in=templates,
    ).distinct()
    context = {'categories': SortedDict.fromkeys(categories, [])}
    for category in context['categories']:
        context['categories'][category] = templates.filter(category=category)
    context['messageable_category_ids'] = set(
        messageable_categories(request.user).values_list('id', flat=True)
    )
    return render(request, 'volunteers/category_schedule_list.html', context)


@login_required
def task_schedule(request, template_id):
    template = get_object_or_404(TaskTemplate, id=template_id)
    if not can_view_template_schedule(request.user, template):
        raise PermissionDenied
    tasks = Task.objects.annotate(volunteers__count=Count("volunteer")).filter(template=template, edition=Edition.get_current()).order_by('date', 'start_time', 'end_time')
    context = {
        'template': template,
        'tasks': SortedDict.fromkeys(tasks, {}),
    }
    for task in context['tasks']:
        context['tasks'][task] = task.approved_volunteers().select_related('user')
    return render(request, 'volunteers/task_schedule.html', context)


@login_required
def task_schedule_csv(request, template_id):
    template = get_object_or_404(TaskTemplate, id=template_id)
    if not can_view_template_schedule(request.user, template):
        raise PermissionDenied
    tasks = Task.objects.annotate(volunteers__count=Count("volunteer")).filter(template=template, edition=Edition.get_current()).order_by('date', 'start_time', 'end_time')
    response = HttpResponse(content_type='text/csv')
    filename = "schedule_%s.csv" % template.name
    response['Content-Disposition'] = 'attachment; filename="%s"' % filename.replace('"', '_')

    writer = csv.writer(response)
    writer.writerow(['Task', 'Volunteers', 'Day', 'Start', 'End', 'Documentation', 'Volunteer', 'Nick', 'Email', 'Mobile', 'Matrix_id'])
    for task in tasks:
        row = [
            task.name,
            "(%s/%s)" % (task.assigned_volunteers(), task.nbr_volunteers),
            task.date.strftime('%a'),
            task.start_time.strftime('%H:%M'),
            task.end_time.strftime('%H:%M'),
            task.info_url or '',
            '', '', '', '', ''
        ]
        writer.writerow(row)
        volunteers = task.approved_volunteers().select_related('user')
        for number, volunteer in enumerate(volunteers):
            row = [
                '', '', '', '', '', '',
                "%s %s" % (volunteer.user.first_name, volunteer.user.last_name),
                volunteer.user.username,
                volunteer.user.email,
                volunteer.mobile_nbr,
                volunteer.matrix_id
            ]
            writer.writerow(row)
        row = [''] * 11
        writer.writerow(row)
    return response


def _handle_compose_request(request, recipients, skipped, on_send):
    """Shared preview -> confirm -> send flow for the informational email compose views.

    Populates request._compose_form and request._compose_preview for the caller to
    render the initial/preview form. Returns an HttpResponse once the message has
    actually been sent (or None while still composing/previewing).
    """
    form = ComposeInfoEmailForm(request.POST or None)
    action = request.POST.get('action') if request.method == 'POST' else None
    request._compose_form = form
    request._compose_preview = False

    if action == 'send' and form.is_valid():
        sent, _skipped_on_send = send_info_email(
            form.cleaned_data['subject'],
            form.cleaned_data['message'],
            recipients,
        )
        return on_send(sent, form)

    if action == 'preview' and form.is_valid():
        request._compose_preview = True

    return None


@login_required
def communications_dashboard(request):
    """Entry point listing tasks/categories the user may send informational email to."""
    edition = Edition.get_current()
    templates = TaskTemplate.objects.filter(category__active=True)
    if not has_permission(request.user, 'send_mass_mail'):
        templates = templates.filter(
            Q(primary=request.user) | Q(secondary=request.user)
        )
    can_message_this_edition = can_message_edition(request.user)
    if not templates.exists() and not can_message_this_edition:
        raise PermissionDenied

    tasks = Task.objects.none()
    if edition:
        tasks = (
            Task.objects.filter(template__in=templates, edition=edition)
            .select_related('template')
            .order_by('date', 'start_time', 'name')
        )
    context = {
        'edition': edition,
        'categories': messageable_categories(request.user),
        'tasks': tasks,
        'can_message_this_edition': can_message_this_edition,
    }
    return render(request, 'volunteers/communication_dashboard.html', context)


@login_required
def edition_email_compose(request):
    """Compose/preview/send an informational email to everyone signed up for the current edition."""
    if not can_message_edition(request.user):
        raise PermissionDenied
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('communications_dashboard')

    include_pending = request.POST.get('include_pending') == 'on'
    audience = list(audience_for_edition(edition, include_pending=include_pending))
    skipped = [v for v in audience if not v.user.email]
    recipients = [v for v in audience if v.user.email]

    def on_send(sent, form):
        log_operational_action(
            request,
            edition,
            f'Sent informational email "{form.cleaned_data["subject"]}" to {sent} volunteer(s) for edition {edition.pk}',
        )
        messages.success(
            request,
            _('Email sent to %(sent)d volunteer(s). %(skipped)d skipped (no email on file).') % {
                'sent': sent,
                'skipped': len(skipped),
            },
        )
        return redirect('communications_dashboard')

    result = _handle_compose_request(request, recipients, skipped, on_send)
    if result is not None:
        return result

    context = {
        'audience_label': _('all volunteers — %(edition)s') % {'edition': edition.name},
        'audience_type': 'edition',
        'edition': edition,
        'recipients': recipients,
        'skipped': skipped,
        'include_pending': include_pending,
        'form': request._compose_form,
        'preview': request._compose_preview,
        'action_url': reverse('edition_email_compose'),
        'cancel_url': reverse('communications_dashboard'),
    }
    return render(request, 'volunteers/communication_compose.html', context)


@login_required
def task_email_compose(request, task_id):
    """Compose/preview/send an informational email to a task's signed-up volunteers."""
    task = get_object_or_404(Task, id=task_id)
    if not can_message_task(request.user, task):
        raise PermissionDenied

    include_pending = request.POST.get('include_pending') == 'on'
    audience = list(audience_for_task(task, include_pending=include_pending))
    skipped = [v for v in audience if not v.user.email]
    recipients = [v for v in audience if v.user.email]

    def on_send(sent, form):
        log_operational_action(
            request,
            task,
            f'Sent informational email "{form.cleaned_data["subject"]}" to {sent} volunteer(s) for task {task.pk}',
        )
        messages.success(
            request,
            _('Email sent to %(sent)d volunteer(s). %(skipped)d skipped (no email on file).') % {
                'sent': sent,
                'skipped': len(skipped),
            },
        )
        return redirect('task_detailed', task_id=task.id)

    result = _handle_compose_request(request, recipients, skipped, on_send)
    if result is not None:
        return result

    context = {
        'audience_label': task.name,
        'audience_type': 'task',
        'task': task,
        'recipients': recipients,
        'skipped': skipped,
        'include_pending': include_pending,
        'form': request._compose_form,
        'preview': request._compose_preview,
        'action_url': reverse('task_email_compose', args=[task.id]),
        'cancel_url': reverse('task_detailed', args=[task.id]),
    }
    return render(request, 'volunteers/communication_compose.html', context)


@login_required
def category_email_compose(request, category_id):
    """Compose/preview/send an informational email to a category's signed-up volunteers."""
    category = get_object_or_404(TaskCategory, id=category_id)
    if not can_message_category(request.user, category):
        raise PermissionDenied
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('communications_dashboard')

    include_pending = request.POST.get('include_pending') == 'on'
    audience = list(audience_for_category(category, edition, include_pending=include_pending))
    skipped = [v for v in audience if not v.user.email]
    recipients = [v for v in audience if v.user.email]

    def on_send(sent, form):
        log_operational_action(
            request,
            category,
            f'Sent informational email "{form.cleaned_data["subject"]}" to {sent} volunteer(s) for category {category.pk}',
        )
        messages.success(
            request,
            _('Email sent to %(sent)d volunteer(s). %(skipped)d skipped (no email on file).') % {
                'sent': sent,
                'skipped': len(skipped),
            },
        )
        return redirect('communications_dashboard')

    result = _handle_compose_request(request, recipients, skipped, on_send)
    if result is not None:
        return result

    context = {
        'audience_label': category.name,
        'audience_type': 'category',
        'category': category,
        'recipients': recipients,
        'skipped': skipped,
        'include_pending': include_pending,
        'form': request._compose_form,
        'preview': request._compose_preview,
        'action_url': reverse('category_email_compose', args=[category.id]),
        'cancel_url': reverse('communications_dashboard'),
    }
    return render(request, 'volunteers/communication_compose.html', context)


@login_required
def volunteer_email_compose(request, task_id, volunteer_id):
    """Compose/preview/send a one-off informational email to a single volunteer assigned to this task."""
    task = get_object_or_404(Task, id=task_id)
    if not can_message_task(request.user, task):
        raise PermissionDenied
    volunteer = get_object_or_404(
        Volunteer.objects.select_related('user'),
        id=volunteer_id,
        volunteertask__task=task,
        volunteertask__status__in=('approved', 'pending'),
    )
    recipients = [volunteer] if volunteer.user.email else []
    skipped = [] if volunteer.user.email else [volunteer]

    def on_send(sent, form):
        log_operational_action(
            request,
            task,
            f'Sent informational email "{form.cleaned_data["subject"]}" to '
            f'{volunteer.user.username} for task {task.pk}',
        )
        if sent:
            messages.success(request, _('Email sent to %s.') % volunteer.user.get_full_name())
        else:
            messages.error(request, _('This volunteer has no email on file; nothing was sent.'))
        return redirect('task_detailed', task_id=task.id)

    result = _handle_compose_request(request, recipients, skipped, on_send)
    if result is not None:
        return result

    context = {
        'audience_label': volunteer.user.get_full_name() or volunteer.user.username,
        'audience_type': 'volunteer',
        'task': task,
        'volunteer': volunteer,
        'recipients': recipients,
        'skipped': skipped,
        'include_pending': None,
        'form': request._compose_form,
        'preview': request._compose_preview,
        'action_url': reverse('volunteer_email_compose', args=[task.id, volunteer.id]),
        'cancel_url': reverse('task_detailed', args=[task.id]),
    }
    return render(request, 'volunteers/communication_compose.html', context)


@login_required
def task_toggle(request, task_id):
    """Toggle a volunteer's sign-up for a task. Returns JSON for AJAX, redirects for no-JS."""
    if request.method != 'POST':
        return redirect('task_list')

    volunteer = get_object_or_404(Volunteer, user=request.user)
    task = get_object_or_404(Task, id=task_id, edition=Edition.get_current())
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # Check if already signed up
    existing = VolunteerTask.objects.filter(task=task, volunteer=volunteer).first()

    if existing:
        if (
            existing.runner_deployments.exists()
            or existing.destination_deployments.exists()
        ):
            message = _('This assignment is part of a recorded runner deployment and cannot be removed.')
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('task_list')
        # Remove sign-up
        existing.delete()
        result_status = 'removed'
        warning = None
    else:
        # Check if task is full
        if task.assigned_volunteers() >= task.nbr_volunteers_max and task.nbr_volunteers_max > 0:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'This task is full.'})
            messages.error(request, _('This task is full.'))
            return redirect('task_list')

        # Add sign-up
        if task.effective_requires_approval:
            VolunteerTask.objects.create(task=task, volunteer=volunteer, status='pending')
            result_status = 'pending'
            # Send approval email
            from .emails import send_approval_request_email, safe_send_email
            safe_send_email(send_approval_request_email, volunteer, task)
        else:
            VolunteerTask.objects.create(task=task, volunteer=volunteer, status='approved')
            result_status = 'added'

        # Dr. Manhattan detection
        is_dr_manhattan, dr_manhattan_task_sets = volunteer.detect_dr_manhattan()
        if is_dr_manhattan:
            # Find the conflict involving this task
            conflicts = []
            for task_set in dr_manhattan_task_sets:
                if task in task_set:
                    for t in task_set:
                        if t.id != task.id:
                            conflicts.append(t.name)
            if conflicts:
                warning = _('Scheduling conflict with: %s') % ', '.join(conflicts)
            else:
                warning = None
        else:
            warning = None

    slots = f'{task.assigned_volunteers()}/{task.nbr_volunteers}'
    pending_count = task.pending_volunteers()

    if is_ajax:
        data = {
            'status': result_status,
            'slots': slots,
            'pending_count': pending_count,
            'warning': warning,
        }
        return JsonResponse(data)

    # No-JS fallback
    if result_status == 'removed':
        messages.success(request, _('Removed from "%s".') % task.name)
    elif result_status == 'pending':
        messages.info(request, _('Your sign-up for "%s" is pending approval.') % task.name)
    elif result_status == 'added':
        messages.success(request, _('Signed up for "%s".') % task.name)
    if warning:
        messages.warning(request, warning)
    return redirect('task_list')


def task_list(request):
    # get the signed in volunteer

    current_tasks = Task.objects.annotate(
        volunteers__count=Count("volunteer")).filter(
        edition=Edition.get_current()).order_by('date', 'start_time', 'end_time')


    if request.user.is_authenticated:
        volunteer = Volunteer.objects.get(user=request.user)
        current_tasks = current_tasks.prefetch_related("volunteers").prefetch_related("volunteers__user")
    else:
        volunteer = None
        is_dr_manhattan = False

    if volunteer:
        is_dr_manhattan, dr_manhattan_task_sets = volunteer.detect_dr_manhattan()
        dr_manhattan_task_ids = [x.id for x in set.union(*dr_manhattan_task_sets)] if dr_manhattan_task_sets else []
        ok_tasks = current_tasks.exclude(id__in=dr_manhattan_task_ids)
    else:
        ok_tasks = current_tasks
    days = sorted(list(set([x.date for x in current_tasks])))

    # get the preferred and other tasks, preserve key order with srteddict for view
    context = {
        'tasks': SortedDict({}),
        'checked': {},
        'attending': {},
        'is_dr_manhattan': is_dr_manhattan,
        'setup_for_current_year_complete': getattr(settings, 'SETUP_FOR_CURRENT_YEAR_COMPLETE', False),
    }
    # get the categories the volunteer is interested in
    if volunteer:
        categories_by_task_pref = {
            'Tasks': TaskCategory.objects.filter(active=True),
        }
        context['volunteer'] = volunteer
        context['dr_manhattan_task_sets'] = dr_manhattan_task_sets
        context['tasks']['Tasks'] = SortedDict.fromkeys(days, {})
    else:
        categories_by_task_pref = {
            # 'preferred tasks': [],
            'Tasks': TaskCategory.objects.filter(active=True),
        }
        context['tasks']['Tasks'] = SortedDict.fromkeys(days, {})
    context['user'] = request.user

    context['user_in_penta'] = hasattr(request.user, 'volunteer') and request.user.volunteer.penta_account_name is not None and len(request.user.volunteer.penta_account_name)>0
    for category_group in context['tasks']:
        for day in context['tasks'][category_group]:
            context['tasks'][category_group][day] = SortedDict.fromkeys(categories_by_task_pref[category_group], [])
            for category in context['tasks'][category_group][day]:
                dct = ok_tasks.filter(template__category=category, date=day)
                context['tasks'][category_group][day][category] = dct

    # mark checked, attending tasks
    if volunteer:
        # Get all volunteer's signups (approved and pending)
        volunteer_task_statuses = dict(
            VolunteerTask.objects.filter(volunteer=volunteer, task__in=current_tasks)
            .values_list('task_id', 'status')
        )
        for task in current_tasks:
            status = volunteer_task_statuses.get(task.id)
            context['checked'][task.id] = 'checked' if status in ('approved', 'pending') else ''
            context['attending'][task.id] = False

        context['pending_task_ids'] = {tid for tid, st in volunteer_task_statuses.items() if st == 'pending'}

        # take the moderation tasks to talks the volunteer is attending
        for task in current_tasks.filter(talk__volunteers=volunteer):
            context['attending'][task.id] = True
        check_profile_completeness(request, volunteer)
    else:
        for task in current_tasks:
            context['attending'][task.id] = False
        context['pending_task_ids'] = set()

    return render(request, 'volunteers/tasks.html', context)


@permission_required('event_signon')
def event_sign_on(request):
    current_tasks = Task.objects.filter(edition=Edition.get_current())
    ok_tasks = current_tasks
    days = sorted(list(set([x.date for x in current_tasks])))
    signup_form = EventSignupForm
    # when the user submitted the form
    if request.method == 'POST':
        # create volunteer
        form = signup_form(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()

            volunteer = Volunteer.objects.get(user=user)
            # get the checked tasks
            task_ids = request.POST.getlist('task')

            # unchecked boxes, delete him/her from the task
            for task in current_tasks.exclude(id__in=task_ids):
                VolunteerTask.objects.filter(
                    task=task,
                    volunteer=volunteer,
                    runner_deployments__isnull=True,
                    destination_deployments__isnull=True,
                ).delete()

            # checked boxes, add the volunteer to the tasks when he/she is not added
            for task in current_tasks.filter(id__in=task_ids):
                VolunteerTask.objects.get_or_create(task=task, volunteer=volunteer)
            log_operational_action(
                request,
                volunteer,
                f'Created event sign-on account with {len(task_ids)} selected tasks',
            )
            # Send tasks
            try:
                volunteer.mail_schedule()
                volunteer.mail_user_created_for_you()
            except Exception:
                messages.warning(request, _('Volunteer created, but notification emails could not be sent.'),
                                 fail_silently=True)
            # show success message when enabled
            messages.success(request, _('Tasks for {0} have been updated.'.format(user.username)),
                                 fail_silently=True)

    # get the preferred and other tasks, preserve key order with srteddict for view
    context = {
        'tasks': SortedDict({}),
        'checked': {},
        'attending': {},
        'is_dr_manhattan': False,
        'setup_for_current_year_complete': getattr(settings, 'SETUP_FOR_CURRENT_YEAR_COMPLETE', False),
    }
    # get the categories the volunteer is interested in
    categories_by_task_pref = {
        # 'preferred tasks': [],
        'tasks': TaskCategory.objects.filter(active=True),
    }
    context['tasks']['tasks'] = SortedDict.fromkeys(days, {})
    context['user'] = request.user
    for category_group in context['tasks']:
        for day in context['tasks'][category_group]:
            context['tasks'][category_group][day] = SortedDict.fromkeys(categories_by_task_pref[category_group], [])
            for category in context['tasks'][category_group][day]:
                dct = ok_tasks.filter(template__category=category, date=day)
                context['tasks'][category_group][day][category] = dct

    # Sign up during the event
    context['form'] = signup_form
    # mark checked, attending tasks
    for task in current_tasks:
        context['attending'][task.id] = False

    return render(request, 'volunteers/event_sign_on.html', context)


@login_required
def render_to_pdf(request, template_src, context_dict):
    template = get_template(template_src)
    context = Context(context_dict)
    html = template.render(context_dict)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="report.pdf"'

    pisa_status = pisa.CreatePDF(html, dest = response)
    if not pisa_status.err:
        return response
    return HttpResponse('We had some errors<pre>%s</pre>' % escape(html))


@login_required
def task_list_detailed(request, username):
    # Detailed current-edition schedule is personal information (which
    # tasks/times/locations a specific volunteer is assigned); only the
    # volunteer themselves or an admin may view it.
    if (
        request.user.username != username
        and not has_permission(request.user, 'view_other_schedules')
    ):
        raise PermissionDenied("you are not allowed to view another user's task schedule")

    context = {}
    edition = Edition.get_current()
    current_tasks = Task.objects.filter(edition=edition).order_by('date', 'start_time', 'end_time')

    # get the requested users tasks
    context['tasks'] = current_tasks.filter(
        volunteertask__volunteer__user__username=username,
        volunteertask__status__in=('approved', 'pending'),
    )
    context['user'] = request.user
    context['profile_user'] = get_object_or_404(User, username=username)
    volunteer = get_object_or_404(Volunteer, user__username=username)
    context['volunteer'] = volunteer
    context['edition'] = edition
    context['signup_statuses'] = dict(
        VolunteerTask.objects.filter(
            volunteer=volunteer,
            task__in=context['tasks'],
        ).values_list('task_id', 'status')
    )
    check_profile_completeness(request, volunteer)

    # Build sign-in availability and status dicts for the template
    signin_available = {}
    signin_status = {}
    if edition and edition.enable_task_signin:
        now = timezone.now()
        for task in context['tasks']:
            task_start = timezone.make_aware(
                _dt.datetime.combine(task.date, task.start_time),
                timezone.get_current_timezone()
            )
            task_end = timezone.make_aware(
                _dt.datetime.combine(task.date, task.end_time),
                timezone.get_current_timezone()
            )
            earliest_signin = task_start - timedelta(minutes=15)

            # Get volunteer_task and attendance
            try:
                vt = VolunteerTask.objects.get(task=task, volunteer=volunteer)
                try:
                    attendance = vt.attendance
                except TaskAttendance.DoesNotExist:
                    attendance = None
            except VolunteerTask.DoesNotExist:
                vt = None
                attendance = None

            can_signin = (
                vt is not None
                and now >= earliest_signin
                and now < task_end
                and (attendance is None or attendance.signed_in_at is None)
            )
            can_signout = (
                attendance is not None
                and attendance.signed_in_at is not None
                and attendance.signed_out_at is None
            )

            signin_available[task.id] = {
                'can_signin': can_signin,
                'can_signout': can_signout,
                'vt_id': vt.id if vt else None,
            }
            signin_status[task.id] = attendance.status if attendance else 'no_record'

    context['signin_available'] = signin_available
    context['signin_status'] = signin_status
    context['enable_task_signin'] = edition.enable_task_signin if edition else False
    context['can_mail_schedule'] = (
        request.user == context['profile_user']
        or has_permission(request.user, 'send_mass_mail')
    )

    if request.POST:
        if 'print_pdf' in request.POST:
            # create the HttpResponse object with the appropriate PDF headers.
            context.update({'pagesize': 'A4'})
            return render_to_pdf(request, 'volunteers/tasks_detailed.html', context)
        elif 'mail_schedule' in request.POST:
            if not context['can_mail_schedule']:
                raise PermissionDenied
            try:
                volunteer.mail_schedule()
                messages.success(request, _('Your schedule has been mailed to %s.' % (volunteer.user.email,)),
                                 fail_silently=True)
            except Exception:
                messages.warning(request, _('Your schedule could not be emailed. Please try again later.'),
                                 fail_silently=True)

    return render(request, 'volunteers/tasks_detailed.html', context)


def signup(request, signup_form=SignupForm,
           template_name='userena/signup_form.html', success_url=None,
           extra_context=None):
    """
        Signup of an account.

        Signup requiring a username, email and password. After signup a user gets
        an email with an activation link used to activate their account. After
        successful signup redirects to ``success_url``.

        :param signup_form:
            Form that will be used to sign a user. Defaults to userena's
            :class:`SignupForm`.

        :param template_name:
            String containing the template name that will be used to display the
            signup form. Defaults to ``userena/signup_form.html``.

        :param success_url:
            String containing the URI which should be redirected to after a
            successful signup. If not supplied will redirect to
            ``userena_signup_complete`` view.

        :param extra_context:
            Dictionary containing variables which are added to the template
            context. Defaults to a dictionary with a ``form`` key containing the
            ``signup_form``.

        **Context**

        ``form``
            Form supplied by ``signup_form``.
    """

    form = signup_form()

    if request.method == 'POST':
        form = signup_form(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            
            confirmation = EmailConfirmation.objects.create(user=user)
            confirmation.send(request)
            return render(request, "userena/activation_send.html")

    if not extra_context:
        extra_context = dict()
    extra_context['form'] = form
    return render(request, template_name, extra_context)


@login_required
def profile_edit(request, username, edit_profile_form=EditProfileForm,
                 template_name='userena/profile_form.html', success_url=None,
                 extra_context=None, **kwargs):
    """
        Edit or view a profile.

        Edits a profile selected by the supplied username. First checks
        permissions if the user is allowed to edit this profile, if denied will
        show a 404. When the profile is successfully edited will redirect to
        ``success_url``.

        :param username:
            Username of the user which profile should be edited.

        :param edit_profile_form:

            Form that is used to edit the profile. The :func:`EditProfileForm.save`
            method of this form will be called when the form
            :func:`EditProfileForm.is_valid`.  Defaults to :class:`EditProfileForm`
            from userena.

        :param template_name:
            String of the template that is used to render this view. Defaults to
            ``userena/edit_profile_form.html``.

        :param success_url:
            Named URL which will be passed on to a django ``reverse`` function after
            the form is successfully saved. Defaults to the ``userena_detail`` url.

        :param extra_context:
            Dictionary containing variables that are passed on to the
            ``template_name`` template.  ``form`` key will always be the form used
            to edit the profile, and the ``profile`` key is always the edited
            profile.

        **Context**

        ``form``
            Form that is used to alter the profile.

        ``profile``
            Instance of the ``Profile`` that is edited.
    """
    
    # we should probably avoid needing this test by not adding the username ot the url,
    # and just using the request username
    if request.user.username != username:
        raise PermissionDenied("you are not allowed to edit another user")

    user = get_object_or_404(get_user_model(), username__iexact=username, volunteer__privacy_policy_accepted_at__isnull=False)

    profile = user.volunteer

    user_initial = {'first_name': user.first_name, 'last_name': user.last_name}

    form = edit_profile_form(instance=profile, initial=user_initial)

    if request.method == 'POST':
        form = edit_profile_form(request.POST, request.FILES, instance=profile, initial=user_initial)

        if form.is_valid():
            profile = form.save()

            messages.success(request, _('Your profile has been updated.'), fail_silently=True)

            if success_url:
                # Send a signal that the profile has changed
                userena_signals.profile_change.send(sender=None, user=user)
                redirect_to = success_url
            else:
                redirect_to = reverse('userena_profile_detail', kwargs={'username': username})
            return redirect(redirect_to)

    if not extra_context: extra_context = dict()
    extra_context['form'] = form
    extra_context['profile'] = profile
    return render(request, template_name, extra_context)

@login_required
def profile_detail(request, username,
                   template_name="userena/profile_detail.html",
                   extra_context=None, **kwargs):
    """
        Detailed view of an user.

        :param username:
            String of the username of which the profile should be viewed.

        :param template_name:
            String representing the template name that should be used to display
            the profile.

        :param extra_context:
            Dictionary of variables which should be supplied to the template. The
            ``profile`` key is always the current profile.

        **Context**

        ``profile``
            Instance of the currently viewed ``Profile``.
    """
    user = get_object_or_404(get_user_model(), username__iexact=username, volunteer__privacy_policy_accepted_at__isnull=False, volunteer__email_confirmed=True)
    current_edition = Edition.get_current()
    current_tasks = Task.objects.filter(edition=current_edition).order_by('date', 'start_time', 'end_time')

    try:
        profile = user.volunteer
    except Volunteer.DoesNotExist:
        profile = Volunteer.objects.create(user=user)

    # Build volunteering history: past editions with their tasks, newest first.
    # Restricted to the profile owner and admins -- it discloses a volunteer's
    # multi-year attendance pattern (dates/times/locations), which other
    # logged-in volunteers should not be able to browse.
    history = []
    if request.user == user or has_permission(request.user, 'view_volunteer_history'):
        past_editions = Edition.objects.filter(
            task__volunteertask__volunteer=profile,
            task__volunteertask__status='approved',
        ).exclude(
            pk=current_edition.pk if current_edition else None
        ).distinct().order_by('-start_date')

        for edition in past_editions:
            edition_tasks = Task.objects.filter(
                edition=edition,
                volunteertask__volunteer=profile,
                volunteertask__status='approved',
            ).order_by('date', 'start_time')
            history.append({'edition': edition, 'tasks': edition_tasks})

    if not extra_context: extra_context = dict()
    extra_context['profile'] = profile
    can_view_tasks = (
        request.user == user
        or has_permission(request.user, 'view_other_schedules')
    )
    extra_context['can_view_current_tasks'] = can_view_tasks
    if can_view_tasks:
        current_signups = VolunteerTask.objects.filter(
            volunteer=profile,
            task__edition=current_edition,
            status__in=('approved', 'pending'),
        )
        extra_context['tasks'] = current_tasks.filter(
            volunteertask__in=current_signups,
        )
        extra_context['task_signup_statuses'] = dict(
            current_signups.values_list('task_id', 'status')
        )
    else:
        extra_context['tasks'] = current_tasks.none()
        extra_context['task_signup_statuses'] = {}
    extra_context['history'] = history
    extra_context['hide_email'] = True
    extra_context['username'] = profile.user.username
    check_profile_completeness(request, user.volunteer)
    return render(request, template_name, extra_context)


class ProfileListView(ListView):
    """ Lists all profiles """
    context_object_name = 'profile_list'
    page = 1
    paginate_by = 50
    template_name = 'userena/profile_list.html' 
    extra_context = None

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super(ProfileListView, self).get_context_data(**kwargs)
        try:
            page = int(self.request.GET.get('page', None))
        except (TypeError, ValueError):
            page = self.page

        if not self.extra_context: self.extra_context = dict()

        context['page'] = page
        context['paginate_by'] = self.paginate_by
        context['extra_context'] = self.extra_context

        return context

    def get_queryset(self):
        profile_model = Volunteer 
        queryset = profile_model.objects.filter(privacy_policy_accepted_at__isnull=False, email_confirmed=True).select_related().extra( \
            select={'lower_name': 'lower(first_name)'}).order_by('lower_name')
        return queryset


@login_required
def privacy_policy_consent(request):
    v = getattr(request.user, 'volunteer', None)

    needs_consent = not v or not v.privacy_policy_accepted_at or v.privacy_policy_version < CURRENT_PRIVACY_POLICY_VERSION
    if not needs_consent:
        return redirect('task_list')

    if request.method == 'POST' and request.POST.get('agree') == 'yes' and v:
        from django.utils import timezone
        v.privacy_policy_accepted_at = timezone.now()
        v.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
        v.save(update_fields=['privacy_policy_accepted_at', 'privacy_policy_version'])
        return redirect('task_list')

    is_reconsent = bool(v and v.privacy_policy_accepted_at)
    return render(request, 'volunteers/privacy_policy_consent.html', {'is_reconsent': is_reconsent})


@login_required
def email_change(request):
    user = request.user
    if request.method == 'POST':
        form = EmailChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect('userena_profile_detail', username=user.username)
    else:
        form = EmailChangeForm(instance=user)
    return render(request, 'userena/email_form.html', {'form': form})

def resend_activation(request):
    if request.method == "POST":
        form = ResendActivationForm(request.POST)
        if form.is_valid():
            user = form.user

            # Get or create token
            confirmation, created = EmailConfirmation.objects.get_or_create(user=user)

            # If it's very old, regenerate token (optional)
            if confirmation.created_at < timezone.now() - timedelta(days=7):
                confirmation.token = uuid.uuid4()
                confirmation.created_at = timezone.now()
                confirmation.save()

            # Send email using your existing method
            confirmation.send(request)
            return render(request, "userena/activation_send.html")
    else:
        form = ResendActivationForm()

    return render(request, "registration/resend_activation.html", {"form": form})

def activate_account(request, token):
    try:
        valid_since = timezone.now() - timedelta(days=7)
        confirmation = EmailConfirmation.objects.get(token=token, created_at__gte=valid_since)
        volunteer = confirmation.user.volunteer
    except (EmailConfirmation.DoesNotExist, Volunteer.DoesNotExist):
        return render(request, "userena/activate_fail.html")

    volunteer.email_confirmed = True
    volunteer.save(update_fields=['email_confirmed'])
    confirmation.delete()
    messages.success(request, "Your account has been successfully activated!")
    return redirect('task_list')



# --- Admin Label Generation Views ---

@permission_required('manage_labels')
def label_dashboard(request):
    """Admin dashboard for generating volunteer labels."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    volunteers = (
        Volunteer.objects.select_related('user')
        .filter(
            volunteertask__task__edition=edition,
            volunteertask__status='approved',
        )
        .distinct()
        .order_by('user__first_name', 'user__last_name')
    )

    # Get last print time for each volunteer in this edition
    last_prints = {}
    for log in LabelPrintLog.objects.filter(edition=edition).order_by('-printed_at'):
        if log.volunteer_id not in last_prints:
            last_prints[log.volunteer_id] = log.printed_at

    context = {
        'edition': edition,
        'volunteers': volunteers,
        'last_prints': last_prints,
    }
    return render(request, 'volunteers/label_dashboard.html', context)


@permission_required('manage_labels')
def label_preview(request):
    """Show confirmation/preview before generating labels, with reprint warnings."""
    if request.method != 'POST':
        return redirect('label_dashboard')

    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('label_dashboard')

    volunteer_ids = request.POST.getlist('volunteer_ids')
    if not volunteer_ids:
        messages.warning(request, _('No volunteers selected.'))
        return redirect('label_dashboard')

    volunteers = (
        Volunteer.objects.select_related('user')
        .filter(
            id__in=volunteer_ids,
            volunteertask__task__edition=edition,
            volunteertask__status='approved',
        )
        .distinct()
        .order_by('user__first_name', 'user__last_name')
    )

    # Check for previous prints
    reprint_info = {}
    for log in LabelPrintLog.objects.filter(edition=edition, volunteer__in=volunteers).order_by('-printed_at'):
        if log.volunteer_id not in reprint_info:
            reprint_info[log.volunteer_id] = log.printed_at

    context = {
        'edition': edition,
        'volunteers': volunteers,
        'reprint_info': reprint_info,
        'volunteer_ids': ','.join(volunteer_ids),
    }
    return render(request, 'volunteers/label_confirm.html', context)


@permission_required('manage_labels')
def label_generate_pdf(request):
    """Generate the PDF and log the print."""
    from .labels import generate_labels_pdf

    if request.method != 'POST':
        return redirect('label_dashboard')

    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('label_dashboard')

    volunteer_ids = request.POST.get('volunteer_ids', '').split(',')
    volunteer_ids = [vid for vid in volunteer_ids if vid.strip()]

    if not volunteer_ids:
        messages.warning(request, _('No volunteers selected.'))
        return redirect('label_dashboard')

    volunteers = (
        Volunteer.objects.select_related('user')
        .prefetch_related('spoken_languages', 'tasks')
        .filter(
            id__in=volunteer_ids,
            volunteertask__task__edition=edition,
            volunteertask__status='approved',
        )
        .distinct()
        .order_by('user__first_name', 'user__last_name')
    )

    # Generate PDF
    pdf_content = generate_labels_pdf(volunteers, edition)

    # Log the prints
    for volunteer in volunteers:
        LabelPrintLog.objects.create(
            volunteer=volunteer,
            edition=edition,
            printed_by=request.user,
        )
    log_operational_action(
        request,
        edition,
        f'Generated labels for {len(volunteers)} volunteers',
    )

    # Return PDF as download
    response = HttpResponse(pdf_content, content_type='application/pdf')
    filename = f'labels_{edition.name}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# --- Admin T-shirt Report View ---

@permission_required('view_tshirt_report')
def tshirt_report(request):
    """T-shirt size statistics per edition, accessible from the standard UI."""
    from collections import defaultdict
    import datetime as dt

    all_editions = Edition.objects.all().order_by('-start_date')

    edition_pk = request.GET.get('edition')
    if edition_pk:
        try:
            selected_edition = Edition.objects.get(pk=edition_pk)
        except Edition.DoesNotExist:
            selected_edition = Edition.get_current() or (all_editions.first() if all_editions.exists() else None)
    else:
        selected_edition = Edition.get_current() or (all_editions.first() if all_editions.exists() else None)

    tshirt_day_offsets = getattr(settings, 'TSHIRT_DAYS', [0, 1])
    tshirt_day_dates = []
    summary = []
    breakdown = []
    total = 0

    if selected_edition:
        tshirt_day_dates = sorted([
            selected_edition.start_date + timedelta(days=d)
            for d in tshirt_day_offsets
        ])

        # Map volunteer → set of distinct t-shirt day dates they work
        vol_dates = defaultdict(set)
        assignments = (
            VolunteerTask.objects
            .filter(
                task__edition=selected_edition,
                task__date__in=tshirt_day_dates,
                status='approved',
            )
            .values_list('volunteer_id', 'task__date')
        )
        for volunteer_id, task_date in assignments:
            vol_dates[volunteer_id].add(task_date)

        # Aggregate by t-shirt size
        size_data = defaultdict(list)
        for vol_pk, dates in vol_dates.items():
            volunteer = Volunteer.objects.select_related('user').get(pk=vol_pk)
            n_shirts = len(dates)
            size = volunteer.tshirt_size or ''
            size_data[size].append((volunteer, n_shirts, sorted(dates)))

        # Order sizes sensibly
        size_order = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '']
        ordered_sizes = sorted(size_data.keys(), key=lambda s: size_order.index(s) if s in size_order else 99)

        for size in ordered_sizes:
            volunteers = sorted(size_data[size], key=lambda x: x[0].user.last_name.lower())
            count = sum(n for _, n, _ in volunteers)
            summary.append((size, count))
            breakdown.append((size, volunteers))
            total += count

    return render(request, 'volunteers/tshirt_report.html', {
        'all_editions': all_editions,
        'selected_edition': selected_edition,
        'tshirt_day_dates': tshirt_day_dates,
        'summary': summary,
        'breakdown': breakdown,
        'total': total,
    })


# --- Admin Matrix IDs Export ---

@permission_required('export_matrix_ids')
def matrix_ids_export(request):
    """Export Matrix IDs of all volunteers for the current edition as a text file."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    volunteers = (
        Volunteer.objects.select_related('user')
        .filter(
            volunteertask__task__edition=edition,
            volunteertask__status='approved',
            matrix_id__isnull=False,
        )
        .exclude(matrix_id='')
        .distinct()
        .order_by('user__first_name', 'user__last_name')
    )

    if 'download' in request.GET:
        # Return as plain text file download
        matrix_ids = [v.matrix_id for v in volunteers]
        content = '\n'.join(matrix_ids)
        response = HttpResponse(content, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="matrix_ids_{edition.name}.txt"'
        log_operational_action(
            request,
            edition,
            f'Exported {len(matrix_ids)} Matrix IDs',
        )
        return response

    context = {
        'edition': edition,
        'volunteers': volunteers,
    }
    return render(request, 'volunteers/matrix_ids_export.html', context)


# --- Admin Approval Dashboard ---

@login_required
def approval_dashboard(request):
    """List all pending sign-up approvals for the current edition."""
    has_global_access = has_permission(request.user, 'manage_approvals')
    if not has_global_access and not has_responsible_templates(request.user):
        raise PermissionDenied

    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    pending = VolunteerTask.objects.filter(
        task__edition=edition,
        status='pending',
    )
    if not has_global_access:
        pending = pending.filter(
            Q(task__template__primary=request.user)
            | Q(task__template__secondary=request.user)
        )
    pending = list(
        pending
        .select_related('volunteer__user', 'task', 'task__template')
        .order_by('requested_at')
    )
    _attach_prior_task_experience(pending)

    context = {
        'edition': edition,
        'pending': pending,
    }
    return render(request, 'volunteers/approval_dashboard.html', context)


@login_required
def approval_respond(request):
    """Approve or deny a pending signup."""
    if request.method != 'POST':
        return redirect('approval_dashboard')

    from .emails import send_approval_decision_email, safe_send_email

    vt_id = request.POST.get('vt_id')
    action = request.POST.get('action')

    vt = get_object_or_404(VolunteerTask, id=vt_id, status='pending')
    if not can_approve_task(request.user, vt.task):
        raise PermissionDenied

    if action == 'approve':
        vt.status = 'approved'
        vt.reviewed_at = timezone.now()
        vt.reviewed_by = request.user
        vt.save()
        log_operational_action(
            request,
            vt,
            f'Approved signup for {vt.volunteer.user.username}',
        )
        if not safe_send_email(send_approval_decision_email, vt, True):
            messages.warning(request, _('Approval saved, but notification email could not be sent.'))
        messages.success(
            request,
            _('%(name)s approved for "%(task)s".') % {
                'name': vt.volunteer.user.get_full_name(),
                'task': vt.task.name,
            }
        )
    elif action == 'deny':
        if not safe_send_email(send_approval_decision_email, vt, False):
            messages.warning(request, _('Denial processed, but notification email could not be sent.'))
        log_operational_action(
            request,
            vt,
            f'Denied signup for {vt.volunteer.user.username}',
        )
        vt.delete()  # Delete so volunteer can re-apply
        messages.success(
            request,
            _('Sign-up denied. The volunteer can re-apply if they wish.')
        )

    return redirect('approval_dashboard')


def _find_task_clashes(volunteer_tasks):
        """Return connected groups of overlapping active sign-ups."""
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


@login_required
def task_clashes_dashboard(request):
    """Show and resolve overlapping approved or pending task sign-ups."""
    has_global_access = has_permission(request.user, 'manage_task_clashes')
    if not has_global_access and not has_responsible_templates(request.user):
        raise PermissionDenied

    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    signups = list(
        VolunteerTask.objects
        .filter(task__edition=edition, status__in=('approved', 'pending'))
        .select_related('volunteer__user', 'task')
        .order_by(
            'volunteer__user__last_name',
            'volunteer__user__first_name',
            'task__date',
            'task__start_time',
        )
    )

    signups_by_volunteer = {}
    for signup in signups:
        signups_by_volunteer.setdefault(signup.volunteer_id, []).append(signup)

    clashes_by_volunteer = {}
    for volunteer_id, volunteer_signups in signups_by_volunteer.items():
        clashes = _find_task_clashes(volunteer_signups)
        if clashes:
            clashes_by_volunteer[volunteer_id] = clashes

    if request.method == 'POST':
        volunteer_id = request.POST.get('volunteer_id')
        action = request.POST.get('action')
        try:
            volunteer_id = int(volunteer_id)
        except (TypeError, ValueError):
            messages.error(request, _('Invalid volunteer.'))
            return redirect('task_clashes_dashboard')

        clashes = clashes_by_volunteer.get(volunteer_id)
        if not clashes:
            messages.error(request, _('This volunteer no longer has any task clashes.'))
            return redirect('task_clashes_dashboard')

        volunteer = clashes[0][0].volunteer
        if action == 'remove':
            signup_id = request.POST.get('signup_id')
            clashing_signup_ids = {
                signup.id
                for clash in clashes
                for signup in clash
            }
            try:
                signup_id = int(signup_id)
            except (TypeError, ValueError):
                signup_id = None
            if signup_id not in clashing_signup_ids:
                messages.error(request, _('That task is not part of this volunteer’s current clashes.'))
                return redirect('task_clashes_dashboard')

            signup = get_object_or_404(
                VolunteerTask,
                id=signup_id,
                volunteer_id=volunteer_id,
                task__edition=edition,
                status__in=('approved', 'pending'),
            )
            if not (
                has_global_access
                or is_task_responsible(request.user, signup.task)
            ):
                raise PermissionDenied
            task_name = signup.task.name
            if (
                signup.runner_deployments.exists()
                or signup.destination_deployments.exists()
            ):
                messages.error(
                    request,
                    _('This assignment is part of a recorded runner deployment and cannot be removed.'),
                )
            else:
                log_operational_action(
                    request,
                    signup,
                    f'Removed clashing signup from task {signup.task_id}',
                )
                signup.delete()
                messages.success(
                    request,
                    _('%(name)s has been removed from “%(task)s”.') % {
                        'name': volunteer.user.get_full_name() or volunteer.user.username,
                        'task': task_name,
                    },
                )
        elif action == 'email':
            if not has_global_access:
                raise PermissionDenied
            if not volunteer.user.email:
                messages.error(request, _('This volunteer does not have an email address.'))
                return redirect('task_clashes_dashboard')

            from .emails import safe_send_email, send_task_clash_email
            task_groups = [
                [signup.task for signup in clash]
                for clash in clashes
            ]
            sent = safe_send_email(
                send_task_clash_email,
                volunteer,
                task_groups,
                request.build_absolute_uri(reverse('task_list')),
            )
            if sent:
                messages.success(
                    request,
                    _('Task clash email sent to %(email)s.') % {
                        'email': volunteer.user.email,
                    },
                )
            else:
                messages.error(request, _('The task clash email could not be sent.'))
        else:
            messages.error(request, _('Invalid action.'))

        return redirect('task_clashes_dashboard')

    volunteers_with_clashes = []
    for clashes in clashes_by_volunteer.values():
        if not has_global_access and not any(
            is_task_responsible(request.user, signup.task)
            for clash in clashes
            for signup in clash
        ):
            continue
        volunteer = clashes[0][0].volunteer
        volunteers_with_clashes.append({
            'volunteer': volunteer,
            'clashes': [
                {
                    'signups': [
                        {
                            'signup': signup,
                            'can_remove': (
                                has_global_access
                                or is_task_responsible(request.user, signup.task)
                            ),
                        }
                        for signup in clash
                    ],
                }
                for clash in clashes
            ],
        })

    volunteers_with_clashes.sort(
        key=lambda item: (
            item['volunteer'].user.last_name.lower(),
            item['volunteer'].user.first_name.lower(),
            item['volunteer'].user.username.lower(),
        )
    )

    return render(request, 'volunteers/task_clashes_dashboard.html', {
        'edition': edition,
        'volunteers_with_clashes': volunteers_with_clashes,
        'can_email_clashes': has_global_access,
    })


# --- Task Sign-in/Sign-out Views ---


def _combine_task_datetime(task, time_field):
    """Combine task date with a time field to produce a timezone-aware datetime."""
    naive = _dt.datetime.combine(task.date, time_field)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def task_signin_token(request, token):
    """Token-based sign-in (no login required). Used from email links."""
    attendance = get_object_or_404(TaskAttendance, signin_token=token)
    task = attendance.volunteer_task.task
    edition = task.edition

    if not edition.enable_task_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'Task check-in is not enabled for this edition.'
        })

    now = timezone.now()
    task_start = _combine_task_datetime(task, task.start_time)
    task_end = _combine_task_datetime(task, task.end_time)
    earliest_signin = task_start - timedelta(minutes=15)

    if now < earliest_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': f'Too early to check in. Check-in opens at {(task_start - timedelta(minutes=15)).strftime("%H:%M")}.',
            'task': task,
        })

    if now >= task_end:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'This task has already ended.',
            'task': task,
        })

    if attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already checked in for this task.',
            'task': task,
        })

    attendance.signed_in_at = now
    attendance.save(update_fields=['signed_in_at'])

    # Send sign-out link email if enabled
    if getattr(settings, 'SIGNIN_EMAIL_ENABLED', False):
        from .emails import send_signout_link_email, safe_send_email
        if safe_send_email(send_signout_link_email, attendance):
            attendance.signout_link_sent_at = now
            attendance.save(update_fields=['signout_link_sent_at'])

    return render(request, 'volunteers/signin_confirm.html', {
        'task': task,
        'attendance': attendance,
    })


def task_signout_token(request, token):
    """Token-based sign-out (no login required). Used from email links."""
    attendance = get_object_or_404(TaskAttendance, signout_token=token)
    task = attendance.volunteer_task.task

    if not attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have not checked in for this task yet.',
            'task': task,
        })

    if attendance.signed_out_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already checked out of this task.',
            'task': task,
        })

    attendance.signed_out_at = timezone.now()
    attendance.save(update_fields=['signed_out_at'])

    return render(request, 'volunteers/signout_confirm.html', {
        'task': task,
        'attendance': attendance,
    })


@login_required
def task_signin(request, vt_id):
    """Login-required sign-in using volunteer_task ID. Verifies ownership."""
    volunteer = get_object_or_404(Volunteer, user=request.user)
    vt = get_object_or_404(VolunteerTask, id=vt_id, volunteer=volunteer)
    task = vt.task
    edition = task.edition

    if not edition.enable_task_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'Task check-in is not enabled for this edition.'
        })

    # Get or create attendance record
    attendance, _created = TaskAttendance.objects.get_or_create(volunteer_task=vt)

    now = timezone.now()
    task_start = _combine_task_datetime(task, task.start_time)
    task_end = _combine_task_datetime(task, task.end_time)
    earliest_signin = task_start - timedelta(minutes=15)

    if now < earliest_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': f'Too early to check in. Check-in opens at {(task_start - timedelta(minutes=15)).strftime("%H:%M")}.',
            'task': task,
        })

    if now >= task_end:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'This task has already ended.',
            'task': task,
        })

    if attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already checked in for this task.',
            'task': task,
        })

    attendance.signed_in_at = now
    attendance.save(update_fields=['signed_in_at'])

    # Send sign-out link email if enabled
    if getattr(settings, 'SIGNIN_EMAIL_ENABLED', False):
        from .emails import send_signout_link_email, safe_send_email
        if safe_send_email(send_signout_link_email, attendance):
            attendance.signout_link_sent_at = now
            attendance.save(update_fields=['signout_link_sent_at'])
        else:
            messages.warning(request, _('You are checked in, but the confirmation email could not be sent.'))

    messages.success(request, _('You are now checked in for "%s".') % task.name)
    return render(request, 'volunteers/signin_confirm.html', {
        'task': task,
        'attendance': attendance,
    })


@login_required
def task_signout(request, vt_id):
    """Login-required sign-out using volunteer_task ID. Verifies ownership."""
    volunteer = get_object_or_404(Volunteer, user=request.user)
    vt = get_object_or_404(VolunteerTask, id=vt_id, volunteer=volunteer)
    task = vt.task

    attendance = get_object_or_404(TaskAttendance, volunteer_task=vt)

    if not attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have not checked in for this task yet.',
            'task': task,
        })

    if attendance.signed_out_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already checked out of this task.',
            'task': task,
        })

    attendance.signed_out_at = timezone.now()
    attendance.save(update_fields=['signed_out_at'])

    messages.success(request, _('You have checked out of "%s".') % task.name)
    return render(request, 'volunteers/signout_confirm.html', {
        'task': task,
        'attendance': attendance,
    })


# --- Admin Attendance Dashboard Views ---

@login_required
def attendance_dashboard(request):
    """Admin attendance dashboard showing all tasks grouped by day with sign-in counts."""
    has_global_access = has_permission(request.user, 'manage_attendance')
    if not has_global_access and not has_responsible_templates(request.user):
        raise PermissionDenied

    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    if not edition.enable_task_signin:
        messages.warning(request, _('Task check-in is not enabled for this edition.'))
        return redirect('task_list')

    tasks = (
        Task.objects.filter(edition=edition)
        .select_related('template', 'template__category')
        .prefetch_related('volunteertask_set__attendance')
        .order_by('date', 'start_time', 'name')
    )
    if not has_global_access:
        tasks = tasks.filter(
            Q(template__primary=request.user)
            | Q(template__secondary=request.user)
        )

    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    # Group tasks by day with attendance counts
    days = {}
    for task in tasks:
        day = task.date
        if day not in days:
            days[day] = []

        assigned = VolunteerTask.objects.filter(task=task, status='approved').count()
        signed_in = TaskAttendance.objects.filter(
            volunteer_task__task=task,
            signed_in_at__isnull=False,
            signed_out_at__isnull=True,
        ).count()
        completed = TaskAttendance.objects.filter(
            volunteer_task__task=task,
            signed_out_at__isnull=False,
        ).count()
        missing = assigned - signed_in - completed

        is_active = task.date == today and task.start_time <= current_time <= task.end_time
        is_unstaffed = is_active and assigned > 0 and signed_in == 0

        days[day].append({
            'task': task,
            'assigned': assigned,
            'signed_in': signed_in,
            'completed': completed,
            'missing': max(0, missing),
            'is_active': is_active,
            'is_unstaffed': is_unstaffed,
        })

    context = {
        'edition': edition,
        'days': dict(sorted(days.items())),
        'pending_deployments': (
            RunnerDeployment.objects.filter(status='pending')
            .select_related(
                'runner_assignment__volunteer__user',
                'runner_assignment__task',
                'destination_task',
                'requested_by',
            )
            if has_global_access else RunnerDeployment.objects.none()
        ),
    }
    return render(request, 'volunteers/attendance_dashboard.html', context)


@login_required
def attendance_task_detail(request, task_id):
    """Admin view showing individual volunteers for a task with their attendance status."""
    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task_attendance(request.user, task):
        raise PermissionDenied
    edition = task.edition

    if not edition.enable_task_signin:
        messages.warning(request, _('Task check-in is not enabled for this edition.'))
        return redirect('task_list')

    volunteer_tasks = (
        VolunteerTask.objects.filter(task=task, status='approved')
        .select_related('volunteer__user')
        .prefetch_related('attendance')
    )

    volunteers_data = []
    for vt in volunteer_tasks:
        attendance = getattr(vt, 'attendance', None)
        try:
            attendance = vt.attendance
        except TaskAttendance.DoesNotExist:
            attendance = None
        volunteers_data.append({
            'volunteer_task': vt,
            'volunteer': vt.volunteer,
            'attendance': attendance,
            'status': attendance.status if attendance else 'no_record',
        })

    # Volunteers currently on Runner duty in a slot that overlaps this task.
    assigned_ids = volunteer_tasks.values_list('volunteer_id', flat=True)
    runner_tasks = Task.objects.filter(
        edition=edition,
        name__iexact='Runner',
        date=task.date,
        start_time__lt=task.end_time,
        end_time__gt=task.start_time,
    ).exclude(id=task.id)
    open_runner_assignments = RunnerDeployment.objects.filter(
        status__in=('pending', 'active'),
    ).values_list('runner_assignment_id', flat=True)
    available_runners = (
        VolunteerTask.objects.filter(task__in=runner_tasks, status='approved')
        .exclude(volunteer_id__in=assigned_ids)
        .exclude(id__in=open_runner_assignments)
        .select_related('volunteer__user', 'task')
        .order_by('task__start_time', 'volunteer__user__first_name', 'volunteer__user__last_name')
    )
    task_deployments = (
        RunnerDeployment.objects.filter(
            destination_task=task,
            status__in=('pending', 'active'),
        )
        .select_related(
            'runner_assignment__volunteer__user',
            'runner_assignment__task',
            'requested_by',
        )
        .order_by('requested_at')
    )

    # Any other volunteer, as a manual backup option (always available).
    all_volunteers = (
        Volunteer.objects.select_related('user')
        .exclude(id__in=assigned_ids)
        .order_by('user__first_name', 'user__last_name')
    )

    context = {
        'task': task,
        'edition': edition,
        'volunteers_data': volunteers_data,
        'available_runners': available_runners,
        'all_volunteers': all_volunteers,
        'signin_email_enabled': getattr(settings, 'SIGNIN_EMAIL_ENABLED', False),
        'signin_matrix_enabled': getattr(settings, 'SIGNIN_MATRIX_ENABLED', False),
        'can_deploy_runner': has_permission(request.user, 'manage_attendance'),
        'task_deployments': task_deployments,
    }
    return render(request, 'volunteers/attendance_task_detail.html', context)


@login_required
def attendance_mark(request):
    """POST: Manually sign-in or sign-out a volunteer."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    vt_id = request.POST.get('vt_id')
    action = request.POST.get('action')  # 'signin' or 'signout'

    vt = get_object_or_404(VolunteerTask, id=vt_id)
    if not can_manage_task_attendance(request.user, vt.task):
        raise PermissionDenied
    attendance, _created = TaskAttendance.objects.get_or_create(volunteer_task=vt)

    now = timezone.now()

    if action == 'signin':
        attendance.signed_in_at = now
        attendance.manually_marked_by = request.user
        attendance.save(update_fields=['signed_in_at', 'manually_marked_by'])
        log_operational_action(
            request,
            attendance,
            f'Manually checked in {vt.volunteer.user.username}',
        )
        messages.success(request, _('Manually checked in %s.') % vt.volunteer.user.get_full_name())
    elif action == 'signout':
        attendance.signed_out_at = now
        attendance.manually_marked_by = request.user
        attendance.save(update_fields=['signed_out_at', 'manually_marked_by'])
        log_operational_action(
            request,
            attendance,
            f'Manually checked out {vt.volunteer.user.username}',
        )
        messages.success(request, _('Manually checked out %s.') % vt.volunteer.user.get_full_name())

    return redirect('attendance_task_detail', task_id=vt.task.id)


def transfer_runner(request):
    """POST: Request or immediately approve a non-destructive runner deployment."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    task_id = request.POST.get('task_id')
    runner_vt_id = request.POST.get('runner_vt_id')

    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task_attendance(request.user, task):
        raise PermissionDenied
    runner_vt = get_object_or_404(VolunteerTask, id=runner_vt_id)
    volunteer = runner_vt.volunteer

    try:
        deployment = request_runner_deployment(runner_vt, task, request.user)
        if has_permission(request.user, 'manage_attendance'):
            deployment = approve_runner_deployment(deployment, request.user)
            message = _('%(name)s is now deployed to "%(task)s". Their Runner assignment has been kept.') % {
                'name': volunteer.user.get_full_name(),
                'task': task.name,
            }
        else:
            message = _('Deployment of %(name)s to "%(task)s" is pending Coordinator approval.') % {
                'name': volunteer.user.get_full_name(),
                'task': task.name,
            }
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('attendance_task_detail', task_id=task.id)

    log_operational_action(
        request,
        deployment,
        f'{"Deployed" if deployment.status == "active" else "Requested deployment of"} '
        f'{volunteer.user.username} from runner task {runner_vt.task_id} to task {task.pk}',
    )
    messages.success(request, message)

    return redirect('attendance_task_detail', task_id=task.id)


@permission_required('manage_attendance')
def runner_deployment_review(request, deployment_id):
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    deployment = get_object_or_404(RunnerDeployment, id=deployment_id)
    action = request.POST.get('action')
    try:
        if action == 'approve':
            deployment = approve_runner_deployment(deployment, request.user)
            message = _('Runner deployment approved.')
        elif action == 'deny':
            deployment = deny_runner_deployment(
                deployment,
                request.user,
                request.POST.get('review_note', '').strip(),
            )
            message = _('Runner deployment denied.')
        else:
            messages.error(request, _('Unknown deployment action.'))
            return redirect('attendance_dashboard')
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('attendance_dashboard')

    log_operational_action(
        request,
        deployment,
        f'{"Approved" if action == "approve" else "Denied"} runner deployment {deployment.pk}',
    )
    messages.success(request, message)
    return redirect('attendance_dashboard')


@login_required
def runner_deployment_return(request, deployment_id):
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    deployment = get_object_or_404(
        RunnerDeployment.objects.select_related('destination_task'),
        id=deployment_id,
    )
    if not can_manage_task_attendance(request.user, deployment.destination_task):
        raise PermissionDenied
    try:
        deployment = complete_runner_deployment(deployment, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect(
            'attendance_task_detail',
            task_id=deployment.destination_task_id,
        )

    log_operational_action(
        request,
        deployment,
        f'Returned runner from deployment {deployment.pk}',
    )
    messages.success(
        request,
        _('Runner returned to the pool; both task assignments were retained.'),
    )
    return redirect(
        'attendance_task_detail',
        task_id=deployment.destination_task_id,
    )


@login_required
def attendance_assign_volunteer(request, task_id):
    """POST: Manually assign any volunteer to this task as a backup option."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task_attendance(request.user, task):
        raise PermissionDenied
    volunteer_id = request.POST.get('volunteer_id')
    if not volunteer_id:
        messages.error(request, _('Please select a volunteer.'))
        return redirect('attendance_task_detail', task_id=task.id)

    volunteer = get_object_or_404(Volunteer, id=volunteer_id)

    vt, created = VolunteerTask.objects.get_or_create(task=task, volunteer=volunteer, defaults={'status': 'approved'})
    if created:
        TaskAttendance.objects.create(volunteer_task=vt)
        log_operational_action(
            request,
            vt,
            f'Assigned backup volunteer {volunteer.user.username}',
        )
        messages.success(
            request,
            _('%(name)s has been assigned to "%(task)s".') % {
                'name': volunteer.user.get_full_name(),
                'task': task.name,
            }
        )
    else:
        messages.info(request, _('%s is already assigned to this task.') % volunteer.user.get_full_name())

    return redirect('attendance_task_detail', task_id=task.id)


@login_required
def summon_runner(request):
    """POST: Send a Matrix message or email to summon a runner.

    Requires 'method' (matrix|email) plus the corresponding config/setting
    and, for matrix, the volunteer having a matrix_id configured.
    """
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    volunteer_id = request.POST.get('volunteer_id')
    task_id = request.POST.get('task_id')
    method = request.POST.get('method')
    volunteer = get_object_or_404(Volunteer, id=volunteer_id)
    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task_attendance(request.user, task):
        raise PermissionDenied

    sent = False

    if method == 'matrix':
        if not getattr(settings, 'SIGNIN_MATRIX_ENABLED', False):
            messages.error(request, _('Matrix notifications are not enabled.'))
            return redirect('attendance_task_detail', task_id=task.id)
        if not volunteer.matrix_id:
            messages.error(request, _('%s has no Matrix ID configured.') % volunteer.user.get_full_name())
            return redirect('attendance_task_detail', task_id=task.id)
        from .matrix_bot import summon_runner_matrix
        sent = summon_runner_matrix(volunteer, task.location or task.name)
    elif method == 'email':
        if not getattr(settings, 'SIGNIN_EMAIL_ENABLED', False):
            messages.error(request, _('Email notifications are not enabled.'))
            return redirect('attendance_task_detail', task_id=task.id)
        if not volunteer.user.email:
            messages.error(request, _('%s has no email address configured.') % volunteer.user.get_full_name())
            return redirect('attendance_task_detail', task_id=task.id)
        try:
            from django.core.mail import EmailMultiAlternatives
            subject = f'[FOSDEM Volunteers] You are needed: {task.name}'
            body = (
                f'Hi {volunteer.user.username},\n\n'
                f'You are needed at "{task.name}" ({task.location or "N/A"}).\n'
                f'Please head there now.\n\n'
                f'Thanks,\nFOSDEM Volunteers System'
            )
            email = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email='volunteer-admin@fosdem.org',
                to=[volunteer.user.email],
            )
            email.send(fail_silently=False)
            sent = True
        except Exception:
            messages.warning(request, _('Email notification could not be sent.'))
    else:
        messages.error(request, _('Unknown summon method.'))
        return redirect('attendance_task_detail', task_id=task.id)

    if sent:
        log_operational_action(
            request,
            task,
            f'Summoned {volunteer.user.username} by {method}',
        )
        messages.success(request, _('Runner summoned: %s') % volunteer.user.get_full_name())
    else:
        messages.error(request, _('Could not summon runner.'))

    return redirect('attendance_task_detail', task_id=task.id)



@login_required
def need_volunteers_matrix(request):
    """POST: Post a message to Matrix room requesting more volunteers. Requires SIGNIN_MATRIX_ENABLED."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    task_id = request.POST.get('task_id')
    task = get_object_or_404(Task, id=task_id)
    if not can_manage_task_attendance(request.user, task):
        raise PermissionDenied

    if not getattr(settings, 'SIGNIN_MATRIX_ENABLED', False):
        messages.error(request, _('Matrix notifications are not enabled.'))
        return redirect('attendance_task_detail', task_id=task.id)

    assigned = VolunteerTask.objects.filter(task=task, status='approved').count()
    signed_in = TaskAttendance.objects.filter(
        volunteer_task__task=task,
        signed_in_at__isnull=False,
        signed_out_at__isnull=True,
    ).count()
    missing = max(0, assigned - signed_in)

    from .matrix_bot import need_volunteers_message
    result = need_volunteers_message(task, missing if missing > 0 else 1)

    if result:
        log_operational_action(
            request,
            task,
            'Posted need-volunteers message to Matrix',
        )
        messages.success(request, _('Posted need-volunteers message to Matrix.'))
    else:
        messages.error(request, _('Failed to post to Matrix room.'))

    return redirect('attendance_task_detail', task_id=task.id)
