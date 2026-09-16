import datetime
# from dateutil import relativedelta
import hashlib
import http.client
import os
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
import logging
import uuid
import glob 

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import connections
from django.db.models import PROTECT, CASCADE
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from PIL import Image

# Bump this whenever the privacy policy (static/privacy_policy.html) changes
# in a way that requires existing users to re-read and re-accept it. Users
# whose Volunteer.privacy_policy_version is lower than this are redirected
# to the consent page again (see middleware.EnforcePrivacyPolicyMiddleware).
CURRENT_PRIVACY_POLICY_VERSION = 2

# Parse dates, times, DRY
def parse_datetime(date_str, format='%Y-%m-%d'):
    return datetime.datetime.strptime(date_str, format)


def parse_date(date_str, format='%Y-%m-%d'):
    return parse_datetime(date_str, format).date()


def parse_time(date_str, format='%H:%M'):
    return parse_datetime(date_str, format).time()


# More DRY: given a start hour and duration, return start and end time.
def parse_hour_duration(start_str, duration_str, format='%H:%M'):
    start = datetime.datetime.strptime(start_str, format)
    dur_tm = datetime.datetime.strptime(duration_str, format)
    duration = datetime.timedelta(hours=dur_tm.hour, minutes=dur_tm.minute, seconds=dur_tm.second)
    end = start + duration
    start_tm = datetime.time(hour=start.hour, minute=start.minute, second=start.second)
    end_tm = datetime.time(hour=end.hour, minute=end.minute, second=end.second)
    return (start_tm, end_tm)


# Helper model
# class HasLinkField():
#    def link(self):
#        return 'Link'


# Create your models here.

class Edition(models.Model):
    class Meta:
        verbose_name = _('Edition')
        verbose_name_plural = _('Editions')
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    name = models.CharField(max_length=128)
    start_date = models.DateField()
    end_date = models.DateField()
    visible_from = models.DateField()
    visible_until = models.DateField()
    digital_edition = models.BooleanField(default=False)
    enable_task_signin = models.BooleanField(default=False, help_text='Enable task sign-in/sign-out tracking for this edition.')

    @classmethod
    def get_current(cls):
        retval = False
        today = datetime.date.today()
        try:
            current = cls.objects.filter(visible_from__lte=today, visible_until__gte=today)
            if current:
                retval = current[0]
        except:
            return False
        return retval

    @classmethod
    def get_previous(cls):
        current = cls.get_current()
        if current:
            previous = cls.objects.filter(end_date__lt=current.start_date)
        else:
            previous = cls.objects.filter(end_date__lt=datetime.date.today())
        if previous:
            return previous[0]
        return False

    @classmethod
    def penta_create_or_update(cls, xml):
        ed_name = xml.find('title').text
        start_date = parse_date(xml.find('start').text)
        end_date = parse_date(xml.find('end').text)
        visible_from = datetime.date(year=start_date.year - 1, month=8, day=1)
        visible_until = datetime.date(year=start_date.year, month=7, day=31)
        editions = cls.objects.filter(name=ed_name)
        if len(editions):
            edition = editions[0]
        else:
            edition = cls(name=ed_name)  # create if required
        edition.start_date = start_date
        edition.end_date = end_date
        edition.visible_from = visible_from
        edition.visible_until = visible_until
        edition.save()
        return edition

    @classmethod
    def init_generic_tasks(cls):
        edition = cls.get_current()
        if edition:
            # Find all XML files in the init_data directory
            init_data_dir = 'volunteers/init_data'
            xml_files = glob.glob(os.path.join(init_data_dir, '*.xml'))
            
            if not xml_files:
                print(f"No XML files found in {init_data_dir}")
                return
            
            print(f"Found {len(xml_files)} XML file(s) to import:")
            
            # Process each XML file
            for xml_file in sorted(xml_files):
                try:
                    print(f"  Processing: {os.path.basename(xml_file)}")
                    generic_task_tree = ET.parse(xml_file)
                    generic_task_root = generic_task_tree.getroot()
                    task_count = 0
                    for task in generic_task_root.findall('task'):
                        Task.create_from_xml(task, edition)
                        task_count += 1
                    print(f"    Imported {task_count} task(s)")
                except Exception as e:
                    print(f"    Error processing {os.path.basename(xml_file)}: {e}")
            
            print("Import complete!")

    @classmethod
    def create_from_task_list(cls, file_name):
        edition = cls.get_current()
        if edition:
            generic_task_tree = ET.parse(file_name)
            generic_task_root = generic_task_tree.getroot()
            for task in generic_task_root.findall('task'):
                Task.create_from_xml(task, edition)

    @classmethod
    def sync_with_penta(cls):
        penta_url = settings.SCHEDULE_SYNC_URI
        response = urllib.request.urlopen(penta_url)
        penta_xml = response.read()
        root = ET.fromstring(penta_xml)
        ###########
        # Edition #
        ###########
        ed = root.find('conference')
        edition = cls.penta_create_or_update(ed)

        #########
        # Talks #
        #########
        days = root.findall('day')
        for day in days:
            day_date = parse_date(day.get('date'))
            rooms = day.findall('room')
            for room in rooms:
                room_name = room.get('name')
                # Lightning talks are done manually since the time slots are so small.
                needs_heralding = False
                needs_video = False

                if room_name in ['Janson', 'K.1.105 (La Fontaine)']:
                    needs_heralding = True
                    needs_video = getattr(settings, 'IMPORT_VIDEO_TASKS', True)

                events = room.findall('event')
                for event in events:
                    talk = Talk.penta_create_or_update(event, edition, day_date)
                    ######################
                    # Tasks, if required #
                    ######################
                    if needs_heralding:
                        Task.create_or_update_from_talk(edition, talk, 'Heralding', [3, 2, 5])
                    if needs_video:
                        Task.create_or_update_from_talk(edition, talk, 'Video', [1, 1, 1])


