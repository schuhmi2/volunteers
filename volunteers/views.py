from django.utils import timezone
from datetime import timedelta
import datetime as _dt

from .models import Volunteer, VolunteerTask, VolunteerTalk, TaskCategory, TaskTemplate, Task, Track, \
    Talk, Edition, EmailConfirmation, LabelPrintLog, TaskAttendance
from .forms import EditProfileForm, SignupForm, EventSignupForm, EmailChangeForm, ResendActivationForm

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.generic.list import ListView
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from collections import OrderedDict as SortedDict
from django.utils.translation import gettext as _
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count
from django.contrib.auth import get_user_model

from django.http import Http404
import csv

# PDF generation (optional for local development)
try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None
from django.template.loader import get_template
from django.template import Context
from django.utils.html import escape

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
    if request.user.is_authenticated and request.user.is_superuser:
        # Provide list of all volunteers for admin assignment dropdown
        assigned_volunteer_ids = task.volunteers.values_list('id', flat=True)
        context['assignable_volunteers'] = (
            Volunteer.objects.select_related('user')
            .exclude(id__in=assigned_volunteer_ids)
            .order_by('user__first_name', 'user__last_name')
        )
        # Pending approval signups
        context['pending_signups'] = (
            VolunteerTask.objects.filter(task=task, status='pending')
            .select_related('volunteer__user')
        )
    return render(request, 'volunteers/task_detailed.html', context)


@user_passes_test(lambda u: u.is_superuser)
def admin_assign_volunteer(request, task_id):
    """Admin-only view to assign any volunteer to a task."""
    task = get_object_or_404(Task, id=task_id)

    if request.method == 'POST':
        volunteer_id = request.POST.get('volunteer_id')
        action = request.POST.get('action', 'assign')

        if action == 'assign' and volunteer_id:
            volunteer = get_object_or_404(Volunteer, id=volunteer_id)
            VolunteerTask.objects.get_or_create(task=task, volunteer=volunteer)
            messages.success(
                request,
                _('%(name)s has been assigned to this task.') % {
                    'name': f'{volunteer.user.first_name} {volunteer.user.last_name}'
                }
            )
        elif action == 'unassign' and volunteer_id:
            volunteer = get_object_or_404(Volunteer, id=volunteer_id)
            VolunteerTask.objects.filter(task=task, volunteer=volunteer).delete()
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
    categories = TaskCategory.objects.filter(active=True)
    context = {'categories': SortedDict.fromkeys(categories, [])}
    for category in context['categories']:
        context['categories'][category] = TaskTemplate.objects.filter(category=category)
    return render(request, 'volunteers/category_schedule_list.html', context)


@login_required
def task_schedule(request, template_id):
    template = TaskTemplate.objects.filter(id=template_id)[0]
    tasks = Task.objects.annotate(volunteers__count=Count("volunteer")).filter(template=template, edition=Edition.get_current()).order_by('date', 'start_time', 'end_time')
    context = {
        'template': template,
        'tasks': SortedDict.fromkeys(tasks, {}),
    }
    for task in context['tasks']:
        context['tasks'][task] = Volunteer.objects.filter(tasks=task)
    return render(request, 'volunteers/task_schedule.html', context)


@login_required
def task_schedule_csv(request, template_id):
    template = TaskTemplate.objects.filter(id=template_id)[0]
    tasks = Task.objects.annotate(volunteers__count=Count("volunteer")).filter(template=template, edition=Edition.get_current()).order_by('date', 'start_time', 'end_time')
    response = HttpResponse(content_type='text/csv')
    filename = "schedule_%s.csv" % template.name
    response['Content-Disposition'] = 'attachment; filename=%s' % filename

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
        volunteers = Volunteer.objects.filter(tasks=task)
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


