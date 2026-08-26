"""
Management command to process task sign-in notifications:
- Send reminder emails before task start
- Auto sign-out at task end
- Create TaskAttendance records for tasks that don't have one
"""
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from volunteers.models import Edition, Task, TaskAttendance, VolunteerTask


class Command(BaseCommand):
    help = 'Process task sign-in notifications: send reminders, auto sign-out, create attendance records.'

    def handle(self, *args, **options):
        edition = Edition.get_current()
        if not edition:
            self.stdout.write(self.style.WARNING('No current edition found.'))
            return

        if not edition.enable_task_signin:
            self.stdout.write(self.style.WARNING('Task sign-in is not enabled for the current edition.'))
            return

        now = timezone.now()
        reminder_minutes = getattr(settings, 'SIGNIN_REMINDER_MINUTES', 15)

        # 1. Create TaskAttendance records for VolunteerTasks that don't have one
        created_count = self._create_missing_attendance_records(edition)
        if created_count:
            self.stdout.write(self.style.SUCCESS(f'Created {created_count} attendance record(s).'))

        # 2. Send reminder emails (if SIGNIN_EMAIL_ENABLED)
        if getattr(settings, 'SIGNIN_EMAIL_ENABLED', False):
            reminder_count = self._send_reminders(edition, now, reminder_minutes)
            if reminder_count:
                self.stdout.write(self.style.SUCCESS(f'Sent {reminder_count} reminder email(s).'))

        # 3. Auto sign-out: set signed_out_at for anyone still active past task end
        signout_count = self._auto_signout(edition, now)
        if signout_count:
            self.stdout.write(self.style.SUCCESS(f'Auto signed-out {signout_count} volunteer(s).'))

        self.stdout.write(self.style.SUCCESS('Done.'))

    def _create_missing_attendance_records(self, edition):
        """Create TaskAttendance records for approved VolunteerTasks without one."""
        vts_without_attendance = (
            VolunteerTask.objects.filter(
                task__edition=edition,
                status='approved',
            )
            .exclude(attendance__isnull=False)
        )

        count = 0
        for vt in vts_without_attendance:
            TaskAttendance.objects.get_or_create(volunteer_task=vt)
            count += 1
        return count

    def _send_reminders(self, edition, now, reminder_minutes):
        """Send reminder emails for tasks starting within reminder_minutes."""
        from volunteers.emails import send_signin_reminder_email

        # Find tasks starting within the reminder window that haven't been reminded
        count = 0
        attendances = TaskAttendance.objects.filter(
            volunteer_task__task__edition=edition,
            volunteer_task__status='approved',
            reminder_sent_at__isnull=True,
            signed_in_at__isnull=True,
        ).select_related(
            'volunteer_task__task',
            'volunteer_task__volunteer__user',
        )

        for attendance in attendances:
            task = attendance.volunteer_task.task
            task_start = timezone.make_aware(
                dt.datetime.combine(task.date, task.start_time),
                timezone.get_current_timezone(),
            )
            time_until_start = task_start - now

            # Send reminder if task starts within reminder window and hasn't started yet
            if dt.timedelta(0) <= time_until_start <= dt.timedelta(minutes=reminder_minutes):
                send_signin_reminder_email(attendance)
                attendance.reminder_sent_at = now
                attendance.save(update_fields=['reminder_sent_at'])
                count += 1

        return count

    def _auto_signout(self, edition, now):
        """Auto sign-out volunteers who are still active past task end time."""
        count = 0
        active_attendances = TaskAttendance.objects.filter(
            volunteer_task__task__edition=edition,
            signed_in_at__isnull=False,
            signed_out_at__isnull=True,
        ).select_related('volunteer_task__task')

        for attendance in active_attendances:
            task = attendance.volunteer_task.task
            task_end = timezone.make_aware(
                dt.datetime.combine(task.date, task.end_time),
                timezone.get_current_timezone(),
            )
            if now >= task_end:
                attendance.signed_out_at = task_end
                attendance.save(update_fields=['signed_out_at'])
                count += 1

        return count
