#!/usr/bin/python3

import json
import asyncio
import aiohttp
import aiofiles
import logging
import os

# This entire thing is overkill but it allows for minimal configuration and shared code and objects
# with the main jukebox application

class librespot_event_handler(object):

    def __init__(self):
        self.config=self.load_config()
        #logging.basicConfig(filename=os.path.join(self.config["log_directory"], "onevent.log"),level=logging.INFO)
        self.loop = asyncio.new_event_loop()

    def start(self, player_event, track_id, old_track_id):
        #logging.info('... onevent ')
        self.error_state=False
        self.loop.run_until_complete(self.relay_event(player_event, track_id, old_track_id))

    def load_config(self):
        try:
            dir_path = os.path.dirname(os.path.realpath(__file__))
            with open(os.path.join(dir_path, 'config.json'),'r') as jsonfile:
                return json.loads(jsonfile.read())
        except :
            return {}
        
    async def relay_event(self, player_event, track_id, old_track_id):
        
        data=json.dumps({"player_event": player_event, "track_id": track_id, "old_track_id": old_track_id })
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            await session.post("https://%s/event" % self.config["hostname"], data=data)
            #logging.info("done sending %s" % data)
            
if __name__ == '__main__':
    event_handler=librespot_event_handler()
    
    if 'PLAYER_EVENT' not in os.environ:
        player_event=""
    else:
        player_event=os.environ['PLAYER_EVENT']

    if 'TRACK_ID' not in os.environ:
        track_id=""
    else:
        track_id=os.environ['TRACK_ID']

    if 'OLD_TRACK_ID' not in os.environ:
        old_track_id=""
    else:
        old_track_id=os.environ['OLD_TRACK_ID']

    event_handler.start(player_event, track_id, old_track_id)