@user_passes_test(lambda u: u.is_superuser)
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
                VolunteerTask.objects.filter(task=task, volunteer=volunteer).delete()

            # checked boxes, add the volunteer to the tasks when he/she is not added
            for task in current_tasks.filter(id__in=task_ids):
                VolunteerTask.objects.get_or_create(task=task, volunteer=volunteer)
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
    context = {}
    edition = Edition.get_current()
    current_tasks = Task.objects.filter(edition=edition).order_by('date', 'start_time', 'end_time')

    # get the requested users tasks
    context['tasks'] = current_tasks.filter(volunteers__user__username=username)
    context['user'] = request.user
    context['profile_user'] = User.objects.filter(username=username)[0]
    volunteer = Volunteer.objects.filter(user__username=username)[0]
    context['volunteer'] = volunteer
    context['edition'] = edition
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

    if request.POST:
        if 'print_pdf' in request.POST:
            # create the HttpResponse object with the appropriate PDF headers.
            context.update({'pagesize': 'A4'})
            return render_to_pdf(request, 'volunteers/tasks_detailed.html', context)
        elif 'mail_schedule' in request.POST:
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
    except profile_model.DoesNotExist:
        profile = Volunteer.objects.create(user=user)

    # Build volunteering history: past editions with their tasks, newest first
    past_editions = Edition.objects.filter(
        task__volunteertask__volunteer=profile
    ).exclude(
        pk=current_edition.pk if current_edition else None
    ).distinct().order_by('-start_date')

    history = []
    for edition in past_editions:
        edition_tasks = Task.objects.filter(
            edition=edition,
            volunteertask__volunteer=profile,
        ).order_by('date', 'start_time')
        history.append({'edition': edition, 'tasks': edition_tasks})

    if not extra_context: extra_context = dict()
    extra_context['profile'] = profile
    extra_context['tasks'] = current_tasks.filter(volunteers__user=user)
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
    
    if v and v.privacy_policy_accepted_at:
        return redirect('task_list')
    
    if request.method == 'POST' and request.POST.get('agree') == 'yes' and v:
        from django.utils import timezone
        v.privacy_policy_accepted_at = timezone.now()
        v.save(update_fields=['privacy_policy_accepted_at'])
        return redirect('task_list')
    
    return render(request, 'volunteers/privacy_policy_consent.html')


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
            if confirmation.created_at < timezone.now() - timezone.timedelta(days=7):
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
    except Exception:
        return render(request, "userena/activate_fail.html")
    
    if confirmation:
        confirmation.user.volunteer.email_confirmed=True
        confirmation.user.volunteer.save()
        confirmation.delete()
        messages.success(request, "Your account has been successfully activated!")
        return redirect('task_list')



# --- Admin Label Generation Views ---

@user_passes_test(lambda u: u.is_superuser)
def label_dashboard(request):
    """Admin dashboard for generating volunteer labels."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    volunteers = (
        Volunteer.objects.select_related('user')
        .filter(tasks__edition=edition)
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


@user_passes_test(lambda u: u.is_superuser)
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
        .filter(id__in=volunteer_ids)
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


@user_passes_test(lambda u: u.is_superuser)
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
        .filter(id__in=volunteer_ids)
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

    # Return PDF as download
    response = HttpResponse(pdf_content, content_type='application/pdf')
    filename = f'labels_{edition.name}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# --- Admin T-shirt Report View ---

@user_passes_test(lambda u: u.is_superuser)
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
        tasks = (
            Task.objects
            .filter(edition=selected_edition, date__in=tshirt_day_dates)
            .prefetch_related('volunteers')
        )
        for task in tasks:
            for volunteer in task.volunteers.all():
                vol_dates[volunteer.pk].add(task.date)

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

@user_passes_test(lambda u: u.is_superuser)
def matrix_ids_export(request):
    """Export Matrix IDs of all volunteers for the current edition as a text file."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    volunteers = (
        Volunteer.objects.select_related('user')
        .filter(tasks__edition=edition, matrix_id__isnull=False)
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
        return response

    context = {
        'edition': edition,
        'volunteers': volunteers,
    }
    return render(request, 'volunteers/matrix_ids_export.html', context)


# --- Admin Approval Dashboard ---

