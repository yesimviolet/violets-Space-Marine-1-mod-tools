import os
import struct
import zlib
import xml.dom.minidom
import tkinter as tk
import subprocess
import ctypes
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk

# =========================================================================
# UPC PARSER & COMPILER (Native Python Translation of smupc)
# =========================================================================
class NativeUPCConverter:
    @staticmethod
    def unpack_pc(in_path, out_path):
        """Unpacks UPC file from source to dest."""
        with open(in_path, 'rb') as f:
            expected_size = struct.unpack('<I', f.read(4))[0]
            compressed_data = f.read()
            
        try:
            uncompressed_data = zlib.decompress(compressed_data)
        except zlib.error:
            uncompressed_data = zlib.decompress(compressed_data, -15)
            
        with open(out_path, 'wb') as f:
            f.write(uncompressed_data)
            
        return True

    @staticmethod
    def pack_pc(in_path, out_path, big_endian=False):
        """Packs .locale file from src back into UPC."""
        with open(in_path, 'rb') as f:
            uncompressed_data = f.read()
            
        compressed_data = zlib.compress(uncompressed_data)
        
        endian_format = '>I' if big_endian else '<I'
        size_bytes = struct.pack(endian_format, len(uncompressed_data))
        
        with open(out_path, 'wb') as f:
            f.write(size_bytes)
            f.write(compressed_data)
            
        return True

