"""Build clipfoundry/assets/models/yamnet.onnx from Google's own YAMNet weights (docs/clipforge/WATCH_AND_LISTEN.md).

YAMNet (Apache-2.0, https://github.com/tensorflow/models/tree/master/research/audioset/yamnet) names the sounds in
0.96 s of audio among AudioSet's 521 classes. Google publishes its trained weights as a Keras file:

    https://storage.googleapis.com/audioset/yamnet.h5   (15,296,092 bytes,
    sha256 13c3308955bbfaef262f175ac9c40e47b134573a93984f009220dd7cc12a1744)

This script reads that file with h5py and writes the same network as an ONNX graph that ONNX Runtime (already used
by ClipForge) runs on any computer: input `patches` [n, 96, 64] float32 log-mel patches (pipeline/listen.py makes
them exactly as YAMNet's features.py does), outputs `scores` [n, 521] (sigmoid) and `embeddings` [n, 1024].
Each batch norm (centre, no scale, epsilon 1e-4) is folded into the convolution before it; Keras's "same" padding
is written out (stride 2: one row and column at the end, as TensorFlow pads). Weights are stored as float16 and cast
to float32 when the session loads (half the file, scores within about 1e-3 of float32; checked by --check).

Needs h5py and onnx (developer tools only; the app needs neither):

    python scripts/export_yamnet.py --h5 yamnet.h5 --out clipfoundry/assets/models/yamnet.onnx [--fp32]
    python scripts/export_yamnet.py --h5 yamnet.h5 --check clipfoundry/assets/models/yamnet.onnx
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

H5_SHA256 = "13c3308955bbfaef262f175ac9c40e47b134573a93984f009220dd7cc12a1744"
EPS = 1e-4
LAYERS = [  # (kind, stride, filters) as in yamnet.py's _YAMNET_LAYER_DEFS
    ("conv", 2, 32), ("sep", 1, 64), ("sep", 2, 128), ("sep", 1, 128), ("sep", 2, 256), ("sep", 1, 256),
    ("sep", 2, 512), ("sep", 1, 512), ("sep", 1, 512), ("sep", 1, 512), ("sep", 1, 512), ("sep", 1, 512),
    ("sep", 2, 1024), ("sep", 1, 1024)]


def _weights(h5: Path) -> dict[str, np.ndarray]:
    import h5py

    out: dict[str, np.ndarray] = {}
    with h5py.File(h5, "r") as f:
        def take(name, obj):
            if isinstance(obj, h5py.Dataset):
                out[name] = np.array(obj, dtype=np.float32)
        f.visititems(take)
    return out


def _find(w: dict[str, np.ndarray], prefix: str, leaf: str) -> np.ndarray:
    hits = [k for k in w if k.startswith(prefix + "/") and k.endswith("/" + leaf)]
    if len(hits) != 1:
        raise SystemExit(f"expected one {prefix} .../{leaf} in the weights, found {hits}")
    return w[hits[0]]


def _bn(w: dict[str, np.ndarray], prefix: str) -> tuple[np.ndarray, np.ndarray]:
    """(scale, shift) of a batch norm with centre and without scale: y = (x - mean) / sqrt(var + eps) + beta."""
    beta = _find(w, prefix, "beta:0")
    mean = _find(w, prefix, "moving_mean:0")
    var = _find(w, prefix, "moving_variance:0")
    scale = 1.0 / np.sqrt(var + EPS)
    return scale.astype(np.float32), (beta - mean * scale).astype(np.float32)


def build(h5: Path, fp16: bool = True):
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    w = _weights(h5)
    nodes, inits = [], []

    def const(name: str, arr: np.ndarray) -> str:
        arr = np.ascontiguousarray(arr)
        if fp16 and arr.dtype == np.float32 and arr.size > 1024:
            inits.append(numpy_helper.from_array(arr.astype(np.float16), name + "_h"))
            nodes.append(helper.make_node("Cast", [name + "_h"], [name], to=TensorProto.FLOAT))
        else:
            inits.append(numpy_helper.from_array(arr, name))
        return name

    def conv(x: str, name: str, kernel_hwio: np.ndarray, bn: tuple[np.ndarray, np.ndarray], stride: int,
             group: int = 1) -> str:
        scale, shift = bn
        k = kernel_hwio.transpose(3, 2, 0, 1)  # [h, w, in, out] -> [out, in, h, w]
        if group > 1:                          # depthwise: [h, w, c, 1] -> [c, 1, h, w]
            k = kernel_hwio.transpose(2, 3, 0, 1)
        k = k * scale[:, None, None, None]
        kh = k.shape[2]
        pads = [0, 0, 0, 0] if kh == 1 else ([1, 1, 1, 1] if stride == 1 else [0, 0, 1, 1])
        y = name + "_y"
        nodes.append(helper.make_node("Conv", [x, const(name + "_w", k), const(name + "_b", shift)], [y],
                                      strides=[stride, stride], pads=pads, group=group,
                                      kernel_shape=[kh, kh]))
        r = name + "_r"
        nodes.append(helper.make_node("Relu", [y], [r]))
        return r

    shape = const("shape", np.array([-1, 1, 96, 64], dtype=np.int64))
    nodes.append(helper.make_node("Reshape", ["patches", shape], ["x0"]))
    x = "x0"
    for n, (kind, stride, _filters) in enumerate(LAYERS, 1):
        p = f"layer{n}"
        if kind == "conv":
            x = conv(x, p, _find(w, f"{p}/conv", "kernel:0"), _bn(w, f"{p}/conv/bn"), stride)
            continue
        dk = _find(w, f"{p}/depthwise_conv", "depthwise_kernel:0")
        x = conv(x, p + "_dw", dk, _bn(w, f"{p}/depthwise_conv/bn"), stride, group=dk.shape[2])
        x = conv(x, p + "_pw", _find(w, f"{p}/pointwise_conv", "kernel:0"), _bn(w, f"{p}/pointwise_conv/bn"), 1)
    nodes.append(helper.make_node("GlobalAveragePool", [x], ["pooled"]))
    nodes.append(helper.make_node("Flatten", ["pooled"], ["embeddings"], axis=1))
    dense_k = [k for k in w if k.endswith("kernel:0") and w[k].ndim == 2]
    dense_b = [k for k in w if k.endswith("bias:0") and w[k].ndim == 1 and w[k].shape[0] == 521]
    if len(dense_k) != 1 or len(dense_b) != 1:
        raise SystemExit(f"expected one dense layer, found {dense_k} {dense_b}")
    nodes.append(helper.make_node("Gemm", ["embeddings", const("dense_w", w[dense_k[0]]),
                                           const("dense_b", w[dense_b[0]])], ["logits"]))
    nodes.append(helper.make_node("Sigmoid", ["logits"], ["scores"]))
    graph = helper.make_graph(
        nodes, "yamnet", [helper.make_tensor_value_info("patches", TensorProto.FLOAT, ["n", 96, 64])],
        [helper.make_tensor_value_info("scores", TensorProto.FLOAT, ["n", 521]),
         helper.make_tensor_value_info("embeddings", TensorProto.FLOAT, ["n", 1024])], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)], producer_name="clipforge",
                              doc_string="YAMNet (Apache-2.0, Google), from storage.googleapis.com/audioset/yamnet.h5 "
                                         f"sha256 {H5_SHA256}; scripts/export_yamnet.py")
    model.ir_version = 8  # readable by every ONNX Runtime from 1.14 on
    onnx.checker.check_model(model)
    return model


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--h5", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fp32", action="store_true", help="store float32 weights (twice the size)")
    ap.add_argument("--check", type=Path, help="compare a written file with a float32 build on random patches")
    a = ap.parse_args()
    got = hashlib.sha256(a.h5.read_bytes()).hexdigest()
    if got != H5_SHA256:
        print(f"{a.h5} is not Google's yamnet.h5 (sha256 {got})", file=sys.stderr)
        return 1
    if a.out:
        model = build(a.h5, fp16=not a.fp32)
        a.out.write_bytes(model.SerializeToString())
        print(f"wrote {a.out}: {a.out.stat().st_size:,} bytes, sha256 {hashlib.sha256(a.out.read_bytes()).hexdigest()}")
    if a.check:
        import onnxruntime as ort

        ref = ort.InferenceSession(build(a.h5, fp16=False).SerializeToString(), providers=["CPUExecutionProvider"])
        new = ort.InferenceSession(str(a.check), providers=["CPUExecutionProvider"])
        x = np.random.default_rng(7).normal(-4.0, 2.0, (16, 96, 64)).astype(np.float32)
        d = float(np.abs(ref.run(["scores"], {"patches": x})[0] - new.run(["scores"], {"patches": x})[0]).max())
        print(f"largest score difference from float32: {d:.2e}")
        return 0 if d < 5e-3 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
