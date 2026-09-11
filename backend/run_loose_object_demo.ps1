# Runs the camera-grounded backend using the REAL YOLO ONNX model and the
# honest loose-object demo experiment (only classes COCO-80 can detect:
# person / bottle / cell phone / knife ...). Hazards are scored by the
# config-driven hazards.json KB — no pen, no red/yellow boxes.
# Usage from `backend/`:  .\run_loose_object_demo.ps1
$env:DETECTION_ENABLED = 'true'
$env:DETECTION_BACKEND = 'yolo'
$env:ACTIVITY_BACKEND = 'live'
$env:EXPERIMENT_FILE = 'C:\Users\Adarsh\Desktop\Coding\SIH2026_Prototype\backend\experiments\demo_loose_object_hazard.json'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8000