"""
A location represents a physical (or virtual) place at FOSDEM, e.g. a room,
building, or online space. It stores an optional mapping to the matching
nav.fosdem.org (c3nav) location slug, so pages can link out to a map.

The name<->slug mapping cannot reliably be derived automatically (not every
location is a real room, and slugs occasionally change), so it is curated:
seeded by a one-off scrape of the FOSDEM schedule archive
(see `scrape_fosdem_rooms` management command), then maintained by hand via
the Django admin.
"""


class Location(models.Model):
    class Meta:
        verbose_name = _('Location')
        verbose_name_plural = _('Locations')
        ordering = ['name']

    def __str__(self):
        return self.name

    name = models.CharField(max_length=128, unique=True)
    building = models.CharField(max_length=50, blank=True, null=True, help_text="Building code, e.g. 'H', 'K', 'AW', 'U'.")
    nav_slug = models.SlugField(
        max_length=100, blank=True, null=True,
        help_text="Slug used on nav.fosdem.org, e.g. 'janson' for https://nav.fosdem.org/l/janson/. Leave blank if this location isn't a mappable room."
    )
    notes = models.CharField(max_length=255, blank=True, null=True, help_text="Optional free-text note, e.g. why no map link exists.")
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def nav_url(self):
        if self.nav_slug:
            return "https://nav.fosdem.org/l/%s/" % self.nav_slug
        return None

    @classmethod
    def get_or_create_for_name(cls, name):
        """Resolve (and lazily create) the Location matching a raw location string.

        Used by task/talk import so new/unrecognized location names don't
        break imports - they just get a Location row without a nav_slug,
        left for a maintainer to fill in via the admin.
        """
        name = (name or '').strip()
        if not name:
            return None
        location, _created = cls.objects.get_or_create(name=name)
        return location


"""
A track is a collection of talks, grouped around one single
concept or subject.
"""


class Track(models.Model):
    class Meta:
        verbose_name = _('Track')
        verbose_name_plural = _('Tracks')
        ordering = ['date', 'start_time', 'title']

    def __str__(self):
        return self.title

    title = models.CharField(max_length=128)
    description = models.TextField(blank=True, null=True)
    edition = models.ForeignKey(Edition, default=Edition.get_current().pk if Edition.get_current() else None, on_delete=PROTECT)
    date = models.DateField()
    start_time = models.TimeField()
    # end_time = models.TimeField()