# =========================================================================
# BOD PARSER & COMPILER CONSTANTS
# =========================================================================
S_HASH_DATA = [
    0x0, 0x0, 0x5800C, 0x1A1561E, 0x0B0018, 0x342AC3C, 0x0E8014, 0x2E3FA22, 0x160030, 0x6855878, 0x13803C, 0x7240E66, 0x1D0028, 0x5C7F444, 0x188024, 0x466A25A,
    0x2C0060, 0x0D0AB0F0, 0x29806C, 0x0CABE6EE, 0x270078, 0x0E481CCC, 0x228074, 0x0FE94AD2, 0x3A0050, 0x0B8FE888, 0x3F805C, 0x0A2EBE96, 0x310048, 0x8CD44B4, 0x348044, 0x96C12AA,
    0x5800C0, 0x1A1561E0, 0x5D80CC, 0x1BB437FE, 0x5300D8, 0x1957CDDC, 0x5680D4, 0x18F69BC2, 0x4E00F0, 0x1C903998, 0x4B80FC, 0x1D316F86, 0x4500E8, 0x1FD295A4, 0x4080E4, 0x1E73C3BA,
    0x7400A0, 0x171FD110, 0x7180AC, 0x16BE870E, 0x7F00B8, 0x145D7D2C, 0x7A80B4, 0x15FC2B32, 0x620090, 0x119A8968, 0x67809C, 0x103BDF76, 0x690088, 0x12D82554, 0x6C8084, 0x1379734A,
    0x0B00180, 0x342AC3C0, 0x0B5818C, 0x358B95DE, 0x0BB0198, 0x37686FFC, 0x0BE8194, 0x36C939E2, 0x0A601B0, 0x32AF9BB8, 0x0A381BC, 0x330ECDA6, 0x0AD01A8, 0x31ED3784, 0x0A881A4, 0x304C619A,
    0x9C01E0, 0x39207330, 0x9981EC, 0x3881252E, 0x9701F8, 0x3A62DF0C, 0x9281F4, 0x3BC38912, 0x8A01D0, 0x3FA52B48, 0x8F81DC, 0x3E047D56, 0x8101C8, 0x3CE78774, 0x8481C4, 0x3D46D16A,
    0x0E80140, 0x2E3FA220, 0x0ED814C, 0x2F9EF43E, 0x0E30158, 0x2D7D0E1C, 0x0E68154, 0x2CDC5802, 0x0FE0170, 0x28BAFA58, 0x0FB817C, 0x291BAC46, 0x0F50168, 0x2BF85664, 0x0F08164, 0x2A59007A,
    0x0C40120, 0x233512D0, 0x0C1812C, 0x229444CE, 0x0CF0138, 0x2077BEEC, 0x0CA8134, 0x21D6E8F2, 0x0D20110, 0x25B04AA8, 0x0D7811C, 0x24111CB6, 0x0D90108, 0x26F2E694, 0x0DC8104, 0x2753B08A,
    0x1600300, 0x68558780, 0x165830C, 0x69F4D19E, 0x16B0318, 0x6B172BBC, 0x16E8314, 0x6AB67DA2, 0x1760330, 0x6ED0DFF8, 0x173833C, 0x6F7189E6, 0x17D0328, 0x6D9273C4, 0x1788324, 0x6C3325DA,
    0x14C0360, 0x655F3770, 0x149836C, 0x64FE616E, 0x1470378, 0x661D9B4C, 0x1428374, 0x67BCCD52, 0x15A0350, 0x63DA6F08, 0x15F835C, 0x627B3916, 0x1510348, 0x6098C334, 0x1548344, 0x6139952A,
    0x13803C0, 0x7240E660, 0x13D83CC, 0x73E1B07E, 0x13303D8, 0x71024A5C, 0x13683D4, 0x70A31C42, 0x12E03F0, 0x74C5BE18, 0x12B83FC, 0x7564E806, 0x12503E8, 0x77871224, 0x12083E4, 0x7626443A,
    0x11403A0, 0x7F4A5690, 0x11183AC, 0x7EEB008E, 0x11F03B8, 0x7C08FAAC, 0x11A83B4, 0x7DA9ACB2, 0x1020390, 0x79CF0EE8, 0x107839C, 0x786E58F6, 0x1090388, 0x7A8DA2D4, 0x10C8384, 0x7B2CF4CA,
    0x1D00280, 0x5C7F4440, 0x1D5828C, 0x5DDE125E, 0x1DB0298, 0x5F3DE87C, 0x1DE8294, 0x5E9CBE62, 0x1C602B0, 0x5AFA1C38, 0x1C382BC, 0x5B5B4A26, 0x1CD02A8, 0x59B8B004, 0x1C882A4, 0x5819E61A,
    0x1FC02E0, 0x5175F4B0, 0x1F982EC, 0x50D4A2AE, 0x1F702F8, 0x5237588C, 0x1F282F4, 0x53960E92, 0x1EA02D0, 0x57F0ACC8, 0x1EF82DC, 0x5651FAD6, 0x1E102C8, 0x54B200F4, 0x1E482C4, 0x551356EA,
    0x1880240, 0x466A25A0, 0x18D824C, 0x47CB73BE, 0x1830258, 0x4528899C, 0x1868254, 0x4489DF82, 0x19E0270, 0x40EF7DD8, 0x19B827C, 0x414E2BC6, 0x1950268, 0x43ADD1E4, 0x1908264, 0x420C87FA,
    0x1A40220, 0x4B609550, 0x1A1822C, 0x4AC1C34E, 0x1AF0238, 0x4822396C, 0x1AA8234, 0x49836F72, 0x1B20210, 0x4DE5CD28, 0x1B7821C, 0x4C449B36, 0x1B90208, 0x4EA76114, 0x1BC8204, 0x4F06370A,
    0x2C00600, 0x0D0AB0F00, 0x2C5860C, 0x0D10A591E, 0x2CB0618, 0x0D3E9A33C, 0x2CE8614, 0x0D248F522, 0x2D60630, 0x0D62E5778, 0x2D3863C, 0x0D78F0166, 0x2DD0628, 0x0D56CFB44, 0x2D88624, 0x0D4CDAD5A,
    0x2EC0660, 0x0DDA1BFF0, 0x2E9866C, 0x0DC00E9EE, 0x2E70678, 0x0DEE313CC, 0x2E28674, 0x0DF4245D2, 0x2FA0650, 0x0DB24E788, 0x2FF865C, 0x0DA85B196, 0x2F10648, 0x0D8664BB4, 0x2F48644, 0x0D9C71DAA,
    0x29806C0, 0x0CABE6EE0, 0x29D86CC, 0x0CB1F38FE, 0x29306D8, 0x0C9FCC2DC, 0x29686D4, 0x0C85D94C2, 0x28E06F0, 0x0CC3B3698, 0x28B86FC, 0x0CD9A6086, 0x28506E8, 0x0CF799AA4, 0x28086E4, 0x0CED8CCBA,
    0x2B406A0, 0x0C7B4DE10, 0x2B186AC, 0x0C615880E, 0x2BF06B8, 0x0C4F6722C, 0x2BA86B4, 0x0C5572432, 0x2A20690, 0x0C1318668, 0x2A7869C, 0x0C090D076, 0x2A90688, 0x0C2732A54, 0x2AC8684, 0x0C3D27C4A,
    0x2700780, 0x0E481CCC0, 0x275878C, 0x0E5209ADE, 0x27B0798, 0x0E7C360FC, 0x27E8794, 0x0E66236E2, 0x26607B0, 0x0E20494B8, 0x26387BC, 0x0E3A5C2A6, 0x26D07A8, 0x0E1463884, 0x26887A4, 0x0E0E76E9A,
    0x25C07E0, 0x0E98B7C30, 0x25987EC, 0x0E82A2A2E, 0x25707F8, 0x0EAC9D00C, 0x25287F4, 0x0EB688612, 0x24A07D0, 0x0EF0E2448, 0x24F87DC, 0x0EEAF7256, 0x24107C8, 0x0EC4C8874, 0x24487C4, 0x0EDEDDE6A,
    0x2280740, 0x0FE94AD20, 0x22D874C, 0x0FF35FB3E, 0x2230758, 0x0FDD6011C, 0x2268754, 0x0FC775702, 0x23E0770, 0x0F811F558, 0x23B877C, 0x0F9B0A346, 0x2350768, 0x0FB535964, 0x2308764, 0x0FAF20F7A,
    0x2040720, 0x0F39E1DD0, 0x201872C, 0x0F23F4BCE, 0x20F0738, 0x0F0DCB1EC, 0x20A8734, 0x0F17DE7F2, 0x2120710, 0x0F51B45A8, 0x217871C, 0x0F4BA13B6, 0x2190708, 0x0F659E994, 0x21C8704, 0x0F7F8BF8A,
    0x3A00500, 0x0B8FE8880, 0x3A5850C, 0x0B95FDE9E, 0x3AB0518, 0x0BBBC24BC, 0x3AE8514, 0x0BA1D72A2, 0x3B60530, 0x0BE7BD0F8, 0x3B3853C, 0x0BFDA86E6, 0x3BD0528, 0x0BD397CC4, 0x3B88524, 0x0BC982ADA,
    0x38C0560, 0x0B5F43870, 0x389856C, 0x0B4556E6E, 0x3870578, 0x0B6B6944C, 0x3828574, 0x0B717C252, 0x39A0550, 0x0B3716008, 0x39F855C, 0x0B2D03616, 0x3910548, 0x0B033CC34, 0x3948544, 0x0B1929A2A,
    0x3F805C0, 0x0A2EBE960, 0x3FD85CC, 0x0A34ABF7E, 0x3F305D8, 0x0A1A9455C, 0x3F685D4, 0x0A0081342, 0x3EE05F0, 0x0A46EB118, 0x3EB85FC, 0x0A5CFE706, 0x3E505E8, 0x0A72C1D24, 0x3E085E4, 0x0A68D4B3A,
    0x3D405A0, 0x0AFE15990, 0x3D185AC, 0x0AE400F8E, 0x3DF05B8, 0x0ACA3F5AC, 0x3DA85B4, 0x0AD02A3B2, 0x3C20590, 0x0A96401E8, 0x3C7859C, 0x0A8C557F6, 0x3C90588, 0x0AA26ADD4, 0x3CC8584, 0x0AB87FBCA,
    0x3100480, 0x8CD44B40, 0x315848C, 0x8D751D5E, 0x31B0498, 0x8F96E77C, 0x31E8494, 0x8E37B162, 0x30604B0, 0x8A511338, 0x30384BC, 0x8BF04526, 0x30D04A8, 0x8913BF04, 0x30884A4, 0x88B2E91A,
    0x33C04E0, 0x81DEFBB0, 0x33984EC, 0x807FADAE, 0x33704F8, 0x829C578C, 0x33284F4, 0x833D0192, 0x32A04D0, 0x875BA3C8, 0x32F84DC, 0x86FAF5D6, 0x32104C8, 0x84190FF4, 0x32484C4, 0x85B859EA,
    0x3480440, 0x96C12AA0, 0x34D844C, 0x97607CBE, 0x3430458, 0x9583869C, 0x3468454, 0x9422D082, 0x35E0470, 0x904472D8, 0x35B847C, 0x91E524C6, 0x3550468, 0x9306DEE4, 0x3508464, 0x92A788FA,
    0x3640420, 0x9BCB9A50, 0x361842C, 0x9A6ACC4E, 0x36F0438, 0x9889366C, 0x36A8434, 0x99286072, 0x3720410, 0x9D4EC228, 0x377841C, 0x9CEF9436, 0x3790408, 0x9E0C6E14, 0x37C8404, 0x9FAD380A
]

