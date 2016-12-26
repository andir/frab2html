#!/usr/bin/env python

import hashlib
from dateutil import parser
import re
import os
import shutil
import sys
from collections import defaultdict
from datetime import time, timedelta, datetime

import json
import requests
from jinja2 import Environment, FileSystemLoader, Markup, evalcontextfilter, escape


# FIXME: Can't get the room rank from the JSON export
main_rooms = [ 'Saal 1', 'Saal 2', 'Saal G', 'Saal 6']
rooms = [ [room[0] for room in [
    ('Saal 1', 359),
    ('Saal 2', 360),
    ('Saal G', 361),
    ('Saal 6', 362),
    #TODO
    (u'Sendezentrumsbühne', 1050),
    ('Podcastingtisch', 1051),
    ('Saal A.1', 1111),
    ('Saal A.2', 1112),
    ('Saal B',   1120),
    ('Saal C.1', 1131),
    ('Saal C.2', 1132),
    ('Saal C.3', 1133),
    ('Saal C.4', 1134),
    ('Saal F',   1230),
    ('Saal 13-14',  1013),
    #('Saal 14',  1014),
    ('Lounge DisKo',   1090),
    # TODO: Lounge Sections
]]]
flatrooms = [item for sublist in rooms for item in sublist]
tracks = []
types = []
#tracks = [
#
#    'Space', 'Ethics, Society & Politics', 'CCC', 'Science', 'Hardware & Making', 'Security',
#    'Art & Culture', 'Entertainment',
#          ]
#types = ['lecture', 'podium', 'demonstration', 'workshop', 'lightning_talk', 'meeting', 'film_screening',
#         'art_performance', 'art_installation', 'other']
days = {}

def convert_url_to_id(url):
    byte_url = url.encode('utf-8')
    return hashlib.md5(byte_url).hexdigest()



class Speaker(object):
    by_id = {}

    @classmethod
    def get_by_id(cls, id):
        return cls.by_id[str(id)]

    @classmethod
    def all_speakers(cls):
        return cls.by_id.values()

    def __init__(self, speaker_dict):
        self.id = str(speaker_dict['id'])
        self.picture = speaker_dict['image']
        self.name = speaker_dict['public_name']
        self.abstract = speaker_dict['abstract']
        self.description = speaker_dict['description']
        self.events = []

        self.by_id[self.id] = self


class Event(object):
    by_id = {}
    by_day = defaultdict(list)
    by_track = defaultdict(list)
    by_type = defaultdict(list)
    lightning = defaultdict(list)

    @classmethod
    def all_events(cls):
        return cls.by_id.values()

    @classmethod
    def get_time_and_room_dict(cls, day):
        d = defaultdict(dict)

        for e in cls.by_day[day]:
            d[e.start_datetime][e.room] = e

        return d

    def __init__(self, event_dict, day=None, room=None):
        self.id = int(event_dict['id'])
        self.abstract = event_dict['abstract']
        self.description = event_dict['description']
        self.title = event_dict['title']
        self.type = event_dict['type']
        self.track = event_dict['track']
        self.links = event_dict['links']
        self.room = room

        self.day = day
        if self.day is None:
            #print "Not adding event {0} because it does not have a day".format(self.id)
            return
        else:
            self.day = int(self.day) + 1

        if event_dict['start']:
            hour, minute = map(int, event_dict['start'].split(':'))
            if hour < 10:
                hour += 16
            if hour >= 24:
                hour -= 24
            self.start = time(hour=hour, minute=minute)
            if self.type == 'lightning_talk':
                if not room in self.lightning:
                    self.lightning[room] = defaultdict(list)
                self.lightning[room][self.day * 100 + hour].append(self)
        else:
            self.start = None

        if event_dict['duration']:
            hours, minutes = map(int, event_dict['duration'].split(':'))
            self.duration = timedelta(hours=hours, minutes=minutes)
            if self.duration.seconds % (15 * 60) != 0:
                if self.type == 'lightning_talk':
                    self.room = None
        else:
            self.duration = None

        if self.room is not None and self.room not in flatrooms:
            print (u"Can't find room {0}".format(room))

        if self.track:
            if self.track not in tracks:
                print (u"Can't find track {0}".format(self.track))
            else:
                self.by_track[self.track].append(self)

        self.by_id[self.id] = self
        self.by_type[self.type].append(self)
        if self.day:
            self.by_day[self.day].append(self)

        self.speakers = []

        for speaker_dict in event_dict['persons']:
            try:
                if 'url' in speaker_dict:
                    speaker_id = convert_url_to_id(speaker_dict['url'])
                else:
                    speaker_id = speaker_dict['id']
                speaker = Speaker.get_by_id(speaker_id)
            except KeyError:
                print (u"Speaker {0} ({0}) not found".format(speaker_dict['full_public_name'], speaker_dict['id']))
            else:
                self.speakers.append(speaker)
                speaker.events.append(self)

    def __str__(self):
        return self.title

    @property
    def slots(self):
        if not self.duration:
            return None

        return self.duration.seconds // (15 * 60)

    @property
    def start_datetime(self):
        if self.start is not None:
            if self.start < time(hour=10):
                return datetime.combine(days[self.day]['date'], self.start) + timedelta(hours=24)
            else:
                return datetime.combine(days[self.day]['date'], self.start)

    @property
    def end_datetime(self):
        return self.start_datetime + self.duration