# class Talk(models.Model, HasLinkField):
class Talk(models.Model):
    class Meta:
        verbose_name = _('Talk')
        verbose_name_plural = _('Talks')
        ordering = ['date', 'start_time', '-end_time', 'title']

    def __str__(self):
        return self.title

    ext_id = models.CharField(max_length=16)  # ID from where we synchronise
    track = models.ForeignKey(Track, related_name="talks", on_delete=CASCADE)
    title = models.CharField(max_length=256)
    speaker = models.CharField(max_length=128)
    description = models.TextField()
    fosdem_url = models.TextField(null=True)
    location = models.CharField(max_length=128, null=True, blank=True)
    location_ref = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Resolved Location matching the 'location' text, used for the nav.fosdem.org map link."
    )

    def save(self, *args, **kwargs):
        previous_location = None
        if self.pk:
            previous_location = type(self).objects.filter(pk=self.pk).values_list('location', flat=True).first()
        if not self.pk or previous_location != self.location:
            self.location_ref = Location.get_or_create_for_name(self.location)
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'location_ref'}
        super().save(*args, **kwargs)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    volunteers = models.ManyToManyField('Volunteer', through='VolunteerTalk', blank=True)

    def assigned_volunteers(self):
        return self.volunteers.count()

    def link(self):
        return 'Link'

    @classmethod
    def penta_create_or_update(cls, xml, edition, day_date):
        event_id = xml.get('id')
        talks = cls.objects.filter(ext_id=event_id, track__edition=edition)
        if len(talks):
            talk = talks[0]
        else:
            talk = cls(ext_id=event_id)
        start_txt = xml.find('start').text
        dur_txt = xml.find('duration').text
        (talk_start, talk_end) = parse_hour_duration(start_txt, dur_txt)
        track_name = xml.find('track').text
        tracks = Track.objects.filter(title=track_name, edition=edition)
        if len(tracks):
            track = tracks[0]
        else:
            track = Track(title=track_name, edition=edition, date=day_date, start_time=talk_start)
        if day_date < track.date:
            track.date = day_date
        if talk_start < track.start_time:
            track.start_time = talk_start
        track.save()
        talk.track = track
        talk.title = xml.find('title').text
        talk.description = xml.find('description').text or ''
        talk.fosdem_url = xml.find('url').text
        talk.location = xml.find('room').text
        talk.location_ref = Location.get_or_create_for_name(talk.location)
        talk.date = day_date
        (talk.start_time, talk.end_time) = (talk_start, talk_end)
        persons = xml.find('persons')
        people = []
        if len(persons):
            for person in persons.findall('person'):
                people.append(person.text)
            speakers_str = ', '.join(people)
            talk.speaker = speakers_str
        talk.save()
        return talk


"""
Categories are things like buildup, cleanup, moderation, ...
"""


class TaskCategory(models.Model):
    class Meta:
        verbose_name = _('Task Category')
        verbose_name_plural = _('Task Categories')
        ordering = ['name']

    def __str__(self):
        return self.name

    name = models.CharField(max_length=50)
    description = models.TextField()
    active = models.BooleanField(default=True)

    def link(self):
        return 'Link'

    @classmethod
    def create_or_update_named(cls, name):
        categories = TaskCategory.objects.filter(name=name)
        if len(categories):
            category = categories[0]
        else:
            category = cls(name=name)
            category.save()
        return category


"""
A task template contains all the data about a task that isn't task specific.
For example, cleanup can happen in multiple locations or at multiple times.
Not sure we need this, but it seemed like a good thing to have when I wrote
down the DB model. ;)
"""


class TaskTemplate(models.Model):
    class Meta:
        verbose_name = _('Task Template')
        verbose_name_plural = _('Task Templates')
        ordering = ['name']
        permissions = [
            ('manage_approvals', 'Can manage signup approvals'),
            ('manage_task_clashes', 'Can manage task clashes'),
            ('manage_attendance', 'Can manage task attendance'),
            ('assign_volunteers', 'Can assign volunteers'),
            ('event_signon', 'Can sign on event volunteers'),
            ('view_other_schedules', 'Can view other volunteer schedules'),
            ('view_volunteer_history', 'Can view full volunteer history'),
            ('export_task_schedules', 'Can export task schedules'),
            ('manage_labels', 'Can generate volunteer labels'),
            ('view_tshirt_report', 'Can view T-shirt reports'),
            ('export_matrix_ids', 'Can export Matrix IDs'),
            ('send_mass_mail', 'Can send mass mail'),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(primary=models.F('secondary')),
                name='tasktemplate_distinct_responsibles',
            ),
        ]

    def __str__(self):
        return self.name

    name = models.CharField(max_length=50)
    description = models.TextField()
    info_url = models.URLField(null=True, blank=True, help_text="Link to volunteer documentation for this task type")
    category = models.ForeignKey(TaskCategory, on_delete=PROTECT)
    primary = models.ForeignKey(
        User,
        default=1,
        limit_choices_to={'is_staff': True},
        on_delete=PROTECT,
        related_name='primary_task_templates',
    )
    secondary = models.ForeignKey(
        User,
        null=True,
        blank=True,
        limit_choices_to={'is_staff': True},
        on_delete=PROTECT,
        related_name='secondary_task_templates',
    )
    requires_approval = models.BooleanField(default=False, help_text="If set, volunteer sign-ups require approval from the task responsible.")

    def clean(self):
        super().clean()
        if self.secondary_id and self.secondary_id == self.primary_id:
            raise ValidationError({
                'secondary': _('Primary and secondary responsibles must be different users.')
            })

    def link(self):
        return 'Link'

    @classmethod
    def create_or_update_named(cls, name):
        templates = cls.objects.filter(name=name)
        if len(templates):
            template = templates[0]
        else:
            template = cls(name=name)
            category = TaskCategory.create_or_update_named(name)
            template.category = category
            template.save()
        return template


