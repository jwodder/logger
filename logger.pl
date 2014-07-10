#!/usr/bin/perl -w
use strict;
use Getopt::Std;
use IO::Socket::INET;
use POSIX 'strftime';

our $VERSION = '1.12';

# Default values:
my $server = 'irc.freenode.net';
my $port = 6667;
my @chans = ('#nethack', '#lojban', '#jbosnu', '#ckule');
my $pass = 'testing';
my @nicks = qw< logger.pl IRCLogBot >;
my $user = 'lurker';
my $real = 'Joey Lurkenstein';
my $nickmode = 2;
my $longmode = 135;
my $S = '# ';
my $dir = '';
my $cntrlpass = '';

sub now();
sub metalog(@);
sub chanlog($@);
sub joinChan($);
sub whereis($);
sub ircArgs($);
sub unircArgs(@);
sub sanitize($;$);

my @skip = qw< 251 252 253 254 255 265 266 250 375 372 376 >;
my @badjoin = qw< 403 405 407 437 471 473 474 475 476 >;
 # Note that 437 can also be returned for NICK failure.  Some of the other
 # @badjoin codes have multiple meanings as well, but those should not apply
 # during the script's normal operation.

my %cmdMasks = (
 JOIN    => 1,
 PART    => 2,
 QUIT    => 4,
 NICK    => 8,
 PRIVMSG => 16,
 TOPIC   => 32,
 KICK    => 64,
 MODE    => 128,
);

$Getopt::Std::STANDARD_HELP_VERSION = 1;

my %opts;
getopts('s:n:N:M:p:u:r:P:L:S:m:d:', \%opts) || exit 2;

$server = $opts{s} if exists $opts{s};
$port = $1 if $server =~ s/:(\d+)$//;
$pass = sanitize($opts{p}, 1) if exists $opts{p};
($user = sanitize $opts{u}) =~ y/@/_/ if exists $opts{u} && $opts{u} !~ /^:?$/;
$real = sanitize($opts{r}, 1) if exists $opts{r};
@nicks = map { sanitize $_ } split /[\s,]+/, $opts{n} if exists $opts{n};
 ### TODO: Filter out empty nicks and deal with illegal characters!
$nickmode = $opts{N} if exists $opts{N} && $opts{N} =~ /^[012]$/;
$longmode = $opts{L} if exists $opts{L} && $opts{L} =~ /^\d+$/;
$S = $opts{S} if exists $opts{S};
$cntrlpass = sanitize $opts{P} if exists $opts{P};
$dir = $opts{d} if exists $opts{d};

@chans = map { sanitize $_ } map { split /[\s,]+/ } @ARGV if @ARGV;
 ### TODO: Filter out empty channels and deal with illegal characters!

my $meta;
if ($opts{M} && $opts{M} eq '-') { $meta = *STDOUT }
elsif ($opts{M}) {
 open $meta, '>>', $opts{M} or die "$0: $opts{M}: $!";
 select((select($meta), $| = 1)[0]);
} else { $meta = *STDERR }

metalog '-' x 40;
metalog $S, 'Starting up.';
metalog $S, "Version: $VERSION";
metalog $S, "Server: $server:$port";
metalog $S, "Server password: $pass";
metalog $S, "Nicknames: @nicks";
metalog $S, "Username: $user";
metalog $S, "Realname: $real";
metalog $S, "Channels: @chans";
metalog $S, "nickmode: $nickmode";
metalog $S, "longmode: $longmode";
metalog $S, 'Control password: ', $cntrlpass ? 'yes' : 'no';
metalog $S, "Log name prefix: $dir";

my $sock = IO::Socket::INET->new(PeerAddr => $server, PeerPort => $port,
 Proto => 'tcp', Type => SOCK_STREAM) or do {
 metalog $S, "Could not connect to $server:$port: $!";
 exit 1;
};
metalog $S, "Connected to server";

$/ = "\r\n";

print $sock "PASS :$pass\r\n";
print $sock "USER $user * * :$real\r\n";

my $me;
nickLoop: for my $n (@nicks) {
 print $sock "NICK $n\r\n";
 while (<$sock>) {
  chomp;
  if (/^:[^ ]+ +NOTICE\b/i) {metalog $_; next; }
  elsif (/^:[^ ]+ +00\d\b/) {
   metalog $S, "Logged in with nickname $me";
   metalog $_;
   $me = $n;
   last nickLoop;
  } elsif (/^:[^ ]+ +[45]\d\d\b/) {metalog $_; next nickLoop; }
  else { metalog "UNKNOWN\t$_" }
 }
}
metalog $S, "Could not log in: all nicknames rejected" and exit 1
 if !defined $me;

