import struct
import array
import sys
from collections import OrderedDict, namedtuple
from types import SimpleNamespace

Tag = namedtuple('Tag', ['name', 'type', 'fmt', 'value', 'region', 'id'])


def slurp(fname, nbytes=None):
    with open(fname, 'rb') as f:
        return f.read(nbytes)


def with_x(src, **kwargs):
    xx = src._asdict()
    xx.update(**kwargs)
    return type(src)(**xx)


formats = dict(file_header='HHI',
               ifd='H',
               dir_entry='HHII')


TYPE_INFO = {
    1: ('B', 1, "uint8"),
    2: ('s', 1, "ASCII (8 bits)"),
    3: ('H', 2, "uint16"),
    4: ('I', 4, "uint32"),
    5: ('II', 8, "RATIONAL (2x LONG, 64 bits)"),
    6: ('b', 1, "int8"),
    7: ('b', 1, "UNDEFINED (8 bits)"),
    8: ('h', 2, "int16"),
    9: ('i', 4, "int32"),
    10: ('II', 8, "SRATIONAL (2x SLONG, 64 bits)"),
    11: ('f', 4, "float32"),
    12: ('d', 8, "float64"),
}


TAGS = {
        # image data structure
        0x0100: ("ImageWidth", "Image width"),
        0x0101: ("ImageLength", "Image height"),
        0x0102: ("BitsPerSample", "Number of bits per component"),
        0x0103: ("Compression", "Compression scheme"),
        0x0106: ("PhotometricInterpretation", "Pixel composition"),
        0x0112: ("Orientation", "Orientation of image"),
        0x0115: ("SamplesPerPixel", "Number of components"),
        0x011C: ("PlanarConfiguration", "Image data arrangement"),
        0x0212: ("YCbCrSubSampling", "Subsampling ratio of Y to C"),
        0x0213: ("YCbCrPositioning", "Y and C positioning"),
        0x011A: ("XResolution", "Image resolution in width direction"),
        0x011B: ("YResolution", "Image resolution in height direction"),
        0x0128: ("ResolutionUnit", "Unit of X and Y resolution"),
        # recording offset
        0x0111: ("StripOffsets", "Image data location"),
        0x0116: ("RowsPerStrip", "Number of rows per strip"),
        0x0117: ("StripByteCounts", "Bytes per compressed strip"),
        0x0201: ("JPEGInterchangeFormat", "Offset to JPEG SOI"),
        0x0202: ("JPEGInterchangeFormatLength", "Bytes of JPEG data"),
        # image data characteristics
        0x012D: ("TransferFunction", "Transfer function"),
        0x013E: ("WhitePoint", "White point chromaticity"),
        0x013F: ("PrimaryChromaticities", "Chromaticities of primaries"),
        0x0211: ("YCbCrCoefficients", "Color space transformation matrix coefficients"),
        0x0214: ("ReferenceBlackWhite", "Pair of black and white reference values"),
        # other tags
        0x0132: ("DateTime", "File change date and time"),
        0x010E: ("ImageDescription", "Image title"),
        0x010F: ("Make", "Image input equipment manufacturer"),
        0x0110: ("Model", "Image input equipment model"),
        0x0131: ("Software", "Software used"),
        0x013B: ("Artist", "Person who created the image"),
        0x8298: ("Copyright", "Copyright holder"),
        0x02bc: ("XMPPacket", "XMP Packet"),
        # TIFF-specific tags
        0x00FE: ("NewSubfileType", "NewSubfileType"),
        0x00FF: ("SubfileType", "SubfileType"),
        0x0107: ("Threshholding", "Threshholding"),
        0x0108: ("CellWidth", "CellWidth"),
        0x0109: ("CellLength", "CellLength"),
        0x010A: ("FillOrder", "FillOrder"),
        0x010D: ("DocumentName", "DocumentName"),
        0x0118: ("MinSampleValue", "MinSampleValue"),
        0x0119: ("MaxSampleValue", "MaxSampleValue"),
        0x011D: ("PageName", "PageName"),
        0x011E: ("XPosition", "XPosition"),
        0x011F: ("YPosition", "YPosition"),
        0x0120: ("FreeOffsets", "FreeOffsets"),
        0x0121: ("FreeByteCounts", "FreeByteCounts"),
        0x0122: ("GrayResponseUnit", "GrayResponseUnit"),
        0x0123: ("GrayResponseCurve", "GrayResponseCurve"),
        0x0124: ("T4Options", "T4Options"),
        0x0125: ("T6Options", "T6Options"),
        0x0129: ("PageNumber", "PageNumber"),
        0x013C: ("HostComputer", "HostComputer"),
        0x013D: ("Predictor", "Predictor"),
        0x0140: ("ColorMap", "ColorMap"),
        0x0141: ("HalftoneHints", "HalftoneHints"),
        0x0142: ("TileWidth", "TileWidth"),
        0x0143: ("TileLength", "TileLength"),
        0x0144: ("TileOffsets", "TileOffsets"),
        0x0145: ("TileByteCounts", "TileByteCounts"),
        0x014B: ("SubIFDs", "SubIFDs"),
        0x014C: ("InkSet", "InkSet"),
        0x014D: ("InkNames", "InkNames"),
        0x014E: ("NumberOfInks", "NumberOfInks"),
        0x0150: ("DotRange", "DotRange"),
        0x0151: ("TargetPrinter", "TargetPrinter"),
        0x0152: ("ExtraSamples", "ExtraSamples"),
        0x0153: ("SampleFormat", "SampleFormat"),
        0x0154: ("SMinSampleValue", "SMinSampleValue"),
        0x0155: ("SMaxSampleValue", "SMaxSampleValue"),
        0x0156: ("TransferRange", "TransferRange"),
        0x0200: ("JPEGProc", "JPEGProc"),
        0x0203: ("JPEGRestartInterval", "JPEGRestartInterval"),
        0x0205: ("JPEGLosslessPredictors", "JPEGLosslessPredictors"),
        0x0206: ("JPEGPointTransforms", "JPEGPointTransforms"),
        0x0207: ("JPEGQTables", "JPEGQTables"),
        0x0208: ("JPEGDCTables", "JPEGDCTables"),
        0x0209: ("JPEGACTables", "JPEGACTables"),
        # GeoTiff
        0x830e: ("ModelPixelScale", ""),
        0x8482: ("ModelTiePoint", ""),
        0x85d8: ("ModelTransformation", ""),
        0x87af: ("GeoKeyDirectory", ""),
        0x87b0: ("GeoDoubleParams", ""),
        0x87b1: ("GeoAsciiParams", ""),
        0xa840: ("GDAL_METADATA", ""),
        0xa841: ("GDAL_NODATA", ""),
}