"""
Contains the specifics of an instance of a task. It's based on a task template
but it can override the name and description, yet not the category.
"""


# class Task(models.Model, HasLinkField):
class Task(models.Model):
    class Meta:
        verbose_name = _('Task')
        verbose_name_plural = _('Tasks')
        ordering = ['date', 'start_time', '-end_time', 'name']

    def __str__(self):
        day = self.date.strftime('%a')
        start = self.start_time.strftime('%H:%M')
        end = self.end_time.strftime('%H:%M')
        return "%s - %s (%s, %s - %s)" % (self.edition.name, self.name, day, start, end)

    name = models.CharField(max_length=300)
    # For auto-importing; otherwise we can't have multiple cloak room and
    # infodesk tasks if we do a simple name search in create_from_xml
    counter = models.CharField(max_length=2)
    description = models.TextField()
    fosdem_url = models.TextField(null=True, blank=True)
    info_url = models.URLField(null=True, blank=True, help_text="Link to volunteer documentation for this task")
    location = models.CharField(null=True, max_length=30)
    location_ref = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Resolved Location matching the 'location' text, used for the nav.fosdem.org map link."
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    nbr_volunteers = models.IntegerField(default=0)
    nbr_volunteers_min = models.IntegerField(default=0)
    nbr_volunteers_max = models.IntegerField(default=0)
    edition = models.ForeignKey(Edition, default=Edition.get_current().pk if Edition.get_current() else None, on_delete=PROTECT)
    template = models.ForeignKey(TaskTemplate, on_delete=PROTECT)
    volunteers = models.ManyToManyField('Volunteer', through='VolunteerTask', blank=True)
    # Only for heralding, or possible future tasks related
    # to a specific talk.
    talk = models.ForeignKey(Talk, blank=True, null=True, on_delete=CASCADE)
    # Override template's requires_approval (null = inherit from template)
    requires_approval = models.BooleanField(
        null=True, blank=True, default=None,
        help_text="Override template setting. Leave blank to inherit from template."
    )

    @property
    def effective_requires_approval(self):
        """Return whether this task requires signup approval (inherits from template if not overridden)."""
        if self.requires_approval is not None:
            return self.requires_approval
        return self.template.requires_approval

    def assigned_volunteers(self):
        """Count only approved volunteers for this task."""
        if hasattr(self, "volunteers__count"):
            # If annotated, it may not filter by status - fall back to query
            return VolunteerTask.objects.filter(task=self, status='approved').count()
        else:
            return VolunteerTask.objects.filter(task=self, status='approved').count()

    def approved_volunteers(self):
        """Return volunteers whose signup for this task is approved."""
        return Volunteer.objects.filter(
            volunteertask__task=self,
            volunteertask__status='approved',
        )

    def pending_volunteers(self):
        """Count volunteers pending approval for this task."""
        return VolunteerTask.objects.filter(task=self, status='pending').count()

    def save(self, *args, **kwargs):
        previous_location = None
        if self.pk:
            previous_location = type(self).objects.filter(pk=self.pk).values_list('location', flat=True).first()
        if not self.pk or previous_location != self.location:
            self.location_ref = Location.get_or_create_for_name(self.location)
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'location_ref'}
        super().save(*args, **kwargs)

    def link(self):
        return 'Link'

    # Create task from talks.
    # @param volunteers= list/tuple of required number of volunteers, in order:
    #        ideal, min, max
    @classmethod
    def create_or_update_from_talk(cls, edition, talk, task_type, volunteers):
        tasks = cls.objects.filter(talk=talk, template__name=task_type, edition=edition)
        templates = TaskTemplate.objects.filter(name=task_type)
        if len(templates):
            template = templates[0]
        else:
            template = TaskTemplate(name=task_type)
            categories = TaskCategory.objects.filter(name=task_type)
            if len(categories):
                category = categories[0]
            else:
                category = TaskCategory(name=task_type)
                category.save()
            template.category = category
            template.save()
        if len(tasks):
            task = tasks[0]
        else:
            task = cls(talk=talk, template=template)
        task.template = template
        task.name = '%s: %s' % (task_type, talk.title)
        task.fosdem_url = talk.fosdem_url
        task.location = talk.location
        task.location_ref = talk.location_ref or Location.get_or_create_for_name(talk.location)
        task.date = talk.date
        task.start_time = talk.start_time
        task.end_time = talk.end_time
        task.edition = edition
        task.description = template.description
        task.info_url = template.info_url
        task.nbr_volunteers = volunteers[0]
        task.nbr_volunteers_min = volunteers[1]
        task.nbr_volunteers_max = volunteers[2]
        task.save()
        return task

    @classmethod
    def create_from_xml(cls, xml, edition):
        template_str = xml.get('template')
        template = TaskTemplate.create_or_update_named(template_str)
        name = xml.find('name').text
        counter = xml.find('counter').text
        tasks = cls.objects.filter(name=name, counter=counter, template=template, edition=edition)
        if len(tasks):
            task = tasks[0]
            # In this specific model I do not want to update after initial import
            return task
        else:
            task = cls(name=name, counter=counter, template=template, edition=edition)
        task.description = xml.find('description').text
        # Read info_url from XML; fall back to template's info_url
        info_url_elem = xml.find('info_url')
        if info_url_elem is not None and info_url_elem.text and info_url_elem.text.strip():
            task.info_url = info_url_elem.text.strip()
        elif template.info_url:
            task.info_url = template.info_url
        location_elem = xml.find('location')
        if location_elem is not None and location_elem.text:
            task.location = location_elem.text
        else:
            task.location = ''
        task.location_ref = Location.get_or_create_for_name(task.location)
        day_offset = int(xml.find('day').text)
        task.date = edition.start_date + datetime.timedelta(days=day_offset)
        task.start_time = parse_time(xml.find('start_time').text)
        task.end_time = parse_time(xml.find('end_time').text)
        task.nbr_volunteers = int(xml.find('nbr_volunteers').text)
        task.nbr_volunteers_min = int(xml.find('nbr_volunteers_min').text)
        task.nbr_volunteers_max = int(xml.find('nbr_volunteers_max').text)
        # Read requires_approval from XML; fall back to template's setting
        requires_approval_elem = xml.find('requires_approval')
        if requires_approval_elem is not None and requires_approval_elem.text:
            task.requires_approval = requires_approval_elem.text.strip().lower() in ('true', '1', 'yes')
        task.save()
        return task

    @property
    def status(self):
        """ Give status of a task"""
        if self.assigned_volunteers() >= self.nbr_volunteers_max:
            return "FULL"
        if self.assigned_volunteers() >= self.nbr_volunteers:
            return "OK"
        if self.assigned_volunteers() >= self.nbr_volunteers_min:
            return "MANAGEABLE"
        else:
            return "NEEDED"

    @property
    def status_color(self):
        colors = {
            "FULL": "blue",
            "OK": "green",
            "MANAGEABLE": "yellow",
            "NEEDED": "red"
        }
        return colors[self.status]

