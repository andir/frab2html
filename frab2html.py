#!/usr/bin/env python

import json
import re
import os
import shutil
import sys
from collections import defaultdict
from datetime import time, timedelta, datetime

import requests
from jinja2 import Environment, FileSystemLoader, Markup, evalcontextfilter, escape

# FIXME: Can't get the room rank from the JSON export
rooms = [u'T1: Orwell Hall', u'T2: Turing Hall', u'T3: Lovelace Tent', u'T4: Lamarr Tent', u'T5: Ockham`s Arena', u'T6: Noisy Square 1',
         u'Noisy Square 2', u'Makerlab', u'Hardware Hacking', u'HOAP', u'Rainbow stage']
days = {}


class Speaker(object):
    by_id = {}

    @classmethod
    def get_by_id(cls, id):
        return cls.by_id[id]

    @classmethod
    def all_speakers(cls):
        return cls.by_id.values()

    def __init__(self, speaker_dict):
        self.id = int(speaker_dict['id'])
        self.picture = speaker_dict['avatar_file_name']
        self.name = speaker_dict['public_name']
        self.abstract = speaker_dict['abstract']
        self.description = speaker_dict['description']
        self.events = []

        self.by_id[self.id] = self


class Event(object):
    by_id = {}
    by_day = defaultdict(list)

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
        self.room = room

        self.day = day
        if self.day is not None:
            self.day = int(self.day) + 1

        if event_dict['start']:
            hour, minute = map(int, event_dict['start'].split(':'))
            self.start = time(hour=hour, minute=minute)
            if self.start.minute % 15 != 0:
                print "Not adding event {} because it does not start on 15 minute boundary".format(self.id)
                return
        else:
            self.start = None

        if event_dict['duration']:
            hours, minutes = map(int, event_dict['duration'].split(':'))
            self.duration = timedelta(hours=hours, minutes=minutes)
            if self.duration.seconds % (15 * 60) != 0:
                print "Not adding event {} because duration is not on a 15 minute boundary".format(self.id)
                return
        else:
            self.duration = None

        if self.room is not None and self.room not in rooms:
            print u"Can't find room {}".format(room)

        self.by_id[self.id] = self
        if self.day:
            self.by_day[self.day].append(self)

        self.speakers = []

        for speaker_dict in event_dict['persons']:
            try:
                speaker = Speaker.get_by_id(int(speaker_dict['id']))
            except KeyError:
                print u"Speaker {} ({}) not found".format(speaker_dict['full_public_name'], speaker_dict['id'])
            else:
                self.speakers.append(speaker)
                speaker.events.append(self)

    def __str__(self):
        return self.title

    @property
    def slots(self):
        if not self.duration:
            return None

        return self.duration.seconds / (15 * 60)

    @property
    def start_datetime(self):
        if self.start:
            return datetime.combine(days[self.day]['date'], self.start)

    @property
    def end_datetime(self):
        return self.start_datetime + self.duration


def parse_events(filename):
    with open(filename) as f:
        schedulejson = f.read()

    # Fix broken JSON from frab
    schedulejson = schedulejson.replace('days', 'num_days', 1)
    schedulejson = schedulejson.replace('\r\n', '\\n')
    schedulejson = schedulejson.replace('\t', ' ')
    schedulejson = schedulejson.replace('&#x27;', "'")
    schedulejson = schedulejson.replace('&amp;', "&")
    schedulejson = schedulejson.replace('&quot;', '\\"')
    schedulejson = re.sub(r',\s+"links":([^\]]|[^\s]])+\s]', "", schedulejson)
    schedulejson = re.sub(r'\},\s*\]', "}]", schedulejson)

    schedule = json.loads(schedulejson)

    for e in schedule['schedule']['conference']['unscheduled']:
        Event(e)

    for day in schedule['schedule']['conference']['days']:
        number = int(day['index']) + 1
        day_date = datetime.strptime(day['date'], "%Y-%m-%d").date()
        days[number] = {'number': number, 'date': day_date, 'start': None, 'end': None}
        for room, events in day['rooms'].items():
            for event_dict in events:
                event = Event(event_dict, day['index'], room)
                if not days[number]['start'] or days[number]['start'] > event.start_datetime:
                    days[number]['start'] = event.start_datetime

                if not days[number]['end'] or days[number]['end'] < event.end_datetime:
                    days[number]['end'] = event.end_datetime