TYPES_MAP = {1: 'object', 2: 'int', 3: 'float', 4: 'bool', 5: '5', 7: 'object', 9: 'array', 11: 'vector', 13: '13', 15: 'hstring', 254: '254', 255: '255'}

def get_sm_hash(text):
    to_hash = text.encode('utf-8')
    f_part = 0xFFFFFFFF
    s_part = 0xFFFFFFFF
    for current in to_hash:
        offset = (current ^ f_part) & 0xFF
        f_part = f_part >> 8
        s_part_last = (s_part & 0xFF) << 24
        f_part = f_part | s_part_last
        s_part = s_part >> 8
        f_part = f_part ^ S_HASH_DATA[offset * 2]
        s_part = s_part ^ S_HASH_DATA[(offset * 2) + 1]
    first_32 = (~f_part) & 0xFFFFFFFF
    second_32 = (~s_part) & 0xFFFFFFFF
    return struct.pack("<II", first_32, second_32)

class NativeBODParser:
    def __init__(self, filepath, dump_xml=True, out_xml_path=None):
        self.valid = False
        self.filepath = filepath
        if not os.path.exists(filepath): return
        with open(filepath, 'rb') as f: raw = f.read()
        if raw[:3] != b'BOD': return
        
        pos = 5
        compressed = raw[pos]
        pos += 5 
        if compressed:
            size = struct.unpack_from('<I', raw, pos)[0]
            pos += 4
            try:
                self.data = zlib.decompress(raw[pos:])
            except zlib.error:
                try:
                    self.data = zlib.decompress(raw[pos:], -15)
                except Exception as e:
                    raise RuntimeError(f"Decompression failed for {filepath}: {e}")
        else:
            self.data = raw[pos:]
            
        self.pos = 0
        self.strings = {}
        
        if len(self.data) < 8: return
        num_strings = self.r_u32()
        self.r_u32() 
        for _ in range(num_strings):
            if self.pos + 8 > len(self.data): break
            str_id = self.r_bytes(8)
            if self.pos + 4 > len(self.data): break
            strlen = self.r_u32()
            if self.pos + strlen > len(self.data): break
            self.strings[str_id] = self.r_bytes(strlen).decode('utf-8', 'ignore')
        
        self.doc = xml.dom.minidom.Document()
        self.root, root_xml = self.r_object(self.doc, None)
        self.doc.appendChild(root_xml)
        self.valid = True

        if dump_xml:
            if not out_xml_path:
                out_xml_path = filepath + ".xml"
            with open(out_xml_path, 'wt', encoding='utf-8') as f:
                self.doc.writexml(f, addindent='\t', newl='\n', encoding='UTF-8')

    def r_bytes(self, size):
        v = self.data[self.pos : self.pos+size]
        self.pos += size
        return v
    def r_u8(self):
        v = self.data[self.pos]
        self.pos += 1
        return v
    def r_u32(self):
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v
    def r_i32(self):
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v
    def r_f32(self):
        v = struct.unpack_from('<f', self.data, self.pos)[0]
        self.pos += 4
        return v
    
    def r_object(self, doc, parent=None):
        assert self.r_u8() == 1
        cls_name = self.strings[self.r_bytes(8)]
        count = self.r_u32()
        
        obj_name = 'Element' if parent else 'Object'
        xml_obj = doc.createElement(obj_name)
        xml_obj.setAttribute('Class', cls_name)
        xml_obj.setAttribute('Type', 'object')
        if parent: parent.appendChild(xml_obj)

        dict_obj = {'Class': cls_name, 'Properties': {}}
        for _ in range(count):
            name = self.strings[self.r_bytes(8)]
            prop_dict, prop_xml = self.r_property(doc, xml_obj)
            prop_xml.setAttribute('Name', name)
            xml_obj.appendChild(prop_xml)
            dict_obj['Properties'][name] = prop_dict
            
        return dict_obj, xml_obj

    def r_property(self, doc, parent):
        ptype = self.r_u8()
        prop_xml = None
        if ptype != 7:
            prop_xml = doc.createElement('Property')
            prop_xml.setAttribute('Type', TYPES_MAP.get(ptype, str(ptype)))
            
        dict_val = None
        
        if ptype == 2:
            v = self.r_i32()
            dict_val = v
            prop_xml.setAttribute('Value', str(v))
        elif ptype == 3:
            v = self.r_f32()
            dict_val = v
            prop_xml.setAttribute('Value', str(v))
        elif ptype == 4:
            v = bool(self.r_u8())
            dict_val = v
            prop_xml.setAttribute('Value', str(v).lower())
        elif ptype == 5:
            v = self.strings[self.r_bytes(8)]
            dict_val = v
            prop_xml.setAttribute('Value', v)
        elif ptype == 7:
            obj_id = self.r_u32()
            dict_val, prop_xml = self.r_object(doc, parent)
            prop_xml.setAttribute('ID', str(obj_id))
        elif ptype == 9:
            count = self.r_u32()
            flag = self.r_u8()
            arr_dict = []
            for _ in range(count):
                name = None
                if flag == 1:
                    assert self.r_u8() == 5
                    name = self.strings[self.r_bytes(8)]
                child_dict, child_xml = self.r_property(doc, prop_xml)
                if name:
                    child_xml.setAttribute('Name', name)
                    arr_dict.append((name, child_dict))
                else:
                    arr_dict.append(child_dict)
                prop_xml.appendChild(child_xml)
            dict_val = arr_dict
        elif ptype == 11:
            count = self.r_u32()
            arr_dict = []
            for _ in range(count):
                child_dict, child_xml = self.r_property(doc, prop_xml)
                arr_dict.append(child_dict)
                prop_xml.appendChild(child_xml)
            dict_val = arr_dict
        elif ptype == 13:
            v_bytes = self.r_bytes(8)
            dict_val = v_bytes
            prop_xml.setAttribute('Value', v_bytes.hex())
        elif ptype == 15:
            v = self.strings[self.r_bytes(8)]
            dict_val = v
            prop_xml.setAttribute('Value', v)
        elif ptype == 254:
            dict_val = None
        elif ptype == 255:
            v = self.r_u32()
            dict_val = v
            prop_xml.setAttribute('Value', str(v))
            
        return dict_val, prop_xml