"""
table to contain the language names and ISO codes
"""


class Language(models.Model):
    class Meta:
        verbose_name = _('Language')
        verbose_name_plural = _('Languages')

    def __str__(self):
        return self.name

    name = models.CharField(max_length=128)
    native_name = models.CharField(max_length=128, blank=True, default='')
    iso_code = models.CharField(max_length=2)

    @property
    def display_name(self):
        """Native name with the English name in brackets, for UI display."""
        if self.native_name and self.native_name != self.name:
            return f'{self.native_name} ({self.name})'
        return self.name

    @property
    def label_name(self):
        """Native name only (falling back to the English name), for printed labels."""
        return self.native_name or self.name


"""
The nice guys n' gals who make it all happen.
"""


class Volunteer(models.Model):
    class Meta:
        verbose_name = _('Volunteer')
        verbose_name_plural = _('Volunteers')
        ordering = ['user__first_name', 'user__last_name']

    def __str__(self):
        return self.user.username

    user = models.OneToOneField(User, unique=True, verbose_name=_('user'), related_name='volunteer', on_delete=CASCADE)
    # Categories in which they're interested to help out.
    # Tasks for which they've signed up.
    tasks = models.ManyToManyField(Task, through='VolunteerTask', blank=True)
    editions = models.ManyToManyField(Edition, through='VolunteerStatus', blank=True)
    spoken_languages = models.ManyToManyField('Language', through='VolunteerLanguage', blank=True)
    signed_up = models.DateField(default=datetime.date.today)
    about_me = models.TextField(_('about me'), blank=True)
    mobile_nbr = models.CharField('Mobile Phone', max_length=30, blank=True, null=True,
                                  help_text="We won't share this, but we need it in case we"
                                            " need to contact you in a pinch during the event.")
    penta_account_name = models.TextField('Your Pentabarf account name (penta.fosdem.org)', null=True,
                                          blank=True, max_length=256, help_text="We need this to link your volunteers account from Pentabarf to participate in heralding/hosting a digital edition.")
    matrix_id = models.CharField('Matrix ID', null=True, blank=True, max_length=256, help_text='If you have a matrix account (mxid), you can specify it here. This is required for the virtual infodesk. The format is @username:homeserver.tld')
    privacy_policy_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_policy_version = models.PositiveIntegerField(
        default=1,
        help_text='Version of the privacy policy this volunteer last accepted.',
    )
    mugshot = models.ImageField(upload_to='mugshots/', blank=True, null=True)
    email_confirmed = models.BooleanField(null=False, default=False)
    privacy = models.CharField(max_length=16, null=True, blank=True)
    language = models.CharField(max_length=8, null=True, blank=True)

    TSHIRT_SIZES = (
        ('', 'Prefer not to say'),
        ('XS', 'XS'),
        ('S', 'S'),
        ('M', 'M'),
        ('L', 'L'),
        ('XL', 'XL'),
        ('XXL', 'XXL'),
        ('XXXL', 'XXXL'),
    )
    tshirt_size = models.CharField(
        'T-shirt size',
        max_length=4,
        blank=True,
        null=True,
        choices=TSHIRT_SIZES,
        help_text=(
            "Volunteer t-shirt size (European sizing). "
            "As the shirt is worn over clothing, consider choosing one size up from your usual size."
        ),
    )
    pronouns = models.CharField(
        'Pronouns',
        max_length=50,
        blank=True,
        null=True,
        help_text="Your preferred pronouns (e.g. she/her, he/him, they/them). Optional.",
    )

    # Just here for the admin interface.
    def full_name(self):
        return " ".join([self.user.first_name, self.user.last_name])

    def email(self):
        return self.user.email

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            if self.mugshot:
                img_path = self.mugshot.path
                img = Image.open(img_path)

                # crop to middle
                width, height = img.size
                min_side = min(width, height)
                left = (width - min_side) / 2
                top = (height - min_side) / 2
                right = (width + min_side) / 2
                bottom = (height + min_side) / 2

                img = img.crop((left, top, right, bottom))

                max_size = (140, 140)  # maximum width/height
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                img.save(img_path)
        except FileNotFoundError:
            self.mugshot=None
            self.save()

    # Dr. Manhattan detection: is this person capable of being in multiple places at once?
    def detect_dr_manhattan(self):
        retval = [False, []]
        current_tasks = Task.objects.filter(
            edition=Edition.get_current(),
            volunteertask__volunteer=self,
            volunteertask__status__in=('approved', 'pending'),
        )
        dates = sorted(list(set([x.date for x in current_tasks])))
        # Yes yes, I know about dict generators; my editor doesn't however and I don't
        # want to see warnings for perfectly valid code.
        schedule = {}
        for date in dates:
            schedule[date] = []
        for task in current_tasks:
            for item in schedule[task.date]:
                # If the times overlap, and they don't have the same name and location, then they need to be Dr Manhattan
                if (item.start_time <= task.start_time < item.end_time \
                    or item.start_time < task.end_time <= item.end_time) \
                        and not (item.name == task.name and item.location == task.location):
                    retval[0] = True
                    item_found = False
                    for task_set in retval[1]:
                        if item in task_set:
                            item_found = True
                            task_set.add(task)
                            break
                    if not item_found:
                        retval[1].append(set([item, task]))
            schedule[task.date].append(task)
        return retval

    def mail_schedule(self):
        subject = "FOSDEM Volunteers: your schedule"
        message_header = []
        message_header.extend(['Dear %s,' % (self.user.first_name), ''])
        edition = Edition.get_current()
        message_header.extend(['Here is your schedule for %s:' % (edition.name,), ''])
        message_body = []
        for task in Task.objects.filter(
            edition=edition,
            volunteertask__volunteer=self,
            volunteertask__status='approved',
        ):
            message_body.extend(["%s, %s-%s: %s" % (
                task.date.strftime('%a'),
                task.start_time,
                task.end_time,
                task.name,
            )])
        message_footer = [
            '',
            'Kind regards,',
            'FOSDEM Volunteers Team'
        ]
        message_txt = '\n'.join(message_header + message_body + message_footer)
        # Uncommenting html stuff for now; it's only in django development ATM
        # message_html = '<br/>'.join(message_header)
        # message_html += '<ul style="font-family: Courier New, monospace"><li>'
        # message_html += '</li><li>'.join(message_body)
        # message_html += '</li></ul>'
        # send_mail(subject, message_txt, settings.DEFAULT_FROM_EMAIL,
        #     [self.user.email], html_message=message_html, fail_silently=False)
        send_mail(subject, message_txt, settings.DEFAULT_FROM_EMAIL,
                  [self.user.email], fail_silently=False)

    def mail_user_created_for_you(self):
        subject = 'FOSDEM Volunteers: user created for you'
        message = [
            'Dear {0},'.format(self.user.first_name),
            '',
            'An account was created on volunteers.fosdem.org for you, probably during FOSDEM.',
            'Please reset your password via https://volunteers.fosdem.org/volunteers/password/reset/ .',
            '',
            'Kind regards,',
            'FOSDEM Volunteers Team'
        ]
        send_mail(subject, '\n'.join(message), settings.DEFAULT_FROM_EMAIL, [self.user.email],
                  fail_silently=False)

    def check_mugshot(self):
        return bool(self.mugshot)

    def get_mugshot_url(self):
        if self.mugshot:
            return self.mugshot.url
        return settings.STATIC_URL + "img/default_mugshot.png"


