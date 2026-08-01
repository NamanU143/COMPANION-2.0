// Procedural pixel-art fox avatar. renderFox(canvas, {emotion, mouthOpen, blink})
// draws a 44x44 sprite; canvas is scaled up with image-rendering: pixelated.
const FOX_N = 44;
const FOX_P = {
    D: '#a8431d', O: '#ef7a3c', L: '#f8a268', w: '#fbeede',
    k: '#33291f', wh: '#ffffff', mouth: '#6e2a17', tongue: '#d9736b',
};

function _inTri(px, py, ax, ay, bx, by, cx, cy) {
    const d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by);
    const d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy);
    const d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay);
    const neg = d1 < 0 || d2 < 0 || d3 < 0, pos = d1 > 0 || d2 > 0 || d3 > 0;
    return !(neg && pos);
}
function _ell(px, py, cx, cy, rx, ry) { const dx = (px - cx) / rx, dy = (py - cy) / ry; return dx * dx + dy * dy; }
function _seg(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    let t = L2 ? ((px - ax) * dx + (py - ay) * dy) / L2 : 0; t = Math.max(0, Math.min(1, t));
    const cx = ax + t * dx, cy = ay + t * dy;
    return (px - cx) * (px - cx) + (py - cy) * (py - cy) <= 1.1;
}

function _base(x, y) {
    if ((y === 31 && x >= 2 && x <= 9) || (y === 34 && x >= 3 && x <= 9) ||
        (y === 31 && x >= 35 && x <= 42) || (y === 34 && x >= 35 && x <= 42)) return FOX_P.w;
    const leOut = _inTri(x, y, 5, 18, 13, 2, 19, 18), reOut = _inTri(x, y, 39, 18, 31, 2, 25, 18);
    if (leOut || reOut) {
        if (y <= 5) return FOX_P.D;
        const leIn = _inTri(x, y, 9, 16, 13, 7, 16, 16), reIn = _inTri(x, y, 35, 16, 31, 7, 28, 16);
        if (leIn || reIn) return FOX_P.w;
        return FOX_P.O;
    }
    const h = _ell(x, y, 22, 25, 16.5, 15.5), inHead = h <= 1, ring = h > 0.86 && h <= 1.03;
    if (inHead && y >= 27 && y <= 31 && Math.abs(x - 22) <= (31 - y) * 0.95) return FOX_P.k; // nose
    const muz = _ell(x, y, 22, 31, 11, 9) <= 1 && y >= 24;
    const chL = _ell(x, y, 12, 30, 4.5, 5) <= 1, chR = _ell(x, y, 32, 30, 4.5, 5) <= 1;
    const epL = _ell(x, y, 15, 23, 3.3, 3.7) <= 1, epR = _ell(x, y, 29, 23, 3.3, 3.7) <= 1;
    if (inHead && (muz || chL || chR || epL || epR)) return FOX_P.w;
    if (ring) return FOX_P.D;
    if (inHead) return (Math.abs(x - 22) <= 2.5 && y >= 11 && y <= 23) ? FOX_P.L : FOX_P.O;
    return null;
}

function _eye(x, y, cx, cy, exp) {
    if (exp === 'happy') {
        const arm = Math.round(cy - (2.2 - Math.abs(x - cx))) === y && Math.abs(x - cx) <= 3.2;
        return arm ? FOX_P.k : null;
    }
    let rx = 2.0, ry = 2.9, oy = 0, hl = true;
    if (exp === 'surprised') { rx = 2.5; ry = 3.4; }
    else if (exp === 'angry') { rx = 2.4; ry = 1.9; oy = 1; hl = false; }
    else if (exp === 'thinking') { ry = 1.4; oy = 1; hl = false; }
    else if (exp === 'sad') { oy = 1; }
    if (_ell(x, y, cx, cy + oy, rx, ry) <= 1) {
        if (hl && x === Math.round(cx - 1) && y === Math.round(cy - 1 + oy)) return FOX_P.wh;
        return FOX_P.k;
    }
    return null;
}

function _brows(x, y, exp) {
    if (exp === 'angry') {
        if (_seg(x, y, 11, 17, 18, 19) || _seg(x, y, 33, 17, 26, 19)) return FOX_P.k;
    } else if (exp === 'sad') {
        if (_seg(x, y, 11, 20, 18, 17) || _seg(x, y, 33, 20, 26, 17)) return FOX_P.k;
    }
    return null;
}

function _mouth(x, y, exp, mo) {
    if (mo > 0.08) {
        const ry = 1.2 + mo * 3.6;
        if (_ell(x, y, 22, 35, 3.2, ry) <= 1) {
            if (y >= 36 && _ell(x, y, 22, 36.5, 1.6, 1.4) <= 1) return FOX_P.tongue;
            return FOX_P.mouth;
        }
        return null;
    }
    if (exp === 'happy') { if ((y === 35 && x >= 19 && x <= 25) || (y === 34 && (x === 18 || x === 26))) return FOX_P.k; }
    else if (exp === 'sad') { if ((y === 35 && (x === 18 || x === 26)) || (y === 36 && x >= 19 && x <= 25)) return FOX_P.k; }
    else if (exp === 'surprised') { if (_ell(x, y, 22, 35, 1.7, 1.9) <= 1 && _ell(x, y, 22, 35, 0.7, 0.7) > 1) return FOX_P.k; }
    else if (exp === 'angry') { if (y === 35 && x >= 19 && x <= 25) return FOX_P.k; }
    else { if ((y === 35 && x >= 20 && x <= 24) || (y === 34 && (x === 19 || x === 25))) return FOX_P.k; }
    return null;
}

function _face(x, y, opts) {
    const exp = opts.emotion, mo = opts.mouthOpen || 0, blink = opts.blink;
    const b = _brows(x, y, exp); if (b) return b;
    const L = [15, 23], R = [29, 23];
    if (blink) { for (const c of [L, R]) if (y === c[1] && Math.abs(x - c[0]) <= 2.6) return FOX_P.k; }
    else { for (const c of [L, R]) { const e = _eye(x, y, c[0], c[1], exp); if (e) return e; } }
    const m = _mouth(x, y, exp, mo); if (m) return m;
    return null;
}

function renderFox(canvas, opts) {
    const g = canvas.getContext('2d');
    g.clearRect(0, 0, FOX_N, FOX_N);
    for (let y = 0; y < FOX_N; y++) {
        for (let x = 0; x < FOX_N; x++) {
            const c = _face(x, y, opts) || _base(x, y);
            if (c) { g.fillStyle = c; g.fillRect(x, y, 1, 1); }
        }
    }
}
