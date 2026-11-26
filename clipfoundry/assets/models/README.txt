face_detection_yunet_2023mar.onnx
Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
License: MIT (Copyright (c) 2020 Shiqi Yu). Bundled unmodified.

yamnet.onnx, yamnet_class_map.csv
Source: YAMNet, https://github.com/tensorflow/models/tree/master/research/audioset/yamnet
License: Apache-2.0 (Copyright The TensorFlow Authors).
yamnet.onnx is Google's published weights (https://storage.googleapis.com/audioset/yamnet.h5, sha256
13c3308955bbfaef262f175ac9c40e47b134573a93984f009220dd7cc12a1744) written as an ONNX graph by
scripts/export_yamnet.py: batch norms folded into the convolutions, weights stored as float16 (scores within 2e-3 of
the float32 network). yamnet_class_map.csv is the class list from the same repository, unmodified.
The 521 class names are AudioSet's ontology (https://research.google.com/audioset/, CC BY 4.0).
