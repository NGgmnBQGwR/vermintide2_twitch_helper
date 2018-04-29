import os
import sys
import time
import socket
import ctypes
import queue
import threading
from ctypes import wintypes

import win32con

try:
    from secret import TWITCH_TOKEN, TWITCH_USERNAME, TWITCH_CHANNEL
except ImportError:
    print('No twitch OAuth token provided.')
    sys.exit(1)

TWITCH_SERVER = 'irc.chat.twitch.tv'
TWITCH_IRC_PORT = 6667
TWITCH_PING_CHECK_INTERVAL = 10

PING_MESSAGE = "PING :tmi.twitch.tv"
PONG_MESSAGE = "PONG :tmi.twitch.tv"


class TwitchThread(threading.Thread):
    def __init__(self, event_queue: queue.Queue):
        super(TwitchThread, self).__init__()
        self.event_queue: queue.Queue = event_queue
        self.stop_request = threading.Event()
        self.irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.last_ping_check = time.time()
        self.connect()

    def send(self, command):
        if not command.endswith('\n'):
            command += '\n'
        if type(command) is str:
            command = command.encode('utf-8')
        bytes = self.irc.send(command)
        print("Sent {} ({} bytes). Reply={}".format(command, bytes, self.get_reply()))

    def send_message(self, message):
        self.send("PRIVMSG {} :{}".format(TWITCH_CHANNEL, message))

    def get_reply(self):
        try:
            reply = self.irc.recv(2040)
        except BlockingIOError:
            return b''

        try:
            return reply.decode('utf-8')
        except UnicodeDecodeError:
            return reply

    def connect(self):
        self.irc.connect((TWITCH_SERVER, TWITCH_IRC_PORT))
        self.irc.setblocking(False)
        self.send("PASS {}".format(TWITCH_TOKEN))
        self.send("NICK {}".format(TWITCH_USERNAME))
        self.send("JOIN {}".format(TWITCH_CHANNEL))

    def reply_to_ping(self):
        print('Checking ping')
        self.last_ping_check = time.time()
        reply = self.get_reply()
        if reply and reply.find(PING_MESSAGE) != -1:
            self.send(PONG_MESSAGE)

    def run(self):
        while not self.stop_request.isSet():
            time.sleep(0.5)

            if time.time() - self.last_ping_check > TWITCH_PING_CHECK_INTERVAL:
                self.reply_to_ping()

            try:
                event = self.event_queue.get(block=False)
            except queue.Empty:
                continue

            print("Got event {}".format(event))
            self.send_message(event)

    def join(self, timeout=None):
        self.send("PART {}".format(TWITCH_CHANNEL))
        self.send_message("/disconnect")
        self.stop_request.set()
        super(TwitchThread, self).join(timeout)


class HotkeyHelper(object):
    def __init__(self, queue: queue.Queue):
        self.queue: queue.Queue = queue
        self.vote_a = '#a'
        self.vote_b = '#b'
        self.vote_c = '#c'
        self.vote_d = '#d'
        self.vote_e = '#e'

    def handle_numpad1(self):
        self.queue.put(self.vote_a)

    def handle_numpad2(self):
        self.queue.put(self.vote_b)

    def handle_numpad3(self):
        self.queue.put(self.vote_c)

    def handle_numpad4(self):
        self.queue.put(self.vote_d)

    def handle_numpad5(self):
        self.queue.put(self.vote_e)

    def do_quit(self):
        ctypes.windll.user32.PostQuitMessage(0)


def start_main_loop(queue: queue.Queue):
    twitch = TwitchThread(event_queue=queue)
    twitch.start()

    HOTKEYS = {
        1: (win32con.VK_NUMPAD1, None),
        2: (win32con.VK_NUMPAD2, None),
        3: (win32con.VK_NUMPAD3, None),
        4: (win32con.VK_NUMPAD4, None),
        5: (win32con.VK_NUMPAD5, None),
        32: (win32con.VK_NUMPAD0, win32con.MOD_WIN),
    }
    helper: HotkeyHelper = HotkeyHelper(queue)
    HOTKEY_ACTIONS = {
        1: helper.handle_numpad1,
        2: helper.handle_numpad2,
        3: helper.handle_numpad3,
        4: helper.handle_numpad4,
        5: helper.handle_numpad5,
        32: helper.do_quit,
    }

    # RegisterHotKey takes:
    #  -Window handle for WM_HOTKEY messages (None = this thread)
    #  -arbitrary id unique within the thread
    #  -modifiers (MOD_SHIFT, MOD_ALT, MOD_CONTROL, MOD_WIN)
    #  -VK code (either ord ('x') or one of win32con.VK_*)
    for key_id, (vk, modifiers) in HOTKEYS.items():
        print("Registering id {} for key {}".format(key_id, vk))
        if not ctypes.windll.user32.RegisterHotKey(None, key_id, modifiers, vk):
            print("Unable to register id {}".format(key_id))

    # Home-grown Windows message loop: does just enough to handle the WM_HOTKEY messages and pass everything else along.
    try:
        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageA(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == win32con.WM_HOTKEY:
                action_to_take = HOTKEY_ACTIONS.get(msg.wParam)
                if action_to_take:
                    action_to_take()
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageA(ctypes.byref(msg))
    finally:
        for id in HOTKEYS.keys():
            ctypes.windll.user32.UnregisterHotKey(None, id)
        twitch.join()


def main():
    event_queue: queue.Queue = queue.Queue()
    start_main_loop(event_queue)


if __name__ == "__main__":
    main()
