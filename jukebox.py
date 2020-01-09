#!/usr/bin/python3

import json
import asyncio
import aiohttp
from aiohttp import web
import ssl
import concurrent.futures
import aiofiles
import datetime
import os
import socket
import sys
from os.path import isfile, isdir, join

import logging
from logging.handlers import RotatingFileHandler

from spotipy import Spotify, Credentials
from spotipy.util import credentials_from_environment
from spotipy.scope import every
from spotipy.client import playlist

import requests
import vlc

class web_server():
    
    def initialize(self):
            
        try:
            self.info = {}
            self.token = None
            self.spotify = Spotify()
            self.goback=''
            self.serverApp = web.Application()
            self.serverApp.router.add_get('/', self.root_handler)
            self.serverApp.router.add_get('/playlist', self.playlist_handler)
            self.serverApp.router.add_get('/playlists', self.playlists_handler)
            self.serverApp.router.add_get('/auth', self.auth_handler)
            self.serverApp.router.add_get('/redirect', self.redirect_handler)
            self.serverApp.router.add_get('/devices', self.devices_handler)
            self.serverApp.router.add_get('/random', self.random_handler)
            self.serverApp.router.add_get('/player', self.player_handler)
            self.runner = aiohttp.web.AppRunner(self.serverApp)
            self.loop.run_until_complete(self.runner.setup())

            ssl_cert = self.config['cert']
            ssl_key = self.config['key']
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(str(ssl_cert), str(ssl_key))

            self.site = web.TCPSite(self.runner, self.config['hostname'], self.config['port'], ssl_context=self.ssl_context)
            self.log.info('Starting editor webserver at https://%s:%s' % (self.config['hostname'], self.config['port']))
            self.loop.run_until_complete(self.site.start())
            return True
        except socket.gaierror:
            self.log.error('Error - DNS or network down during intialize.', exc_info=True)
            return False
        except:
            self.log.error('Error starting REST server', exc_info=True)
            return False


    def date_handler(self, obj):
        
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            self.log.info('Caused type error: %s' % obj)
            raise TypeError

    async def root_handler(self, request):
        try:
            if self.goback:
                q=self.goback
                self.goback=None
                raise web.HTTPTemporaryRedirect(q)    
            return web.Response(text=str(self.app.spotify.get_user()))
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')

    async def devices_handler(self, request):
        #sp=Spotify(token=self.token)
        devices = self.app.spotify.player.playback_devices()
        display_list=[]
        for dev in devices:
            display_list.append(dev)
        display_list=devices
            
        return web.Response(text=str(display_list))


    async def playlists_handler(self, request):
        sp=Spotify(token=self.token)
        playlists = sp.followed_playlists()
        display_list=[]
        for playlist in playlists.items:
            display_list.append({"name":playlist.name, "id":playlist.id})
            
        return web.Response(text=str(display_list))

    async def playlist_handler(self, request):
        id='00H7xjekNG5qqE9KFtCW5m'
        sp=Spotify(token=self.token)
        playlist = sp.playlist(id)
        display_list=[]
        for track in playlist.tracks.items:
            print(dir(track))
            display_list.append(track.track.name)
            
        return web.Response(text=str(display_list))


    async def auth_handler(self, request):
        #self.cred = Credentials(*self.app.creds)
        #auth_url = self.cred.user_authorisation_url(scope=every)
        raise web.HTTPTemporaryRedirect(self.app.spotify.get_auth_url())
            
    async def redirect_handler(self, request):
        
        vals=self.get_query_string_variables(request.query_string)
        code=vals['code']
        #self.app.spotify.set_token(self.cred.request_user_token(code))
        self.app.spotify.set_token(code)
        #self.token = self.cred.request_user_token(code)
        #with self.spotify.token_as(self.token):
        #    self.info = self.spotify.current_user()
        raise web.HTTPTemporaryRedirect('/')

    async def player_handler(self, request):
        
        try:
            return web.Response(text=json.dumps({"position": self.app.player.vlc.get_position() }, default=self.date_handler))
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.Response(text='[]')

    def get_query_string_variables(self, query_string):
        
        try:
            vals={}
            for item in query_string.split('&'):
                if item and item.find('='):
                    try:
                        if "=" in item:
                            vals[item.split('=')[0]]=item.split('=')[1]
                        else:
                            vals[item]=True
                    except:
                        self.log.error('Error with query string var: %s' % item)
            return vals
        except:
            self.log.error('Error getting query string variables: %s' % query_string,exc_info=True)
            return {}
 

    def shutdown(self):
        self.loop.run_until_complete(self.serverApp.shutdown())

    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app

    async def random_handler(self, request):
        try:
            #sp=Spotify(token=self.token)
            vals=self.get_query_string_variables(request.query_string)
            genre=vals['genre']
            num_results = 20
            result = self.app.spotify.search('genre:"%s"' % genre, types=('track',), limit=num_results)
            return web.Response(text=str(result))
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.error('Error getting random: %s %s' % (request.raw_path, dir(request)),exc_info=True)
            return web.Response(text='error')