def parse_events(filename):
    global tracks, rooms, types, flatrooms
    with open(filename) as f:
        schedule = json.load(f)

    conference = schedule['schedule']['conference']
    tracks = []
    types = []
    rooms = []
    for day in conference['days']:
        for room_name, events in day['rooms'].items():
            rooms.append(room_name.replace('Hall', 'Saal'))
            for event in events:
                tracks.append(event['track'])
                types.append(event['type'])

    tracks = sorted(set(tracks))
    rooms = set(rooms)
    flatrooms = sorted(rooms)
    subrooms = sorted(set([r for r in rooms if r not in main_rooms ]))
    rooms = [ sorted(rooms-set(subrooms)), subrooms ]
    types = sorted(set(types))

    for day in schedule['schedule']['conference']['days']:
        number = int(day['index']) + 1
        day_date = datetime.strptime(day['date'], "%Y-%m-%d").date()
        day_start = parser.parse(day['day_start']).replace(tzinfo=None)
        day_end = parser.parse(day['day_end']).replace(tzinfo=None)
        days[number] = {'number': number, 'date': day_date, 'start': None, 'end': None}
        for room, events in day['rooms'].items():
            for event_dict in events:
                event = Event(event_dict, day['index'], room.replace('Hall', 'Saal'))

                if not event.id in Event.by_id:
                    continue

                if days[number]['start'] is None:
                    days[number]['start'] = event.start_datetime
                elif days[number]['start'] > event.start_datetime and event.start_datetime > day_start:
                    days[number]['start'] = event.start_datetime

                if days[number]['end'] is None:
                    days[number]['end'] = event.end_datetime
                elif days[number]['end'] < event.end_datetime and event.end_datetime <= day_end:
                    days[number]['end'] = event.end_datetime

            print(days)


def parse_speakers(filename, schedule_filename):
    with open(filename) as f:
        for p in json.load(f)['schedule_speakers']['speakers']:
            Speaker(p)

    with open(schedule_filename) as f:
        for day in json.load(f)['schedule']['conference']['days']:
            for room_name, events in day['rooms'].items():
                for event in events:
                    for person in event['persons']:
                        if 'url' in person:
                            fake_dict = dict(
                                id=convert_url_to_id(person['url']),
                                image=None,
                                public_name=person['public_name'],
                                abstract=None,
                                description=None
                            )
                            Speaker(fake_dict)
                        elif event['track'] in ['Podcastingtisch', 'Sendezentrumsbühne']:
                            person['image'] = None
                            person['abstract'] = None
                            person['description'] = None
                            Speaker(person)



def fetch_menu():
    menu = requests.get("https://ohm2013.org/site/wp-content/uploads/montezuma/clean_menu.php").text

    menu = menu.replace('src="/site/wp-content/themes/montezuma/images/ohm2013-oblong-960px.png"',
                        'src="https://ohm2013.org/site/wp-content/themes/montezuma/images/ohm2013-oblong-960px.png"')
    menu = menu.replace('href="/wiki', 'href="https://ohm2013.org/wiki')
    menu = menu.replace('item-program', 'active item-program')

    return menu


def makedirs(directories):
    for d in directories:
        try:
            os.makedirs(d)
        except OSError as e:
            # It's possible the directory already exists
            if e.errno != 17:
                raise


_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')


@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p.replace(u'\n', u'<br>\n')
                          for p in _paragraph_re.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


def format_time(t):
    return ':'.join(str(t).split(':')[:2])


