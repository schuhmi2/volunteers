"""
Tests to be run via "manage.py test"
"""

import datetime
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from volunteers.forms import ActivationAwareAuthenticationForm, EditProfileForm
from volunteers.models import (
    CURRENT_PRIVACY_POLICY_VERSION,
    EmailConfirmation,
    Edition,
    Location,
    RunnerDeployment,
    Talk,
    Task,
    TaskAttendance,
    TaskCategory,
    TaskTemplate,
    Track,
    Volunteer,
    VolunteerTask,
)
from volunteers.views import _find_task_clashes, promo


class PromoTestCase(TestCase):
    @patch('volunteers.views.render')
    def test_promo_view_renders_static_page(self, render_mock):
        static_promo_page_content = 'Some promo page'
        render_mock.return_value = static_promo_page_content
        ret = promo(None)
        self.assertEqual(ret, static_promo_page_content)


class EditProfileFormPhoneValidationTestCase(TestCase):
    """Tests for mobile phone number international format validation."""

    def _form_data(self, **overrides):
        data = {'first_name': 'Test', 'last_name': 'User'}
        data.update(overrides)
        return data

    def test_phone_without_plus_is_rejected(self):
        form = EditProfileForm(data=self._form_data(mobile_nbr='0612345678'))
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_nbr', form.errors)
        self.assertIn('international format', form.errors['mobile_nbr'][0])

    def test_phone_with_plus_is_accepted(self):
        form = EditProfileForm(data=self._form_data(mobile_nbr='+32612345678'))
        self.assertNotIn('mobile_nbr', form.errors)

    def test_empty_phone_is_accepted(self):
        form = EditProfileForm(data=self._form_data(mobile_nbr=''))
        self.assertNotIn('mobile_nbr', form.errors)

    def test_phone_with_spaces_and_plus_is_accepted(self):
        """Users may enter +32 6 123 456 78 — only the + prefix matters."""
        form = EditProfileForm(data=self._form_data(mobile_nbr='+32 6 123 456 78'))
        self.assertNotIn('mobile_nbr', form.errors)

    def test_phone_with_leading_whitespace_and_plus_is_accepted(self):
        """Leading/trailing whitespace should be stripped before validation."""
        form = EditProfileForm(data=self._form_data(mobile_nbr='  +32612345678  '))
        self.assertNotIn('mobile_nbr', form.errors)

    def test_phone_with_leading_whitespace_no_plus_is_rejected(self):
        form = EditProfileForm(data=self._form_data(mobile_nbr='  0612345678  '))
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_nbr', form.errors)


class EditProfileFormMatrixIdValidationTestCase(TestCase):
    """Tests for Matrix ID format validation."""

    def _form_data(self, **overrides):
        data = {'first_name': 'Test', 'last_name': 'User'}
        data.update(overrides)
        return data

    def test_valid_matrix_id_accepted(self):
        form = EditProfileForm(data=self._form_data(matrix_id='@user:matrix.org'))
        self.assertNotIn('matrix_id', form.errors)

    def test_matrix_id_without_at_sign_rejected(self):
        form = EditProfileForm(data=self._form_data(matrix_id='user:matrix.org'))
        self.assertFalse(form.is_valid())
        self.assertIn('matrix_id', form.errors)

    def test_matrix_id_without_colon_rejected(self):
        form = EditProfileForm(data=self._form_data(matrix_id='@usermatrix.org'))
        self.assertFalse(form.is_valid())
        self.assertIn('matrix_id', form.errors)

    def test_matrix_id_with_spaces_rejected(self):
        """Previously saved bad data should be caught on next edit."""
        form = EditProfileForm(data=self._form_data(matrix_id='@user name:matrix.org'))
        self.assertFalse(form.is_valid())
        self.assertIn('matrix_id', form.errors)

    def test_empty_matrix_id_accepted(self):
        form = EditProfileForm(data=self._form_data(matrix_id=''))
        self.assertNotIn('matrix_id', form.errors)

    def test_matrix_id_with_subdomain_server_accepted(self):
        form = EditProfileForm(data=self._form_data(matrix_id='@user:chat.example.com'))
        self.assertNotIn('matrix_id', form.errors)

    def test_matrix_id_with_special_chars_accepted(self):
        """Matrix allows . _ = - / in usernames."""
        form = EditProfileForm(data=self._form_data(matrix_id='@user.name_1=test:matrix.org'))
        self.assertNotIn('matrix_id', form.errors)

    def test_matrix_id_just_random_text_rejected(self):
        """Previously saved garbage data should be caught."""
        form = EditProfileForm(data=self._form_data(matrix_id='not a matrix id'))
        self.assertFalse(form.is_valid())
        self.assertIn('matrix_id', form.errors)
        self.assertIn('@username:homeserver.tld', form.errors['matrix_id'][0])


