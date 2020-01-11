#!/usr/bin/python3

import json
import asyncio

import aiohttp
from aiohttp import web
from aiohttp_sse import sse_response
import aiohttp_cors

import ssl
import concurrent.futures
import aiofiles
import datetime
import os
import socket
import sys
import datetime
from os.path import isfile, isdir, join
import subprocess

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
            self.subscribers= set()
            self.info = {}
            self.token = None
            self.spotify = Spotify()
            self.goback=''
            self.serverApp = web.Application()
            self.cors = aiohttp_cors.setup(self.serverApp, defaults={
                "*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_methods='*', allow_headers="*")
            })

            self.cors.add(self.serverApp.router.add_get('/', self.root_handler))
            self.cors.add(self.serverApp.router.add_static('/client', path=self.config['client_build_directory'], append_version=True))
            self.cors.add(self.serverApp.router.add_get('/sse', self.sse_handler))
            
            self.cors.add(self.serverApp.router.add_get('/playlist/{playlist}', self.playlist_handler))
            self.cors.add(self.serverApp.router.add_get('/playlists', self.playlists_handler))
            self.cors.add(self.serverApp.router.add_get('/auth', self.auth_handler))
            self.cors.add(self.serverApp.router.add_get('/redirect', self.redirect_handler))
            self.cors.add(self.serverApp.router.add_get('/random', self.random_handler))
            self.cors.add(self.serverApp.router.add_get('/player', self.player_handler))
            self.cors.add(self.serverApp.router.add_get('/play', self.play_handler))
            self.cors.add(self.serverApp.router.add_get('/next', self.next_handler))
            self.cors.add(self.serverApp.router.add_get('/pause', self.pause_handler))
            self.cors.add(self.serverApp.router.add_get('/devices', self.devices_handler))
            self.cors.add(self.serverApp.router.add_get('/set_device/{device}', self.setdevice_handler))
            self.cors.add(self.serverApp.router.add_get('/setbackup/{playlist}', self.setbackup_handler))
            self.cors.add(self.serverApp.router.add_get('/user', self.user_handler))
            self.cors.add(self.serverApp.router.add_get('/queue', self.queue_handler))
            self.cors.add(self.serverApp.router.add_get('/search/{search}', self.search_handler))
            self.cors.add(self.serverApp.router.add_get('/add/{id}', self.add_handler))
            self.cors.add(self.serverApp.router.add_get('/nowplaying', self.nowplaying_handler))
            self.cors.add(self.serverApp.router.add_get('/del/{id}', self.del_handler))
            self.cors.add(self.serverApp.router.add_get('/spotifyd/{action}', self.spotifyd_handler))
            self.runner = aiohttp.web.AppRunner(self.serverApp)
            self.loop.run_until_complete(self.runner.setup())

            ssl_cert = self.config['cert']
            ssl_key = self.config['key']
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(str(ssl_cert), str(ssl_key))

            self.site = web.TCPSite(self.runner, self.config['hostname'], self.config['port'], ssl_context=self.ssl_context)
            self.log.info('.. Starting jukebox webserver at https://%s:%s' % (self.config['hostname'], self.config['port']))
            self.loop.run_until_complete(self.site.start())
            return True
        except socket.gaierror:
            self.log.error('!! Error - DNS or network down during intialize.', exc_info=True)
            return False
        except:
            self.log.error('!! Error starting REST server', exc_info=True)
            return False

    def authenticate(func):
        def wrapper(self):
            try:
                return func(self)
            except AuthorizationNeeded:
                self.goback=request.raw_path
                raise web.HTTPTemporaryRedirect('/auth')        
        return wrapper


    def shutdown(self):
        self.loop.run_until_complete(self.serverApp.shutdown())

    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app

    def date_handler(self, obj):
        
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            self.log.info('Caused type error: %s' % obj)
            raise TypeError

    async def root_handler(self, request):
        try:
            self.log.info('Serving react app to %s' % request.remote)
            #return web.FileResponse(os.path.join(self.config['client_static_directory'],'index.html'))
            return web.FileResponse(os.path.join(self.config['client_build_directory'],'index.html'))
        except:
            self.log.error('Error serving root page', exc_info=True)

    async def old_root_handler(self, request):
        try:
            if self.goback:
                q=self.goback
                self.goback=None
                raise web.HTTPTemporaryRedirect(q)    
            return web.json_response(self.app.spotify.get_user())
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')

    async def sse_handler(self, request):
        async with sse_response(request) as response:
            remoteip=request.remote
            queue = asyncio.Queue()
            self.log.info('.. new remote user from %s' % remoteip)
            self.subscribers.add(queue)
            try:
                while not response.task.done():
                    payload = await queue.get()
                    await response.send(payload)
                    queue.task_done()
            finally:
                self.subscribers.remove(queue)
                self.log.info('.. user disconnected from %s' % remoteip)
        return response

    async def user_handler(self, request):
        try:
            return web.json_response(self.app.spotify.get_user())
        except requests.exceptions.HTTPError:
            return web.json_response({})

    async def playlists_handler(self, request):
        try:
            display_list=self.app.spotify.get_user_playlists()
            return web.json_response(display_list)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.info('error getting user playlists', exc_info=True)
            return web.json_response([])

    async def devices_handler(self, request):
        try:
            display_list=self.app.spotify.get_playback_devices()
            return web.json_response(display_list)
        except AuthorizationNeeded:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')        
        except:
            self.log.info('error getting user playlists', exc_info=True)
            return web.json_response([])

    async def setdevice_handler(self, request):
        
        try:
            name=request.match_info['device']
            self.log.info('Trying to set device to %s' % name)
            result=await self.app.spotify.set_playback_device(name)
            return web.json_response(result)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.info('error setting device', exc_info=True)
            result=False
        return web.Response(text="Device set to %s: %s" % (name, result))

    async def playlist_handler(self, request):
        
        try:
            display_list=[]
            name=request.match_info['playlist']
            playlist=self.app.spotify.get_user_playlist(request.match_info['playlist'])
            display_list=self.app.spotify.get_playlist_tracks(playlist['id'])
            return web.json_response(display_list)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')

        except:
            self.log.info('error getting playlist', exc_info=True)
            return web.json_response([])

    async def setbackup_handler(self, request):
        
        try:
            playlist=await self.app.spotify.set_backup_playlist(request.match_info['playlist'])
            return web.json_response(playlist)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.info('error getting playlist', exc_info=True)
            return web.json_response([])


    async def auth_handler(self, request):
        #self.cred = Credentials(*self.app.creds)
        #auth_url = self.cred.user_authorisation_url(scope=every)
        raise web.HTTPTemporaryRedirect(self.app.spotify.get_auth_url())
            
    async def redirect_handler(self, request):
        
        vals=self.get_query_string_variables(request.query_string)
        if 'code' in vals:
            code=vals['code']
            result=await self.app.spotify.set_token(code)
            return web.json_response({'authenticated':True})

        return web.json_response({'authenticated':False})

    async def player_handler(self, request):
        
        try:
            return web.json_response({"position": self.app.player.vlc.get_position() })
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    async def pause_handler(self, request):
        
        try:
            result=await self.app.spotify.pause()
            return web.json_response(await self.app.spotify.now_playing())
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])


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

    async def play_handler(self, request):
        try:
            result=await self.app.spotify.play()
            return web.json_response(await self.app.spotify.now_playing())
        except:
            self.log.error('Error sending play command',exc_info=True)
            return web.Response(text='error')

    async def next_handler(self, request):
        try:
            result=await self.app.spotify.next_track()
            return web.json_response(await self.app.spotify.now_playing())
        except:
            self.log.error('Error sending play command',exc_info=True)
            return web.Response(text='error')

    async def search_handler(self, request):
        try:
            search=request.match_info['search']
            return web.json_response(await self.app.spotify.search(search))
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    async def add_handler(self, request):
        try:
            song_id=request.match_info['id']
            return web.json_response(await self.app.spotify.add_track(song_id))
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    async def del_handler(self, request):
        try:
            song_id=request.match_info['id']
            return web.json_response(await self.app.spotify.del_track(song_id))
        except:
            self.log.info('error removing track', exc_info=True)
            return web.json_response([])

    async def spotifyd_handler(self, request):
        try:
            action=request.match_info['action']
            return web.json_response(await self.app.spotify.spotifyd_control(action))
        except:
            self.log.info('error removing track', exc_info=True)
            return web.json_response([])


    async def queue_handler(self, request):
        return web.json_response(await self.app.spotify.get_queue())

    async def nowplaying_handler(self, request):
        return web.json_response(await self.app.spotify.now_playing())