@user_passes_test(lambda u: u.is_superuser)
def approval_dashboard(request):
    """List all pending sign-up approvals for the current edition."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    pending = (
        VolunteerTask.objects
        .filter(task__edition=edition, status='pending')
        .select_related('volunteer__user', 'task', 'task__template')
        .order_by('requested_at')
    )

    context = {
        'edition': edition,
        'pending': pending,
    }
    return render(request, 'volunteers/approval_dashboard.html', context)


@user_passes_test(lambda u: u.is_superuser)
def approval_respond(request):
    """Approve or deny a pending signup."""
    if request.method != 'POST':
        return redirect('approval_dashboard')

    from .emails import send_approval_decision_email, safe_send_email

    vt_id = request.POST.get('vt_id')
    action = request.POST.get('action')

    vt = get_object_or_404(VolunteerTask, id=vt_id, status='pending')

    if action == 'approve':
        vt.status = 'approved'
        vt.reviewed_at = timezone.now()
        vt.reviewed_by = request.user
        vt.save()
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
        vt.delete()  # Delete so volunteer can re-apply
        messages.success(
            request,
            _('Sign-up denied. The volunteer can re-apply if they wish.')
        )

    return redirect('approval_dashboard')


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
            'error': 'Task sign-in is not enabled for this edition.'
        })

    now = timezone.now()
    task_start = _combine_task_datetime(task, task.start_time)
    task_end = _combine_task_datetime(task, task.end_time)
    earliest_signin = task_start - timedelta(minutes=15)

    if now < earliest_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': f'Too early to sign in. Sign-in opens at {(task_start - timedelta(minutes=15)).strftime("%H:%M")}.',
            'task': task,
        })

    if now >= task_end:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'This task has already ended.',
            'task': task,
        })

    if attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already signed in for this task.',
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
    attendance = get_object_or_404(TaskAttendance, signin_token=token)
    task = attendance.volunteer_task.task

    if not attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have not signed in for this task yet.',
            'task': task,
        })

    if attendance.signed_out_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already signed out of this task.',
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
            'error': 'Task sign-in is not enabled for this edition.'
        })

    # Get or create attendance record
    attendance, _created = TaskAttendance.objects.get_or_create(volunteer_task=vt)

    now = timezone.now()
    task_start = _combine_task_datetime(task, task.start_time)
    task_end = _combine_task_datetime(task, task.end_time)
    earliest_signin = task_start - timedelta(minutes=15)

    if now < earliest_signin:
        return render(request, 'volunteers/signin_error.html', {
            'error': f'Too early to sign in. Sign-in opens at {(task_start - timedelta(minutes=15)).strftime("%H:%M")}.',
            'task': task,
        })

    if now >= task_end:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'This task has already ended.',
            'task': task,
        })

    if attendance.signed_in_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already signed in for this task.',
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
            messages.warning(request, _('You are signed in, but the confirmation email could not be sent.'))

    messages.success(request, _('You are now signed in for "%s".') % task.name)
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
            'error': 'You have not signed in for this task yet.',
            'task': task,
        })

    if attendance.signed_out_at:
        return render(request, 'volunteers/signin_error.html', {
            'error': 'You have already signed out of this task.',
            'task': task,
        })

    attendance.signed_out_at = timezone.now()
    attendance.save(update_fields=['signed_out_at'])

    messages.success(request, _('You have signed out of "%s".') % task.name)
    return render(request, 'volunteers/signout_confirm.html', {
        'task': task,
        'attendance': attendance,
    })


# --- Admin Attendance Dashboard Views ---

@user_passes_test(lambda u: u.is_superuser)
def attendance_dashboard(request):
    """Admin attendance dashboard showing all tasks grouped by day with sign-in counts."""
    edition = Edition.get_current()
    if not edition:
        messages.error(request, _('No current edition found.'))
        return redirect('task_list')

    if not edition.enable_task_signin:
        messages.warning(request, _('Task sign-in is not enabled for this edition.'))
        return redirect('task_list')

    tasks = (
        Task.objects.filter(edition=edition)
        .select_related('template', 'template__category')
        .prefetch_related('volunteertask_set__attendance')
        .order_by('date', 'start_time', 'name')
    )

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

        days[day].append({
            'task': task,
            'assigned': assigned,
            'signed_in': signed_in,
            'completed': completed,
            'missing': max(0, missing),
        })

    context = {
        'edition': edition,
        'days': dict(sorted(days.items())),
    }
    return render(request, 'volunteers/attendance_dashboard.html', context)


@user_passes_test(lambda u: u.is_superuser)
def attendance_task_detail(request, task_id):
    """Admin view showing individual volunteers for a task with their attendance status."""
    task = get_object_or_404(Task, id=task_id)
    edition = task.edition

    if not edition.enable_task_signin:
        messages.warning(request, _('Task sign-in is not enabled for this edition.'))
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

    # Get available runners for transfer dropdown (volunteers not on this task)
    assigned_ids = volunteer_tasks.values_list('volunteer_id', flat=True)
    available_runners = (
        Volunteer.objects.select_related('user')
        .filter(tasks__edition=edition)
        .exclude(id__in=assigned_ids)
        .distinct()
        .order_by('user__first_name', 'user__last_name')
    )

    context = {
        'task': task,
        'edition': edition,
        'volunteers_data': volunteers_data,
        'available_runners': available_runners,
        'signin_email_enabled': getattr(settings, 'SIGNIN_EMAIL_ENABLED', False),
        'signin_matrix_enabled': getattr(settings, 'SIGNIN_MATRIX_ENABLED', False),
    }
    return render(request, 'volunteers/attendance_task_detail.html', context)


@user_passes_test(lambda u: u.is_superuser)
def attendance_mark(request):
    """POST: Manually sign-in or sign-out a volunteer."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    vt_id = request.POST.get('vt_id')
    action = request.POST.get('action')  # 'signin' or 'signout'

    vt = get_object_or_404(VolunteerTask, id=vt_id)
    attendance, _created = TaskAttendance.objects.get_or_create(volunteer_task=vt)

    now = timezone.now()

    if action == 'signin':
        attendance.signed_in_at = now
        attendance.manually_marked_by = request.user
        attendance.save(update_fields=['signed_in_at', 'manually_marked_by'])
        messages.success(request, _('Manually signed in %s.') % vt.volunteer.user.get_full_name())
    elif action == 'signout':
        attendance.signed_out_at = now
        attendance.manually_marked_by = request.user
        attendance.save(update_fields=['signed_out_at', 'manually_marked_by'])
        messages.success(request, _('Manually signed out %s.') % vt.volunteer.user.get_full_name())

    return redirect('attendance_task_detail', task_id=vt.task.id)