class sofa_spotify_controller(object):

    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app
        self.task=None
        self.info = {}
        self.token = None
        self.spotify = Spotify()
        self.config_creds=(self.config["client_id"], self.config["client_secret"], self.config["client_redirect_uri"])
        self.credentials=Credentials(*self.config_creds)
        self.auth_url = None
        self.spotify = Spotify()
        self.user_info={}
        self.player=None
        
    def start(self):
        pass
    
    def search(self, search, types=('track',), limit=10):
        try:
            display_list=[]
            result = self.player.search(search, types=types, limit=limit)      
            for track in result[0].items:
                #print(track.__dict__)
                artists=""
                for artist in track.artists:
                    artists+=artist.name
                display_list.append({"name": track.name, "artists": artists, "album": track.album.name, "url":track.href})
                self.prevurl=track.preview_url
            display_list=json.loads(json.dumps(display_list))

            #self.player.play(self.prevurl)
            return display_list

        except:
            self.log.error('Error searching spotify', exc_info=True)
            return []
    
    def set_token(self, code):
        self.log.info('Setting token from code: %s...' % code[:10])
        self.token = self.credentials.request_user_token(code)
        self.player = Spotify(token=self.token)
        
    def get_user(self):
        with self.spotify.token_as(self.token):
            self.user_info = self.spotify.current_user()
        return self.user_info
    
    def get_auth_url(self):
        self.auth_url = self.credentials.user_authorisation_url(scope=every)
        return self.auth_url

class sofa_player(object):
    
    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app
        self.task=None
        opt=""
        if 'vlcargs' in self.config:
            opt=self.config['vlcargs']
        self.instance = vlc.Instance(opt)
        self.vlc = self.instance.media_player_new()
        
    async def start(self):
        self.task = loop.create_task(periodic())

    def stop(self):
        self.task.cancel()

    async def poll_status(self):
        try:
            while True:
                print('player: %s %s of %s' % (self.vlc.get_state(), (self.vlc.get_position() * (self.vlc.get_length() / 1000)), self.vlc.get_length() / 1000))
                if self.vlc.get_state()=="State.Ended":
                    self.loop.call_soon(self.stop)
                await asyncio.sleep(1)
        except:
            self.log.error('Error polling', exc_info=True)

    def play(self, url):
        try:
            if not self.task:
                self.task = self.loop.create_task(self.poll_status())
            self.log.info('Trying to play: %s' % url)
            self.Media = self.instance.media_new(url)
            self.vlc.set_media(self.Media)
            self.vlc.play()
        except:
            self.log.error('Error trying to play', exc_info=True)
 
class sofa_jukebox(object):

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
            self.player = sofa_player(config=self.config, loop=self.loop, log=self.log, app=self)
            result=self.server.initialize()
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
        self.loop.close()
        if self.error_state:
            sys.exit(1)


if __name__ == '__main__':
    jukebox=sofa_jukebox()
    jukebox.start()
 