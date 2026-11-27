# Cell boxes for the three crew sheets: (name, sheet, x0, y0, x1, y1) of the robot area (labels excluded).
REF = '/mnt/project-files/space-studio/references/'
S1 = REF + 'crew-1-command-to-boost.png'
S2 = REF + 'crew-2-frame-to-core.png'
S3 = REF + 'crew-3-switch-to-dock.png'
def grid(sheet, xs, ys, names, label_frac):
    out = []
    k = 0
    for r in range(len(ys) - 1):
        for c in range(len(xs) - 1):
            if k >= len(names): break
            n = names[k]; k += 1
            if n is None: continue
            x0, x1 = xs[c] + 6, xs[c + 1] - 6
            y0, y1 = ys[r] + 6, ys[r + 1] - 6
            y1 = int(y0 + (y1 - y0) * label_frac)
            out.append((n, sheet, x0, y0, x1, y1))
    return out
CELLS = (
    grid(S1, [11, 316, 617, 920, 1222, 1525], [10, 506, 1012],
         ['command', 'tracker', 'radar', 'gavel', 'clock', 'pulse', 'vector', 'archive', 'spark', 'boost'], 0.80)
    + grid(S2, [13, 426, 828, 1240], [11, 418, 810, 1235],
           ['frame', 'story', 'splice', 'script', 'glyph', 'curator', 'metric', 'synapse', 'core'], 0.83)
    + grid(S3, [1, 387, 767, 1153, 1535], [1, 500, 1023],
           ['switch', 'check', 'patch', None, 'harbor', 'quill', 'lock', 'dock'], 0.80)
)
