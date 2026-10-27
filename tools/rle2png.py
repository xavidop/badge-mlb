import sys, struct, zlib
data = open(sys.argv[1], 'rb').read()
W, H = 320, 240
pixels = []
for i in range(0, len(data), 4):
    count, value = struct.unpack_from('<HH', data, i)
    pixels.extend([value] * count)
assert len(pixels) == W * H, len(pixels)
rows = []
for y in range(H):
    row = bytearray([0])
    for x in range(W):
        v = pixels[y * W + x]
        row += bytes((((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
    rows.append(bytes(row))
def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
open(sys.argv[2], 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))
