#!/usr/bin/python3
from jukebox_spotify import sofa_spotify_controller
from jukebox_webserver import web_server

import json
import asyncio
import aiofiles
import datetime
import os
import socket
import sys
import datetime
from os.path import isfile, isdir, join

import logging
from logging.handlers import RotatingFileHandler

from datetime import datetime
import uuid

class sofa_jukebox(object):
    
    def loadJSON(self, jsonfilename):
        
        try:
            with open(os.path.join(self.config['data_directory'], '%s.json' % jsonfilename),'r') as jsonfile:
                return json.loads(jsonfile.read())
        except FileNotFoundError:
            self.log.error('!! Error loading json - file does not exist: %s' % jsonfilename)
            return []
        except:
            self.log.error('Error loading pattern: %s' % jsonfilename,exc_info=True)
            return []
            
    def saveJSON(self, jsonfilename, data):
        
        try:
            jsonfile = open(os.path.join(self.config['data_directory'], '%s.json' % jsonfilename), 'wt')
            json.dump(data, jsonfile, ensure_ascii=False, default=self.jsonDateHandler)
            jsonfile.close()
        except:
            self.log.error('Error saving json: %s' % jsonfilename,exc_info=True)
            return []

    def jsonDateHandler(self, obj):

        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            self.log.error('Found unknown object for json dump: (%s) %s' % (type(obj),obj))
            return None

    async def get_config(self, path):
        try:
            async with aiofiles.open(path, mode='r') as f:
                result = await f.read()
                config=json.loads(result)
                self.config=config
            return config
        except:
            self.log.error('An error occurred while getting config: %s' % path, exc_info=True)
            return {}

    def logsetup(self, logbasepath, logname, level="INFO", errorOnly=[]):

        #log_formatter = logging.Formatter('%(asctime)-6s.%(msecs).03d %(levelname).1s %(lineno)4d %(threadName)-.1s: %(message)s','%m/%d %H:%M:%S')
        log_formatter = logging.Formatter('%(asctime)-6s.%(msecs).03d %(levelname).1s%(lineno)4d: %(message)s','%m/%d %H:%M:%S')
        logpath=os.path.join(logbasepath, 'log')
        logfile=os.path.join(logpath,"%s.log" % logname)
        if not os.path.exists(logpath):
            os.makedirs(logpath)
        #check if a log file already exists and if so rotate it

        needRoll = os.path.isfile(logfile)
        log_handler = RotatingFileHandler(logfile, mode='a', maxBytes=1024*1024, backupCount=5)
        log_handler.setFormatter(log_formatter)
        log_handler.setLevel(getattr(logging,level))
        if needRoll:
            log_handler.doRollover()
            
        console = logging.StreamHandler()
        console.setFormatter(log_handler)
        console.setLevel(logging.INFO)
        
        logging.getLogger(logname).addHandler(console)

        self.log =  logging.getLogger(logname)
        self.log.setLevel(logging.INFO)
        self.log.addHandler(log_handler)
        
        self.log.info('-- -----------------------------------------------')

    def __init__(self):
        self.error_state=False
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.get_config('./config.json'))
        self.logsetup(self.config["log_directory"], 'jukebox')

    def start(self):
        try:
            self.log.info('.. Starting jukebox server')
            asyncio.set_event_loop(self.loop)
            self.spotify = sofa_spotify_controller(config=self.config, loop=self.loop, log=self.log, app=self)
            self.server = web_server(config=self.config, loop=self.loop, log=self.log, app=self)
            result=self.server.initialize()
            self.spotify_polling_loop = self.loop.create_task(self.spotify.poll_status())
            self.loop.run_until_complete(self.spotify.start())
            if result:
                self.loop.run_forever()
            else:
                self.error_state=True
        except KeyboardInterrupt:  # pragma: no cover
            pass
        except:
            self.log.error('Loop terminated', exc_info=True)
        finally:
            self.server.shutdown()
        
        self.log.info('.. stopping sofa jukebox')
        for task in asyncio.Task.all_tasks():
            task.cancel()
        #self.loop.close()
        if self.error_state:
            sys.exit(1)


if __name__ == '__main__':
    jukebox=sofa_jukebox()
    jukebox.start()
 
