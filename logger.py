#!/usr/bin/env python3
__requires__ = [
    'click   ~= 6.5',
    'Twisted ~= 18.4',
]
__version__ = '1.12'
from   collections  import defaultdict
import os
import os.path
import platform
import sys
import re
import time
from   urllib.parse import quote
import click
from   twisted.internet            import reactor
from   twisted.internet.endpoints  import HostnameEndpoint, connectProtocol
from   twisted.protocols.basic     import LineOnlyReceiver

# Default values:
SERVER    = 'irc.freenode.net'
PORT      = 6667
ENCODING  = 'utf-8'
CHANS     = ('#nethack', '#lojban', '#jbosnu', '#ckule')
PASS      = 'testing'
NICKS     = ('logger_py', 'IRCLogBot')
USER      = 'lurker'
REAL      = 'Joey Lurkenstein'
LONGMODE  = 0b10000111  # JOIN, PART, QUIT, MODE
CNTRLPASS = None

SKIP = {
    '251', '252', '253', '254', '255', '265', '266', '250', '375', '372', '376'
}
BADJOIN = {'403', '405', '407', '437', '471', '473', '474', '475', '476'}
# Note that 437 can also be returned for NICK failure.  Some of the other
# BADJOIN codes have multiple meanings as well, but those should not apply
# during the script's normal operation.

CMD_MASKS = {
    "JOIN":      1,
    "PART":      2,
    "QUIT":      4,
    "NICK":      8,
    "PRIVMSG":  16,
    "TOPIC":    32,
    "KICK":     64,
    "MODE":    128,
}

def sanitize(s, trailing=False):
    s = s.translate({0: ' ', 10: ' ', 13: ' '})
    if not trailing:
        s = s.replace(' ', '_')
        if s.startswith(":"):
            s = s[1:]
    return s

@click.command()
@click.option('-s', '--server', default=SERVER)
@click.option('-p', '--password', default=PASS, type=lambda p: sanitize(p,True))
@click.option(
    '-u', '--user', '--username', 'username',
    default = USER,
    type    = lambda u: sanitize(u, True).replace('@', '_'),
)
@click.option('-n', '--nicks', '--nicknames', 'nicknames')
@click.option('-M', '--meta', type=click.File('a'), default=sys.stderr)
@click.option('-r', '--realname', default=REAL, type=lambda r: sanitize(r,True))
@click.option('-P', '--cntrlpass', type=sanitize, default=CNTRLPASS)
@click.option('-L', '--longmode', type=int, default=LONGMODE)
@click.option('-m', '--modestring')
@click.option('-d', '--directory', default=os.curdir)
@click.argument('channels', nargs=-1)
def main(server, username, password, realname, nicknames, longmode, cntrlpass,
         directory, channels, modestring, meta):

    m = re.search(r':(\d+)$', server)
    if m:
        server = server[:m.start()]
        port = int(m.group(1))
    else:
        port = PORT

    if nicknames is not None:
        ### TODO: Filter out empty nicks and deal with illegal characters!
        nicks = tuple(map(sanitize, re.split(r'[\s,]+', nicknames)))
    else:
        nicks = NICKS

    if channels:
        chanList = [
            sanitize(cs) for c in channels for cs in re.split(r'[\s,]+', c)
        ]
    else:
        chanList = CHANS

    connectProtocol(
        HostnameEndpoint(reactor, server, port),
        IRCLogger(
            server     = server,
            port       = port,
            username   = username,
            password   = password,
            nicks      = nicks,
            realname   = realname,
            modestring = modestring,
            chanList   = chanList,
            longmode   = longmode,
            cntrlpass  = cntrlpass,
            directory  = directory,
            meta       = meta,
        ),
    )
    reactor.run()


