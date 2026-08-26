"""
Matrix bot utilities for task sign-in notifications.
"""
import json
import uuid
import urllib.request
import urllib.parse
import urllib.error

from django.conf import settings


def post_to_matrix_room(message):
    """Post a message to the configured Matrix room."""
    if not settings.SIGNIN_MATRIX_ENABLED:
        return False

    homeserver = settings.MATRIX_BOT_HOMESERVER
    token = settings.MATRIX_BOT_TOKEN
    room_alias = settings.MATRIX_BOT_ROOM

    if not homeserver or not token or not room_alias:
        return False

    try:
        # Resolve room alias to room_id
        encoded_alias = urllib.parse.quote(room_alias, safe='')
        resolve_url = f'{homeserver}/_matrix/client/v3/directory/room/{encoded_alias}'
        req = urllib.request.Request(resolve_url)
        req.add_header('Authorization', f'Bearer {token}')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        room_id = data.get('room_id')
        if not room_id:
            return False

        # Send message
        txn_id = str(uuid.uuid4())
        encoded_room_id = urllib.parse.quote(room_id, safe='')
        send_url = (
            f'{homeserver}/_matrix/client/v3/rooms/'
            f'{encoded_room_id}/send/m.room.message/{txn_id}'
        )
        payload = json.dumps({
            'msgtype': 'm.text',
            'body': message,
        }).encode('utf-8')
        req = urllib.request.Request(send_url, data=payload, method='PUT')
        req.add_header('Authorization', f'Bearer {token}')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return False


def summon_runner_matrix(volunteer, location):
    """Send a Matrix message summoning a runner volunteer to a location."""
    matrix_id = volunteer.matrix_id
    if not matrix_id:
        return False
    message = f'\U0001f3c3 {matrix_id} \u2014 you\'re needed at {location}, please head there now'
    return post_to_matrix_room(message)


def need_volunteers_message(task, missing_count):
    """Post a message requesting more volunteers for a task."""
    message = (
        f'\u26a0\ufe0f Task "{task.name}" ({task.location}, '
        f'{task.start_time.strftime("%H:%M")}\u2013{task.end_time.strftime("%H:%M")}): '
        f'need {missing_count} more volunteer(s) \u2014 who can help?'
    )
    return post_to_matrix_room(message)
