"""
Tests to be run via "manage.py test"
"""

from unittest.mock import patch
from django.test import TestCase
from volunteers.views import promo
from volunteers.forms import EditProfileForm


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