def compile_bod_from_xml(xml_path, out_path):
    if not os.path.exists(xml_path): return False
    try:
        doc = xml.dom.minidom.parse(xml_path)
        strings = {}
        string_list = []

        def add_str(s):
            if s and s not in strings:
                strings[s] = get_sm_hash(s)
                string_list.append(s)

        def gather_strings(node):
            if node.nodeType == node.ELEMENT_NODE:
                if node.tagName in ('Object', 'Element'):
                    add_str(node.getAttribute('Class'))
                if node.hasAttribute('Name'):
                    add_str(node.getAttribute('Name'))
                if node.getAttribute('Type') in ('5', 'hstring'):
                    add_str(node.getAttribute('Value'))
            for child in node.childNodes:
                gather_strings(child)

        gather_strings(doc.documentElement)

        data = bytearray()
        def w_u8(v): data.extend(struct.pack('<B', v))
        def w_u32(v): data.extend(struct.pack('<I', v))
        def w_i32(v): data.extend(struct.pack('<i', v))
        def w_f32(v): data.extend(struct.pack('<f', v))
        def w_bytes(b): data.extend(b)

        def w_property(node):
            if node.tagName in ('Object', 'Element'):
                w_u8(7)
                w_u32(int(node.getAttribute('ID')))
                w_object(node)
                return

            t_str = node.getAttribute('Type')
            ptype = {'int': 2, 'float': 3, 'bool': 4, '5': 5, 'array': 9, 'vector': 11, '13': 13, 'hstring': 15, '254': 254, '255': 255}.get(t_str, 254)
            w_u8(ptype)

            if ptype == 2: w_i32(int(node.getAttribute('Value')))
            elif ptype == 3: w_f32(float(node.getAttribute('Value')))
            elif ptype == 4: w_u8(1 if node.getAttribute('Value').lower() == 'true' else 0)
            elif ptype == 5: w_bytes(strings[node.getAttribute('Value')])
            elif ptype == 9:
                children = [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]
                w_u32(len(children))
                flag = 1 if (len(children) > 0 and children[0].hasAttribute('Name')) else 0
                w_u8(flag)
                for c in children:
                    if flag == 1:
                        w_u8(5)
                        w_bytes(strings[c.getAttribute('Name')])
                    w_property(c)
            elif ptype == 11:
                children = [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]
                w_u32(len(children))
                for c in children:
                    w_property(c)
            elif ptype == 13: w_bytes(bytes.fromhex(node.getAttribute('Value')))
            elif ptype == 15: w_bytes(strings[node.getAttribute('Value')])
            elif ptype == 255: w_u32(int(node.getAttribute('Value')))

        def w_object(node):
            w_u8(1)
            w_bytes(strings[node.getAttribute('Class')])
            children = [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]
            w_u32(len(children))
            for c in children:
                w_bytes(strings[c.getAttribute('Name')])
                w_property(c)

        w_u32(len(string_list))
        total_len = sum(8 + 4 + len(s.encode('utf-8')) for s in string_list)
        w_u32(total_len)
        
        for s in string_list:
            b = s.encode('utf-8')
            w_bytes(strings[s])
            w_u32(len(b))
            w_bytes(b)

        w_object(doc.documentElement)

        out = bytearray(b'BOD\x01\x00\x00\x00\x00\x00\x00')
        out.extend(data)
        
        with open(out_path, 'wb') as f:
            f.write(out)
            
        return True
    except Exception as e:
        raise RuntimeError(f"BOD compilation failed for {xml_path}: {e}")