"""
Many volunteers come back year after year, but sometimes they
take a hiatus of one or multiple years. This is there to capture
their availability on a per-event basis, in order to filter out
inactive volunteers from the selection pool.
"""


class VolunteerStatus(models.Model):
    class Meta:
        verbose_name = _('Volunteer Status')
        verbose_name_plural = _('Volunteer Statuses')

    def __str__(self):
        return '%s %s - %s: %s' % (self.volunteer.user.first_name,
                                   self.volunteer.user.last_name, self.edition.year,
                                   'Yes' if self.active else 'No')

    active = models.BooleanField()
    volunteer = models.ForeignKey(Volunteer, on_delete=CASCADE)
    edition = models.ForeignKey(Edition, default=Edition.get_current().pk if Edition.get_current() else None, on_delete=PROTECT)


"""
M2M tables because I want to have the relationship on both model admin pages
"""


class VolunteerTask(models.Model):
    class Meta:
        verbose_name = _('VolunteerTask')
        verbose_name_plural = _('VolunteerTasks')

    def __str__(self):
        return self.task.name

    STATUS_CHOICES = (
        ('approved', 'Approved'),
        ('pending', 'Pending Approval'),
        ('denied', 'Denied'),
    )

    volunteer = models.ForeignKey(Volunteer, on_delete=CASCADE)
    task = models.ForeignKey(Task, on_delete=CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='approved')
    requested_at = models.DateTimeField(auto_now_add=True, null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_signups'
    )


