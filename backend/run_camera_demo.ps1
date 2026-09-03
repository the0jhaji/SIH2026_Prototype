# Runs the camera-grounded backend: heuristic detector (real frames), live
# activity perception, and the heuristic-compatible demo experiment.
# Usage from `backend/`:  .\run_camera_demo.ps1
$env:DETECTION_ENABLED = 'true'
$env:DETECTION_BACKEND = 'heuristic'
$env:ACTIVITY_BACKEND = 'live'
$env:EXPERIMENT_FILE = 'C:\Users\Adarsh\Desktop\Coding\SIH2026_Prototype\backend\experiments\heuristic_live_demo.json'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8000