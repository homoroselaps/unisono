#!/bin/sh
python3.7 server.py &
echo $! > pid