class RunnerDeployment(models.Model):
    class Meta:
        verbose_name = _('Runner Deployment')
        verbose_name_plural = _('Runner Deployments')
        ordering = ['-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['runner_assignment'],
                condition=models.Q(status__in=('pending', 'active')),
                name='one_open_runner_deployment',
            ),
        ]

    STATUS_CHOICES = (
        ('pending', 'Pending Approval'),
        ('active', 'Deployed'),
        ('completed', 'Returned'),
        ('denied', 'Denied'),
        ('cancelled', 'Cancelled'),
        ('invalidated', 'Invalidated'),
    )

    runner_assignment = models.ForeignKey(
        VolunteerTask,
        related_name='runner_deployments',
        on_delete=PROTECT,
    )
    destination_task = models.ForeignKey(
        Task,
        related_name='runner_deployments',
        on_delete=PROTECT,
    )
    destination_assignment = models.ForeignKey(
        VolunteerTask,
        related_name='destination_deployments',
        null=True,
        blank=True,
        on_delete=PROTECT,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='requested_runner_deployments',
        on_delete=PROTECT,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='reviewed_runner_deployments',
        null=True,
        blank=True,
        on_delete=PROTECT,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    deployed_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='pending',
    )
    review_note = models.TextField(blank=True)

    def __str__(self):
        return _('%(volunteer)s: %(source)s → %(destination)s') % {
            'volunteer': self.runner_assignment.volunteer.user.username,
            'source': self.runner_assignment.task.name,
            'destination': self.destination_task.name,
        }


"""
link table between volunteers and languages
"""


class VolunteerLanguage(models.Model):
    class Meta:
        verbose_name = _('VolunteerLanguage')
        verbose_name_plural = _('VolunteerLanguages')

    def __str__(self):
        return self.language.name

    volunteer = models.ForeignKey(Volunteer, on_delete=CASCADE)
    language = models.ForeignKey(Language, on_delete=CASCADE)


"""
link table between volunteers and talks
"""


class VolunteerTalk(models.Model):
    class Meta:
        verbose_name = _('VolunteerTalk')
        verbose_name_plural = _('VolunteerTalks')

    def __str__(self):
        return self.talk.title

    volunteer = models.ForeignKey(Volunteer, on_delete=CASCADE)
    talk = models.ForeignKey(Talk, on_delete=CASCADE)


