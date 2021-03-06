#!/usr/bin/env python
# @Author: Paul Joannon <paulloz>
# @Date:   2016-02-15T11:51:42+01:00
# @Email:  hello@pauljoannon.com
# @Last modified by:   paulloz
# @Last modified time: 2016-03-17T10:52:05+01:00
# -*- coding: utf-8 -*-

from __future__ import print_function  # In case we're running with python2

import sys
import os
import time
import json
import argparse
import subprocess
import requests
import pystache
import tweepy
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

twitter_api = None


def getTweet(url):
    global twitter_api


def canBuildLess(f):
    try:
        subprocess.Popen(['lessc', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print('Il semblerait qu\'il soit impossible de compiler le style, \
               demande à ce cher Paulloz de le faire pour toi.', file=sys.stderr)
        return lambda: None
    return f


@canBuildLess
def buildLessFiles():
    p = subprocess.Popen(['lessc', 'less/main.less', '--include-path=less/'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode > 0:
        print(stderr.decode('utf-8'), file=sys.stderr)
    else:
        print("Built style.css")
        with open('dist/style.css', mode='w') as f:
            if isinstance(stdout, str):
                f.write(stdout)
            else:
                f.write(stdout.decode('utf-8'))


class Sheet():
    def __init__(self, key):
        self.__endpoint = 'https://spreadsheets.google.com'
        self.__key = key

        self.__twitter_api = None
        self.__instagram_api = dict(endpoint='https://api.instagram.com/publicapi/oembed/?url=')
        self.__vine_api = dict(endpoint='https://vine.co/oembed.json?url=')

        self.__data = list()

        self._initData(key)

    def _initData(self, key):
        try:
            path = '/feeds/worksheets/{key}/public/basic?alt=json'.format(key=key)
            for entry in self._requestData(path)['feed']['entry']:
                path = '/feeds/list/{key}/{sheetId}/public/values?alt=json'.format(
                    key=key,
                    sheetId=entry['link'][len(entry['link']) - 1]['href'].split('/').pop()
                )

                self._setData([
                    {key[4:]: value['$t']
                        for key, value in entry.items()
                        if key[:4] == 'gsx$'}
                    for entry in self._requestData(path)['feed']['entry']])

        except requests.exceptions.RequestException as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def _requestData(self, path):
        r = requests.get(self.__endpoint + path)
        if r.status_code == 200:
            return r.json()
        raise requests.exceptions.RequestException("Seems we can't find {0}".format(self.__key))

    def _setData(self, data, formated=False):
        if formated:
            self.__data = data
        else:
            self.__data = self.__formatData(data)

    def __formatTweet(self, url):
        if self.__twitter_api is None:
            with open('.twitter.json', 'r') as f:
                self.__twitter_api = json.loads(f.read())
        api = tweepy.API(
            tweepy.AppAuthHandler(self.__twitter_api['api_key'], self.__twitter_api['api_secret'])
        )
        tweet = api.get_status(url.split('/')[-1])
        return dict(tweet=dict(
            id=tweet.id,
            fromname=tweet.author.name,
            fromscreenname=tweet.author.screen_name,
            text=tweet.text,
            date=tweet.created_at.strftime('%d/%m/%Y, %H:%M'),
            picture=tweet.author.profile_image_url
        ))

    def __formatInstagram(self, url):
        media = requests.get('{0}{1}'.format(self.__instagram_api['endpoint'], url))
        if media.status_code == 200:
            media = media.json()
            return dict(instagram=dict(
                url=url,
                html=media['html'],
                fromname=media['author_name']
            ))
        return None

    def __formatVine(self, url):
        vine = requests.get('{0}{1}'.format(self.__vine_api['endpoint'], url))
        if vine.status_code == 200:
            vine = vine.json()
            return dict(vine=dict(
                url=url,
                html=vine['html'],
                fromname=vine['author_name']
            ))
        return None

    def __formatData(self, data):
        def getOrFalse(d, k):
            return len(d[k]) > 0 and dict(value=d[k].encode('utf-8')) or False

        def addNBSPs(s):
            for char in ['?', ':', '!']:
                s = s.replace(' {0}'.format(char), '&nbsp;{0}'.format(char))
            return s

        _data = dict(items=[])
        for i, d in enumerate(data):
            if d['type'] in ['titre', 'sous-titre', 'chapo']:
                _data[d['type']] = addNBSPs(d['texteext.']).encode('utf-8')
            elif d['type'] in ['lire-aussi']:
                _data[d['type']] = dict(
                    textext=addNBSPs(d['texteext.']).encode('utf-8'),
                    textint=addNBSPs(d['texteint.']).encode('utf-8')
                )
            elif d['type'] in ['tweet']:
                _data['items'].append(self.__formatTweet(d['texteext.']))
            elif d['type'] in ['instagram']:
                _data['items'].append(self.__formatInstagram(d['texteext.']))
            elif d['type'] in ['vine']:
                _data['items'].append(self.__formatVine(d['texteext.']))
            else:
                _d = dict()
                _d[d['type']] = dict(
                    textext=addNBSPs(d['texteext.']).encode('utf-8'),
                    textint=addNBSPs(d['texteint.']).encode('utf-8'),
                    image=d['image'].encode('utf-8'),
                    id=str(i)
                )
                _data['items'].append(_d)
        return _data

    def getData(self):
        return self.__data


class LocalSheet(Sheet):
    def _initData(self, key):
        try:
            self._setData(self._requestData(key))
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def _requestData(self, path):
        with open(path, 'r') as file:
            return json.loads(file.read())


def watchFiles(sheet_id):
    class EventHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            print("{0} has been modified".format(event.src_path))
            directory = os.path.split(os.path.split(event.src_path)[0])[1]
            if directory == 'templates':
                buildIndex(sheet_id)
            elif directory == 'less':
                buildLessFiles()

    handler = EventHandler()

    observer = Observer()
    observer.schedule(handler, 'less/', recursive=True)
    observer.schedule(handler, 'templates/', recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def buildIndex(sheet_id):
    with open('dist/index.html', 'w') as index:
        with open('templates/base.mustache', 'r') as template:
            sheet = LocalSheet(sheet_id) if os.path.isfile(sheet_id) else Sheet(sheet_id)
            index.write(pystache.render(template.read(), sheet.getData()))
    print("Built index.html")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['watch', 'build'], default='build', nargs='?')
    parser.add_argument('sheet-id')
    args = parser.parse_args()

    if args.action == 'watch':
        buildLessFiles()
        buildIndex(vars(args)['sheet-id'])
        watchFiles(vars(args)['sheet-id'])
    elif args.action == 'build':
        buildLessFiles()
        buildIndex(vars(args)['sheet-id'])