def parse_speakers(filename):
    with open(filename) as f:
        for p in json.load(f):
            Speaker(p)


def fetch_menu():
    menu = requests.get("https://ohm2013.org/site/wp-content/uploads/montezuma/clean_menu.php").text

    menu = menu.replace('src="/site/wp-content/themes/montezuma/images/ohm2013-oblong-960px.png"',
                        'src="https://ohm2013.org/site/wp-content/themes/montezuma/images/ohm2013-oblong-960px.png"')
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
    result = u'\n\n'.join(u'<p>%s</p>' % unicode(p).replace(u'\n', u'<br>\n')
                          for p in _paragraph_re.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


def export(menu, output_directory):
    env = Environment(loader=FileSystemLoader('templates'), extensions=['jinja2.ext.autoescape'], autoescape=True)
    env.filters['nl2br'] = nl2br
    day_template = env.get_template("day.html")
    event_template = env.get_template("event.html")
    event_list_template = env.get_template("event_list.html")
    speaker_template = env.get_template("speaker.html")
    speaker_list_template = env.get_template("speaker_list.html")

    event_list = Event.all_events()
    event_list.sort(cmp=lambda x, y: cmp(x.title.lower(), y.title.lower()))
    for e in event_list:
        with open(os.path.join(output_directory, "event/{0}.html".format(e.id)), "w") as f:
            f.write(event_template.render(menu=menu, event=e).encode('utf-8'))

    speaker_list = Speaker.all_speakers()
    speaker_list.sort(cmp=lambda x, y: cmp(x.name.lower(), y.name.lower()))
    for p in speaker_list:
        with open(os.path.join(output_directory, "speaker/{0}.html".format(p.id)), "w") as f:
            f.write(speaker_template.render(menu=menu, speaker=p).encode('utf-8'))

    with open(os.path.join(output_directory, "speakers.html"), "w") as f:
        f.write(speaker_list_template.render(menu=menu, speaker_list=speaker_list).encode('utf-8'))

    with open(os.path.join(output_directory, "events.html"), "w") as f:
        f.write(event_list_template.render(menu=menu, event_list=event_list).encode('utf-8'))

    for day in days.values():
        day_dict = Event.get_time_and_room_dict(day['number'])
        start_times = day_dict.keys()
        start_times.sort()
        schedule = []
        rowspan = {}

        for i in range((day['end'] - day['start']).seconds / (15 * 60)):
            start = day['start'] + timedelta(minutes=15 * i)
            if i == 0 or start.minute == 0 or start.minute == 30:
                row = [start.strftime("%H:%M")]
            else:
                row = [None]

            for room in rooms:
                if room in day_dict[start]:
                    event = day_dict[start][room]
                    row.append(event)
                    rowspan[room] = event.slots - 1
                else:
                    if room in rowspan and rowspan[room] != 0:
                        rowspan[room] -= 1
                    else:
                        row.append(None)
            schedule.append(row)

        with open(os.path.join(output_directory, "day_{0}.html".format(day['number'])), "w") as f:
            f.write(day_template.render(menu=menu, day=day, schedule=schedule, rooms=rooms).encode('utf-8'))

    shutil.copy("schedule.css", os.path.join(output_directory, "schedule.css"))
    shutil.copy(os.path.join(output_directory, "day_1.html"), os.path.join(output_directory, "index.html"))

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print "Usage: {0} schedule.json speakers.json output_directory".format(sys.argv[0])
        sys.exit(1)

    output_directory = sys.argv[3]

    makedirs([os.path.join(output_directory, "event"),
              os.path.join(output_directory, "speaker")])
    menu = fetch_menu()
    parse_speakers(sys.argv[2])
    parse_events(sys.argv[1])
    export(menu, output_directory)