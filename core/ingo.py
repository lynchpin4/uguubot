import re
import socket
import time
import thread
import Queue
import inspect
import json
import os
import string

import itertools
from time import sleep
from StringIO import StringIO
from ws4py.client.threadedclient import WebSocketClient
from ssl import wrap_socket, CERT_NONE, CERT_REQUIRED, SSLError

from HTMLParser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        self.reset()
        self.fed = []
    def handle_data(self, d):
        self.fed.append(d)
    def get_data(self):
        return ''.join(self.fed)

def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()

aimblast_rem = re.compile(r'[(.*?)] (.*?)').match
aimblast_message_rem = re.compile(r'\((.*?)\) (.*?)').match

class IngoClient(WebSocketClient):
    def opened(self):
        self.send(json.dumps({"hello": "world"}))
        print "Opened and sent warm hello packet"
        self.send(json.dumps({"cmd": "login", "username": self.parent.screenname, "password": self.parent.password }))
        print "Sent login"
    def send_message(self, to, msg):
        self.send(json.dumps({ "c": "msg", "chat": to, "msg": msg }))
    def closed(self, code, reason=None):
        print "Ingo socket closed.", code, reason
        sleep(4)
        self.parent.connect()
    def got_json(self, msg):
        msg = msg.strip()
        if len(msg) < 5:
            return

        io = StringIO(msg)
        obj = json.load(io)
        #print obj

        #if obj.get('code'):
        #    status = obj["status"]
        #    if 'connected' in status:
        #        status = status.split(':')
        #        print('connected '+status[0]+' on '+status[1])
        #if obj.get('buddy'):
        #    print 'buddy status: '+obj['buddy']+' status: '+str(obj['status'])
        #    if obj.get('status_type'):
        #        print 'type: '+obj['status_type']
        if obj.get('chat') and obj.get('sender'):
            message = strip_tags(obj['msg'])
            sender = obj['chat'].lower()
            time = obj['time']

            print '-----NEW MSG!'
            print message

            params = [message]

            if sender.startswith("["):
                # aim blast
                print 'aim blast'
                #sender = aimblast_rem(sender).groups()[0]
                name_part = str(aimblast_message_rem(message).groups()[0])
                message = message.split(name_part+") ")[1]
            print 'Message from: '+sender
            print message

            fake_irc = sender+'!~'+sender+'@aim.com PRIVMSG #'+sender+' '+message
            params = [fake_irc, sender+'!~'+sender+'@aim.com', 'PRIVMSG', '#'+sender+' '+message, sender, sender, 'aim.com', sender+'!~'+sender+'@aim.com', [sender, message], message]

            self.parent.out.put(params)
            print params
            print 'END OF MSG----------'

    def received_message(self, m):
        # print m
        m = str(m)
        msgs = m.split('\n')
        for msg in msgs:
            self.got_json(msg)

    def keep_going(self):
        print 'running forever'
        #self.run_forever()
        print 'done?'

class INGO(object):
    "handles the ingo remote purple protocol"
    def __init__(self, name, server, port, screenname, password, channels, conf):
        self.name = name
        self.channels = channels
        self.conf = conf
        self.server = server
        self.port = port
        self.screenname = screenname
        self.password = password
        self.nick = screenname
        self.user = screenname

        self.out = Queue.Queue()  # responses from the server are placed here
        # format: [rawline, prefix, command, params,
        # nick, user, host, paramlist, msg]
        self.connect()

        #thread.start_new_thread(self.parse_loop, ())

    def create_connection(self):
        ws_url = 'ws://'+self.server+':'+str(self.port)+'/'
        print 'Connecting to: '+ws_url
        self.connection = IngoClient(ws_url, protocols=['http-only', 'chat'])
        #self.connection.daemon = True
        self.connection.parent = self
        self.connection.connect()
        self.connection.keep_going()

    def connect(self):
        self.conn = self.create_connection()

        #thread.start_new_thread(self.connection.run_forever, ())
        #self.set_pass(self.conf.get('server_password'))
        #self.set_nick(self.nick)
        #self.cmd("USER",
        #    [conf.get('user', 'uguubot'), "3", "*", conf.get('realname',
        #        'UguuBot - http://github.com/infinitylabs/UguuBot')])

    def parse_loop(self):
        while True:
            # get a message from the input queue
            msg = self.conn.iqueue.get()

            if msg == StopIteration:
                self.connect()
                continue

            # parse the message
            if msg.startswith(":"):  # has a prefix
                prefix, command, params = irc_prefix_rem(msg).groups()
            else:
                prefix, command, params = irc_noprefix_rem(msg).groups()
            nick, user, host = irc_netmask_rem(prefix).groups()
            mask = user + "@" + host
            paramlist = irc_param_ref(params)
            lastparam = ""
            if paramlist:
                if paramlist[-1].startswith(':'):
                    paramlist[-1] = paramlist[-1][1:]
                lastparam = paramlist[-1]
            # put the parsed message in the response queue


            self.out.put([msg, prefix, command, params, nick, user, host,
                    mask, paramlist, lastparam])
            # if the server pings us, pong them back
            if command == "PING":
                self.cmd("PONG", paramlist)

    def set_pass(self, password):
        print 'Set pass: '+password

    def set_nick(self, nick):
        print 'Set nick: '+nick

    def join(self, channel):
        """ makes the bot join a channel """
        print 'Join: '+channel
        self.channels.append(channel)

    def part(self, channel):
        """ makes the bot leave a channel """
        print 'Part: '+channel

    def msg(self, target, text):
        """ makes the bot send a message to a user """
        print 'To: '+target+' Content: '+text

        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')

        if 'ACTION' in text:
            text = text.replace('ACTION', '')
            text = '<i>'+text+'</i>'

        self.connection.send_message(target, text.strip())

    def ctcp(self, target, ctcp_type, text):
        """ makes the bot send a PRIVMSG CTCP to a target """
        out = u"\x01{} {}\x01".format(ctcp_type, text)
        self.cmd("PRIVMSG", [target, out])

    def cmd(self, command, params=None):
        msg = ""
        if params:
            params[-1] = ':' + params[-1]
            msg = command + ' ' + ' '.join(map(censor, params))
            print("cmd:"+command + ' ' + ' '.join(map(censor, params)))
        else:
            msg = command
            print("dndt work cmd:"+command)

        if 'NOTICE' in msg:
            omsg = msg
            msg = msg.split(' ')
            self.msg(msg[1], omsg.split(' :')[1])

    def send(self, str):
        self.conn.oqueue.put(str)
