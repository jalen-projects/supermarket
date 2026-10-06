"""A QR code, drawn as SVG, in plain Python.

WHY NOT A LIBRARY: the shop PC installs offline from wheelhouse/ and has no
internet to fetch one, and a script loaded in the browser would make the
receipt depend on JavaScript running before the print dialog opens. This is
the standard algorithm (ISO/IEC 18004) cut down to what a receipt needs:
byte mode, error correction level M (a slip with a crease or a coffee ring
still scans), versions 1 to 10 - up to 213 bytes, far more than a receipt
link or its offline summary ever is.

WHY SVG: it is drawn by the printer driver at the printer's own resolution,
so every module lands sharp on the thermal roll instead of being a scaled-up
bitmap with fuzzy edges. See `svg()` for the size it prints at.

Checked against a real decoder (OpenCV) in sales/tests_receipt_qr.py.
"""

from functools import lru_cache

# Error-correction codewords per block and number of blocks, level M,
# indexed by version (index 0 unused).
_ECC_PER_BLOCK_M = (None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_BLOCKS_M = (None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_MAX_VERSION = 10
_FORMAT_ECL_M = 0  # the two format bits that mean "level M"


class TooLong(ValueError):
    pass


# -- Galois field arithmetic for Reed-Solomon --------------------------------
def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# -- sizes -------------------------------------------------------------------
def _raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK_M[ver] * _BLOCKS_M[ver]


def _alignment_positions(ver):
    if ver == 1:
        return []
    n = ver // 7 + 2
    size = ver * 4 + 17
    step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    result = [size - 7 - i * step for i in range(n - 1)]
    return [6] + sorted(result)


# -- the matrix --------------------------------------------------------------
class _Matrix:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x, y, dark):
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def draw_function_patterns(self):
        size = self.size
        for i in range(size):           # timing patterns
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):   # finders
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        d = max(abs(dx), abs(dy))
                        self.set(x, y, d not in (2, 4))
        pos = _alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue            # those corners are finders
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)             # reserve; real bits drawn later
        self.draw_version()

    def draw_format(self, mask):
        data = _FORMAT_ECL_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        size = self.size
        for i in range(0, 6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(0, 8):
            self.set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, size - 15 + i, bit(i))
        self.set(8, size - 8, True)     # the dark module, always

    def draw_version(self):
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self.set(a, b, dark)
            self.set(b, a, dark)

    def draw_codewords(self, data):
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.fixed[y][x] and i < len(data) * 8:
                        self.dark[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        for y in range(self.size):
            for x in range(self.size):
                if self.fixed[y][x]:
                    continue
                if mask == 0:
                    flip = (x + y) % 2 == 0
                elif mask == 1:
                    flip = y % 2 == 0
                elif mask == 2:
                    flip = x % 3 == 0
                elif mask == 3:
                    flip = (x + y) % 3 == 0
                elif mask == 4:
                    flip = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    flip = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    flip = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    flip = ((x + y) % 2 + x * y % 3) % 2 == 0
                if flip:
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self):
        """Rules 1 to 4 of the standard's mask scoring. Any of the eight
        masks gives a valid code; scoring only picks the one a scanner reads
        most easily (fewest long runs and solid blocks, closest to half dark)."""
        size, dark, score = self.size, self.dark, 0
        for lines in (dark, list(zip(*dark))):
            for row in lines:
                run, colour = 0, None
                for cell in row:
                    if cell == colour:
                        run += 1
                    else:
                        if run >= 5:
                            score += run - 2
                        run, colour = 1, cell
                if run >= 5:
                    score += run - 2
        for y in range(size - 1):
            for x in range(size - 1):
                c = dark[y][x]
                if c == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        # Rule 3: anything that looks like a finder pattern (1:1:3:1:1 with
        # light space beside it) confuses a scanner about where the code is.
        pattern = (True, False, True, True, True, False, True)
        light = (False,) * 4
        for lines in (dark, list(zip(*dark))):
            for row in lines:
                row = tuple(row)
                for x in range(len(row) - 6):
                    if row[x:x + 7] == pattern and (
                            row[max(0, x - 4):x] == light[:min(4, x)]
                            or row[x + 7:x + 11] == light[:len(row[x + 7:x + 11])]):
                        score += 40
        total = sum(sum(row) for row in dark)
        k = abs(total * 20 - size * size * 10) // (size * size)
        return score + k * 10


def _encode_data(payload, ver):
    """Byte-mode bit stream, padded to the version's capacity."""
    bits = []

    def put(value, length):
        bits.extend((value >> i) & 1 for i in reversed(range(length)))

    put(0b0100, 4)
    put(len(payload), 8 if ver <= 9 else 16)
    for b in payload:
        put(b, 8)
    capacity = _data_codewords(ver) * 8
    put(0, min(4, capacity - len(bits)))
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    return [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]


def _add_ecc_and_interleave(data, ver):
    blocks_n = _BLOCKS_M[ver]
    ecc_len = _ECC_PER_BLOCK_M[ver]
    raw = _raw_modules(ver) // 8
    short_n = blocks_n - raw % blocks_n
    short_len = raw // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(blocks_n):
        take = short_len - ecc_len + (0 if i < short_n else 1)
        dat = data[k:k + take]
        k += take
        ecc = _rs_remainder(dat, divisor)
        if i < short_n:
            dat = dat + [None]          # keeps the columns lined up
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if block[i] is not None:
                result.append(block[i])
    return result


@lru_cache(maxsize=64)
def _cached(text):
    return tuple(tuple(row) for row in _build(text))


def matrix(text):
    """The QR code for `text` as rows of booleans (True = dark). Kept for a
    while, because a receipt is often opened twice: once to print, once
    again when the customer asks for a copy."""
    return [list(row) for row in _cached(text)]


def _build(text):
    payload = text.encode("utf-8")
    for ver in range(1, _MAX_VERSION + 1):
        header = 4 + (8 if ver <= 9 else 16)
        if header + len(payload) * 8 <= _data_codewords(ver) * 8:
            break
    else:
        raise TooLong(f"{len(payload)} bytes is too long for a receipt QR code.")

    codewords = _add_ecc_and_interleave(_encode_data(payload, ver), ver)
    # Draw once, then try each of the eight masks on a copy - only the mask
    # and the format bits differ between them.
    base = _Matrix(ver)
    base.draw_function_patterns()
    base.draw_codewords(codewords)
    best, best_score = None, None
    for mask in range(8):
        m = _Matrix(ver)
        m.dark = [row[:] for row in base.dark]
        m.fixed = base.fixed
        m.apply_mask(mask)
        m.draw_format(mask)
        score = m.penalty()
        if best_score is None or score < best_score:
            best, best_score = m, score
    return best.dark


#: One module = 0.75 mm = exactly 6 dots of a 203 dpi thermal head (8 dots
#: per mm). A whole number of dots per module is what keeps every square
#: the same size on the roll; a fractional one prints alternate rows thin.
MODULE_MM = 0.75
QUIET = 4   # the white margin, in modules, that the standard requires


def svg(text, module_mm=MODULE_MM):
    """An <svg> element for the receipt. Sized in millimetres, one path for
    all the dark modules, edges kept crisp rather than anti-aliased."""
    rows = matrix(text)
    n = len(rows)
    full = n + QUIET * 2
    parts = []
    for y, row in enumerate(rows):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + QUIET} {y + QUIET}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    size = f"{full * module_mm:g}mm"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full} {full}" '
            f'width="{size}" height="{size}" shape-rendering="crispEdges" '
            f'role="img" aria-label="QR code">'
            f'<rect width="{full}" height="{full}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(parts)}"/></svg>')
