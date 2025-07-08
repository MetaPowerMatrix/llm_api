#! /bin/bash

curl -X POST "http://127.0.0.1:8000/megatts/upload-voice" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@/home/user/audio.wav" \
     -F "voice_id=my_voice"