class IRCLogger(LineOnlyReceiver):
    def __init__(self, server, port, username, password, nicks, realname,
                 modestring, chanList, longmode, cntrlpass, directory, meta):
        super().__init__()
        self.nickiter = iter(nicks)
        self.nickname = None
        self.password = password
        self.username = username
        self.realname = realname
        self.modestring = modestring
        self.chanList = chanList
        self.longmode = longmode
        self.cntrlpass = cntrlpass
        self.directory = directory
        self.meta = meta
        self.chanlogfiles = {}
        self.nicks = defaultdict(list)
        self.nickBuf = {}
        self.last = None
        self.current_ts = None
        self.metalog('-' * 40)
        self.metalog('# Starting up.')
        self.metalog("# Version: ", __version__)
        self.metalog("# Server: {}:{}".format(server, port))
        self.metalog("# Server password: ", self.password)
        self.metalog("# Nicknames: ", ' '.join(nicks))
        self.metalog("# Username: ", username)
        self.metalog("# Realname: ", realname)
        self.metalog("# Channels: ", ' '.join(chanList))
        self.metalog("# longmode: ", longmode)
        self.metalog('# Control password: ', 'yes' if cntrlpass else 'no')
        self.metalog("# Log name prefix: ", directory)

    def connectionMade(self):
        self.metalog("# Connected to server")
        self.sendLine('PASS :{}'.format(self.password))
        self.sendLine('USER {} * * :{}'.format(self.username, self.realname))
        self.try_next_nick()

    def connectionLost(self, reason=None):
        self.metalog('# Connection closed')

    def try_next_nick(self):
        try:
            self.current_nick = next(self.nickiter)
        except StopIteration:
            self.metalog("# Could not log in: all nicknames rejected")
            sys.exit("Could not log in: all nicknames rejected")
        self.sendLine('NICK ' + self.current_nick)

    def sendLine(self, line):
        super().sendLine(line.encode(ENCODING))

    def lineReceived(self, line):
        line = line.decode(ENCODING)
        self.last = self.current_ts
        self.current_ts = now()

        if self.nickname is None:
            if re.match(r'^:[^ ]+ +NOTICE\b', line, flags=re.I):
                self.metalog(line)
            elif re.match(r'^:[^ ]+ +00\d\b', line):
                self.nickname = self.current_nick
                self.metalog("# Logged in with nickname ", self.nickname)
                self.metalog(line)
                if self.modestring is not None:
                    modes = [
                        re.sub(r'^:', '', s)
                        for s in re.split(
                            r'\s+|(?=[-+])',
                            sanitize(self.modestring, True),
                        )
                    ]
                    while modes and modes[0] == '':
                        modes.pop(0)
                    if modes:
                        self.sendLine('MODE {} {}'
                                      .format(self.nickname, ' '.join(modes)))
                        self.metalog("# Setting user MODE to: ", ' '.join(modes))
                self.start = now()
                for c in self.chanList:
                    self.joinChan(c)
            elif re.match(r'^:[^ ]+ +[45]\d\d\b', line):
                self.metalog(line)
                self.try_next_nick()
            else:
                self.metalog("UNKNOWN\t" + line)
            return

        if re.match(r'^PING\s+', line, flags=re.I):
            self.sendLine('PONG' + line[4:])
            return

        m = re.fullmatch(r'^(?:[:]([^ ]+)[ ]+)?([^ ]+)(?:[ ]+(.*))?$', line)
        if not m:
            self.metalog('UNKNOWN\t' + line)
            return
        sender, cmd, shargs = m.groups()
        cmd = cmd.upper()
        if cmd in CMD_MASKS:
            m = re.fullmatch(r'^([^!]+)!(.+)$', sender)
            if m:
                if self.longmode & CMD_MASKS[cmd]:
                    nick = m.group(1)
                    longnick = "{} ({})".format(*m.groups())
                else:
                    nick = longnick = m.group(1)
            else:
                nick = longnick = sender
        else:
            nick = longnick = sender
        args = ircArgs(shargs)

        if cmd in SKIP:
            pass
        elif cmd in BADJOIN and len(args) >= 2:
            to, chan, *about = args
            self.chanlog(
                chan,
                "ERROR: COULD NOT JOIN",
                ' '.join((':',) + about) if about else '',
            )
            self.chanlogfiles[chan].close()
            del self.chanlogfiles[chan]
        elif cmd in ('NOTICE', 'ERROR') or cmd.startswith(('0', '4', '5')):
            self.metalog(line)
        elif cmd == '331' and len(args) >= 2:
            self.chanlog(args[1], "NO TOPIC")
        elif cmd == '332' and len(args) == 3:
            self.chanlog(args[1], "TOPIC: {}".format(args[2]))
        elif cmd == '353' and len(args) == 4:
            self.nickBuf.setdefault(args[2], []).extend(args[3].split())
        elif cmd == '366' and len(args) >= 2:
            chan = args[1]
            mem = self.nickBuf.pop(chan)
            self.chanlog(chan, 'MEMBERS ({}): {}'.format(len(mem), ' '.join(mem)))
            for m in mem:
                if m.startswith(('@', '+')):
                    # The @ prefix is for channel operators, and the +
                    # prefix seems to be for voiced users on moderated
                    # channels.
                    m = m[1:]
                self.nicks[m].append(chan)

        elif cmd == 'JOIN' and len(args) == 1:
            if nick == self.nickname:
                for chan in args[0].split(','):
                    self.chanlog(chan, 'JOINED')
            else:
                for chan in args[0].split(','):
                    if chan in self.chanlogfiles:
                        self.chanlog(chan, "# {} joins {}.".format(longnick, chan))
                        self.nicks[nick].append(chan)

        elif cmd == 'PART' and len(args) >= 1:
            if nick == self.nickname:
                for chan in args[0].split(','):
                    if chan in self.chanlogfiles:
                        self.chanlog(chan, 'PARTED')
                        self.chanlog(chan, '-' * 40)
                        self.chanlogfiles[chan].close()
                        del self.chanlogfiles[chan]
                        for n in self.nicks.keys():
                            self.nicks[n] = [c for c in self.nicks[n] if c != chan]
            else:
                for chan in args[0].split(','):
                    if chan in self.chanlogfiles:
                        self.chanlog(
                            chan,
                            "# {} leaves {}".format(longnick, chan),
                            ": " + args[1] if len(args) > 1 else '.',
                        )
                        self.nicks[nick] = [c for c in self.nicks[nick] if c != chan]

        elif cmd == 'QUIT':
            if nick == self.nickname:
                for chan in self.chanlogfiles.keys():
                    self.chanlog(chan, 'QUIT')
                    self.chanlog(chan, '-' * 40)
                    self.chanlogfiles[chan].close()
                    del self.chanlogfiles[chan]
            else:
                for ch in self.whereis(nick):
                    self.chanlog(
                        ch,
                        "# {} quits{}"
                            .format(longnick, ': ' + args[0] if args else '.')
                    )
                self.nicks.pop(nick, None)

        elif cmd == 'NICK' and len(args) == 1:
            for ch in self.whereis(nick):
                self.chanlog(ch, '# {} is now known as "{}".'
                            .format(longnick, args[0]))
            self.nicks[args[0]] = self.nicks.pop(nick)

        elif cmd == 'PRIVMSG' and len(args) == 2:
            target, msg = args
            if target == self.nickname:
                edict = ircArgs(msg)
                if self.cntrlpass and edict and edict[0] == self.cntrlpass:
                    edict.pop(0)
                    if edict:
                        subcmd, *subargs = edict
                        subcmd = subcmd.upper()
                    else:
                        subcmd = None
                        subargs = ()
                    if subcmd is None or subcmd == 'QUIT':
                        self.metalog("# Quitting, as commanded by ", sender)
                        for chan in self.chanlogfiles.keys():
                            self.chanlog(
                                chan,
                                "QUITTING (as commanded by ", sender, ")",
                            )
                        self.sendLine('PRIVMSG ' + nick + ' :Thy will be done.')
                        self.sendLine(
                            'QUIT :' + (subargs[0] if subargs else 'My work here is done.')
                        )

                    elif subcmd == 'JOIN':
                        newchans = [
                            c for sa in subargs
                              for c in re.split(r'[\s,]+', sa)
                        ]
                        # TODO: Should channels that I'm already in be filtered
                        # out here?
                        self.metalog("# Joining: {} (as commanded by {})"
                                .format(' '.join(newchans), sender))
                        for ch in newchans:
                            self.joinChan(ch)
                        self.sendLine("PRIVMSG " + nick + " :Ok.")

                    elif subcmd == 'PART':
                        oldchans = [
                            c for sa in subargs
                              for c in re.split(r'[\s,]+', sa)
                              if c in self.chanlogfiles
                        ]
                        self.metalog("# Parting: {} (as commanded by {})"
                                .format(' '.join(oldchans), sender))
                        for ch in oldchans:
                            self.chanlog(ch, "PARTING {} (as commanded by {})"
                                             .format(ch, sender))
                            self.sendLine("PART " + ch)
                        self.sendLine("PRIVMSG " + nick + " :Ok.")

                    elif subcmd == 'PASS' and len(subargs) == 1:
                        self.cntrlpass = self.subargs[0]
                        self.metalog('# Control password {} by {}'.format(
                            'changed' if self.cntrlpass else 'deactivated',
                            sender,
                        ))
                        # Should deactivating the password even be allowed?
                        self.sendLine("PRIVMSG " + nick + " :Ok.")

                    elif subcmd == 'STATS':
                        self.sendLine(
                            "PRIVMSG {} :Running since {}, last message {},"
                            " currently logging: {}".format(
                                nick,
                                self.start,
                                self.last,
                                ' '.join(sorted(self.chanlogfiles.keys()))
                            )
                        )
                        ### TODO: Should this be metalogged in some form?

                    ### elif subcmd == 'NICK' and len(subargs) == 1:

                    elif subcmd == 'MODE':
                        modes = [
                            re.sub(r'^:', '', s)
                            for sa in subargs
                            for s in re.split(r'\s+|(?=[-+])', sa)
                        ]
                        while modes and modes[0] == '':
                            modes.pop(0)
                        if modes:
                            self.metalog("# Setting user MODE to: ",
                                         ' '.join(modes))
                            self.sendLine('MODE {} {}'
                                          .format(self.nickname, ' '.join(modes)))
                            self.sendLine("PRIVMSG " + nick + " :Ok.")

                    elif subcmd == 'LONG' and len(subargs) == 1 and \
                            subargs[0].isdigit():
                        self.longmode = int(subargs[0])
                        self.metalog("# longmode set to {} by {}"
                                     .format(self.longmode, sender))
                        self.sendLine("PRIVMSG " + nick + " :Ok.")

                    else:
                        self.metalog(
                            "# Unknown authenticated command from ",sender,": ",
                            unircArgs(subcmd, *subargs),
                        )
                        self.sendLine("PRIVMSG " + nick + " :...What?")

                    return
                #END if self.cntrlpass and edict and edict[0] == self.cntrlpass

                self.metalog(line)
                if msg == "\x01USERINFO\x01":
                    self.send_notice(nick, "\x01USERINFO :Shh!  I'm lurking!\x01")
                elif msg == "\x01FINGER\x01":
                    self.send_notice(
                        nick,
                        "\x01FINGER :I am " + self.realname + ", I swear!\x01",
                    )
                elif re.match(r'^\x01PING\b', msg):
                    self.send_notice(nick, msg)
                elif msg == "\x01TIME\x01":
                    self.send_notice(nick, "\x01TIME :" + now() + "\x01")
                elif msg == "\x01CLIENTINFO\x01":
                    self.send_notice(
                        nick, "\x01CLIENTINFO :I know CLIENTINFO, USERINFO,"
                        " FINGER, PING, TIME, VERSION, and ERRMSG, but I won't"
                        " help you with them.\x01"
                    )
                elif re.match(r'^\x01CLIENTINFO\b', msg):
                    self.send_notice(nick, "\x01CLIENTINFO :Go look it up yourself.\x01")
                elif msg == "\x01VERSION\x01":
                    self.send_notice(nick, '\x01VERSION {}:{}:{} {}\x01'.format(
                        os.path.basename(__file__),
                        __version__,
                        platform.python_implementation(),
                        platform.python_version(),
                    ))
                elif re.match(r'^\x01ERRMSG (.+)\x01$', msg):
                    self.send_notice(
                        nick,
                        "\x01ERRMSG " + msg[8:-1]
                            + " :What are you trying to do?\x01",
                    )
                elif re.match(r'^\x01ACTION\b', msg):
                    # ignore
                    pass
                elif re.match(r'^\x01(.+)\x01$', msg):
                    self.send_notice(
                        nick,
                        "\x01ERRMSG " + msg[1:-1]
                            + " :I don't know what that means.\x01"
                    )

            #END if target == self.nickname

            elif re.match(r'^\x01ACTION (.*)\x01$', msg):
                for ch in target.split(','):
                    self.chanlog(ch, "* {} {}".format(longnick, msg[8:-1]))
            else:
                for chan in target.split(','):
                    self.chanlog(chan, '<{}> {}'.format(longnick, msg))

        elif cmd == 'TOPIC' and len(args) == 2:
            self.chanlog(args[0], "# {} sets the channel topic to: {}"
                             .format(longnick, args[1]))

        elif cmd == 'KICK' and len(args) >= 2:
            self.chanlog(
                args[0],
                "# {} is kicked from the channel by {}{}".format(
                    args[1], longnick, ': ' + args[2] if len(args) == 3 else '.',
                )
            )
            self.nicks[args[1]] = [c for c in self.nicks[args[1]] if c != args[0]]

        elif cmd == 'MODE' and len(args) >= 2:
            moded = args.pop(0)
            if moded.startswith(tuple('#&+!')):
                self.chanlog(
                    moded,
                    "# {} sets channel mode: {}".format(longnick, ' '.join(args)),
                )
            # else assume moded == nick as required by the RFCs
            elif nick == self.nickname:
                self.metalog("Mode set: " + ' '.join(args))
            else:
                for ch in self.whereis(nick):
                    self.chanlog(
                        ch,
                        "# {} sets user mode: {}".format(longnick, ' '.join(args))
                    )

        elif cmd == 'WALLOPS' and len(args) == 1:
            self.metalog("# WALLOPS message from {}: {}".format(sender, args[0]))

        else:
            self.metalog("UNKNOWN\t", line)

    def metalog(self, *args):
        print(now(), '\t', *args, sep='', file=self.meta, flush=True)

    def chanlog(self, ch, *args):
        if ch in self.chanlogfiles:
            print(now(), '\t', *args, sep='', file=self.chanlogfiles[ch],
                  flush=True)

    def joinChan(self, chan):
        if chan in self.chanlogfiles:
            return
        filename = os.path.join(self.directory, quote(chan, safe=':+=,') + '.txt')
        try:
            log = open(filename, 'a')
        except IOError as e:
            self.metalog(
                "# Could not open {} to log {}: {}".format(filename, chan, e)
            )
            return
        self.chanlogfiles[chan] = log
        self.sendLine('JOIN ' + chan)
        self.chanlog(chan, '-' * 40)
        self.chanlog(chan, "JOINING " + chan)

    def whereis(self, nick):
        return self.nicks.get(nick, [])

    def send_notice(self, user, msg):
        self.sendLine('NOTICE {} :{}'.format(user, msg))


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

def ircArgs(shargs):
    args = []
    if shargs is not None:
        while shargs != '':
            m = re.match(r'^:(.*)$', shargs)
            if m:
                args.append(m.group(1))
                break
            else:
                m = re.match(r'^([^ ]+)[ ]*', shargs)
                if m:
                    args.append(m.group(1))
                    shargs = shargs[m.end():]
    return args

def unircArgs(*args):
    s = ''
    while args:
        if re.search(r' |^:|^$', args[0]):
            return '{}:{}'.format(s, ' '.join(args))
        s += ' ' + args[0]
        args = args[1:]
    return s

if __name__ == '__main__':
    main()