@user_passes_test(lambda u: u.is_superuser)
def transfer_runner(request):
    """POST: Assign a runner volunteer to a task."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    task_id = request.POST.get('task_id')
    volunteer_id = request.POST.get('volunteer_id')

    task = get_object_or_404(Task, id=task_id)
    volunteer = get_object_or_404(Volunteer, id=volunteer_id)

    vt, created = VolunteerTask.objects.get_or_create(task=task, volunteer=volunteer)
    if created:
        # Create attendance record
        attendance = TaskAttendance.objects.create(volunteer_task=vt)
        messages.success(
            request,
            _('%(name)s has been assigned as runner to "%(task)s".') % {
                'name': volunteer.user.get_full_name(),
                'task': task.name,
            }
        )
    else:
        messages.info(request, _('%s is already assigned to this task.') % volunteer.user.get_full_name())

    return redirect('attendance_task_detail', task_id=task.id)


@user_passes_test(lambda u: u.is_superuser)
def summon_runner(request):
    """POST: Send Matrix message or email to summon a runner. Requires SIGNIN_MATRIX_ENABLED or SIGNIN_EMAIL_ENABLED."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    volunteer_id = request.POST.get('volunteer_id')
    task_id = request.POST.get('task_id')
    volunteer = get_object_or_404(Volunteer, id=volunteer_id)
    task = get_object_or_404(Task, id=task_id)

    sent = False

    # Try Matrix first
    if getattr(settings, 'SIGNIN_MATRIX_ENABLED', False):
        from .matrix_bot import summon_runner_matrix
        sent = summon_runner_matrix(volunteer, task.location or task.name)

    # Fallback to email
    if not sent and getattr(settings, 'SIGNIN_EMAIL_ENABLED', False) and volunteer.user.email:
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

    if sent:
        messages.success(request, _('Runner summoned: %s') % volunteer.user.get_full_name())
    else:
        messages.error(request, _('Could not summon runner. No Matrix or email available.'))

    return redirect('attendance_task_detail', task_id=task.id)


@user_passes_test(lambda u: u.is_superuser)
def need_volunteers_matrix(request):
    """POST: Post a message to Matrix room requesting more volunteers. Requires SIGNIN_MATRIX_ENABLED."""
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    task_id = request.POST.get('task_id')
    task = get_object_or_404(Task, id=task_id)

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
        messages.success(request, _('Posted need-volunteers message to Matrix.'))
    else:
        messages.error(request, _('Failed to post to Matrix room.'))

    return redirect('attendance_task_detail', task_id=task.id)
