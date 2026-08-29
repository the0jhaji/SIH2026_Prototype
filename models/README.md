# models/

Location for trained model weights used by the perception pipeline (`ai/`).

Deliberately **not committed** to the repository (large binaries). Place files
such as:

- `yolo/` — YOLO detection weights (`.onnx` / `.pt`)
- `pose/` — pose / hand-landmark models
- `har/` — temporal activity-recognition weights

Execution from `ai/README.md` for the pipeline contract.