# =========================================================================
# EXTERNAL BAF CONVERTER WRAPPER (Xml2Baf.exe)
# =========================================================================
class ExternalBAFConverter:
    EXE_PATH = "Xml2Baf.exe"

    @staticmethod
    def baf_to_xml(in_path, out_path):
        if not os.path.exists(ExternalBAFConverter.EXE_PATH):
            raise FileNotFoundError(f"Missing required executable: {ExternalBAFConverter.EXE_PATH}")
            
        try:
            subprocess.run(
                [ExternalBAFConverter.EXE_PATH, "-f", "-x", "-i", in_path, "-o", out_path],
                check=True, 
                creationflags=subprocess.CREATE_NO_WINDOW 
            )
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Xml2Baf.exe failed to unpack {os.path.basename(in_path)}")

    @staticmethod
    def xml_to_baf(in_path, out_path):
        if not os.path.exists(ExternalBAFConverter.EXE_PATH):
            raise FileNotFoundError(f"Missing required executable: {ExternalBAFConverter.EXE_PATH}")
            
        try:
            subprocess.run(
                [ExternalBAFConverter.EXE_PATH, "-f", "-i", in_path, "-o", out_path], 
                check=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Xml2Baf.exe failed to compile {os.path.basename(in_path)}")

# =========================================================================
# UNIFIED TKINTER GUI WITH THEME OVERRIDES
# =========================================================================
class UniversalModdingConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Space Marine Universal Converter")
        self.root.geometry("600x420")
        
        self.dark_mode = tk.BooleanVar(value=True)
        self.always_on_top = tk.BooleanVar(value=False)
        self.pack_big_endian = tk.BooleanVar(value=False)
        self.last_directory = ""
        
        self.setup_menu()
        self.setup_ui()
        self.apply_theme()
        
        self.log("Ready to process assets.", "info")
        self.log("Select files to convert. Native BOD support + Xml2Baf integration active.", "info")

    def setup_menu(self):
        self.menubar = tk.Menu(self.root)
        
        self.options_menu = tk.Menu(self.menubar, tearoff=0)
        self.options_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self.apply_theme)
        self.options_menu.add_checkbutton(label="Always on Top", variable=self.always_on_top, command=self.toggle_topmost)
        self.options_menu.add_separator()
        self.options_menu.add_checkbutton(label="Pack UPC as Big Endian (Console)", variable=self.pack_big_endian)
        self.menubar.add_cascade(label="Options", menu=self.options_menu)

        self.tools_menu = tk.Menu(self.menubar, tearoff=0)
        self.tools_menu.add_command(label="Open Last Output Folder", command=self.open_last_folder)
        self.tools_menu.add_separator()
        self.tools_menu.add_command(label="Clear Log", command=self.clear_log)
        self.menubar.add_cascade(label="Tools", menu=self.tools_menu)
        
        self.root.config(menu=self.menubar)

    def setup_ui(self):
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')

        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.title_label = ttk.Label(main_frame, text="Space Marine Universal Converter", font=("Segoe UI", 16, "bold"))
        self.title_label.pack(pady=(0, 5))
        
        self.desc_label = ttk.Label(main_frame, text="Batch convert .O3d, .object-manifest, .bod, .attr_pc, .PSystem, .Layer, .region, .world, .ssdecal, and .pc files.", font=("Segoe UI", 9))
        self.desc_label.pack(pady=(0, 20))

        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=10)

        style = ttk.Style()
        style.configure("Green.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Blue.TButton", font=("Segoe UI", 10, "bold"))

        self.btn_xml = ttk.Button(controls_frame, text="Extract (to XML / Locale)...", command=self.convert_to_xml, style="Green.TButton", width=25)
        self.btn_xml.pack(side=tk.LEFT, padx=10, expand=True)

        self.btn_binary = ttk.Button(controls_frame, text="Compile (to Binary / PC)...", command=self.convert_to_binary, style="Blue.TButton", width=25)
        self.btn_binary.pack(side=tk.RIGHT, padx=10, expand=True)

        self.log_label = ttk.Label(main_frame, text="Console Output:", font=("Segoe UI", 9, "bold"))
        self.log_label.pack(anchor=tk.W, pady=(15, 5))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_text = tk.Text(text_frame, wrap=tk.WORD, height=12, font=("Consolas", 9), borderwidth=0)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=self.scrollbar.set)
        
        self.log_text.tag_config("info", foreground="black")
        self.log_text.tag_config("success", foreground="#007E33") 
        self.log_text.tag_config("error", foreground="#CC0000")   

    def set_titlebar_color(self, dark_mode=True):
        try:
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE_V2 = 19
            val = ctypes.c_int(2 if dark_mode else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_V2, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def set_menu_theme(self, dark):
        bg = "#2D2D30" if dark else "#F0F0F0"
        fg = "#F1F1F1" if dark else "black"
        for menu in (self.menubar, self.options_menu, self.tools_menu):
            menu.configure(bg=bg, fg=fg)

    def apply_theme(self):
        style = ttk.Style()
        dark = self.dark_mode.get()
        
        self.set_titlebar_color(dark)
        self.set_menu_theme(dark)
        
        if dark:
            bg_color = "#2D2D30"
            fg_color = "#F1F1F1"
            scroll_bg = "#3E3E42"
            scroll_trough = "#1E1E1E"
            
            self.root.configure(bg=bg_color)
            style.configure("TFrame", background=bg_color)
            style.configure("TLabel", background=bg_color, foreground=fg_color)
            
            self.log_text.configure(bg="#1E1E1E", fg="#D4D4D4", insertbackground="#FFFFFF")
            self.log_text.tag_config("info", foreground="#D4D4D4")
            self.log_text.tag_config("success", foreground="#4CAF50")
            self.log_text.tag_config("error", foreground="#F44336")
            
            style.configure("Vertical.TScrollbar", background=scroll_bg, troughcolor=scroll_trough, bordercolor=bg_color, arrowcolor=fg_color)
            style.map("Vertical.TScrollbar", background=[("active", "#505050")])
        else:
            bg_color = "#F0F0F0"
            fg_color = "#000000"
            scroll_bg = "#E0E0E0"
            scroll_trough = "#F0F0F0"
            
            self.root.configure(bg=bg_color)
            style.configure("TFrame", background=bg_color)
            style.configure("TLabel", background=bg_color, foreground=fg_color)
            
            self.log_text.configure(bg="#FFFFFF", fg="#000000", insertbackground="#000000")
            self.log_text.tag_config("info", foreground="#000000")
            self.log_text.tag_config("success", foreground="#007E33")
            self.log_text.tag_config("error", foreground="#CC0000")
            
            style.configure("Vertical.TScrollbar", background=scroll_bg, troughcolor=scroll_trough, bordercolor=bg_color, arrowcolor=fg_color)
            style.map("Vertical.TScrollbar", background=[("active", "#D0D0D0")])

        style.configure("Green.TButton", font=("Segoe UI", 10, "bold"), background="#388E3C", foreground="white", bordercolor=bg_color)
        style.map("Green.TButton", background=[("active", "#4CAF50"), ("pressed", "#2E7D32")])
        
        style.configure("Blue.TButton", font=("Segoe UI", 10, "bold"), background="#1976D2", foreground="white", bordercolor=bg_color)
        style.map("Blue.TButton", background=[("active", "#2196F3"), ("pressed", "#1565C0")])

    def toggle_topmost(self):
        self.root.attributes("-topmost", self.always_on_top.get())

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def open_last_folder(self):
        if self.last_directory and os.path.exists(self.last_directory):
            try:
                os.startfile(self.last_directory)
            except AttributeError:
                subprocess.Popen(['explorer', os.path.normpath(self.last_directory)])
        else:
            messagebox.showinfo("Folder Not Found", "No recent successful conversions to open.")

    def log(self, message, tag="info"):
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)
        self.root.update()

    def convert_to_xml(self):
        filepaths = filedialog.askopenfilenames(
            title="Select Files to Extract/Convert",
            filetypes=[("Space Marine Binary Files", "*.attr_pc *.O3d *.bmat *.object-manifest *.bod *.pc *.PSystem *.Layer *.region *.world *.ssdecal"), ("All Files", "*.*")]
        )
        if not filepaths: return

        self.log(f"\n--- Starting Extraction ({len(filepaths)} files) ---", "info")
        success_count, failed_count = 0, 0

        for in_path in filepaths:
            filename = os.path.basename(in_path)
            self.last_directory = os.path.dirname(in_path)
            
            try:
                if filename.lower().endswith('.attr_pc'):
                    out_path = in_path + ".xml"
                    ExternalBAFConverter.baf_to_xml(in_path, out_path)
                    self.log(f"[OK] External Converter: {filename} -> {filename}.xml", "success")
                elif filename.lower().endswith('.pc'):
                    out_path = in_path[:-3] + ".locale"
                    NativeUPCConverter.unpack_pc(in_path, out_path)
                    self.log(f"[OK] Native UPC: {filename} -> {os.path.basename(out_path)}", "success")
                else:
                    out_path = in_path + ".xml"
                    parser = NativeBODParser(in_path, dump_xml=True, out_xml_path=out_path)
                    if not parser.valid:
                        raise ValueError("Invalid BOD structure.")
                    self.log(f"[OK] Native Parser: {filename} -> {filename}.xml", "success")
                    
                success_count += 1
            except Exception as e:
                self.log(f"[ERROR] Failed {filename}: {e}", "error")
                failed_count += 1

        self.log(f"--- Processing Complete. Success: {success_count} | Failed: {failed_count} ---", "info")

    def convert_to_binary(self):
        filepaths = filedialog.askopenfilenames(
            title="Select XML Files to Compile to Binary",
            filetypes=[("Editable Formats", "*.xml *.locale"), ("All Files", "*.*")]
        )
        if not filepaths: return

        self.log(f"\n--- Starting Binary Compilation ({len(filepaths)} files) ---", "info")
        success_count, failed_count = 0, 0
        use_big_endian = self.pack_big_endian.get()
        BOD_EXTENSIONS = ('.o3d', '.object-manifest', '.bod', '.bmat', '.psystem', '.layer', '.region', '.world', '.ssdecal')

        for in_path in filepaths:
            filename = os.path.basename(in_path)
            self.last_directory = os.path.dirname(in_path)
            lower_name = filename.lower()
            
            try:
                if lower_name.endswith('.locale'):
                    out_path = in_path[:-7] + ".pc"
                    NativeUPCConverter.pack_pc(in_path, out_path, big_endian=use_big_endian)
                    self.log(f"[OK] Native UPC: {filename} -> {os.path.basename(out_path)}", "success")
                else:
                    if lower_name.endswith('.xml'):
                        out_path = in_path[:-4]
                    else:
                        out_path = in_path + ".bin" 

                    base_name = os.path.basename(out_path)
                    lower_base = base_name.lower()
                    
                    if lower_base.endswith('.attr_pc'):
                        ExternalBAFConverter.xml_to_baf(in_path, out_path)
                        self.log(f"[OK] External Compiler: {filename} -> {os.path.basename(out_path)}", "success")
                        
                    elif lower_base.endswith(BOD_EXTENSIONS):
                        compile_bod_from_xml(in_path, out_path)
                        self.log(f"[OK] Native Compiler: {filename} -> {os.path.basename(out_path)}", "success")
                        
                    else:
                        out_path = out_path + '.attr_pc'
                        ExternalBAFConverter.xml_to_baf(in_path, out_path)
                        self.log(f"[OK] Fallback (External): {filename} -> {os.path.basename(out_path)}", "success")
                        
                success_count += 1
            except Exception as e:
                self.log(f"[ERROR] Failed {filename}: {e}", "error")
                failed_count += 1

        self.log(f"--- Processing Complete. Success: {success_count} | Failed: {failed_count} ---", "info")

if __name__ == "__main__":
    root = tk.Tk()
    app = UniversalModdingConverterApp(root)
    root.mainloop()