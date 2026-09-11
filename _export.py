from pathlib import Path
from ultralytics import YOLO

best = Path("runs/detect/experiment_custom/weights/best.pt")
print(f"best.pt: {best.stat().st_size/1024/1024:.1f} MB")

yolo = YOLO(str(best))
print(f"Classes: {yolo.names}")

# Export to ONNX
print("\nExporting to ONNX...")
yolo.export(format="onnx", imgsz=640, simplify=True)

# Verify
onnx_path = best.with_suffix(".onnx")
print(f"ONNX: {onnx_path} ({onnx_path.stat().st_size/1024/1024:.1f} MB)" if onnx_path.exists() else "ONNX not found")
