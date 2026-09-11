# Runs the safety demo with a fully synthetic feed: mock camera + mock
# detector playing the space_station scene (person + drifting floating_tool +
# loose_cable). No webcam or model weights needed. Earth escalation is enabled
# so CRITICAL incidents stage local escalation packages.
# Usage from `backend/`:  .\run_mock_demo.ps1
$env:CAMERA_MOCK = 'true'
$env:DETECTION_ENABLED = 'true'
$env:DETECTION_BACKEND = 'mock'
$env:MOCK_SCENE = 'space_station'
$env:ACTIVITY_BACKEND = 'live'
$env:SAFETY_ENABLED = 'true'
$env:EARTH_ESCALATION_ENABLED = 'true'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8000