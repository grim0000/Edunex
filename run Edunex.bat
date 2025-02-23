@echo off
echo Starting EDUNEX...

:: Open index.html in the default browser (this will still show briefly but won't leave a window open)
start "" "index.html"

:: Start offline.py silently in the background on port 5000
start /B pythonw offline.py

:: Start online.py silently in the background on port 5001
start /B pythonw online.py

:: No need for a final echo since it won't be visible anyway
exit