if (exists $opts{m}) {
 my @modes = split /\s+|(?=[-+])/, sanitize($opts{m}, 1);
 s/^:// for @modes;
 shift @modes while @modes && $modes[0] eq '';
 if (@modes) {
  print $sock "MODE $me @modes\r\n";
  metalog $S, "Setting user MODE to: @modes";
 }
}

my %chans = ();
my %nicks = ();
my %nickBuf = ();
my($start, $last) = (now, now);
joinChan $_ for @chans;

while (<$sock>) {
 chomp;
 print $sock "PONG $1\r\n" and next if /^PING +(.*)$/i;
 /^(?:[:]([^ ]+)[ ]+)?([^ ]+)(?:[ ]+(.*))?$/ or metalog "UNKNOWN\t$_" and next;
 my($sender, $cmd, $shargs) = ($1, $2, $3);
 $cmd = uc $cmd;
 my($nick, $long);
 if (exists $cmdMasks{$cmd} && $sender =~ /^([^!]+)!(.+)$/) {
  if ($longmode & $cmdMasks{$cmd}) {$nick = $1; $long = "$1 ($2)"; }
  else { $nick = $long = $1 }
 } else { $nick = $long = $sender }
 my @args = ircArgs $shargs;

 if (grep { $_ eq $cmd } @skip) { }
 elsif (grep { $_ eq $cmd } @badjoin && @args >= 2) {
  my($to, $chan, @about) = @args;
  chanlog $chan, "ERROR: COULD NOT JOIN", @about ? ": @about" : '';
  close $chans{$chan};
  delete $chans{$chan};
 } elsif ($cmd eq 'NOTICE' || $cmd eq 'ERROR' || $cmd =~ /^[045]/) {metalog $_}
 elsif ($cmd eq '331' && @args >= 2) { chanlog $args[1], "NO TOPIC" }
 elsif ($cmd eq '332' && @args == 3) { chanlog $args[1], "TOPIC: $args[2]" }
 elsif ($cmd eq '353' && @args == 4) {
  push @{$nickBuf{$args[2]}}, split ' ', $args[3]
 } elsif ($cmd eq '366' && @args >= 2) {
  my $chan = $args[1];
  my @mem = @{$nickBuf{$chan}};
  delete $nickBuf{$chan};
  chanlog $chan, 'MEMBERS (', scalar @mem, "): @mem";
  if ($nickmode == 2) {
   for (@mem) {s/^[@+]//; push @{$nicks{$_}}, $chan; }
   # The @ prefix is for channel operators, and the + prefix seems to be for
   # voiced users on moderated channels.
  }

 } elsif ($cmd eq 'JOIN' && @args == 1) {
  if ($nick eq $me) { chanlog $_, 'JOINED' for split /,/, $args[0] }
  else {
   for my $chan (grep { exists $chans{$_} } split /,/, $args[0]) {
    chanlog $chan, "$S$long joins $chan.";
    push @{$nicks{$nick}}, $chan if $nickmode == 2;
   }
  }

 } elsif ($cmd eq 'PART' && @args >= 1) {
  if ($nick eq $me) {
   for my $chan (grep { exists $chans{$_} } split /,/, $args[0]) {
    chanlog $chan, 'PARTED';
    chanlog $chan, '-' x 40;
    close $chans{$chan};
    delete $chans{$chan};
    if ($nickmode == 2) {
     $nicks{$_} = [ grep { $_ ne $chan } @{$nicks{$_}} ] for keys %nicks
    }
   }
  } else {
   for my $chan (grep { exists $chans{$_} } split /,/, $args[0]) {
    chanlog $chan, "$S$long leaves $chan", @args > 1 ? ": $args[1]" : '.';
    $nicks{$nick} = [ grep { $_ ne $chan } @{$nicks{$nick}} ] if $nickmode == 2;
   }
  }

 } elsif ($cmd eq 'QUIT') {
  if ($nick eq $me) {
   for my $chan (keys %chans) {
    chanlog $chan, 'QUIT';
    chanlog $chan, '-' x 40;
    close $chans{$chan};
    delete $chans{$chan};
   }
  } else {
   chanlog $_, "$S$long quits", @args ? ": $args[0]" : '.' for whereis $nick;
   delete $nicks{$nick} if $nickmode == 2;
  }

 } elsif ($cmd eq 'NICK' && @args == 1) {
  chanlog $_, "$S$long is now known as \"$args[0]\"." for whereis $nick;
  $nicks{$args[0]} = delete $nicks{$nick} if $nickmode == 2;

 } elsif ($cmd eq 'PRIVMSG' && @args == 2) {
  my($target, $msg) = @args;
  if ($target eq $me) {
   my @edict = ircArgs $msg;
   if ($cntrlpass && @edict && $edict[0] eq $cntrlpass) {
    shift @edict;
    my($subcmd, @subargs) = @edict;
    $subcmd = uc $subcmd if defined $subcmd;
    if (!defined $subcmd || $subcmd eq 'QUIT') {
     metalog $S, "Quitting, as commanded by $sender";
     chanlog $_, "QUITTING (as commanded by $sender)" for keys %chans;
     print $sock "PRIVMSG $nick :Thy will be done.\r\n";
     print $sock 'QUIT :', @subargs ? $subargs[0] : 'My work here is done.',
      "\r\n";
    } elsif ($subcmd eq 'JOIN') {
     my @newchans = map { split /[\s,]+/ } @subargs;
     # Should channels that I'm already in be filtered out here?
     metalog $S, "Joining: @newchans (as commanded by $sender)";
     joinChan $_ for @newchans;
     print $sock "PRIVMSG $nick :Ok.\r\n";
    } elsif ($subcmd eq 'PART') {
     my @oldchans = grep { exists $chans{$_} } map { split /[\s,]+/ } @subargs;
     metalog $S, "Parting: @oldchans (as commanded by $sender)";
     for (@oldchans) {
      chanlog $_, "PARTING $_ (as commanded by $sender)";
      print $sock "PART $_\r\n";
     }
     print $sock "PRIVMSG $nick :Ok.\r\n";
    } elsif ($subcmd eq 'PASS' && @subargs == 1) {
     $cntrlpass = $subargs[0];
     metalog $S, 'Control password ', $cntrlpass ? 'changed' : 'deactivated',
      " by $sender";
     # Should deactivating the password even be allowed?
     print $sock "PRIVMSG $nick :Ok.\r\n";
    } elsif ($subcmd eq 'STATS') {
     print $sock "PRIVMSG $nick :Running since $start, last message $last,",
      " currently logging: @{[sort keys %chans]}\r\n";
     ### Should this be metalogged in some form?

### } elsif ($subcmd eq 'NICK' && @subargs == 1) {

    } elsif ($subcmd eq 'MODE') {
     my @modes = map { split /\s+|(?=[-+])/ } @subargs;
     s/^:// for @modes;
     shift @modes while @modes && $modes[0] eq '';
     if (@modes) {
      metalog $S, "Setting user MODE to: @modes (as commanded by $sender)";
      print $sock "MODE $me @modes\r\n";
      print $sock "PRIVMSG $nick :Ok.\r\n";
     }
    } elsif ($subcmd eq 'LONG' && @subargs == 1 && $subargs[0] =~ /^\d+$/) {
     $longmode = $subargs[0];
     metalog $S, "longmode set to $longmode by $sender";
     print $sock "PRIVMSG $nick :Ok.\r\n";
    } else {
     metalog $S, "Unknown authenticated command from $sender: ",
      unircArgs($subcmd, @subargs);
     print $sock "PRIVMSG $nick :...What?\r\n";
    }
    next;
   }
   metalog $_;
   if ($msg eq "\cAUSERINFO\cA") {
    print $sock "NOTICE $nick :\cAUSERINFO :Shh!  I'm lurking!\cA\r\n"
   } elsif ($msg eq "\cAFINGER\cA") {
    print $sock "NOTICE $nick :\cAFINGER :I am $real, I swear!\cA\r\n"
   } elsif ($msg =~ /^\cAPING\b/) {
    print $sock "NOTICE $nick :$msg\r\n"
   } elsif ($msg eq "\cATIME\cA") {
    print $sock "NOTICE $nick :\cATIME :", now, "\cA\r\n";
   } elsif ($msg eq "\cACLIENTINFO\cA") {
    print $sock "NOTICE $nick :\cACLIENTINFO :I know CLIENTINFO, USERINFO,",
     " FINGER, PING, TIME, VERSION, and ERRMSG, but I won't help you with",
     " them.\cA\r\n"
   } elsif ($msg =~ /^\cACLIENTINFO\b/) {
    print $sock "NOTICE $nick :\cACLIENTINFO :Go look it up yourself.\cA\r\n"
   } elsif ($msg eq "\cAVERSION\cA") {
    print $sock "NOTICE $nick :\cAVERSION $0:$VERSION:Perl ",
     sprintf("%vd", $^V), "\cA\r\n"
   } elsif ($msg =~ /^\cAERRMSG (.+)\cA$/) {
    print $sock "NOTICE $nick :\cAERRMSG $1 :What are you trying to do?\cA\r\n"
   } elsif ($msg =~ /^\cAACTION\b/) {
    # ignore
   } elsif ($msg =~ /^\cA(.+)\cA$/) {
    print $sock "NOTICE $nick :\cAERRMSG $1 :I don't know what that means.",
     "\cA\r\n"
   }
  } elsif ($msg =~ /^\cAACTION (.*)\cA$/) {
   chanlog $_, "* $long $1" for split /,/, $target
  } else { chanlog $_, "<$long> $msg" for split /,/, $target }

 } elsif ($cmd eq 'TOPIC' && @args == 2) {
  chanlog $args[0], "$S$long sets the channel topic to: $args[1]"

 } elsif ($cmd eq 'KICK' && @args >= 2) {
  chanlog $args[0], "$S$args[1] is kicked from the channel by $long",
   @args == 3 ? ": $args[2]" : '.';
  $nicks{$args[1]} = [ grep { $_ ne $args[0] } @{$nicks{$args[1]}} ]
   if $nickmode == 2;

 } elsif ($cmd eq 'MODE' && @args >= 2) {
  my $moded = shift @args;
  if ($moded =~ /^[#&+!]/) {chanlog $moded, "$S$long sets channel mode: @args"}
  else {
   # Assume $moded eq $nick as required by the RFCs.
   if ($nick eq $me) { metalog $S, "Mode set: @args" }
   else { chanlog $_, "$S$long sets user mode: @args" for whereis $nick }
  }

 } elsif ($cmd eq 'WALLOPS' && @args == 1) {
  metalog $S, "WALLOPS message from $sender: $args[0]"
  # Should $S be prepended here or not?

 } else { metalog "UNKNOWN\t$_" }
} continue { $last = now }
metalog $S, 'Connection closed';
close $sock;

sub now() { strftime('%Y-%m-%dT%H:%M:%SZ', gmtime) }

sub metalog(@) { print $meta now, "\t", @_, "\n" }

sub chanlog($@) {
 my $ch = shift;
 print { $chans{$ch} } now, "\t", @_, "\n" if exists $chans{$ch};
}

sub joinChan($) {
 my $chan = shift;
 return if exists $chans{$chan};
 (my $file = $chan) =~ s/([^-\w.:+=,])/sprintf "%%%02x", ord $1/ge;
 open my $log, '>>', "$dir$file.txt" or do {
  metalog $S, "Could not open $dir$file.txt to log $chan: $!";
  return;
 };
 select((select($log), $| = 1)[0]);
 $chans{$chan} = $log;
 print $sock "JOIN $chan\r\n";
 chanlog $chan, '-' x 40;
 chanlog $chan, "JOINING $chan";
}

sub whereis($) {
 if ($nickmode == 1) { keys %chans }
 elsif ($nickmode == 2) { @{$nicks{$_[0]}} }
 else { () }
}

sub ircArgs($) {
 my $shargs = shift;
 my @args = ();
 if (defined $shargs) {
  while ($shargs ne '') {
   if ($shargs =~ s/^:(.*)$//) { push @args, $1 }
   else {$shargs =~ s/^([^ ]+)[ ]*//; push @args, $1; }
  }
 }
 return @args;
}

sub unircArgs(@) {
 my $str = '';
 while (@_) {
  return "$str:@_" if $_[0] =~ / |^:|^$/;
  $str .= ' ' . shift;
 }
 return $str;
}

sub sanitize($;$) {
 my($str, $trailing) = @_;
 $str =~ tr/\0\r\n/ /;
 if (!$trailing) {
  $str =~ tr/ /_/;
  $str =~ s/^://;
 }
 return $str;
}

__END__

Options:
 - -N [012] - specify how to determine what channels to send NICK, QUIT, and
   (user) MODE messages to:
  - 0 - don't record any such messages
  - 1 - log all such messages in every channel transcript, regardless of
    membership
  - 2 - keep track of what users are in what channel and log such messages to
    the appropriate transcripts
 - -M file - specify the file to which to log "meta" messages; default
   STDERR; an argument of "-" can be supplied to specify STDOUT
 - -n nicks - supply a comma-separated list of nicknames to attempt to use, in
   order
 - -p pass - set password
 - -u name - set username
 - -r name - set real name
 - -s server[:port] - set server
 - -P pass - set control password
 - -L bitmask - specify what kinds of messages should include user's "long
   names" when logged; bits:
  - 1 - JOIN
  - 2 - PART
  - 4 - QUIT
  - 8 - NICK
  - 16 - PRIVMSG (Should there be separate bits for ACTIONs and non-ACTIONs?)
  - 32 - TOPIC
  - 64 - KICK
  - 128 - MODE (Should there be separate bits for channel and user MODEs?)
 - -S str - set the string to display in front of non-PRIVMSG messages (ircII
   apparently uses '*** ')
 - -m modestring - specify a mode string to send immediately after logging in
 - -d str - specify a prefix (most likely a directory name) to prepend to the
   names of all channel logfiles (but not the metafile!)
