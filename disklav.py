#!/usr/bin/env python3
# disklav.py
# Manage MIDI/E-Seq files inside of Disklavier images
# Licensed under the GPLv3, see "COPYING"

import re
import os
import sys
import argparse
from bitstring import ConstBitStream

# Positions, lengths, and byte sequences per disk format
#-----------------------------------------------------------------------#
# Smart PianoSoft
sps_title_len = 60
sps_toc_skip = 176
sps_toc_offset = 18
sps_toc_len = 32
sps_toc_start = b'\x0D\x0A\x30'
sps_track_start = b'MThd'
sps_track_end = b'\xFF\x2F\x00'

# PianoSoft Plus
psp_title_pos = int(0x2ED0)
psp_title_len = 64
psp_toc_start = int(0x1C40)
psp_toc_skip = 80
psp_toc_len = 32
psp_track_start = b'\xFE\x00\x00'
psp_track_end = b'\xF2\x00\x00'

# PianoSoft DOM-30
dom_disknum_len = 15
dom_title_len = 53
dom_toc_offset = 57
dom_toc_skip = 80
dom_toc_len = 32
dom_track_start = b'\xFE\x00\x00'
dom_track_end = b'\x00\x0C\xF2'

# Define functions
#-----------------------------------------------------------------------#
# Get ASCII data from file given start position and length
def getData(start, length):
    return (''.join(chr(i) for i in diskimage[start:(start + length)]))

# Attempt to identify disk type, limited testing
def diskType():
    global diskformat
    print("Format:", end=' ')
    if len(diskdata.find(b'PDISK')) != 0:
        print("Smart PianoSoft")
        diskformat = "SPS"
        return

    # Find ToC
    toc_pos = diskdata.find(b'PIANODIR')[0]
    if toc_pos == 57400:
        print("PianoSoft Plus")
        diskformat = "PSP"
        return
    if toc_pos == 30720:
        print("PianoSoft DOM-30")
        diskformat = "DOM"
        locateTOC()
        return

    # If we get here, we don't know this disk type and give up
    print("Unknown")
    exit()

# Print available disk information (depends on format)
def diskTitle():
    # Default to NULL
    disk_title = "NULL"

    # For Smart PlayerSoft, must search
    if diskformat == "SPS":
        title_ref = diskdata.find(b'P.PLAYER')
        sps_title_start = int((title_ref[0] / 8) + 30)
        disk_title = getData(sps_title_start, sps_title_len)

    # Title always seems to be in same place for PlayerSoft Plus
    if diskformat == "PSP":
        disk_title = getData(psp_title_pos, psp_title_len)

    # For DOM-30, also print disk number
    if diskformat == "DOM":
        disk_title = getData((dom_disknum_pos + dom_disknum_len), dom_title_len)
        disk_number = getData(dom_disknum_pos, dom_disknum_len)
        print("Disk: %s" % disk_number.lstrip())

    # Print result
    print("Title: %s" % disk_title.lstrip())

    # Return title length
    return disk_title.lstrip()

# Read track information from Table of Contents
def listTracks(numtracks):
    if diskformat == "SPS":
        track_ref = diskdata.find(sps_toc_start)
        track_start = int((track_ref[0] / 8))
        track_skip = sps_toc_skip
        title_len = sps_toc_len
        title_offset = sps_toc_offset
    if diskformat == "PSP":
        track_start = psp_toc_start
        track_skip = psp_toc_skip
        title_len = psp_toc_len
        title_offset = 0
    if diskformat == "DOM":
        track_start = (dom_toc_start + dom_toc_offset)
        track_skip = dom_toc_skip
        title_len = dom_toc_len
        title_offset = 0

    for track in range(0, numtracks):
        # Keep track of where we are
        current_pos = (track_start + (track_skip * track))

        # Get title
        current_title = (" ".join(getData((current_pos + title_offset), title_len).split())).rstrip('.')

        # If first character is blank, bail out
        if not ord(current_title[0]):
            return

        # If we get here, print track number/title
        print("Track {:02d} -".format(track + 1), current_title)

