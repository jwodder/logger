Options
-------
- `-M file` - specify the file to which to log "meta" messages; default STDERR;
  an argument of "-" can be supplied to specify STDOUT
- `-n nicks` - supply a comma-separated list of nicknames to attempt to use, in
  order
- `-p pass` - set password
- `-u name` - set username
- `-r name` - set real name
- `-s server[:port]` - set server
- `-P pass` - set control password
- `-L bitmask` - specify what kinds of messages should include user's "long
  names" when logged; bits:
    - 1 - JOIN
    - 2 - PART
    - 4 - QUIT
    - 8 - NICK
    - 16 - PRIVMSG (Should there be separate bits for ACTIONs and non-ACTIONs?)
    - 32 - TOPIC
    - 64 - KICK
    - 128 - MODE (Should there be separate bits for channel and user MODEs?)
- `-m modestring` - specify a mode string to send immediately after logging in
- `-d str` - specify a prefix (most likely a directory name) to prepend to the
  names of all channel logfiles (but not the metafile!)
