# Round 9c: phone-video rotation fix
Bug: phone clips are stored 1920x1080 with a rotation flag (90). probe() ignored it -> portrait video treated as landscape -> LONG 16:9 mode, face cropped to chin, no end card.
Fix: raw_edit.probe() reads rotate tag / display-matrix rotation and swaps w/h (affects raw_edit.py and talking_head.py).
Test: tests/test_round9c.py

## Audio / music option (talking_head)
Extra audio file is mixed UNDER the voice: looped/trimmed to the video, auto-ducked while you speak (sidechain), fade in/out, final -14 LUFS.
- CLI: `python talking_head.py --video raw/clip.mp4 --audio music.mp3 [--audio-vol 0.22]`
- Workflow talking_head.yml: new inputs `audio` (path/https link) and `audio_vol`.
- Studio page: "Music / audio file" picker + volume (halka/normal/tez). Works with file upload and YouTube link.
- th_report.json: `"music": true/false`.
