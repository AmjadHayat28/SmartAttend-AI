"""Face detection and recognition, isolated from the rest of the app.

- detection.py (Phase 4): OpenCV YuNet — validates enrollment uploads (exactly one face).
- model.py / model_store.py (Phase 6): InsightFace (SCRFD + ArcFace) via ONNX Runtime, loaded
  once per process from a verified, git-ignored model cache.
- matching.py: roster-scoped cosine matching, one-to-one assignment, confidence categories.
- types.py: shared data types and the FaceEngine protocol (tests use a deterministic fake).

Recognition only ever pre-fills a DRAFT for the teacher to review; see
services/recognition_service.py.
"""