def _penta_event_id(volunteer_task):
    task = volunteer_task.task
    if task.talk_id is None and task.template.name.lower() != 'infodesk':
        return None
    if task.template.name.lower() == 'infodesk':
        if task.date.weekday() == datetime.datetime.strptime('2021-02-06', '%Y-%m-%d').weekday():
            # Saturday
            return '11762'
        # Sunday
        return '11763'
    return task.talk.ext_id


def _delete_penta_assignment(volunteer_task):
    event_id = _penta_event_id(volunteer_task)
    account_name = volunteer_task.volunteer.penta_account_name
    if not event_id or not account_name:
        return

    logger = logging.getLogger("pentabarf")
    logger.debug("Values in delete: %s, %s", event_id, account_name)
    try:
        with connections['pentabarf'].cursor() as cursor:
            cursor.execute(
                "delete from event_person where event_id=%s "
                "and person_id=(select person_id from auth.account where login_name = %s) "
                "and event_role='host' and remark='volunteer';",
                (event_id, account_name),
            )
    except Exception as err:
        logger.exception(err)


@receiver(pre_save, sender=VolunteerTask)
def remember_previous_volunteer_task_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = (
        VolunteerTask.objects.filter(pk=instance.pk)
        .values_list('status', flat=True)
        .first()
    )


@receiver(post_save, sender=VolunteerTask)
def save_penta(sender, instance, **kwargs):
    previous_status = getattr(instance, '_previous_status', None)
    if previous_status == 'approved' and instance.status != 'approved':
        _delete_penta_assignment(instance)
        return
    if instance.status != 'approved':
        return

    event_id = _penta_event_id(instance)
    account_name = instance.volunteer.penta_account_name
    if not event_id or not account_name:
        return

    logger = logging.getLogger("pentabarf")
    logger.debug("Values in insert: %s, %s" % (event_id, account_name))
    try:
        with connections['pentabarf'].cursor() as cursor:
            cursor.execute("""
            insert into event_person (event_id, person_id, event_role,remark)
            VALUES (%s,(select person_id from auth.account where login_name = %s),'host','volunteer')
            on conflict on constraint event_person_event_id_person_id_event_role_key do nothing;
            """, (event_id, account_name))
    except Exception as err:
        logger.exception(err)


@receiver(post_delete, sender=VolunteerTask)
def delete_volunteertask(sender, instance, **kwargs):
    if instance.status != 'approved':
        return
    _delete_penta_assignment(instance)

class EmailConfirmation(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def send(self, request):
        """
        Send activation email:
        """
        subject = "[FOSDEM Volunteers] Activate your account"
        ctx = {
            "user": self.user,
            "confirmation": self,
            "domain": request.get_host(),
            "protocol": "https" if request.is_secure() else "http"
        }
        
        text_body = render_to_string(
            "userena/emails/activation_email_message_short.txt", ctx
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email="volunteers@fosdem.org",
            to=[self.user.email],
        )
        email.send()


class TaskAttendance(models.Model):
    """Tracks volunteer sign-in/sign-out for a task assignment."""
    class Meta:
        verbose_name = _('Task Attendance')
        verbose_name_plural = _('Task Attendances')

    volunteer_task = models.OneToOneField('VolunteerTask', on_delete=models.CASCADE, related_name='attendance')
    signed_in_at = models.DateTimeField(null=True, blank=True)
    signed_out_at = models.DateTimeField(null=True, blank=True)
    signin_token = models.UUIDField(default=uuid.uuid4, unique=True)
    signout_token = models.UUIDField(default=uuid.uuid4, unique=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    signout_link_sent_at = models.DateTimeField(null=True, blank=True)
    manually_marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='attendance_marks'
    )

    @property
    def is_signed_in(self):
        return self.signed_in_at is not None and self.signed_out_at is None

    @property
    def status(self):
        if self.signed_out_at:
            return 'completed'
        if self.signed_in_at:
            return 'active'
        return 'not_arrived'

    def __str__(self):
        return f'{self.volunteer_task} - {self.status}'


class LabelPrintLog(models.Model):
    """Tracks when labels were printed for a volunteer in a given edition."""
    class Meta:
        verbose_name = _('Label Print Log')
        verbose_name_plural = _('Label Print Logs')
        ordering = ['-printed_at']

    volunteer = models.ForeignKey(Volunteer, on_delete=CASCADE, related_name='label_prints')
    edition = models.ForeignKey(Edition, on_delete=CASCADE)
    printed_at = models.DateTimeField(auto_now_add=True)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='label_prints_made'
    )

    def __str__(self):
        return f'{self.volunteer} - {self.edition} - {self.printed_at:%Y-%m-%d %H:%M}'