def export(menu, output_directory):
    env = Environment(loader=FileSystemLoader('templates'), extensions=['jinja2.ext.autoescape'], autoescape=True)
    env.filters['nl2br'] = nl2br
    env.filters['format_time'] = format_time
    day_template = env.get_template("day.html")
    event_template = env.get_template("event.html")
    event_list_template = env.get_template("event_list.html")
    speaker_template = env.get_template("speaker.html")
    speaker_list_template = env.get_template("speaker_list.html")
    track_list_template = env.get_template("track_list.html")
    icalxcaljson_template = env.get_template("icalxcaljson.html")

    for e in Event.all_events():
        concurrent_events = []
        for ce in Event.all_events():
            startA = e.start_datetime
            startB = ce.start_datetime
            endA = startA + e.duration
            endB = startB + ce.duration
            if (startA < endB) and (endA > startB):
                concurrent_events.append(ce)
            concurrent_events.sort(key=lambda x: x.start_datetime)

        with open(os.path.join(output_directory, "event/{0}.html".format(e.id)), "w") as f:
            rendered = event_template.render(menu=menu, event=e, concurrent_events=concurrent_events)
            f.write(rendered)

    speaker_list = sorted(Speaker.all_speakers(), key=lambda x:x.name.lower())
    for p in speaker_list:
        with open(os.path.join(output_directory, "speaker/{0}.html".format(p.id)), "w") as f:
            f.write(speaker_template.render(menu=menu, speaker=p))

    with open(os.path.join(output_directory, "speakers.html"), "w") as f:
        f.write(speaker_list_template.render(menu=menu, speaker_list=speaker_list))

    type_list = []
    for type in types:
        type_list.append({'name': type, 'title': type.replace('_', ' ').capitalize(), 'events': Event.by_type[type]})
    with open(os.path.join(output_directory, "events.html"), "w") as f:
        f.write(event_list_template.render(menu=menu, event_list=type_list))

    track_list = []
    for track in tracks:
        track_list.append({'name': track, 'events': Event.by_track[track]})

    with open(os.path.join(output_directory, "tracks.html"), "w") as f:
        f.write(track_list_template.render(menu=menu, track_list=track_list))

    for day in days.values():
        schedules = []
        for subrooms in rooms:
            day_dict = Event.get_time_and_room_dict(day['number'])
            print(day_dict.keys())
            #start_times = sorted(day_dict.keys())
            schedule = []
            rowspan = {}

            for i in range((day['end'] - day['start']).seconds // (15 * 60)):
                start = day['start'] + timedelta(minutes=15 * i)
                if i == 0 or start.minute == 0 or start.minute == 30:
                    row = [start.strftime("%H:%M")]
                else:
                    row = [None]

                start_rooms = {}
                if i > 0:
                    candidate_earliest_start = day['start'] + timedelta(minutes=15 * (i - 1))
                else:
                    candidate_earliest_start = day['start']

                candidate_latest_start = start
                for event_start, rs in day_dict.items():
#                    print(i, event_start, candidate_earliest_start, candidate_latest_start)
                    if candidate_earliest_start < event_start <= candidate_latest_start:
                        for room, event in rs.items():
                            start_rooms[room] = event

                for room in subrooms:
                    lightning_talks = []
                    if room in Event.lightning:
                        lightning_talks = Event.lightning[room][day['number'] * 100 + start.hour]
                    if room in rowspan and rowspan[room] != 0:
                        rowspan[room] -= 1
                    elif len(lightning_talks) > 0:
                        rowspan[room] = 3
                        item = {}
                        item['lightning'] = True
                        item['talks'] = lightning_talks
                        row.append(item)
                    elif room in day_dict[start] and room in start_rooms:
                        event = start_rooms[room]
                        row.append(event)
                        end = datetime.combine(day['start'], event.start) + event.duration
                        if end >  day['end']:
                            rowspan[room ] = (day['end'] - end).seconds // 15
                        else:
                            rowspan[room] = event.slots - 1
                    else:
                        row.append(None)
                schedule.append(row)

            schedules.append(schedule)

        with open(os.path.join(output_directory, "day_{0}.html".format(day['number'])), "w") as f:
            f.write(day_template.render(menu=menu, day=day, schedules=schedules, rooms=rooms))

    with open(os.path.join(output_directory, "icalxcaljson.html"), "w") as f:
        f.write(icalxcaljson_template.render(menu=menu, icalxcaljson=True))

    shutil.copy("schedule.css", os.path.join(output_directory, "schedule.css"))
    shutil.copy(os.path.join(output_directory, "day_1.html"), os.path.join(output_directory, "index.html"))


if __name__ == "__main__":
    if len(sys.argv) != 7:
        print ("Usage: {0} schedule.json speakers.json schedule.xcal schedule.ics schedule.xml output_directory".format(
            sys.argv[0]))
        sys.exit(1)

    output_directory = sys.argv[6]

    makedirs([os.path.join(output_directory, "event"),
              os.path.join(output_directory, "speaker")])
    menu = 'FIXME!!' #fetch_menu()

    parse_speakers(sys.argv[2], sys.argv[1])
    parse_events(sys.argv[1])
    shutil.copy(sys.argv[1], os.path.join(output_directory, "schedule.json"))
    shutil.copy(sys.argv[2], os.path.join(output_directory, "speakers.json"))
    shutil.copy(sys.argv[3], os.path.join(output_directory, "schedule.xcal"))
    shutil.copy(sys.argv[4], os.path.join(output_directory, "schedule.ics"))
    shutil.copy(sys.argv[5], os.path.join(output_directory, "schedule.xml"))
    export(menu, output_directory)
