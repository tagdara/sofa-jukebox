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

import tekore
from tekore import Spotify, Credentials, RefreshingToken, AsyncPersistentSender, RetryingSender
from datetime import datetime
import uuid

import random
import requests
import subprocess

class AuthorizationNeeded(Exception):
    pass

class sofa_spotify_controller(object):

    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app
        self.device=None
        self.user_pause=False
        self.task=None
        self.active=False
        self.running=True
        self.info = {}
        self.user_info={}
        self.token = None
        self.spotify = Spotify()
        self.credentials=Credentials(self.config["client_id"], self.config["client_secret"], self.config["client_redirect_uri"])
        self.sender = RetryingSender(sender=AsyncPersistentSender())
        self.playback_device_name=self.config['default_device']

        self.user_info={}

        self.load_auth()
        self.backup_playlist=self.load_and_confirm('backup_playlist')
        self.user_playlist=self.load_and_confirm('user_playlist')
        self.previous_picks=self.load_and_confirm('previous_picks')

    async def start(self):
        try:
            nowplaying=await self.update_now_playing()
            self.log.info('.. startup now playing: %s' % nowplaying)
        except:
            self.log.error('.! error starting initial nowplaying check', exc_info=True)
            self.active=False

    @property
    def auth_url(self):
        try:
            return self.credentials.user_authorisation_url(scope=tekore.scope.every)
        except:
            self.log.error('.. error retrieving authorization url', exc_info=True)
        return "" 
        
    def load_and_confirm(self, listname):
        # Load queues from disk and ensure they have a selection_tracker uuid to help deal with unique key requirements in the client
        playlist=[]
        try:
            playlist=self.app.loadJSON(listname)
            for item in playlist:
                if 'selection_tracker' not in item:
                    item['selection_tracker']=str(uuid.uuid4())
        except:
            self.log.error('!! error loading and checking list: %s' % listname)
        return playlist
        

    def load_auth(self):
        
        try:
            conf=(self.config["client_id"], self.config["client_secret"], self.config["client_redirect_uri"])
            with open(os.path.join(self.config['base_directory'], 'token.json'),'r') as jsonfile:
                token_contents=json.loads(jsonfile.read())
            #self.token = RefreshingToken(None, self.credentials)
            #self.token.refresh_user_token(conf,token_contents['refresh_token'])
            #self.log.info('Using refresh Token: %s' % token_contents['refresh_token'])
            token=self.credentials.refresh_user_token(token_contents['refresh_token'])
            #self.log.info('pre Token: %s' % token)
            self.token = RefreshingToken(token, self.credentials)
            self.spotify = Spotify(token=self.token, sender=self.sender, max_limits_on=True)
            #self.log.info('Token: %s' % self.token)
        except:
            self.log.error('.. Error loading token', exc_info=True)


    async def save_auth(self, token=None, code=None):
        
        try:
            token_data={'last_code':code, "type": token.token_type, "access_token": token.access_token, "refresh_token": token.refresh_token, "expires_at": token.expires_at}
            self.log.info('.. saving token data: %s' % token_data)
            async with aiofiles.open(os.path.join(self.config['base_directory'], 'token.json'), 'w') as f:
                await f.write(json.dumps(token_data))
        except:
            self.log.error('.. Error saving token and code' % (token[:10], code[:10]), exc_info=True)

    async def set_token(self, code):
        try:
            self.log.info('.. Setting token from code: %s...' % code[:10])
            self.code = code
            token = self.credentials.request_user_token(code)
            self.token = RefreshingToken(token, self.credentials)
            self.log.info('.. Token is now: %s' % self.token)
            await self.save_auth(token=self.token, code=self.code)
            self.spotify = Spotify(token=self.token, sender=self.sender, max_limits_on=True)
            #await self.monitor_token()
            
            # This is currently removed for troubleshooting when a device gets picked
            #if self.spotify:
            #    if not self.device:
            #        await self.set_playback_device(self.config['default_device'])
                    
                    
            await self.update_list('update')
            await self.update_now_playing()
        except:
            self.log.error('Error setting token from code %s' % code[:10], exc_info=True)


    def authenticated(func):
        def wrapper(self):
            self.log.info('checking authentication')
            if self.token and self.spotify:
                return func(self)
            else:
                self.log.info('must be authenticated before using spotify API')
                #return False
                raise AuthorizationNeeded
        return wrapper
        
    async def get_user(self):

        try:
            if self.token:
                #self.log.info('user: %s' % await self.spotify.current_user())
                userobj=await self.spotify.current_user()
                return userobj.asbuiltin()
        except tekore.client.decor.error.Unauthorised:
            self.log.error('.. Invalid access token: %s' % self.token.access_token)
        except:
            self.log.error('.. error getting user info', exc_info=True)
        return {}
    
    async def restart_local_playback_device(self):
        # This allows you to select a playback device by name
        try:
            stdoutdata = subprocess.getoutput("systemctl restart raspotify")
            self.log.info('>> restart local playback device %s' % stdoutdata)
            return True
        except:
            self.log.error('Error restarting local playback', exc_info=True)
        return False
        
    async def set_playback_device(self, name, restart=True):
        # This allows you to select a playback device by name
        try:
            # try to restart the local spotifyd since it tends to fail over time     
            devs=await self.spotify.playback_devices()
            for dev in devs:
                if dev.name==name:
                    self.log.info('transferring to %s' % dev.id)
                    await self.spotify.playback_transfer(dev.id)
                    self.device=dev.id
                    return True
                    
            self.log.info('did not find local playback device %s.  restarting' % name)
            
            await self.restart_local_playback_device()
            await asyncio.sleep(2)
            
            devs=await self.spotify.playback_devices()
            for dev in devs:
                if dev.name==name:
                    self.log.info('transferring to %s' % dev.id)
                    await self.spotify.playback_transfer(dev.id)
                    self.device=dev.id
                    return True

            return False
        except:
            self.log.error('Error setting playback device to %s' % name, exc_info=True)

    async def check_playback_devices(self):
        # This allows you to select a playback device by name
        try:
            devs=await self.spotify.playback_devices()
            for dev in devs:
                self.log.info('Device: %s' % dev)

        except:
            self.log.error('Error checking playback devices', exc_info=True)
        return False

    async def check_playback_device(self):
        # This allows you to select a playback device by name
        try:
            devs=await self.spotify.playback_devices()
            for dev in devs:
                if dev.name==self.playback_device_name:
                    if dev.is_active:
                        return True

        except:
            self.log.error('Error checking playback devices', exc_info=True)
        return False


    @authenticated
    async def get_playback_devices(self):
        try:
            outlist=[]
            devices=await self.spotify.playback_devices()
            for dev in devices:
                newdev=dev.asbuiltin()
                newdev['type']='unknown'
                outlist.append(newdev)
            self.log.info('X: %s' % outlist )
            return outlist
        except:
            self.log.error('Error getting spotify connect devices', exc_info=True)
            return []
            
    async def get_user_playlist(self, name):
        
        try:
            playlists = await self.spotify.followed_playlists()
            for playlist in playlists.items:
                if playlist.name==name:
                    self.log.info('found playlist: %s %s' % (playlist.name, playlist.owner))
                    return {"name":playlist.name, "id":playlist.id}
            return {}
        except:
            self.log.error('Error searching spotify', exc_info=True)
            return {}


    async def get_user_playlists(self):
        
        try:
            display_list=[]
            playlists = await self.spotify.followed_playlists()
            #playlists = self.spotify.followed_playlists()
            for playlist in playlists.items:
                #self.log.info('found playlist: %s %s' % (playlist.name, playlist.owner.id))
                try:
                    cover=""
                    covers=await self.spotify.playlist_cover_image(playlist.id)
                    if len(covers)>0:
                        cover=covers[0].url
                except concurrent.futures._base.CancelledError:
                    self.log.error('Error getting cover for %s (cancelled)' % playlist.name, exc_info=True)
                except:
                    self.log.error('Error getting cover for %s' % playlist.name, exc_info=True)
                display_list.append({"name":playlist.name, "id":playlist.id, "art": cover, "owner": playlist.owner.id})
            return display_list
        except:
            self.log.error('Error getting user playlists from spotify', exc_info=True)
            return []


    async def get_playlist_tracks(self, id):
        
        try:
            display_list=[]
            #playlist = self.spotify.playlist(id)
            tracks = await self.spotify.playlist_tracks(id)
            tracks = self.spotify.all_items(tracks)
            self.log.info('.. Tracks: %s' % tracks)
            async for track in tracks:
                display_list.append({"id": track.track.id, 'selection_tracker':str(uuid.uuid4()), "name": track.track.name, "art":track.track.album.images[0].url, "artist": track.track.artists[0].name, "album": track.track.album.name, "url":track.track.href})
            return display_list
        except:
            self.log.error('Error getting spotify playlist tracks', exc_info=True)
            return []

    
    async def search(self, search, types=('track',), limit=20):
        try:
            display_list=[]
            result = await self.spotify.search(search, types=types, limit=limit)      
            for track in result[0].items:
                display_list.append({"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href})
            return display_list

        except:
            self.log.error('Error searching spotify', exc_info=True)
            return []
            
    async def add_track_to_playlist(self, song_id, playlist_id):
        try:
            #playlist=await self.get_user_playlist("Discovered")
            #playlist_id=playlist['id']
            await self.spotify.playlist_tracks_add(playlist_id, [song_id])
        except:
            self.log.error('Error adding tracks to playlist', exc_info=True)

    async def add_track(self, song_id):
        try:
            track = await self.spotify.track(song_id)
            prevcount=0
            for prev in self.previous_picks:
                if track.id==prev['id']:
                    if 'count' in prev:
                        prevcount=prev['count']+1
                    else:
                        prevcount=1
                    prev['count']=prevcount

            pltrack={"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href, "votes": 1, "count":prevcount}
            self.log.info('Adding track: %s - %s' % (pltrack['artist'], pltrack['name']))    
            self.user_playlist.append(pltrack)
            self.app.saveJSON('user_playlist', self.user_playlist)
            if prevcount==0:
                self.previous_picks.append({"id": track.id, "name": track.name, "art":track.album.images[0].url, "artist": track.artists[0].name, "album": track.album.name, "url":track.href, "count":1})
            self.app.saveJSON('previous_picks', self.previous_picks)
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
            self.app.saveJSON('user_playlist', self.user_playlist)
            
            newlist=[]
            for song in self.backup_playlist:
                if song['id']!=song_id:
                    newlist.append(song)
                else:
                    remove_count+=1
            self.backup_playlist=newlist
            self.app.saveJSON('backup_playlist', self.backup_playlist)   
            await self.update_list('update')
            return {"removed":remove_count}
        except:
            self.log.error('Error adding song %s' % song_id, exc_info=True)
            return []

    async def shuffle_backup(self):
        try:
            promoted_list=[]
            working_backup=[]
            ids=[]
            for item in self.backup_playlist:
                if item['id'] not in ids:
                    ids.append(item['id'])
                else:
                    self.log.info('dupe track: %s' % item)
                if 'promoted' in item and item['promoted']==True:
                    promoted_list.append(item)
                else:
                    working_backup.append(item)
            random.shuffle(working_backup)
            self.backup_playlist=promoted_list+working_backup
            #self.log.info('.. new backup list: %s' % self.backup_playlist)
            return self.backup_playlist
        except:
            self.log.error('Error shuffling backup list', exc_info=True)
            return []
            
    async def get_queue(self):
        try:
            splitqueue={'user':self.user_playlist, 'backup': self.backup_playlist, 'previous': self.previous_picks}
            return splitqueue
            #fullqueue=self.user_playlist+self.backup_playlist
            #return fullqueue
        except:
            self.log.error('Error getting full queue', exc_info=True)
            return []

    async def list_next_tracks(self, maxcount=5):
        try:
            next_tracks=[]
            next_tracks=self.user_playlist[:maxcount]
            if len(next_tracks)<maxcount:
                next_tracks=next_tracks+self.backup_playlist[:maxcount]
            return next_tracks
        except:
            self.log.error('Error getting next tracks', exc_info=True)
            return []
           
    async def update_now_playing(self):
        try:
        
            nowplaying=await self.now_playing()
            self.log.info('Updating nowplaying data: %s' % nowplaying)
            if 'webdisplay_url' in self.config:
                try:
                    async with aiohttp.ClientSession() as session:
                        #self.log.info('Sending to %s' % (self.config['webdisplay_url']+"/set/nowplaying") )
                        await session.post(self.config['webdisplay_url']+"/set/nowplaying", data=json.dumps({'nowplaying':nowplaying, 'next': await self.list_next_tracks(maxcount=3)})) 
                except:
                    self.log.error('Error updating webdisplay', exc_info=True)
            await self.app.server.send_update_to_subscribers({'nowplaying':nowplaying})
            return nowplaying
            
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return {}

    async def update_list(self, action):
        try:
            nowplaying=await self.now_playing()
            await self.app.server.send_update_to_subscribers({'playlist':action})
            
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return []

    async def get_track_data(self, track):
        try:
            if not track:
                return {}
            item=track.item
            return {"id": item.id, "name": item.name, "art":item.album.images[0].url, "artist": item.artists[0].name, 
                    "album": item.album.name, "url":item.href, "is_playing": track.is_playing, "length": int(track.item.duration_ms/1000), "position": int(track.progress_ms/1000) }
        except:
            self.log.error('.. error getting track data from %s' % track)
            return {}
               
    async def now_playing(self):
        try:
            nowplaying={}
            npdata=None
            if self.spotify:
                try:
                    npdata=await self.spotify.playback_currently_playing()
                    #self.log.info('raw: %s' % npdata)
                    #self.log.info('raw: %s' % npdata.item)
                    nowplaying=await self.get_track_data(npdata)
                except requests.exceptions.HTTPError:
                    self.log.warn('.. Token may have expired: %s' % self.token)
                    self.active=False
        except:
            self.log.error('Error getting now playing', exc_info=True)
            self.active=False
        return nowplaying
            
            
    async def pause(self):     
        try:
            self.log.info('sending pause')
            await self.spotify.playback_pause()
            await self.update_now_playing()
            await self.start_status()
            self.user_pause=True
            return True
        except:
            self.log.error('Error pausing', exc_info=True)
            return False


    async def play(self):     
        try:
            if not await self.check_playback_device():
                await self.set_playback_device(self.playback_device_name)
            playing = await self.spotify.playback_currently_playing()
            # TESTING
            #if not self.device:
            #    await self.set_playback_device(self.config['default_device'])
            
            try:
                await self.spotify.playback_resume()
            except tekore.Forbidden:
                await self.next_track()

            self.active=True
            await self.update_now_playing()
            await self.start_status()
            self.user_pause=False
            return True

            # TODO: need handler for this error:
            # tekore.client.decor.error.NotFound: Error in https://api.spotify.com/v1/me/player/play:
            # 404: Player command failed: No active device found
            # Requires an active device and the user has none.

        except:
            self.log.error('Error playing', exc_info=True)
            return False
            
    async def set_backup_playlist(self, playlist_id):
        try:
            #playlist=await self.get_user_playlist(name)
            #track_list=await self.app.spotify.get_playlist_tracks(playlist['id'])
            track_list=await self.app.spotify.get_playlist_tracks(playlist_id)
            for item in track_list:
                item['selection_tracker']=str(uuid.uuid4())

            self.backup_playlist=list(track_list)
            self.app.saveJSON('backup_playlist', self.backup_playlist)
            #self.log.info('Backup playlist is now: %s' % self.backup_playlist)
            return track_list
        except:
            self.log.error('Error setting backup playlist', exc_info=True)
            return []

    async def get_next_track(self):
        try:
            next_track={}
            next_track=await self.pop_user_track()
            if next_track:
                self.log.info('Getting user track: %s - %s' % (next_track['artist'], next_track['name']))
            else:
                next_track=await self.pop_backup_track()
                if next_track:
                    self.log.info('Getting backup track: %s - %s' % (next_track['artist'], next_track['name']))
            return next_track
        except:
            self.log.error('Error getting next track from queues', exc_info=True)
            return {}

    async def pop_user_track(self):
        try:
            if self.user_playlist:
                next_track=self.user_playlist.pop(0)
                self.app.saveJSON('user_playlist', self.user_playlist)
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
                self.app.saveJSON('backup_playlist', self.backup_playlist)
                return next_track
            else:
                return {}
        except:
            self.log.error('Error getting track from backup playlist', exc_info=True)
            return {}


    async def promote_backup_track(self, song_id, super_promote=False):
        try:
            newlist=[]
            promoted_track=None
            promoted_count=0
            for song in self.backup_playlist:
                if song['id']==song_id:
                    promoted_track=song
                else:
                    if 'promoted' in song and song['promoted']==True:
                        promoted_count+=1
                    newlist.append(song)
            if promoted_track:
                if super_promote:
                    result=await self.add_track(promoted_track['id'])
                else:  
                    promoted_track['promoted']=True
                    if promoted_count==0:
                        newlist.insert(0,promoted_track)
                    else:
                        newlist.insert(promoted_count, promoted_track)
            self.backup_playlist=newlist
            self.app.saveJSON('backup_playlist', self.backup_playlist)   
            await self.update_list('update')
            return {"promoted":song_id}
        except:
            self.log.error('Error adding song %s' % song_id, exc_info=True)
            return []



    async def next_track(self):
        try:
            next_track=await self.get_next_track()
            if next_track:
                self.active=True
                await self.play_id(next_track['id'])
                await self.update_now_playing()
                await self.update_list('pop')
            else:
                self.log.info('No more tracks to play')
                self.active=False
        except:
            self.log.error('Error trying to play', exc_info=True)
            self.active=False

    async def play_id(self, id):
        try:
            await self.spotify.playback_start_tracks([id])
            self.active=True
        except:
            self.log.error('Error trying to play id %s' % id, exc_info=True)
            self.active=False


    async def start_status(self):
        self.log.info('.. Starting status loop')
        track=await self.spotify.playback_currently_playing()
        track_data=await self.get_track_data(track)
        self.log.info('.. currently playing: %s - %s' % (track_data['artist'], track_data['name']))
        self.active=True
        #self.task = self.loop.create_task(self.poll_status())

    def stop(self):
        self.task.cancel()
        

    async def check_status(self):
        try:
            track=await self.spotify.playback_currently_playing()
            if not track:
                self.log.info('.. no track currently active')
                self.active=False
            else:
                track_data=await self.get_track_data(track)
                if track_data and track.progress_ms==0 and not self.user_pause:
                    self.log.info('.. track ended: %s - %s' % (track_data['artist'], track_data['name']))
                    self.active=False
                    await self.next_track()
        except:        
            self.log.error('!! error checking track', exc_info=True)


    async def poll_status(self):
        
        while self.running:
            try:
                if self.active:
                    pass
                    # TODO/CHEESE - this is only needed if we are not using the event tracker from librespot
                    #await self.check_status()
                await asyncio.sleep(1)
            except GeneratorExit:
                #self.log.error('!! Generator Exit')
                self.running=False
                self.active=False
            except requests.exceptions.HTTPError:
                self.log.error('!! Token may have expired. (http error)')
                        #self.token=self.credentials.refresh(self.token)
            except:
                self.log.error('.. error while polling - delaying 5 seconds', exc_info=True)
                await asyncio.sleep(5)


 
