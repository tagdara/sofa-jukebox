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
#import datetime
import os
import socket
import sys
from os.path import isfile, isdir, join
import subprocess

import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
import uuid
import random


class web_server():
    
    def __init__(self, config, loop, log=None, app=None):
        self.config=config
        self.loop = loop
        self.log=log
        self.app=app
    
    def initialize(self):
            
        try:
            self.subscribers= set()
            self.info = {}
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
            self.cors.add(self.serverApp.router.add_get('/play', self.play_handler))
            self.cors.add(self.serverApp.router.add_get('/next', self.next_handler))
            self.cors.add(self.serverApp.router.add_get('/pause', self.pause_handler))
            self.cors.add(self.serverApp.router.add_get('/devices', self.devices_handler))
            self.cors.add(self.serverApp.router.add_get('/set_device/{device}', self.setdevice_handler))
            self.cors.add(self.serverApp.router.add_get('/setbackup/{playlist}', self.setbackup_handler))
            self.cors.add(self.serverApp.router.add_get('/user', self.user_handler))
            self.cors.add(self.serverApp.router.add_get('/queue', self.queue_handler))
            self.cors.add(self.serverApp.router.add_get('/backup/shuffle', self.shuffle_backup_handler))
            self.cors.add(self.serverApp.router.add_get('/search/{search}', self.search_handler))
            self.cors.add(self.serverApp.router.add_get('/add/{id}', self.add_handler))
            self.cors.add(self.serverApp.router.add_get('/addtoplaylist/{id}/{playlistid}', self.add_to_playlist_handler))
            self.cors.add(self.serverApp.router.add_get('/nowplaying', self.nowplaying_handler))
            self.cors.add(self.serverApp.router.add_get('/del/{id}', self.del_handler))
            self.cors.add(self.serverApp.router.add_get('/promote/{id}', self.promote_handler))
            self.cors.add(self.serverApp.router.add_get('/superpromote/{id}', self.super_promote_handler))
            self.cors.add(self.serverApp.router.add_get('/display/{cmd:.+}', self.display_passthrough_handler))
            self.cors.add(self.serverApp.router.add_post('/event', self.event_handler))
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
            
    def shutdown(self):
        self.loop.run_until_complete(self.serverApp.shutdown())

    def authenticate(func):
        def wrapper(self):
            try:
                return func(self)
            except AuthorizationNeeded:
                self.goback=request.raw_path
                raise web.HTTPTemporaryRedirect('/auth')        
        return wrapper

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

    # Handlers for api URL's

    async def root_handler(self, request):
        try:
            self.log.info('.. new application load from %s' % request.remote)
            return web.FileResponse(os.path.join(self.config['client_build_directory'],'index.html'))
        except:
            self.log.error('!! Error serving base application to %s' % request.remote, exc_info=True)

    async def user_handler(self, request):
        try:
            return web.json_response(await self.app.spotify.get_user())
        except requests.exceptions.HTTPError:
            return web.json_response({})


    # Spotify authentication
    
    async def auth_handler(self, request):
        raise web.HTTPTemporaryRedirect(self.app.spotify.auth_url)
        
    async def redirect_handler(self, request):
        try:
            vals=self.get_query_string_variables(request.query_string)
            if 'code' in vals:
                code=vals['code']
                result=await self.app.spotify.set_token(code)
        except:
            self.log.error('.. Error handling Spotify redirect callback after manual authentication', exc_info=True)
        raise web.HTTPTemporaryRedirect('/')

    # Librespot on-event handler for shim 
    
    async def event_handler(self, request):
        
        try:
            if request.body_exists:
                try:
                    body=await request.read()
                    body=body.decode()
                    self.log.info('.. librespot onevent: %s' % body)
                    await self.app.spotify.check_status()
                except:
                    self.log.info('error onevent request', exc_info=True)
                    
            return web.json_response({"data":"thanks"})
        
        except:
            self.log.info('error handling list post', exc_info=True)

        return web.json_response({"data":"failed"})
       
        
    # Backup playlist lists and management
    
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

    async def playlists_handler(self, request):
        try:
            display_list=await self.app.spotify.get_user_playlists()
            return web.json_response(display_list)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.info('error getting user playlists', exc_info=True)
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

    async def shuffle_backup_handler(self, request):
        
        try:
            return web.json_response(await self.app.spotify.shuffle_backup())
        except:
            self.log.info('error shuffling backup list', exc_info=True)
        return web.json_response([])
        
    # Handlers for listing and changing Spotify Connect devices

    async def devices_handler(self, request):
        try:
            display_list=await self.app.spotify.get_playback_devices()
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
            display_list=await self.app.spotify.get_playback_devices()
            self.log.info('Trying to set device to %s from %s' % (name, display_list))
            result=await self.app.spotify.set_playback_device(name)
            return web.json_response(result)
        except requests.exceptions.HTTPError:
            self.goback=request.raw_path
            raise web.HTTPTemporaryRedirect('/auth')
        except:
            self.log.info('error setting device', exc_info=True)
            result=False
        return web.Response(text="Device set to %s: %s" % (name, result))

    # Now playing track commands

    async def nowplaying_handler(self, request):
        try:
            return web.json_response(await self.app.spotify.update_now_playing())
        except:
            self.log.error('Error with nowplaying', exc_info=True)
            return web.json_response({})

    async def pause_handler(self, request):
        try:
            result=await self.app.spotify.pause()
            return web.json_response(await self.app.spotify.update_now_playing())
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    async def play_handler(self, request):
        try:
            result=await self.app.spotify.play()
            return web.json_response(await self.app.spotify.update_now_playing())
        except:
            self.log.error('Error sending play command',exc_info=True)
            return web.Response(text='error')

    async def next_handler(self, request):
        try:
            result=await self.app.spotify.next_track()
            return web.json_response(await self.app.spotify.update_now_playing())
        except:
            self.log.error('Error sending play command',exc_info=True)
            return web.Response(text='error')
            
    # Track searching

    async def search_handler(self, request):
        try:
            search=request.match_info['search']
            return web.json_response(await self.app.spotify.search(search))
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    # User queue management

    async def queue_handler(self, request):
        return web.json_response(await self.app.spotify.get_queue())

    async def add_handler(self, request):
        try:
            song_id=request.match_info['id']
            await self.app.spotify.add_track(song_id)
            
            return web.json_response(await self.app.spotify.get_queue())
        except:
            self.log.info('error getting favorites', exc_info=True)
            return web.json_response([])

    async def add_to_playlist_handler(self, request):
        try:
            song_id=request.match_info['id']
            playlist_id=request.match_info['playlistid']
            await self.app.spotify.add_track_to_playlist(song_id, playlist_id)
            return web.json_response(await self.app.spotify.get_queue())
        except:
            self.log.info('error adding to playlist', exc_info=True)
            return web.json_response([])

    async def del_handler(self, request):
        try:
            song_id=request.match_info['id']
            await self.app.spotify.del_track(song_id)
            return web.json_response(await self.app.spotify.get_queue())
        except:
            self.log.info('error removing track', exc_info=True)
            return web.json_response([])
            
    # Backup queue management

    async def super_promote_handler(self, request):
        try:
            song_id=request.match_info['id']
            await self.app.spotify.promote_backup_track(song_id, super_promote=True)
            return web.json_response(await self.app.spotify.get_queue())
        except:
            self.log.info('error super promoting track', exc_info=True)
            return web.json_response([])

    async def promote_handler(self, request):
        try:
            song_id=request.match_info['id']
            await self.app.spotify.promote_backup_track(song_id, super_promote=False)
            return web.json_response(await self.app.spotify.get_queue())
        except:
            self.log.info('error promoting track', exc_info=True)
            return web.json_response([])

    # webdisplay passthrough
    
    async def display_passthrough_handler(self, request):
        try:
            self.log.info('matchinfo: %s %s' % (request.match_info['cmd'], self.config))
            if 'webdisplay_url' in self.config:
                try:
                    async with aiohttp.ClientSession() as session:
                        self.log.info('Sending to %s' % (self.config['webdisplay_url']+"/"+request.match_info['cmd']) )
                        await session.get(self.config['webdisplay_url']+"/"+request.match_info['cmd']) 
                except:
                    self.log.error('Error sending cmd to webdisplay', exc_info=True)
            
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            
        return web.json_response([])

    # SSE Data delivery and subscription
    
    async def send_update_to_subscribers(self, data):
        try:
            payload = json.dumps(data)
            for q in self.subscribers:
                await q.put(payload)      
        except:
            self.log.error('Error updating now playing subscribers', exc_info=True)
            return []           
            
    async def sse_handler(self, request):
        try:
            queue = asyncio.Queue()
            self.log.info('.. new remote user subscription from %s' % request.remote)
            last_heartbeat=datetime.now(timezone.utc)
            async with sse_response(request) as response:
                self.subscribers.add(queue)
                await self.app.spotify.update_now_playing()
                try:
                    while True:
                    #while not response.task.done():
                        try:
                            payload = queue.get_nowait()
                        except asyncio.queues.QueueEmpty:
                            payload=None
                        #payload = await queue.get()
                        if payload:
                            await response.send(payload)
                            last_heartbeat=datetime.now(timezone.utc)
                            queue.task_done()
                            
                        if last_heartbeat < datetime.now(timezone.utc) - timedelta(seconds=60):
                            last_heartbeat=datetime.now(timezone.utc)
                            #self.log.info('.. sending heartbeat to %s' % request.remote)
                            await response.send(json.dumps({"event": "Heartbeat"}))
                        await asyncio.sleep(.1)
                except GeneratorExit:
                    self.log.info("-- SSE connection cancelled / Generator exit")
                except concurrent.futures._base.CancelledError:
                    self.log.info('-- SSE connection cancelled for %s' % request.remote)
                except:
                    self.log.error('.. error in sse handling', exc_info=True)
                finally:
                    self.subscribers.remove(queue)
                    self.log.info('.. user disconnected from %s' % request.remote)
            return response
        except concurrent.futures._base.CancelledError:
            self.log.info('-- SSE closed for %s' % request.remote)
            #del self.active_sessions[sessionid]
            return resp
        except:
            self.log.error('Error in SSE loop', exc_info=True)
            #del self.active_sessions[sessionid]
            return resp

