#!/usr/bin/env python

import dataset

db_roaming = dataset.connect('sqlite:///roaming.db')

for message in db_roaming['message'].find():
    if message['published'] == None:
        message['published'] = True
    db_roaming['message'].update(message, ['id'])