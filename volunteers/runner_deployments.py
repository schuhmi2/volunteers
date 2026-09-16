from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    RunnerDeployment,
    TaskAttendance,
    VolunteerTask,
)


def validate_runner_deployment(runner_assignment, destination_task):
    runner_task = runner_assignment.task
    if runner_assignment.status != 'approved':
        raise ValidationError('The runner assignment is no longer approved.')
    if runner_task.name.lower() != 'runner':
        raise ValidationError('The selected assignment is not a Runner shift.')
    if destination_task.pk == runner_task.pk or destination_task.name.lower() == 'runner':
        raise ValidationError('A runner must be deployed to a non-Runner task.')
    if runner_task.edition_id != destination_task.edition_id:
        raise ValidationError('Runner and destination must belong to the same edition.')
    if runner_task.date != destination_task.date:
        raise ValidationError('Runner and destination must occur on the same day.')
    if not (
        runner_task.start_time < destination_task.end_time
        and destination_task.start_time < runner_task.end_time
    ):
        raise ValidationError('Runner and destination shifts do not overlap.')
    if VolunteerTask.objects.filter(
        volunteer=runner_assignment.volunteer,
        task=destination_task,
    ).exists():
        raise ValidationError('This volunteer is already assigned to the destination task.')


@transaction.atomic
def request_runner_deployment(runner_assignment, destination_task, requested_by):
    runner_assignment = VolunteerTask.objects.select_for_update().select_related(
        'task',
        'volunteer__user',
    ).get(pk=runner_assignment.pk)
    validate_runner_deployment(runner_assignment, destination_task)
    existing = RunnerDeployment.objects.filter(
        runner_assignment=runner_assignment,
        status__in=('pending', 'active'),
    ).first()
    if existing:
        raise ValidationError('This runner already has an open deployment.')
    return RunnerDeployment.objects.create(
        runner_assignment=runner_assignment,
        destination_task=destination_task,
        requested_by=requested_by,
    )


def approve_runner_deployment(deployment, reviewed_by):
    validation_error = None
    with transaction.atomic():
        deployment = RunnerDeployment.objects.select_for_update().select_related(
            'runner_assignment__task',
            'runner_assignment__volunteer',
            'destination_task',
        ).get(pk=deployment.pk)
        if deployment.status != 'pending':
            raise ValidationError('This deployment request is no longer pending.')

        try:
            validate_runner_deployment(
                deployment.runner_assignment,
                deployment.destination_task,
            )
        except ValidationError as error:
            deployment.status = 'invalidated'
            deployment.reviewed_by = reviewed_by
            deployment.reviewed_at = timezone.now()
            deployment.review_note = error.messages[0]
            deployment.save(update_fields=[
                'status',
                'reviewed_by',
                'reviewed_at',
                'review_note',
            ])
            validation_error = error
        else:
            now = timezone.now()
            destination_assignment = VolunteerTask.objects.create(
                task=deployment.destination_task,
                volunteer=deployment.runner_assignment.volunteer,
                status='approved',
                reviewed_at=now,
                reviewed_by=reviewed_by,
            )
            TaskAttendance.objects.create(
                volunteer_task=destination_assignment,
                signed_in_at=now,
                manually_marked_by=reviewed_by,
            )
            deployment.destination_assignment = destination_assignment
            deployment.status = 'active'
            deployment.reviewed_by = reviewed_by
            deployment.reviewed_at = now
            deployment.deployed_at = now
            deployment.save(update_fields=[
                'destination_assignment',
                'status',
                'reviewed_by',
                'reviewed_at',
                'deployed_at',
            ])
    if validation_error:
        raise validation_error
    return deployment


@transaction.atomic
def deny_runner_deployment(deployment, reviewed_by, note=''):
    deployment = RunnerDeployment.objects.select_for_update().get(pk=deployment.pk)
    if deployment.status != 'pending':
        raise ValidationError('This deployment request is no longer pending.')
    deployment.status = 'denied'
    deployment.reviewed_by = reviewed_by
    deployment.reviewed_at = timezone.now()
    deployment.review_note = note
    deployment.save(update_fields=[
        'status',
        'reviewed_by',
        'reviewed_at',
        'review_note',
    ])
    return deployment


@transaction.atomic
def complete_runner_deployment(deployment, returned_by):
    deployment = RunnerDeployment.objects.select_for_update().select_related(
        'destination_assignment',
    ).get(pk=deployment.pk)
    if deployment.status != 'active':
        raise ValidationError('This runner deployment is no longer active.')

    now = timezone.now()
    attendance, _ = TaskAttendance.objects.get_or_create(
        volunteer_task=deployment.destination_assignment,
    )
    if attendance.signed_in_at is None:
        attendance.signed_in_at = deployment.deployed_at or now
    attendance.signed_out_at = now
    attendance.manually_marked_by = returned_by
    attendance.save(update_fields=[
        'signed_in_at',
        'signed_out_at',
        'manually_marked_by',
    ])

    deployment.status = 'completed'
    deployment.returned_at = now
    deployment.save(update_fields=['status', 'returned_at'])
    return deployment