KEYS_OF_INTEREST = ['ImageWidth',
                    'ImageLength',

                    'Compression',
                    'Predictor',

                    'SampleFormat',
                    'BitsPerSample',
                    'SamplesPerPixel',
                    'PlanarConfiguration',
                    'PhotometricInterpretation',

                    'RowsPerStrip',
                    'StripOffsets',
                    'StripByteCounts',

                    'TileWidth',
                    'TileLength',
                    'TileOffsets',
                    'TileByteCounts']


def check_byte_order(data):
    a, b = struct.unpack('>HH', data[:4])

    if a == 0x4949:
        return 'little'
    elif b == 0x4D4D:
        return 'big'

    raise ValueError('Not a TIFF header')


def have_bytes_for_tag(tag, buffer):
    if tag.region is None or buffer is None:
        return False

    roi, _ = tag.region
    return roi.stop <= len(buffer)


def extract_tag_data(tag, buffer, byteorder):
    assert tag.region is not None

    roi, _ = tag.region

    if len(buffer) < roi.stop:
        return None

    if tag.fmt == 's':
        return buffer[roi][:-2].decode('ascii')

    if tag.fmt not in array.typecodes:
        return None

    aa = array.array(tag.fmt)
    aa.frombytes(buffer[roi])

    if byteorder != sys.byteorder:
        aa.byteswap()

    return aa


def process_tag(tag_id, val_type, val_count, value_or_offet):
    name, *_ = TAGS.get(tag_id,
                        ('Tag_%d' % tag_id, 'Unknown'))

    tt = TYPE_INFO.get(val_type)

    if tt is not None:
        pack_fmt, item_sz, type_name = tt
        if item_sz <= 4 and val_count == 1:
            value, offset, nbytes = value_or_offet, None, None
        else:
            value, offset, nbytes = None, value_or_offet, val_count*item_sz
    else:
        pack_fmt = None
        type_name, item_sz = "UNKNOWN", -1
        value, offset, nbytes = None, None, None

    if offset is not None:
        region = (slice(offset, offset + nbytes), val_count)
    else:
        region = None

    return Tag(name, type_name, pack_fmt, value, region, tag_id)


def hdr_from_bytes(buffer):
    byteorder = check_byte_order(buffer)
    prefix = {'little': '<',
              'big': '>'}[byteorder]

    fmts = {k: (prefix+v) for k, v in formats.items()}

    _, _42, offset = struct.unpack(fmts['file_header'], buffer[:8])
    if _42 != 42:
        raise ValueError('Not a TIFF header')

    n_tags, = struct.unpack_from(fmts['ifd'], buffer, offset)
    print('Found {} tags @ offset {}'.format(n_tags, offset))

    tags = [struct.unpack_from(fmts['dir_entry'], buffer, offset + 2 + 12*i)
            for i in range(n_tags)]

    parsed_tags = OrderedDict()
    for tag in tags:
        tag = process_tag(*tag)

        if tag.value is None:
            if have_bytes_for_tag(tag, buffer):
                vv = extract_tag_data(tag, buffer, byteorder)
                if vv is not None:
                    tag = with_x(tag, value=vv)

        parsed_tags[tag.name] = tag

    info = SimpleNamespace(**{k: (parsed_tags[k].value if k in parsed_tags else None)
                              for k in KEYS_OF_INTEREST})

    return SimpleNamespace(byteorder=byteorder,
                           info=info,
                           tags=parsed_tags)


def test_1():
    from base64 import b64decode

    sample = '''
SUkqAAgAAAARAAABAwABAAAACx4AAAEBAwABAAAAeR4AAAIBAwABAAAAEAAA
AAMBAwABAAAACAAAAAYBAwABAAAAAQAAABUBAwABAAAAAQAAABwBAwABAAAA
AQAAAD0BAwABAAAAAgAAAEIBAwABAAAAAAIAAEMBAwABAAAAAAIAAEQBBAAA
AQAA2gQAAEUBBAAAAQAA2gAAAFMBAwABAAAAAQAAAA6DDAADAAAA2ggAAIKE
DAAGAAAA8ggAAK+HAwAgAAAAIgkAALGHAgAeAAAAYgkAAAAAAAATAg==
'''
    sample = b64decode(sample.encode('ascii'))

    hh = hdr_from_bytes(sample)

    assert hh.byteorder == 'little'
