from django.urls import path, re_path
from django.contrib.auth.decorators import login_required
from django.conf.urls.static import static
from django.views.static import serve as django_static_serve
import volunteers.views as views
from volunteers.views import *
from django.contrib import admin
from django.contrib.auth import views as auth_views
admin.autodiscover()

from volunteers.forms import ActivationAwareAuthenticationForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', promo, name='promo'),
    path('faq/', faq, name='faq'),
    path('privacy_policy/', privacy_policy, name='privacy_policy'),
    path('privacy-consent/', privacy_policy_consent, name='privacy_policy_consent'),
    path('volunteers/signup', signup, name='signup'),

    re_path(
        r'^volunteers/(?P<username>(?!signout|signup|signin)[^/]+)/$',
        profile_detail,
        name='userena_profile_detail'
    ),
    re_path(
        r'^volunteers/(?P<username>[^/]+)/edit/$',
        profile_edit,
        name='userena_profile_edit'
    ),
    re_path(
        r'^volunteers/page/(?P<page>[0-9]+)/$',
        views.ProfileListView.as_view(),
        name='userena_profile_list_paginated'
    ),
    path('volunteers/', views.ProfileListView.as_view(), name='userena_profile_list'),

    re_path(r'^tasks/(?P<username>[\.\w-]+)', task_list_detailed, name='task_list_detailed'),
    path('task/<int:task_id>/', task_detailed, name='task_detailed'),
    path('task/<int:task_id>/assign/', admin_assign_volunteer, name='admin_assign_volunteer'),
    path('admin-labels/', label_dashboard, name='label_dashboard'),
    path('admin-labels/preview/', label_preview, name='label_preview'),
    path('admin-labels/generate/', label_generate_pdf, name='label_generate_pdf'),
    path('admin-tshirts/', tshirt_report, name='tshirt_report'),
    path('admin-matrix-ids/', matrix_ids_export, name='matrix_ids_export'),
    path('admin-approvals/', approval_dashboard, name='approval_dashboard'),
    path('admin-approvals/respond/', approval_respond, name='approval_respond'),
    path('signin/<uuid:token>/', task_signin_token, name='task_signin_token'),
    path('signout/<uuid:token>/', task_signout_token, name='task_signout_token'),
    path('task-signin/<int:vt_id>/', task_signin, name='task_signin_ui'),
    path('task-signout/<int:vt_id>/', task_signout, name='task_signout_ui'),
    path('admin-attendance/', attendance_dashboard, name='attendance_dashboard'),
    path('admin-attendance/task/<int:task_id>/', attendance_task_detail, name='attendance_task_detail'),
    path('admin-attendance/mark/', attendance_mark, name='attendance_mark'),
    path('admin-attendance/transfer-runner/', transfer_runner, name='transfer_runner'),
    path('admin-attendance/summon/', summon_runner, name='summon_runner'),
    path('admin-attendance/need-volunteers/', need_volunteers_matrix, name='need_volunteers_matrix'),
    path('talk/<int:talk_id>/', talk_detailed, name='talk_detailed'),
    path('tasks/', task_list, name='task_list'),
    path('event_sign_on/', event_sign_on, name='event_sign_on'),
    path('talks/', talk_list, name='talk_list'),
    path('category_schedule/', category_schedule_list, name='category_schedule_list'),
    path('task_schedule/<int:template_id>/', task_schedule, name='task_schedule'),
    path('task_schedule_csv/<int:template_id>/', task_schedule_csv, name='task_schedule_csv'),

    re_path(
        r'^media/(?P<path>.*)$',
        login_required(django_static_serve),
        {'document_root': settings.MEDIA_ROOT, 'show_indexes': True}
    ),
    path("accounts/login/", auth_views.LoginView.as_view(authentication_form=ActivationAwareAuthenticationForm), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/activate/<str:token>/", activate_account ,name="activate"),
    path(
    "accounts/resend-activation/",
    resend_activation,
    name="resend_activation"
),
    path('accounts/password/change/',
         auth_views.PasswordChangeView.as_view(template_name='userena/password_form.html'),
         name='userena_password_change'),
    path('accounts/password/change/done/',
         auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_reset_done.html'),
         name='password_change_done'),
    path('accounts/email/change/', email_change,
         name='userena_email_change'),
    path("accounts/password/reset/",
         auth_views.PasswordResetView.as_view(template_name="registration/password_reset_form.html", email_template_name="registration/password_reset_email.txt", subject_template_name="registration/password_reset_subject.txt"),
         name="password_reset"),

    path("accounts/password/reset/done/",
         auth_views.PasswordResetDoneView.as_view(),
         name="password_reset_done"),

    path("accounts/password/reset/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),

    path("accounts/password/reset/complete/",
         auth_views.PasswordResetCompleteView.as_view(),
         name="password_reset_complete"),
]
