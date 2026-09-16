"""
Tests to be run via "manage.py test"
"""

import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from volunteers.forms import EditProfileForm
from volunteers.models import (
    Edition,
    Task,
    TaskCategory,
    TaskTemplate,
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