class TaskClashesDashboardTestCase(TestCase):
    def setUp(self):
        today = datetime.date.today()
        self.admin = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password',
        )
        user = User.objects.create_user(
            username='volunteer',
            first_name='Test',
            last_name='Volunteer',
            email='volunteer@example.com',
            password='password',
        )
        self.volunteer = Volunteer.objects.create(user=user)
        self.edition = Edition.objects.create(
            name='Current edition',
            start_date=today,
            end_date=today + datetime.timedelta(days=2),
            visible_from=today - datetime.timedelta(days=1),
            visible_until=today + datetime.timedelta(days=3),
        )
        category = TaskCategory.objects.create(
            name='General',
            description='General tasks',
        )
        template = TaskTemplate.objects.create(
            name='General',
            description='General tasks',
            category=category,
            primary=self.admin,
        )
        self.first_task = self._create_task(
            template, 'Morning setup', datetime.time(9), datetime.time(12)
        )
        self.second_task = self._create_task(
            template, 'Info desk', datetime.time(10), datetime.time(11)
        )
        self.adjacent_task = self._create_task(
            template, 'Lunch cover', datetime.time(12), datetime.time(13)
        )
        self.denied_task = self._create_task(
            template, 'Denied overlap', datetime.time(10, 15), datetime.time(10, 45)
        )
        self.first_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.first_task,
            status='approved',
        )
        self.second_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.second_task,
            status='pending',
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.adjacent_task,
            status='approved',
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.denied_task,
            status='denied',
        )

    def _create_task(self, template, name, start_time, end_time):
        return Task.objects.create(
            name=name,
            counter='1',
            description=name,
            location='K building',
            date=self.edition.start_date,
            start_time=start_time,
            end_time=end_time,
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=2,
            edition=self.edition,
            template=template,
        )

    def test_contained_pending_signup_is_reported_as_clash(self):
        clashes = _find_task_clashes([
            self.first_signup,
            self.second_signup,
        ])

        self.assertEqual(clashes, [[self.first_signup, self.second_signup]])

    def test_dashboard_lists_active_clash_but_not_adjacent_task(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('task_clashes_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Volunteer')
        self.assertContains(response, 'Morning setup')
        self.assertContains(response, 'Info desk')
        self.assertNotContains(response, 'Lunch cover')
        self.assertNotContains(response, 'Denied overlap')
        self.assertContains(response, 'Pending Approval')

    def test_non_superuser_cannot_open_dashboard(self):
        self.client.force_login(self.volunteer.user)

        response = self.client.get(reverse('task_clashes_dashboard'))

        self.assertEqual(response.status_code, 302)

    def test_admin_can_remove_clashing_signup(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('task_clashes_dashboard'), {
            'action': 'remove',
            'volunteer_id': self.volunteer.id,
            'signup_id': self.second_signup.id,
        })

        self.assertRedirects(response, reverse('task_clashes_dashboard'))
        self.assertFalse(
            VolunteerTask.objects.filter(id=self.second_signup.id).exists()
        )

    def test_admin_can_email_volunteer_about_all_clashes(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('task_clashes_dashboard'), {
            'action': 'email',
            'volunteer_id': self.volunteer.id,
        })

        self.assertRedirects(response, reverse('task_clashes_dashboard'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['volunteer@example.com'])
        self.assertIn('Morning setup', mail.outbox[0].body)
        self.assertIn('Info desk', mail.outbox[0].body)
        self.assertIn(
            'remove enough tasks from each conflict group',
            mail.outbox[0].body,
        )
        self.assertIn(
            'so that none of your remaining tasks overlap',
            mail.outbox[0].body,
        )
        self.assertIn(reverse('task_list'), mail.outbox[0].body)


class CurrentEditionWorkflowTestCase(TestCase):
    def setUp(self):
        today = datetime.date.today()
        self.admin = User.objects.create_superuser(
            username='workflow-admin',
            email='admin@example.com',
            password='password',
        )
        self.user = User.objects.create_user(
            username='workflow-volunteer',
            first_name='Approved',
            last_name='Volunteer',
            email='approved@example.com',
            password='password',
        )
        self.volunteer = Volunteer.objects.create(
            user=self.user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
            matrix_id='@approved:example.org',
            tshirt_size='M',
        )
        self.pending_user = User.objects.create_user(
            username='pending-volunteer',
            first_name='Pending',
            last_name='Volunteer',
            email='pending@example.com',
            password='password',
        )
        self.pending_volunteer = Volunteer.objects.create(
            user=self.pending_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
            matrix_id='@pending:example.org',
            tshirt_size='L',
        )
        self.denied_user = User.objects.create_user(
            username='denied-volunteer',
            first_name='Denied',
            last_name='Volunteer',
            email='denied@example.com',
            password='password',
        )
        self.denied_volunteer = Volunteer.objects.create(
            user=self.denied_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
            matrix_id='@denied:example.org',
            tshirt_size='XL',
        )
        self.edition = Edition.objects.create(
            name='Current edition',
            start_date=today,
            end_date=today + datetime.timedelta(days=2),
            visible_from=today - datetime.timedelta(days=1),
            visible_until=today + datetime.timedelta(days=3),
            enable_task_signin=True,
        )
        self.category = TaskCategory.objects.create(
            name='Workflow category',
            description='Workflow category',
        )
        self.template = TaskTemplate.objects.create(
            name='Workflow template',
            description='Workflow template',
            category=self.category,
            primary=self.admin,
        )
        self.task = self.create_task(
            name='Workflow task',
            start_time=datetime.time(10),
            end_time=datetime.time(11),
        )
        self.approved_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.task,
            status='approved',
        )
        self.pending_signup = VolunteerTask.objects.create(
            volunteer=self.pending_volunteer,
            task=self.task,
            status='pending',
        )
        self.denied_signup = VolunteerTask.objects.create(
            volunteer=self.denied_volunteer,
            task=self.task,
            status='denied',
        )

    def create_task(self, name, start_time, end_time, date=None, template=None, location='K building'):
        return Task.objects.create(
            name=name,
            counter='1',
            description=name,
            location=location,
            date=date or self.edition.start_date,
            start_time=start_time,
            end_time=end_time,
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=3,
            edition=self.edition,
            template=template or self.template,
        )

    def test_operational_schedule_and_csv_only_list_approved_volunteers(self):
        self.client.force_login(self.admin)

        page = self.client.get(reverse('task_schedule', args=[self.template.id]))
        csv_response = self.client.get(reverse('task_schedule_csv', args=[self.template.id]))

        self.assertContains(page, 'Approved Volunteer')
        self.assertNotContains(page, 'Pending Volunteer')
        self.assertNotContains(page, 'Denied Volunteer')
        csv_body = csv_response.content.decode()
        self.assertIn('Approved Volunteer', csv_body)
        self.assertNotIn('Pending Volunteer', csv_body)
        self.assertNotIn('Denied Volunteer', csv_body)

    def test_task_detail_separates_approved_and_pending_volunteers(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('task_detailed', args=[self.task.id]))

        self.assertContains(response, 'Approved Volunteer')
        self.assertContains(response, 'Pending Volunteer')
        self.assertContains(response, 'Pending Approval')
        self.assertNotContains(response, 'Denied Volunteer')

    def test_task_detail_keeps_each_short_roster_member_visible(self):
        edge_user = User.objects.create_user(
            username='local-edgecase-max',
            first_name='A' * 150,
            last_name='Z' * 150,
            email='edge@example.com',
            password='password',
        )
        edge_volunteer = Volunteer.objects.create(
            user=edge_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        third_user = User.objects.create_user(
            username='third-volunteer',
            first_name='Avery',
            last_name='Novak',
            email='third@example.com',
            password='password',
        )
        third_volunteer = Volunteer.objects.create(
            user=third_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        VolunteerTask.objects.create(
            volunteer=edge_volunteer,
            task=self.task,
            status='approved',
        )
        VolunteerTask.objects.create(
            volunteer=third_volunteer,
            task=self.task,
            status='approved',
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('task_detailed', args=[self.task.id]))

        self.assertContains(response, '<ul class="space-y-0.5">', html=False)
        self.assertContains(response, 'Approved Volunteer')
        self.assertContains(response, 'Avery Novak')
        self.assertContains(response, 'A' * 150)

    def test_labels_tshirts_and_matrix_export_only_include_approved(self):
        self.client.force_login(self.admin)

        labels = self.client.get(reverse('label_dashboard'))
        shirts = self.client.get(reverse('tshirt_report'))
        matrix_export = self.client.get(reverse('matrix_ids_export') + '?download=1')

        self.assertContains(labels, 'Approved Volunteer')
        self.assertNotContains(labels, 'Pending Volunteer')
        self.assertNotContains(labels, 'Denied Volunteer')
        shirt_names = {
            volunteer.user.get_full_name()
            for _size, volunteers in shirts.context['breakdown']
            for volunteer, _count, _dates in volunteers
        }
        self.assertEqual(shirt_names, {'Approved Volunteer'})
        self.assertEqual(matrix_export.content.decode(), '@approved:example.org')

    def test_own_schedule_shows_pending_status_and_omits_denied(self):
        pending_only = self.create_task(
            'Pending-only task',
            datetime.time(11),
            datetime.time(12),
        )
        denied_only = self.create_task(
            'Denied-only task',
            datetime.time(12),
            datetime.time(13),
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=pending_only,
            status='pending',
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=denied_only,
            status='denied',
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('task_list_detailed', args=[self.user.username])
        )

        self.assertContains(response, 'Workflow task')
        self.assertContains(response, 'Pending-only task')
        self.assertContains(response, 'Pending approval')
        self.assertNotContains(response, 'Denied-only task')

    def test_profile_shows_pending_status_and_approved_history_only(self):
        pending_only = self.create_task(
            'Profile pending task',
            datetime.time(11),
            datetime.time(12),
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=pending_only,
            status='pending',
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('userena_profile_detail', args=[self.user.username])
        )

        self.assertContains(response, 'Profile pending task')
        self.assertContains(response, 'Pending approval')

    @patch('volunteers.models.send_mail')
    def test_mailed_schedule_excludes_pending_and_denied(self, send_mail):
        pending_task = self.create_task(
            'Pending mail task',
            datetime.time(11),
            datetime.time(12),
        )
        denied_task = self.create_task(
            'Denied mail task',
            datetime.time(12),
            datetime.time(13),
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=pending_task,
            status='pending',
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=denied_task,
            status='denied',
        )

        self.volunteer.mail_schedule()

        body = send_mail.call_args.args[1]
        self.assertIn('Workflow task', body)
        self.assertNotIn('Pending mail task', body)
        self.assertNotIn('Denied mail task', body)

    def test_task_location_reference_updates_when_location_changes(self):
        self.assertEqual(self.task.location_ref.name, 'K building')

        self.task.location = 'H building'
        self.task.save(update_fields=['location'])
        self.task.refresh_from_db()

        self.assertEqual(self.task.location_ref, Location.objects.get(name='H building'))

    def test_approval_required_signup_is_pending(self):
        approval_task = self.create_task(
            'Approval task',
            datetime.time(11),
            datetime.time(12),
        )
        approval_task.requires_approval = True
        approval_task.save(update_fields=['requires_approval'])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('task_toggle', args=[approval_task.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'pending')
        self.assertEqual(
            VolunteerTask.objects.get(
                volunteer=self.volunteer,
                task=approval_task,
            ).status,
            'pending',
        )

    def test_full_task_rejects_self_service_signup(self):
        full_task = self.create_task(
            'Full task',
            datetime.time(11),
            datetime.time(12),
        )
        full_task.nbr_volunteers_max = 1
        full_task.save(update_fields=['nbr_volunteers_max'])
        VolunteerTask.objects.create(
            volunteer=self.pending_volunteer,
            task=full_task,
            status='approved',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('task_toggle', args=[full_task.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(
            VolunteerTask.objects.filter(
                volunteer=self.volunteer,
                task=full_task,
            ).exists()
        )

    def test_privacy_policy_reconsent_updates_version(self):
        self.volunteer.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION - 1
        self.volunteer.save(update_fields=['privacy_policy_version'])
        self.client.force_login(self.user)

        blocked = self.client.get(reverse('task_list'))
        self.assertRedirects(
            blocked,
            reverse('privacy_policy_consent'),
            fetch_redirect_response=False,
        )
        accepted = self.client.post(
            reverse('privacy_policy_consent'),
            {'agree': 'yes'},
        )
        self.volunteer.refresh_from_db()

        self.assertRedirects(accepted, reverse('task_list'))
        self.assertEqual(
            self.volunteer.privacy_policy_version,
            CURRENT_PRIVACY_POLICY_VERSION,
        )

    @patch('volunteers.models.connections')
    def test_pentabarf_sync_only_tracks_approved_assignments(self, connections):
        track = Track.objects.create(
            title='Track',
            description='Track',
            edition=self.edition,
            date=self.edition.start_date,
            start_time=datetime.time(10),
        )
        talk = Talk.objects.create(
            ext_id='event-1',
            track=track,
            title='Talk',
            speaker='Speaker',
            description='Talk',
            location='K building',
            date=self.edition.start_date,
            start_time=datetime.time(10),
            end_time=datetime.time(11),
        )
        penta_task = self.create_task(
            'Talk task',
            datetime.time(10),
            datetime.time(11),
        )
        penta_task.talk = talk
        penta_task.save(update_fields=['talk'])
        self.volunteer.penta_account_name = 'penta-user'
        self.volunteer.save(update_fields=['penta_account_name'])
        cursor = (
            connections.__getitem__.return_value.cursor.return_value
            .__enter__.return_value
        )

        signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=penta_task,
            status='pending',
        )
        cursor.execute.assert_not_called()

        signup.status = 'approved'
        signup.save(update_fields=['status'])
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn('insert into event_person', cursor.execute.call_args.args[0])

        cursor.execute.reset_mock()
        signup.status = 'denied'
        signup.save(update_fields=['status'])
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn('delete from event_person', cursor.execute.call_args.args[0])

    def test_missing_schedule_objects_return_404(self):
        self.client.force_login(self.admin)

        self.assertEqual(
            self.client.get(reverse('task_schedule', args=[999999])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse('task_list_detailed', args=['missing-volunteer'])
            ).status_code,
            404,
        )

    def test_non_superuser_is_denied_admin_operations(self):
        self.client.force_login(self.user)

        for url_name in ('label_dashboard', 'attendance_dashboard', 'task_clashes_dashboard'):
            self.assertEqual(self.client.get(reverse(url_name)).status_code, 403)


class OperationalPermissionsTestCase(TestCase):
    def setUp(self):
        today = datetime.date.today()
        self.primary = self.create_staff_user('primary')
        self.secondary = self.create_staff_user('secondary')
        self.other_lead = self.create_staff_user('other-lead')
        self.coordinator = self.create_staff_user('coordinator')
        self.logistics = self.create_staff_user('logistics')
        self.ordinary_staff = self.create_staff_user('ordinary-staff')
        self.volunteer_user = User.objects.create_user(
            username='permission-volunteer',
            first_name='Permission',
            last_name='Volunteer',
            email='permission-volunteer@example.com',
            password='password',
        )
        self.volunteer = Volunteer.objects.create(
            user=self.volunteer_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        self.edition = Edition.objects.create(
            name='Permission edition',
            start_date=today,
            end_date=today + datetime.timedelta(days=1),
            visible_from=today - datetime.timedelta(days=1),
            visible_until=today + datetime.timedelta(days=2),
            enable_task_signin=True,
        )
        self.previous_edition = Edition.objects.create(
            name='Previous permission edition',
            start_date=today - datetime.timedelta(days=365),
            end_date=today - datetime.timedelta(days=364),
            visible_from=today - datetime.timedelta(days=370),
            visible_until=today - datetime.timedelta(days=360),
        )
        self.category = TaskCategory.objects.create(
            name='Permission category',
            description='Permission category',
        )
        self.template = TaskTemplate.objects.create(
            name='Owned template',
            description='Owned template',
            category=self.category,
            primary=self.primary,
            secondary=self.secondary,
        )
        self.other_template = TaskTemplate.objects.create(
            name='Other template',
            description='Other template',
            category=self.category,
            primary=self.other_lead,
        )
        self.task = self.create_task(self.template, 'Owned task')
        self.other_task = self.create_task(self.other_template, 'Other task')
        self.pending = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.task,
            status='pending',
        )
        self.other_pending = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.other_task,
            status='pending',
        )
        Group.objects.get(name='Coordinator').user_set.add(self.coordinator)
        Group.objects.get(name='Logistics').user_set.add(self.logistics)

    def create_staff_user(self, username):
        user = User.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password='password',
            is_staff=True,
        )
        Volunteer.objects.create(
            user=user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        return user

    def create_task(self, template, name, edition=None):
        target_edition = edition or self.edition
        return Task.objects.create(
            name=name,
            counter='1',
            description=name,
            location='K building',
            date=target_edition.start_date,
            start_time=datetime.time(10),
            end_time=datetime.time(11),
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=3,
            edition=target_edition,
            template=template,
        )

    def test_bootstrapped_groups_have_only_their_default_permissions(self):
        coordinator_codenames = set(
            Group.objects.get(name='Coordinator')
            .permissions.values_list('codename', flat=True)
        )
        logistics_codenames = set(
            Group.objects.get(name='Logistics')
            .permissions.values_list('codename', flat=True)
        )

        self.assertIn('manage_attendance', coordinator_codenames)
        self.assertNotIn('manage_labels', coordinator_codenames)
        self.assertEqual(
            logistics_codenames,
            {'manage_labels', 'view_tshirt_report', 'export_matrix_ids'},
        )

    def test_primary_and_secondary_see_only_their_approvals(self):
        for responsible in (self.primary, self.secondary):
            self.client.force_login(responsible)

            response = self.client.get(reverse('approval_dashboard'))

            self.assertContains(response, 'Owned task')
            self.assertNotContains(response, 'Other task')

    def test_coordinator_sees_global_operational_surfaces(self):
        self.client.force_login(self.coordinator)

        approvals = self.client.get(reverse('approval_dashboard'))
        attendance = self.client.get(reverse('attendance_dashboard'))

        self.assertContains(approvals, 'Owned task')
        self.assertContains(approvals, 'Other task')
        self.assertEqual(attendance.status_code, 200)

    def test_approval_request_notifies_both_responsibles(self):
        from volunteers.emails import send_approval_request_email

        send_approval_request_email(self.volunteer, self.task)

        self.assertEqual(
            {message.to[0] for message in mail.outbox},
            {self.primary.email, self.secondary.email},
        )

    def test_secondary_can_approve_own_task_and_action_is_audited(self):
        self.client.force_login(self.secondary)

        response = self.client.post(reverse('approval_respond'), {
            'vt_id': self.pending.id,
            'action': 'approve',
        })
        self.pending.refresh_from_db()

        self.assertRedirects(response, reverse('approval_dashboard'))
        self.assertEqual(self.pending.status, 'approved')
        self.assertEqual(self.pending.reviewed_by, self.secondary)
        self.assertTrue(
            LogEntry.objects.filter(
                user=self.secondary,
                object_id=str(self.pending.id),
            ).exists()
        )

    def test_secondary_cannot_approve_another_responsibles_task(self):
        self.client.force_login(self.secondary)

        response = self.client.post(reverse('approval_respond'), {
            'vt_id': self.other_pending.id,
            'action': 'approve',
        })
        self.other_pending.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.other_pending.status, 'pending')

    def test_task_responsible_sees_only_same_template_history(self):
        previous_same = self.create_task(
            self.template,
            'Previous owned task',
            self.previous_edition,
        )
        previous_other = self.create_task(
            self.other_template,
            'Previous unrelated task',
            self.previous_edition,
        )
        previous_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=previous_same,
            status='approved',
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=previous_other,
            status='approved',
        )
        TaskAttendance.objects.create(
            volunteer_task=previous_signup,
            signed_in_at=timezone.now(),
        )
        self.client.force_login(self.primary)

        response = self.client.get(reverse('approval_dashboard'))

        self.assertContains(response, 'Previously assigned once')
        self.assertContains(response, self.previous_edition.name)
        self.assertContains(response, '1 recorded check-in')
        self.assertNotContains(response, 'Previous unrelated task')

    def test_task_responsible_can_manage_own_attendance_but_not_other_task(self):
        approved = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=self.task,
            status='approved',
        )
        self.client.force_login(self.secondary)

        own_detail = self.client.get(
            reverse('attendance_task_detail', args=[self.task.id])
        )
        other_detail = self.client.get(
            reverse('attendance_task_detail', args=[self.other_task.id])
        )
        marked = self.client.post(reverse('attendance_mark'), {
            'vt_id': approved.id,
            'action': 'signin',
        })

        self.assertEqual(own_detail.status_code, 200)
        self.assertEqual(other_detail.status_code, 403)
        self.assertRedirects(
            marked,
            reverse('attendance_task_detail', args=[self.task.id]),
        )

    def test_task_responsible_can_export_only_their_task_template(self):
        self.client.force_login(self.secondary)

        schedule_index = self.client.get(reverse('category_schedule_list'))
        own_schedule = self.client.get(
            reverse('task_schedule', args=[self.template.id])
        )
        other_schedule = self.client.get(
            reverse('task_schedule', args=[self.other_template.id])
        )
        own_export = self.client.get(
            reverse('task_schedule_csv', args=[self.template.id])
        )
        other_export = self.client.get(
            reverse('task_schedule_csv', args=[self.other_template.id])
        )

        self.assertContains(schedule_index, self.template.name)
        self.assertNotContains(schedule_index, self.other_template.name)
        self.assertEqual(own_schedule.status_code, 200)
        self.assertEqual(other_schedule.status_code, 403)
        self.assertEqual(own_export.status_code, 200)
        self.assertEqual(other_export.status_code, 403)

    def test_removed_staff_status_revokes_task_responsible_access(self):
        self.secondary.is_staff = False
        self.secondary.save(update_fields=['is_staff'])
        self.client.force_login(self.secondary)

        response = self.client.get(reverse('approval_dashboard'))

        self.assertEqual(response.status_code, 403)

    def test_task_responsible_can_request_runner_without_removing_source(self):
        runner_template = TaskTemplate.objects.create(
            name='Runner',
            description='Runner',
            category=self.category,
            primary=self.other_lead,
        )
        runner_task = self.create_task(runner_template, 'Runner')
        runner_signup = VolunteerTask.objects.create(
            volunteer=self.secondary.volunteer,
            task=runner_task,
            status='approved',
        )
        self.client.force_login(self.secondary)

        response = self.client.post(reverse('transfer_runner'), {
            'task_id': self.task.id,
            'runner_vt_id': runner_signup.id,
        })

        self.assertRedirects(
            response,
            reverse('attendance_task_detail', args=[self.task.id]),
        )
        self.assertTrue(
            VolunteerTask.objects.filter(id=runner_signup.id).exists()
        )
        deployment = RunnerDeployment.objects.get(
            runner_assignment=runner_signup,
            destination_task=self.task,
        )
        self.assertEqual(deployment.status, 'pending')
        self.assertEqual(deployment.requested_by, self.secondary)
        self.assertFalse(
            VolunteerTask.objects.filter(
                volunteer=self.secondary.volunteer,
                task=self.task,
            ).exists()
        )

    def test_logistics_access_is_limited_to_logistics_surfaces(self):
        self.client.force_login(self.logistics)

        self.assertEqual(
            self.client.get(reverse('label_dashboard')).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('approval_dashboard')).status_code,
            403,
        )

    def test_ordinary_staff_has_no_implicit_operational_access(self):
        self.client.force_login(self.ordinary_staff)

        for url_name in (
            'approval_dashboard',
            'attendance_dashboard',
            'label_dashboard',
        ):
            self.assertEqual(self.client.get(reverse(url_name)).status_code, 403)

    def test_navigation_matches_task_responsible_scope(self):
        self.client.force_login(self.secondary)

        response = self.client.get(reverse('approval_dashboard'))

        self.assertContains(response, 'Approvals')
        self.assertContains(response, 'Attendance')
        self.assertNotContains(response, 'Django Admin')
        self.assertNotContains(response, 'T-shirt Report')
        self.assertNotContains(response, 'Matrix IDs')

    def test_same_user_cannot_be_primary_and_secondary(self):
        template = TaskTemplate(
            name='Invalid template',
            description='Invalid template',
            category=self.category,
            primary=self.primary,
            secondary=self.primary,
        )

        with self.assertRaises(ValidationError):
            template.full_clean()


class CommunicationsComposeTestCase(TestCase):
    def setUp(self):
        today = datetime.date.today()
        self.primary = self.create_staff_user('comms-primary')
        self.other_lead = self.create_staff_user('comms-other-lead')
        self.admin = self.create_staff_user('comms-admin')
        self.admin.user_permissions.add(
            Permission.objects.get(codename='send_mass_mail')
        )
        self.coordinator = self.create_staff_user('comms-coordinator')
        Group.objects.get(name='Coordinator').user_set.add(self.coordinator)
        self.edition = Edition.objects.create(
            name='Comms edition',
            start_date=today,
            end_date=today + datetime.timedelta(days=1),
            visible_from=today - datetime.timedelta(days=1),
            visible_until=today + datetime.timedelta(days=2),
        )
        self.category = TaskCategory.objects.create(
            name='Comms category',
            description='Comms category',
        )
        self.template = TaskTemplate.objects.create(
            name='Owned comms template',
            description='Owned comms template',
            category=self.category,
            primary=self.primary,
        )
        self.other_template = TaskTemplate.objects.create(
            name='Other comms template',
            description='Other comms template',
            category=self.category,
            primary=self.other_lead,
        )
        self.task = self.create_task(self.template, 'Owned comms task')
        self.other_task = self.create_task(self.other_template, 'Other comms task')

        self.approved_volunteer = self.create_volunteer('comms-approved', 'approved@example.com')
        self.pending_volunteer = self.create_volunteer('comms-pending', 'pending@example.com')
        self.no_email_volunteer = self.create_volunteer('comms-noemail', '')

        VolunteerTask.objects.create(volunteer=self.approved_volunteer, task=self.task, status='approved')
        VolunteerTask.objects.create(volunteer=self.pending_volunteer, task=self.task, status='pending')
        VolunteerTask.objects.create(volunteer=self.no_email_volunteer, task=self.task, status='approved')

        self.other_task_volunteer = self.create_volunteer('comms-other-task', 'other-task@example.com')
        VolunteerTask.objects.create(volunteer=self.other_task_volunteer, task=self.other_task, status='approved')

    def create_staff_user(self, username):
        user = User.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password='password',
            is_staff=True,
        )
        Volunteer.objects.create(
            user=user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        return user

    def create_volunteer(self, username, email):
        user = User.objects.create_user(
            username=username,
            first_name=username,
            email=email,
            password='password',
        )
        return Volunteer.objects.create(
            user=user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )

    def create_task(self, template, name):
        return Task.objects.create(
            name=name,
            counter='1',
            description=name,
            location='K building',
            date=self.edition.start_date,
            start_time=datetime.time(10),
            end_time=datetime.time(11),
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=3,
            edition=self.edition,
            template=template,
        )

    def test_task_owner_can_compose_and_send_to_approved_volunteers(self):
        self.client.force_login(self.primary)

        response = self.client.post(
            reverse('task_email_compose', args=[self.task.id]),
            {'action': 'send', 'subject': 'Task info', 'message': 'Body text'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['approved@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'Task info')

    def test_include_pending_expands_audience(self):
        self.client.force_login(self.primary)

        self.client.post(
            reverse('task_email_compose', args=[self.task.id]),
            {
                'action': 'send',
                'subject': 'Task info',
                'message': 'Body text',
                'include_pending': 'on',
            },
        )

        recipients = {message.to[0] for message in mail.outbox}
        self.assertEqual(recipients, {'approved@example.com', 'pending@example.com'})

    def test_each_recipient_gets_a_separate_email(self):
        self.client.force_login(self.primary)

        self.client.post(
            reverse('task_email_compose', args=[self.task.id]),
            {
                'action': 'send',
                'subject': 'Task info',
                'message': 'Body text',
                'include_pending': 'on',
            },
        )

        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)

    def test_non_owner_cannot_compose_for_task(self):
        self.client.force_login(self.other_lead)

        response = self.client.get(reverse('task_email_compose', args=[self.task.id]))

        self.assertEqual(response.status_code, 403)

    def test_admin_permission_can_compose_for_any_task(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('task_email_compose', args=[self.task.id]))

        self.assertEqual(response.status_code, 200)

    def test_category_compose_dedupes_across_tasks(self):
        second_task = self.create_task(self.template, 'Second comms task')
        VolunteerTask.objects.create(volunteer=self.approved_volunteer, task=second_task, status='approved')
        self.client.force_login(self.primary)

        self.client.post(
            reverse('category_email_compose', args=[self.category.id]),
            {'action': 'send', 'subject': 'Category info', 'message': 'Body text'},
        )

        self.assertEqual(len(mail.outbox), 2)
        recipients = {message.to[0] for message in mail.outbox}
        self.assertEqual(recipients, {'approved@example.com', 'other-task@example.com'})

    def test_non_owner_cannot_compose_for_category(self):
        third_lead = self.create_staff_user('comms-third-lead')
        self.client.force_login(third_lead)

        response = self.client.get(reverse('category_email_compose', args=[self.category.id]))

        self.assertEqual(response.status_code, 403)

    def test_volunteer_compose_sends_single_email(self):
        self.client.force_login(self.primary)

        response = self.client.post(
            reverse('volunteer_email_compose', args=[self.task.id, self.approved_volunteer.id]),
            {'action': 'send', 'subject': 'Hello', 'message': 'Body text'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['approved@example.com'])

    def test_volunteer_compose_rejects_volunteer_from_other_task(self):
        outside_volunteer = self.create_volunteer('comms-outside', 'outside@example.com')
        self.client.force_login(self.primary)

        response = self.client.get(
            reverse('volunteer_email_compose', args=[self.task.id, outside_volunteer.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_no_email_volunteer_is_skipped(self):
        self.client.force_login(self.primary)

        response = self.client.get(reverse('task_email_compose', args=[self.task.id]))

        self.assertContains(response, 'skipped')

    def test_coordinator_can_email_whole_edition(self):
        self.client.force_login(self.coordinator)

        self.client.post(
            reverse('edition_email_compose'),
            {'action': 'send', 'subject': 'Edition info', 'message': 'Body text'},
        )

        recipients = {message.to[0] for message in mail.outbox}
        self.assertEqual(recipients, {'approved@example.com', 'other-task@example.com'})

    def test_admin_can_email_whole_edition(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('edition_email_compose'))

        self.assertEqual(response.status_code, 200)

    def test_task_owner_without_broader_role_cannot_email_edition(self):
        self.client.force_login(self.primary)

        response = self.client.get(reverse('edition_email_compose'))

        self.assertEqual(response.status_code, 403)

    def test_edition_compose_button_visible_only_to_authorized_users(self):
        self.client.force_login(self.coordinator)
        coordinator_response = self.client.get(reverse('communications_dashboard'))
        self.assertContains(coordinator_response, 'Email all volunteers')

        self.client.force_login(self.primary)
        owner_response = self.client.get(reverse('communications_dashboard'))
        self.assertNotContains(owner_response, 'Email all volunteers')


class ActivationHardeningTestCase(TestCase):
    def test_login_validation_handles_user_without_volunteer_profile(self):
        user = User.objects.create_user(
            username='partial-user',
            email='partial@example.com',
            password='password',
        )
        form = ActivationAwareAuthenticationForm()

        with self.assertRaises(ValidationError):
            form.confirm_login_allowed(user)

    def test_activation_token_for_user_without_profile_fails_cleanly(self):
        user = User.objects.create_user(
            username='partial-activation',
            email='partial-activation@example.com',
            password='password',
        )
        confirmation = EmailConfirmation.objects.create(user=user)

        response = self.client.get(reverse('activate', args=[confirmation.token]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'userena/activate_fail.html')

    def test_valid_activation_marks_profile_confirmed_and_consumes_token(self):
        user = User.objects.create_user(
            username='valid-activation',
            email='valid-activation@example.com',
            password='password',
        )
        volunteer = Volunteer.objects.create(user=user, email_confirmed=False)
        confirmation = EmailConfirmation.objects.create(user=user)

        response = self.client.get(reverse('activate', args=[confirmation.token]))
        volunteer.refresh_from_db()

        self.assertRedirects(response, reverse('task_list'))
        self.assertTrue(volunteer.email_confirmed)
        self.assertFalse(
            EmailConfirmation.objects.filter(id=confirmation.id).exists()
        )


class AttendanceWorkflowTestCase(TestCase):
    def setUp(self):
        now = timezone.localtime()
        self.admin = User.objects.create_superuser(
            username='attendance-admin',
            email='attendance-admin@example.com',
            password='password',
        )
        self.user = User.objects.create_user(
            username='attendance-volunteer',
            email='attendance@example.com',
            password='password',
        )
        self.volunteer = Volunteer.objects.create(
            user=self.user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        self.other_user = User.objects.create_user(
            username='other-volunteer',
            email='other@example.com',
            password='password',
        )
        self.other_volunteer = Volunteer.objects.create(
            user=self.other_user,
            email_confirmed=True,
            privacy_policy_accepted_at=timezone.now(),
            privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        )
        self.edition = Edition.objects.create(
            name='Attendance edition',
            start_date=now.date() - datetime.timedelta(days=1),
            end_date=now.date() + datetime.timedelta(days=1),
            visible_from=now.date() - datetime.timedelta(days=2),
            visible_until=now.date() + datetime.timedelta(days=2),
            enable_task_signin=True,
        )
        category = TaskCategory.objects.create(
            name='Attendance category',
            description='Attendance category',
        )
        self.template = TaskTemplate.objects.create(
            name='Attendance template',
            description='Attendance template',
            category=category,
            primary=self.admin,
        )

    def create_task(self, name, start, end, date=None):
        return Task.objects.create(
            name=name,
            counter='1',
            description=name,
            date=date or timezone.localdate(),
            start_time=start,
            end_time=end,
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=2,
            edition=self.edition,
            template=self.template,
        )

    def create_runner_assignment(self):
        now = timezone.localtime()
        runner_template = TaskTemplate.objects.create(
            name='Runner',
            description='Runner',
            category=self.template.category,
            primary=self.admin,
        )
        runner_task = Task.objects.create(
            name='Runner',
            counter='1',
            description='Runner',
            date=timezone.localdate(),
            start_time=(now - datetime.timedelta(minutes=5)).time(),
            end_time=(now + datetime.timedelta(hours=1)).time(),
            nbr_volunteers=1,
            nbr_volunteers_min=1,
            nbr_volunteers_max=2,
            edition=self.edition,
            template=runner_template,
        )
        return VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=runner_task,
            status='approved',
        )

    def test_volunteer_cannot_check_in_for_someone_else(self):
        now = timezone.localtime()
        task = self.create_task(
            'Current task',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        other_signup = VolunteerTask.objects.create(
            volunteer=self.other_volunteer,
            task=task,
            status='approved',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('task_signin_ui', args=[other_signup.id]))

        self.assertEqual(response.status_code, 404)

    def test_signin_reminder_and_auto_checkout_command(self):
        now = timezone.make_aware(
            datetime.datetime.combine(timezone.localdate(), datetime.time(12))
        )
        upcoming_task = self.create_task(
            'Upcoming task',
            datetime.time(12, 5),
            datetime.time(13),
        )
        upcoming_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=upcoming_task,
            status='approved',
        )
        upcoming_attendance = TaskAttendance.objects.create(
            volunteer_task=upcoming_signup
        )
        finished_task = self.create_task(
            'Finished task',
            datetime.time(10),
            datetime.time(11),
        )
        finished_signup = VolunteerTask.objects.create(
            volunteer=self.other_volunteer,
            task=finished_task,
            status='approved',
        )
        finished_attendance = TaskAttendance.objects.create(
            volunteer_task=finished_signup,
            signed_in_at=now - datetime.timedelta(hours=2),
        )

        with patch(
            'volunteers.management.commands.process_signin_notifications.timezone.now',
            return_value=now,
        ):
            call_command('process_signin_notifications')
        upcoming_attendance.refresh_from_db()
        finished_attendance.refresh_from_db()

        self.assertIsNotNone(upcoming_attendance.reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(finished_attendance.signed_out_at)

    def test_coordinator_deployment_preserves_both_assignments(self):
        now = timezone.localtime()
        destination = self.create_task(
            'Needs help',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        self.client.force_login(self.admin)

        response = self.client.post(reverse('transfer_runner'), {
            'task_id': destination.id,
            'runner_vt_id': runner_signup.id,
        })

        self.assertRedirects(
            response,
            reverse('attendance_task_detail', args=[destination.id]),
        )
        self.assertTrue(VolunteerTask.objects.filter(id=runner_signup.id).exists())
        new_signup = VolunteerTask.objects.get(
            volunteer=self.volunteer,
            task=destination,
        )
        self.assertEqual(new_signup.status, 'approved')
        attendance = TaskAttendance.objects.get(volunteer_task=new_signup)
        self.assertIsNotNone(attendance.signed_in_at)
        deployment = RunnerDeployment.objects.get(
            runner_assignment=runner_signup,
            destination_assignment=new_signup,
        )
        self.assertEqual(deployment.status, 'active')
        self.assertEqual(deployment.requested_by, self.admin)
        self.assertEqual(deployment.reviewed_by, self.admin)

    def test_task_responsible_requests_and_coordinator_approves_deployment(self):
        now = timezone.localtime()
        responsible = User.objects.create_user(
            username='task-responsible',
            email='responsible@example.com',
            password='password',
            is_staff=True,
        )
        self.template.secondary = responsible
        self.template.save()
        destination = self.create_task(
            'Needs approval',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        self.client.force_login(responsible)

        response = self.client.post(reverse('transfer_runner'), {
            'task_id': destination.id,
            'runner_vt_id': runner_signup.id,
        })

        self.assertRedirects(
            response,
            reverse('attendance_task_detail', args=[destination.id]),
        )
        deployment = RunnerDeployment.objects.get()
        self.assertEqual(deployment.status, 'pending')
        self.assertFalse(
            VolunteerTask.objects.filter(
                volunteer=self.volunteer,
                task=destination,
            ).exists()
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('runner_deployment_review', args=[deployment.id]),
            {'action': 'approve'},
        )
        deployment.refresh_from_db()

        self.assertRedirects(response, reverse('attendance_dashboard'))
        self.assertEqual(deployment.status, 'active')
        self.assertTrue(VolunteerTask.objects.filter(id=runner_signup.id).exists())
        self.assertIsNotNone(deployment.destination_assignment)

    def test_denied_deployment_does_not_change_assignments(self):
        now = timezone.localtime()
        destination = self.create_task(
            'Denied help',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        deployment = RunnerDeployment.objects.create(
            runner_assignment=runner_signup,
            destination_task=destination,
            requested_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('runner_deployment_review', args=[deployment.id]),
            {'action': 'deny', 'review_note': 'No longer needed'},
        )
        deployment.refresh_from_db()

        self.assertRedirects(response, reverse('attendance_dashboard'))
        self.assertEqual(deployment.status, 'denied')
        self.assertEqual(deployment.review_note, 'No longer needed')
        self.assertTrue(VolunteerTask.objects.filter(id=runner_signup.id).exists())
        self.assertFalse(
            VolunteerTask.objects.filter(
                volunteer=self.volunteer,
                task=destination,
            ).exists()
        )

    def test_return_completes_deployment_and_preserves_assignments(self):
        now = timezone.localtime()
        destination = self.create_task(
            'Temporary help',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        self.client.force_login(self.admin)
        self.client.post(reverse('transfer_runner'), {
            'task_id': destination.id,
            'runner_vt_id': runner_signup.id,
        })
        deployment = RunnerDeployment.objects.get()

        response = self.client.post(
            reverse('runner_deployment_return', args=[deployment.id]),
        )
        deployment.refresh_from_db()
        attendance = TaskAttendance.objects.get(
            volunteer_task=deployment.destination_assignment,
        )

        self.assertRedirects(
            response,
            reverse('attendance_task_detail', args=[destination.id]),
        )
        self.assertEqual(deployment.status, 'completed')
        self.assertIsNotNone(deployment.returned_at)
        self.assertIsNotNone(attendance.signed_out_at)
        self.assertTrue(VolunteerTask.objects.filter(id=runner_signup.id).exists())
        self.assertTrue(
            VolunteerTask.objects.filter(
                id=deployment.destination_assignment_id,
            ).exists()
        )

    def test_open_deployment_removes_runner_from_available_list(self):
        now = timezone.localtime()
        responsible = User.objects.create_user(
            username='availability-responsible',
            email='availability@example.com',
            password='password',
            is_staff=True,
        )
        self.template.secondary = responsible
        self.template.save()
        destination = self.create_task(
            'Needs runner',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        self.client.force_login(responsible)
        self.client.post(reverse('transfer_runner'), {
            'task_id': destination.id,
            'runner_vt_id': runner_signup.id,
        })

        response = self.client.get(
            reverse('attendance_task_detail', args=[destination.id]),
        )

        self.assertEqual(list(response.context['available_runners']), [])
        self.assertEqual(response.context['task_deployments'].count(), 1)

    def test_task_responsible_cannot_review_deployment_request(self):
        now = timezone.localtime()
        responsible = User.objects.create_user(
            username='review-responsible',
            email='review@example.com',
            password='password',
            is_staff=True,
        )
        self.template.secondary = responsible
        self.template.save()
        destination = self.create_task(
            'Review protected',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        deployment = RunnerDeployment.objects.create(
            runner_assignment=self.create_runner_assignment(),
            destination_task=destination,
            requested_by=responsible,
        )
        self.client.force_login(responsible)

        response = self.client.post(
            reverse('runner_deployment_review', args=[deployment.id]),
            {'action': 'approve'},
        )
        deployment.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(deployment.status, 'pending')

    def test_stale_approval_invalidates_request(self):
        now = timezone.localtime()
        destination = self.create_task(
            'Stale deployment',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        deployment = RunnerDeployment.objects.create(
            runner_assignment=runner_signup,
            destination_task=destination,
            requested_by=self.admin,
        )
        VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=destination,
            status='approved',
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('runner_deployment_review', args=[deployment.id]),
            {'action': 'approve'},
        )
        deployment.refresh_from_db()

        self.assertRedirects(response, reverse('attendance_dashboard'))
        self.assertEqual(deployment.status, 'invalidated')
        self.assertIsNone(deployment.destination_assignment)

    def test_deployment_overlap_is_suppressed_but_third_task_still_clashes(self):
        now = timezone.localtime()
        destination = self.create_task(
            'Intentional destination',
            (now - datetime.timedelta(minutes=5)).time(),
            (now + datetime.timedelta(hours=1)).time(),
        )
        runner_signup = self.create_runner_assignment()
        self.client.force_login(self.admin)
        self.client.post(reverse('transfer_runner'), {
            'task_id': destination.id,
            'runner_vt_id': runner_signup.id,
        })
        deployment = RunnerDeployment.objects.get()

        self.assertEqual(
            _find_task_clashes([
                runner_signup,
                deployment.destination_assignment,
            ]),
            [],
        )

        third_task = self.create_task(
            'Unrelated overlap',
            now.time(),
            (now + datetime.timedelta(minutes=30)).time(),
        )
        third_signup = VolunteerTask.objects.create(
            volunteer=self.volunteer,
            task=third_task,
            status='approved',
        )
        clashes = _find_task_clashes([
            runner_signup,
            deployment.destination_assignment,
            third_signup,
        ])

        self.assertEqual(len(clashes), 1)
        self.assertIn(third_signup, clashes[0])
