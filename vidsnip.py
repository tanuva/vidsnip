#!/usr/bin/env python3

"""
TODO
"""

import argparse
from enum import Enum
from datetime import timedelta
from mutagen.mp3 import EasyMP3 as MP3
import os
import simplejson as json
import subprocess


class SnipSection(Enum):
    META = 0
    TRACKS = 1


def run_or_simulate(cmd, simulate):
    if simulate:
        print(" ".join(cmd))
        return (True, None)
    else:
        try:
            completedProcess = subprocess.run(cmd, capture_output=True, text=True)
            return (True, completedProcess)
        except Exception as e:
            print(e)
            return (False, e)


def parse_timestamp(timestampStr):
    if timestampStr.index(":") == -1:
        print("Malformed snipfile in line: \"{0}\"" % (line))
        exit(-1)

    timestampParts = timestampStr.split(":")
    timestamp = None
    if len(timestampParts) == 3:
        timestamp = timedelta(hours=int(timestampParts[0]),
                              minutes=int(timestampParts[1]),
                              seconds=int(timestampParts[2]))
    elif len(timestampParts) == 2:
        timestamp = timedelta(minutes=int(timestampParts[0]),
                              seconds=int(timestampParts[1]))
    else:
        print("Malformed timestamp in line: \"{0}\"" % (line))
        exit(-1)

    return timestamp


def parse_meta(line):
    tagName = line[:line.index(":")]
    tagValue = line[line.index(" ") + 1:]
    return (tagName, tagValue)


def parse_track(line):
    timestamp = None
    title = None

    try:
        firstSpaceIdx = line.index(" ")
        timestamp = parse_timestamp(line[0:firstSpaceIdx])
        title = line[firstSpaceIdx + 1:]
    except(ValueError):
        timestamp = parse_timestamp(line)

    return (timestamp, title) if timestamp != None else None

def parse_snipfile(snipfilename):
    meta = {}
    tracks = []

    with open(snipfilename) as f:
        snipfile = f.read().splitlines()
        section = SnipSection.TRACKS

        for line in snipfile:
            if (len(line) == 0
                or len(line) > 0 and line[0] == "#"):
                continue
            elif line == "[Meta]":
                section = SnipSection.META
                continue
            elif line == "[Tracks]":
                section = SnipSection.TRACKS
                continue

            if section == SnipSection.META:
                tag, value = parse_meta(line)
                meta[tag] = value
            elif section == SnipSection.TRACKS:
                tracks.append(parse_track(line))

    return {"meta": meta, "tracks": tracks}


def normalize_first_pass(vfile, simulate):
    # We're doing two-pass normalization. Do the measurement run first.
    # See https://peterforgacs.github.io/2018/05/20/Audio-normalization-with-ffmpeg/
    # TODO Make the parameters configurable
    # TODO Don't forget the parameter copies in snip()
    cmd = [
        "ffmpeg", "-i", vfile,
        "-af", "loudnorm=I=-6:LRA=4.5:tp=-2:print_format=json",
        "-f", "null"
    ]

    if simulate:
        cmd += ["-t", "0:05"]
        print(" ".join(cmd))
    else:
        cmd += ["-t", "5:00"] # For quicker testing...

    cmd += ["-"]

    success, completedProcess = run_or_simulate(cmd, False)
    if not success:
        print(completedProcess)
        return None

    try:
        output = completedProcess.stderr
        parsedLoudnormIdx = output.index("Parsed_loudnorm")
        curlyAfterParsedLoudnorm = output.index("{", parsedLoudnormIdx)
        loudnormParamsText = output[curlyAfterParsedLoudnorm:]
        print("loudnorm params:\n", loudnormParamsText)
        return json.loads(loudnormParamsText)
    except Exception as e:
        print("Exception while processing ffmpeg output:", e)
        print("ffmpeg says:\n", output)


def snip(vfile, outfile, start, duration, loudnormParams, simulate):
    loudnormParamsStr = None
    if loudnormParams:
        loudnormParamsStr = "loudnorm=I=-6:LRA=4.5:tp=-2:measured_I={0}:measured_LRA={1}:measured_tp={2}:measured_thresh={3}:offset={4}".format(
            #loudnormParams["input_i"],
            #loudnormParams["input_lra"],
            #loudnormParams["input_tp"],
            #loudnormParams["input_thresh"],
            loudnormParams["output_i"],
            loudnormParams["output_lra"],
            loudnormParams["output_tp"],
            loudnormParams["output_thresh"],
            loudnormParams["target_offset"]
        )

    cmd = [
        "ffmpeg", "-ss", str(start), "-i", vfile,
        "-t", str(duration),
        "-vcodec", "none",
        "-acodec", "libmp3lame", "-ar", "44100", "-ab", "320000",
        "-y",
        #"-filter:a", "volume=+8dB"
    ]

    if loudnormParams:
        cmd += ["-af", loudnormParamsStr]

    cmd += [outfile]

    return run_or_simulate(cmd, simulate)[0]


def tag(filepath, metadata, track_num, track_count, title, simulate):
    if simulate:
        print("Writing tags: {title}".format(title=title))
        return

    file = MP3(filepath)
    file["album"] = metadata["Album"]
    file["artist"] = metadata["Artist"]
    file["genre"] = metadata["Genre"]
    file["title"] = title
    file["tracknumber"] = "{0}/{1}".format(track_num, track_count)
    file["date"] = metadata["Year"]
    file.save()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("snipfile",
                        help="The file that holds timestamps and titles")
    parser.add_argument("video",
                        help="The video file to split")
    parser.add_argument("-s", "--simulate", default=False, action="store_true",
                        help="Only prints the ffmpeg calls that would be done")
    parser.add_argument("-l", "--limit", default=None, action="store", type=int,
                        help="Limit processing to n tracks")
    parser.add_argument("-n", "--normalize", default=False, action="store_true",
                        help="Normalize volume of processed audio tracks (experimental)")
    a
    parser.add_argument("--fade-in", default=None, action="store",
                        help="Fade into the first track (seconds)")
    parser.add_argument("--fade-out", default=None, action="store",
                        help="Fade out of the last track (seconds)")
    return parser.parse_args()


def main():
    args = parse_args()
    snipdata = parse_snipfile(args.snipfile)


    loudnormParams = None
    if args.normalize:
        print("Preprocessing video for normalization...")
        loudnormParams = normalize_first_pass(args.video, args.simulate)
        if not loudnormParams:
            print("Normalization failed")
            return

    metadata = snipdata["meta"]
    tracks = snipdata["tracks"]
    track_count = args.limit if args.limit else len(tracks) - 1
    for i in range(track_count):
        track_num = i + 1
        padded_track_num = "{:02.0f}".format(track_num)
        start = tracks[i][0]
        title = tracks[i][1]
        end = tracks[i + 1][0]
        outfile = f"{padded_track_num} {metadata['Artist']} - {title}.mp3"

        print("{0}/{1} Snipping '{2}'".format(track_num, track_count, title))
        if not snip(args.video,
                    outfile,
                    start,
                    end - start,
                    loudnormParams,
                    args.simulate):
            break
        tag(outfile, metadata, i + 1, track_count, title, args.simulate)


if __name__ == "__main__":
    main()