class AuthorizationNeeded(Exception):
    pass

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
        self.device=None
        self.user_pause=False
        
        self.backup_playlist=self.loadJSON('backup_playlist')
        self.user_playlist=self.loadJSON('user_playlist')
        self.active=False
        
    async def fetch_page(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                print(resp.status)
                return await resp.text()

    async def set_token(self, code):
        try:
            self.log.info('Setting token from code: %s...' % code[:10])
            self.code = code
            self.token = self.credentials.request_user_token(code)
            self.player = Spotify(token=self.token)
            if self.player:
                if not self.device:
                    await self.set_playback_device(self.config['default_device'])
            await self.update_list('update')
            await self.update_nowplaying()
        except:
            self.log.error('Error setting playback device to %s' % name, exc_info=True)


    def authenticated(func):
        def wrapper(self):
            self.log.info('checking authentication')
            if self.token and self.player:
                return func(self)
            else:
                self.log.info('must be authenticated before using spotify API')
                #return False
                raise AuthorizationNeeded
        return wrapper
        
    def get_user(self):
        with self.spotify.token_as(self.token):
            self.user_info = self.spotify.current_user()
            userinfo=json.loads(str(self.user_info))
        return userinfo
    
    def get_auth_url(self):
        self.auth_url = self.credentials.user_authorisation_url(scope=every)
        return self.auth_url
        
    async def set_playback_device(self, name):
        # This allows you to select a playback device by name
        try:
            devs=self.player.playback_devices()
            for dev in devs:
                if dev.name==name:
                    self.player.playback_transfer(dev.id)
                    self.device=dev.id
                    return True
            return False
        except:
            self.log.error('Error setting playback device to %s' % name, exc_info=True)

    @authenticated
    async def get_playback_devices(self):
        try:
            return json.loads(str(self.player.playback_devices()))
        except:
            self.log.error('Error getting spotify connect devices', exc_info=True)
            return []
            
    async def get_user_playlist(self, name):
        
        try:
            playlists = self.player.followed_playlists()
            for playlist in playlists.items:
                if playlist.name==name:
                    self.log.info('found playlist: %s' % playlist.name)
                    return {"name":playlist.name, "id":playlist.id}
            return {}
        except:
            self.log.error('Error searching spotify', exc_info=True)
            return {}

    async def get_user_playlists(self):
        
        try:
            display_list=[]
            playlists = self.player.followed_playlists()
            for playlist in playlists.items:
                display_list.append({"name":playlist.name, "id":playlist.id})
            return display_list
        except:
            self.log.error('Error getting user playlists from spotify', exc_info=True)
            return []


    async def get_playlist_tracks(self, id):
        
        try:
            display_list=[]
            playlist = self.player.playlist(id)
            for track in playlist.tracks.items:
                display_list.append({"id": track.track.id, "name": track.track.name, "art":track.track.album.images[0].url, "artist": track.track.artists[0].name, "album": track.track.album.name, "url":track.track.href})
            return display_list
        except:
            self.log.error('Error getting spotify playlist tracks', exc_info=True)
            return []

    
    async def search(self, search, types=('track',), limit=20):
        try:
            display_list=[]
            result = self.player.search(search, types=types, limit=limit)      
            for track in result[0].items:
                display_list.append({"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href})
            return display_list

        except:
            self.log.error('Error searching spotify', exc_info=True)
            return []

    async def add_track(self, song_id):
        try:
            self.log.info('Track ID: %s' % song_id)
            track = self.player.track(song_id)
            self.log.info('Adding track: %s' % {"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href})
            pltrack={"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href}
            self.user_playlist.append(pltrack)
            self.saveJSON('user_playlist', self.user_playlist)
            await self.update_list('update')
        except:
            self.log.error('Error adding song %s' % song_id, exc_info=True)
            return []

    async def del_track(self, song_id):
        try:
            remove_count=0
            newlist=[]
            for song in self.user_playlist:
                if song['id']!=song_id:
                    self.log.info('Adding non-delete: %s vs %s' % (song['id'],song_id))
                    newlist.append(song)
                else:
                    remove_count+=1
            self.user_playlist=newlist
            self.saveJSON('user_playlist', self.user_playlist)
            
            newlist=[]
            for song in self.backup_playlist:
                if song['id']!=song_id:
                    newlist.append(song)
                else:
                    remove_count+=1
            self.backup_playlist=newlist
            self.saveJSON('backup_playlist', self.backup_playlist)   
            await self.update_list('update')
            return {"removed":remove_count}
        except:
            self.log.error('Error adding song %s' % song_id, exc_info=True)
            return []



    async def get_queue(self):
        try:
            fullqueue=self.user_playlist+self.backup_playlist
            return fullqueue
        except:
            self.log.error('Error getting full queue', exc_info=True)
            return []
            
    async def update_nowplaying(self):
        try:
            nowplaying=await self.now_playing()
            await self.update_subscribers({'nowplaying':nowplaying})
            
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return []

    async def update_list(self, action):
        try:
            nowplaying=await self.now_playing()
            await self.update_subscribers({'playlist':action})
            
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return []


    async def update_subscribers(self, data):
        try:
            payload = json.dumps(data)
            for q in self.app.server.subscribers:
                await q.put(payload)      
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return []

    async def spotifyd_control(self, action="restart"):
        
        try:
            stdoutdata = subprocess.getoutput("systemctl %s spotifyd" % action)
            return stdoutdata
        except:
            self.log.error('!! Error restarting adapter', exc_info=True)


                
    async def now_playing(self):
        try:
            npdata=self.player.playback_currently_playing()
            if npdata:
                track=npdata.item
                nowplaying={"id": track.id, "name": track.name, "art":track.album.images[0].url, 
                            "artist": track.artists[0].name, "album": track.album.name, "url":track.href,
                            "is_playing": npdata.is_playing
                }

                self.log.info('Nowplaying: %s' % nowplaying)
                return nowplaying
            else:
                return {}
        except:
            self.log.error('Error getting now playing', exc_info=True)
            return {}
            
    async def pause(self):     
        try:
            self.log.info('sending pause')
            self.player.playback_pause()
            await self.update_nowplaying()
            await self.start_status()
            self.user_pause=True
            return True
        except:
            self.log.error('Error pausing', exc_info=True)
            return False

    async def play(self):     
        try:
            self.log.info('sending play')
            self.player.playback_resume()
            self.active=True
            await self.update_nowplaying()
            await self.start_status()
            self.user_pause=False
            return True
        except:
            self.log.error('Error playing', exc_info=True)
            return False


    async def set_backup_playlist(self, name):
        try:
            playlist=await self.get_user_playlist(name)
            track_list=await self.app.spotify.get_playlist_tracks(playlist['id'])
            self.backup_playlist=list(track_list)
            self.saveJSON('backup_playlist', self.backup_playlist)
            #self.log.info('Backup playlist is now: %s' % self.backup_playlist)
            return track_list
        except:
            self.log.error('Error setting backup playlist', exc_info=True)
            return []

    async def get_next_track(self):
        try:
            next_track={}
            next_track=await self.pop_user_track()
            self.log.info('Getting user track: %s' % next_track)
            if not next_track:
                next_track=await self.pop_backup_track()
                self.log.info('Getting backup track: %s' % next_track)
            return next_track
        except:
            self.log.error('Error getting next track from queues')
            return {}

    async def pop_user_track(self):
        try:
            if self.user_playlist:
                next_track=self.user_playlist.pop(0)
                self.saveJSON('user_playlist', self.user_playlist)
                return next_track
            else:
                return {}
        except:
            self.log.error('Error getting track from backup playlist')
            return {}
            
    async def pop_backup_track(self):
        try:
            if self.backup_playlist:
                next_track=self.backup_playlist.pop(0)
                self.saveJSON('backup_playlist', self.backup_playlist)
                return next_track
            else:
                return {}
        except:
            self.log.error('Error getting track from backup playlist', exc_info=True)
            return {}

    async def next_track(self):
        try:
            next_track=await self.get_next_track()
            if next_track:
                self.active=True
                await self.play_id(next_track['id'])
                await self.update_nowplaying()
                await self.update_list('pop')
            else:
                self.log.info('No more tracks to play')
                #self.active=False
        except:
            self.log.error('Error trying to play', exc_info=True)
            #self.active=False

    async def play_id(self, id):
        try:
            self.player.playback_start_tracks([id])
            self.active=True
        except:
            self.log.error('Error trying to play id %s' % id, exc_info=True)
            self.active=False

    def loadJSON(self, jsonfilename):
        
        try:
            with open(os.path.join('/opt/jukebox/', '%s.json' % jsonfilename),'r') as jsonfile:
                return json.loads(jsonfile.read())
        except FileNotFoundError:
            self.log.error('!! Error loading json - file does not exist: %s' % jsonfilename)
            return []
        except:
            self.log.error('Error loading pattern: %s' % jsonfilename,exc_info=True)
            return []
            
    def saveJSON(self, jsonfilename, data):
        
        try:
            jsonfile = open(os.path.join('/opt/jukebox/', '%s.json' % jsonfilename), 'wt')
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


    async def start_status(self):
        self.log.info('Starting status loop')

        self.task = self.loop.create_task(self.poll_status())

    def stop(self):
        self.task.cancel()

    async def poll_status(self):
        try:
            while self.active:
                try:
                    npdata=self.player.playback_currently_playing()
                    #self.log.info('Progress: %s / %s' % ( npdata.progress_ms, npdata.item.duration_ms))
                    #self.loop.call_soon(self.stop)
                    if npdata.progress_ms==0 and not self.user_pause:
                        await self.next_track()
                except:
                    self.log.error('.. error while polling - delaying 5 seconds', exc_info=True)
                    await asyncio.sleep(5)
                await asyncio.sleep(1)
        except:
            self.log.error('Error polling', exc_info=True)

    def test_player(self):
        with self.subTest('Set volume'):
            self.client.playback_volume(0, device_id=self.device.id)

        with self.subTest('Transfer playback'):
            self.client.playback_transfer(self.device.id, force_play=True)

        self.client.playback_start_tracks(track_ids, offset=1)
        self.assertPlaying('Playback start with offset index', track_ids[1])

        playing = self.client.playback_currently_playing()
        with self.subTest('Currently playing has item'):
            self.assertIsNotNone(playing.item)

        self.client.playback_start_tracks(track_ids, offset=track_ids[1])
        self.assertPlaying('Playback start with offset uri', track_ids[1])

        self.client.playback_start_tracks(track_ids)
        self.assertPlaying('Playback start', track_ids[0])

        self.client.playback_pause()
        playing = self.currently_playing()
        with self.subTest('Playback pause'):
            self.assertFalse(playing.is_playing)

        with self.subTest('Player error: already paused'):
            with self.assertRaises(HTTPError):
                self.client.playback_pause()

        self.client.playback_resume()
        playing = self.currently_playing()
        with self.subTest('Playback resume'):
            self.assertTrue(playing.is_playing)

        self.client.playback_next()
        self.assertPlaying('Playback next', track_ids[1])

        self.client.playback_previous()
        self.assertPlaying('Playback previous', track_ids[0])

        self.client.playback_seek(30 * 1000)
        playing = self.currently_playing()
        with self.subTest('Playback seek'):
            self.assertGreater(playing.progress_ms, 30 * 1000)

        with self.subTest('Playback repeat'):
            self.client.playback_repeat('off')

        with self.subTest('Playback shuffle'):
            self.client.playback_shuffle(False)

        with self.subTest('Playback start context'):
            self.client.playback_start_context('spotify:album:' + album_id)


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
 