# Search image file for tracks, return number found
def locateTracks():
    # Allow other functions to access lists
    global track_starts
    global track_stops

    if diskformat == "SPS":
        track_start = sps_track_start
        track_end = sps_track_end
    if diskformat == "PSP":
        track_start = psp_track_start
        track_end = psp_track_end
    if diskformat == "DOM":
        track_start = dom_track_start
        track_end = dom_track_end

    # Perform searches
    track_headers = diskdata.findall(track_start, bytealigned=True)
    track_ends = diskdata.findall(track_end, bytealigned=True)

    # Put positions in list
    track_starts = list(track_headers)
    track_stops = list(track_ends)

    # Remove first entry in list because it's in ToC
    if diskformat == "PSP":
        del track_starts[0]

    # If there are file fragments, count tracks by end points
    if len(track_stops) < len(track_starts):
        return len(track_stops)

    # Otherwise use track starts
    return len(track_starts)

# Note: Functions beyond this point depend on locateTracks being run first

# Print out track locations.
def printLocations(numtracks):
    for track in range(0, numtracks):
        # Check if length is negative for sanity
        track_length = (int((track_stops[track] / 8)) - int((track_starts[track] / 8)) + 3)

        if track_length < 0:
            print("")
            print("Track start and stop points do not appear to be sequential, exiting.")
            exit()

        # Print out variables
        print("Track {:02d}".format(track + 1), end=' - ')
        print("Pos:", int((track_starts[track] / 8)), end=', ')
        print("Len:", track_length)

# Use list of start/stop points to extract individual files
def ripTracks(numtracks):
    # Base the filenames on the image name
    basename = os.path.splitext(os.path.basename(args.filename))[0]

    # Extension depends on format
    if diskformat == "SPS":
        extension = ".mid"
    if diskformat == "PSP" or diskformat == "DOM":
        extension = ".fil"

    for track in range(0, numtracks):
        # Create output filename
        current_file = basename + "-track{:02d}".format(track + 1) + extension
        print("Extracting %s" % current_file, end='...')

        # Get the data
        track_buff = diskimage[int((track_starts[track] / 8)):int((track_stops[track] / 8) + 3)]

        # If we didn't get anything, exit
        if len(track_buff) == 0:
            print("ERROR!")
            print("")
            print("Automatic track extraction seems to have failed.")
            print("Use the -l option to view detected file locations.")
            exit()

        # Print file size
        print(str(len(track_buff))[:2], end='KB')

        # Write it out
        output = open(current_file, 'wb')
        output.write(track_buff)
        output.close()

        # Move on to the next one
        print("")

# For DOM-30, ToC info is at variable position towards end of disk
def locateTOC():
    global dom_toc_start
    global dom_disknum_pos
    dom_toc_start = int((diskdata.find(b'PIANODIR', start=diskdata.pos + 1)[0] / 8))
    dom_disknum_pos = int((diskdata.find(b'PPC', start=diskdata.pos + 1)[0] / 8))

# Execution below this line
#-----------------------------------------------------------------------#
parser = argparse.ArgumentParser(description='List and extract MIDI/E-Seq tracks from Yamaha Disklavier images')
parser.add_argument('-t', '--tracks', action='store_true', help='List tracks found in image file')
parser.add_argument('-l', '--locate', action='store_true', help='Find the start and stop positions of files in image')
parser.add_argument('-e', '--extract', action='store_true', help='Automatically extract tracks to individual files')
parser.add_argument('filename')
args = parser.parse_args()

# Load file
print("Loading file...", end='')
with open(args.filename, 'rb') as file:
    diskimage = file.read()
print("OK")

# Close file, we're done with it
file.close()

# Load into stream for funtions to access
diskdata = ConstBitStream(diskimage)

# Always show the format and title
diskType()
diskTitle()

# Make a pretty if the user wants to see more
if args.tracks or args.locate or args.extract:
    print("--------------------------------------------------------------------")

if args.tracks:
    listTracks(locateTracks())
    exit()

if args.locate:
    printLocations(locateTracks())
    exit()

if args.extract:
    ripTracks(locateTracks())
    exit()

exit()
# EOF
