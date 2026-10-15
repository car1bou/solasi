import struct
import zlib


def png_fixture():
    def chunk(kind,data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    pixels = b"".join(b"\0"+bytes([255,255,255])*80 for _ in range(40))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",80,40,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(pixels))+chunk(b"IEND",b"")


def pdf_fixture():
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>"]
    for n in range(3):
        content = ("BT /F1 16 Tf 50 720 Td (Lecture page %d: process memory scheduler and threads.) Tj ET"%(n+1)).encode()
        if n==0:
            content += b" q 100 0 0 100 60 500 cm /Im1 Do Q"
        objects += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 9 0 R >> /XObject << /Im1 10 0 R >> >> /Contents "+str(4+2*n).encode()+b" 0 R >>", b"<< /Length "+str(len(content)).encode()+b" >>\nstream\n"+content+b"\nendstream"]
    objects += [b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 12 >>\nstream\n"+bytes([255,0,0,0,255,0,0,0,255,255,255,0])+b"\nendstream"]
    output = b"%PDF-1.4\n"
    offsets = [0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(output))
        output += str(i).encode()+b" 0 obj\n"+obj+b"\nendobj\n"
    start = len(output)
    output += b"xref\n0 11\n0000000000 65535 f \n"+b"".join(("%010d 00000 n \n"%offset).encode() for offset in offsets[1:])
    return output+b"trailer\n<< /Size 11 /Root 1 0 R >>\nstartxref\n"+str(start).encode()+b"\n%%EOF"
