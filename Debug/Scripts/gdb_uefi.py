"""
Allows loading TianoCore symbols into a GDB session attached to EFI
Firmware.

This is how it works: build GdbSyms - it's a dummy binary that
contains the relevant symbols needed to find and load image symbols.

$ gdb /path/to/GdbSyms.dll
(gdb) target remote ....
(gdb) source Scripts/gdb_uefi.py
(gdb) reload-uefi -o /path/to/GdbSyms.dll

N.B: it was noticed that GDB for certain targets behaves strangely
when run without any binary - like assuming a certain physical
address space size and endianness. To avoid this madness and
seing strange bugs, make sure to pass /path/to/GdbSyms.dll
when starting gdb.

The -o option should be used if you've debugging EFI, where the PE
images were converted from MACH-O or ELF binaries.

"""

import array
import getopt
import binascii
import re
import sys
import os
import subprocess

__license__ = "BSD"
__version = "1.0.0"
__maintainer__ = "Andrei Warkentin"
__email__ = "andrey.warkentin@gmail.com"
__status__ = "Works"

if sys.version_info > (3,):
    long = int

class UefiMisc():
    #
    # Returns string corresponding to type value in specified charset.
    #
    @classmethod
    def parse_string (cls, value, type, charset):
        index = 0
        data = array.array (type)
        while value[index] != 0:
            # TODO: add more ASCII symbols?
            v = value[index]
            if v == 0x0A: # \n
                data.append(0x5C)
                data.append(0x6E)
            elif v == 0x0D: # \r
                data.append(0x5C)
                data.append(0x72)
            elif v == 0x09: # \t
                data.append(0x5C)
                data.append(0x74)
            elif v == 0x22: # "
                data.append(0x5C)
                data.append(0x22)
            elif v == 0x5C: # \
                data.append(0x5C)
                data.append(0x5C)
            else:
                data.append (v)
            index = index + 1
        return data.tostring ().decode (charset)

    #
    # Returns a UTF16 string corresponding to a (CHAR16 *) value in EFI.
    #
    @classmethod
    def parse_utf16 (cls, value):
        return UefiMisc.parse_string (value, 'H', 'utf-16')

    #
    # Returns a UTF8 string corresponding to a (CHAR8 *) value in EFI.
    #
    @classmethod
    def parse_utf8 (cls, value):
        return UefiMisc.parse_string (value, 'B', 'utf-8')

    #
    # Returns a printable EFI or RETURN status.
    #
    @classmethod
    def parse_status (cls, value, efi):
        suffix = ''
        err = 0
        val = long(value)
        if val & 0x80000000:
            err = val & ~0x80000000
        elif val & 0x8000000000000000:
            err = val & ~0x8000000000000000

        if err != 0:
            # TODO: make this a collection...
            if err == 1:
                suffix = 'LOAD_ERROR'
            elif err == 2:
                suffix = 'INVALID_PARAMETER'
            elif err == 3:
                suffix = 'UNSUPPORTED'
            elif err == 4:
                suffix = 'BAD_BUFFER_SIZE'
            elif err == 5:
                suffix = 'BUFFER_TOO_SMALL'
            elif err == 6:
                suffix = 'NOT_READY'
            elif err == 7:
                suffix = 'DEVICE_ERROR'
            elif err == 8:
                suffix = 'WRITE_PROTECTED'
            elif err == 9:
                suffix = 'OUT_OF_RESOURCES'
            elif err == 10:
                suffix = 'VOLUME_CORRUPTED'
            elif err == 11:
                suffix = 'VOLUME_FULL'
            elif err == 12:
                suffix = 'NO_MEDIA'
            elif err == 13:
                suffix = 'MEDIA_CHANGED'
            elif err == 14:
                suffix = 'NOT_FOUND'
            elif err == 15:
                suffix = 'ACCESS_DENIED'
            elif err == 16:
                suffix = 'NO_RESPONSE'
            elif err == 17:
                suffix = 'NO_MAPPING'
            elif err == 18:
                suffix = 'TIMEOUT'
            elif err == 19:
                suffix = 'NOT_STARTED'
            elif err == 20:
                suffix = 'ALREADY_STARTED'
            elif err == 21:
                suffix = 'ABORTED'
            elif err == 22:
                suffix = 'ICMP_ERROR'
            elif err == 23:
                suffix = 'TFTP_ERROR'
            elif err == 24:
                suffix = 'PROTOCOL_ERROR'
            elif err == 25:
                suffix = 'INCOMPATIBLE_VERSION'
            elif err == 26:
                suffix = 'SECURITY_VIOLATION'
            elif err == 27:
                suffix = 'CRC_ERROR'
            elif err == 28:
                suffix = 'END_OF_MEDIA'
            elif err == 31:
                suffix = 'END_OF_FILE'
            elif err == 32:
                suffix = 'INVALID_LANGUAGE'
            elif err == 33:
                suffix = 'COMPROMISED_DATA'
            elif err == 35:
                suffix = 'HTTP_ERROR'
            elif efi and err == 100:
                suffix = 'NETWORK_UNREACHABLE'
            elif efi and err == 101:
                suffix = 'HOST_UNREACHABLE'
            elif efi and err == 102:
                suffix = 'PROTOCOL_UNREACHABLE'
            elif efi and err == 103:
                suffix = 'PORT_UNREACHABLE'
            elif efi and err == 104:
                suffix = 'CONNECTION_FIN'
            elif efi and err == 105:
                suffix = 'CONNECTION_RESET'
            elif efi and err == 106:
                suffix = 'CONNECTION_REFUSED'
        else:
            if val == 0:
                suffix = 'SUCCESS'
            elif val == 1:
                suffix = 'WARN_UNKNOWN_GLYPH'
            elif val == 2:
                suffix = 'WARN_DELETE_FAILURE'
            elif val == 3:
                suffix = 'WARN_WRITE_FAILURE'
            elif val == 4:
                suffix = 'WARN_BUFFER_TOO_SMALL'
            elif val == 5:
                suffix = 'WARN_STALE_DATA'
            elif val == 6:
                suffix = 'WARN_FILE_SYSTEM'
        if suffix != '':
            return ('EFI_' if efi else 'RETURN_') + suffix
        return hex(val)

    #
    # Returns a UTF16 string corresponding to a (CHAR16 *) value in EFI.
    #
    @classmethod
    def parse_guid (cls, value):
        guid = "<%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X>" % (
            value['Data1'],
            value['Data2'],
            value['Data3'],
            value['Data4'][0],
            value['Data4'][1],
            value['Data4'][2],
            value['Data4'][3],
            value['Data4'][4],
            value['Data4'][5],
            value['Data4'][6],
            value['Data4'][7])
        return guid

class ReloadUefi (gdb.Command):
    """Reload UEFI symbols"""

    #
    # Various constants.
    #

    EINVAL = 0xffffffff
    CV_NB10 = 0x3031424E
    CV_RSDS = 0x53445352
    CV_MTOC = 0x434F544D
    DOS_MAGIC = 0x5A4D
    PE32PLUS_MAGIC = 0x20b
    EST_SIGNATURE = 0x5453595320494249L
    DEBUG_GUID = [0x49152E77, 0x1ADA, 0x4764,
                  [0xB7,0xA2,0x7A,0xFE,
                   0xFE,0xD9,0x5E, 0x8B]]
    DEBUG_IS_UPDATING = 0x1

    #
    # If the images were built as ELF/MACH-O and then converted to PE,
    # then the base address needs to be offset by PE headers.
    #

    offset_by_headers = False

    def __init__ (self):
        super (ReloadUefi, self).__init__ ("reload-uefi", gdb.COMMAND_OBSCURE)

    #
    # Returns gdb.Type for a type.
    #

    def type (self, typename):
        return gdb.lookup_type (typename)

    #
    # Returns gdb.Type for a pointer to a type.
    #

    def ptype (self, typename):
        return gdb.lookup_type (typename).pointer ()

    #
    # Computes CRC32 on an array of data.
    #

    def crc32 (self, data):
        return binascii.crc32 (data) & 0xFFFFFFFF

    #
    # Sets a field in a struct to a value, i.e.
    #      value->field_name = data.
    #
    # Newer Py bindings to Gdb provide access to the inferior
    # memory, but not all, so have to do it this awkward way.
    #

    def set_field (self, value, field_name, data):
        gdb.execute ("set *(%s *) 0x%x = 0x%x" % \
            (str (value[field_name].type), \
             long (value[field_name].address), data))

    #
    # Returns data backing a gdb.Value as an array.
    # Same comment as above regarding newer Py bindings...
    #

    def value_data (self, value, bytes=0):
        value_address = gdb.Value (value.address)
        array_t = self.ptype ('UINT8')
        value_array = value_address.cast (array_t)
        if bytes == 0:
            bytes = value.type.sizeof
        data = array.array ('B')
        for i in range (0, bytes):
            data.append (value_array[i])
        return data

    #
    # Locates the EFI_SYSTEM_TABLE as per UEFI spec 17.4.
    # Returns base address or -1.
    #

    def search_est (self):
        address = 0
        estp_t = self.ptype ('EFI_SYSTEM_TABLE_POINTER')
        while True:
            try:
                estp = gdb.Value(address).cast(estp_t)
                if estp['Signature'] == self.EST_SIGNATURE:
                    oldcrc = long(estp['Crc32'])
                    self.set_field (estp, 'Crc32', 0)
                    newcrc = self.crc32 (self.value_data (estp.dereference (), 0))
                    self.set_field (estp, 'Crc32', long(oldcrc))
                    if newcrc == oldcrc:
                        return estp['EfiSystemTableBase']
            except gdb.MemoryError:
                pass

            address = address + 4*1024*1024
            if long(address) == 0:
                return gdb.Value(self.EINVAL)

    #
    # Searches for a vendor-specific configuration table (in EST),
    # given a vendor-specific table GUID. GUID is a list like -
    # [32-bit, 16-bit, 16-bit, [8 bytes]]
    #

    def search_config (self, cfg_table, count, guid):
        index = 0
        while index != count:
            cfg_entry = cfg_table[index]['VendorGuid']
            if cfg_entry['Data1'] == guid[0] and \
                    cfg_entry['Data2'] == guid[1] and \
                    cfg_entry['Data3'] == guid[2] and \
                    self.value_data (cfg_entry['Data4']).tolist () == guid[3]:
                return cfg_table[index]['VendorTable']
            index = index + 1
        return gdb.Value(self.EINVAL)

    #
    # Returns offset of a field within structure. Useful
    # for getting container of a structure.
    #

    def offsetof (self, typename, field):
        t = gdb.Value (0).cast (self.ptype (typename))
        return long(t[field].address)

    #
    # Returns sizeof of a type.
    #

    def sizeof (self, typename):
        return self.type (typename).sizeof

    #
    # Returns the EFI_IMAGE_NT_HEADERS32 pointer, given
    # an ImageBase address as a gdb.Value.
    #

    def pe_headers (self, imagebase):
        dosh_t = self.ptype ('EFI_IMAGE_DOS_HEADER')
        head_t = self.ptype ('EFI_IMAGE_OPTIONAL_HEADER_UNION')
        dosh = imagebase.cast (dosh_t)
        h_addr = imagebase
        if dosh['e_magic'] == self.DOS_MAGIC:
            h_addr = h_addr + dosh['e_lfanew']
        return gdb.Value(h_addr).cast (head_t)

    def pe_sections (self, opt, file, imagebase):
        sect_t = self.ptype ('EFI_IMAGE_SECTION_HEADER')
        sections = (opt.address + 1).cast (sect_t)
        sects = {}
        for i in xrange (file['NumberOfSections']):
            name = UefiMisc.parse_utf8 (sections[i]['Name'])
            addr = long(sections[i]['VirtualAddress'])
            if name != '':
                sects[name] = addr
        return sects

    # TODO: implement pe sections

    #
    # Returns True if pe_headers refer to a PE32+ image.
    #

    def pe_is_64 (self, pe_headers):
        if pe_headers['Pe32']['OptionalHeader']['Magic'] == self.PE32PLUS_MAGIC:
            return True
        return False

    #
    # Returns the PE fileheader.
    #

    def pe_file (self, pe):
        if self.pe_is_64 (pe):
            return pe['Pe32Plus']['FileHeader']
        else:
            return pe['Pe32']['FileHeader']

    #
    # Returns the PE (not so) optional header.
    #

    def pe_optional (self, pe):
        if self.pe_is_64 (pe):
            return pe['Pe32Plus']['OptionalHeader']
        else:
            return pe['Pe32']['OptionalHeader']

    #
    # Returns the symbol file name for a PE image.
    #

    def pe_parse_debug (self, pe):
        opt = self.pe_optional (pe)
        debug_dir_entry = opt['DataDirectory'][6]
        dep = debug_dir_entry['VirtualAddress'] + opt['ImageBase']
        dep = dep.cast (self.ptype ('EFI_IMAGE_DEBUG_DIRECTORY_ENTRY'))
        cvp = dep.dereference ()['RVA'] + opt['ImageBase']
        cvv = cvp.cast(self.ptype ('UINT32')).dereference ()
        if cvv == self.CV_NB10:
            return cvp + self.sizeof('EFI_IMAGE_DEBUG_CODEVIEW_NB10_ENTRY')
        elif cvv == self.CV_RSDS:
            return cvp + self.sizeof('EFI_IMAGE_DEBUG_CODEVIEW_RSDS_ENTRY')
        elif cvv == self.CV_MTOC:
            return cvp + self.sizeof('EFI_IMAGE_DEBUG_CODEVIEW_MTOC_ENTRY')
        return gdb.Value(self.EINVAL)

    #
    # Prepares gdb symbol load command with proper section information.
    # Currently supports Mach-O and single-section files.
    #
    # TODO: Proper ELF support.
    #
    def get_sym_cmd (self, file, orgbase, sections, macho, fallack_base):
        cmd = 'add-symbol-file %s' % file

        # Fallback case, no sections, just load .text.
        if not sections.get('.text') or not sections.get('.data'):
            cmd += ' 0x%x' % (fallack_base)
            return cmd

        cmd += ' 0x%x' % (long(orgbase) + sections['.text'])

        if not macho or not os.path.exists(file):
            # Another fallback, try to load data at least.
            cmd += ' -s .data 0x%x' % (long(orgbase) + sections['.data'])
            return cmd

        # 1. Parse Mach-O.
        # FIXME: We should not rely on otool really.
        commands = subprocess.check_output(['otool', '-l', file])
        in_sect = False
        machsections = {}
        for line in commands.split('\n'):
            line = line.strip()
            if line.startswith('Section'):
                in_sect = True
                sectname = None
                segname = None
            elif in_sect:
                if line.startswith('sectname'):
                    sectname = line.split()[1]
                elif line.startswith('segname'):
                    segname = line.split()[1]
                elif line.startswith('addr'):
                    machsections[segname + '.' + sectname] = long(line.split()[1], base=16)
                    in_sect = False

        # 2. Convert section names to gdb sections.
        mapping = {
            '__TEXT.__cstring':         '.cstring',
            '__TEXT.__const':           '.const',
            '__TEXT.__ustring':         '__TEXT.__ustring',
            '__DATA.__const':           '.const_data',
            '__DATA.__data':            '.data',
            '__DATA.__bss':             '.bss',
            '__DATA.__common':          '__DATA.__common',
            # FIXME: These should not be loadable, but gdb still loads them :/
            # '__DWARF.__apple_names':    '__DWARF.__apple_names',
            # '__DWARF.__apple_namespac': '__DWARF.__apple_namespac',
            # '__DWARF.__apple_types':    '__DWARF.__apple_types',
            # '__DWARF.__apple_objc':     '__DWARF.__apple_objc',
        }

        # 3. Rebase.
        for entry in mapping:
            if machsections.get(entry):
                cmd += ' -s %s 0x%x' % (mapping[entry], long(orgbase) + machsections[entry])

        return cmd

    #
    # Parses an EFI_LOADED_IMAGE_PROTOCOL, figuring out the symbol file name.
    # This file name is then appended to list of loaded symbols.
    #
    # TODO: Support TE images.
    #

    def parse_image (self, image, syms):
        orgbase = base = image['ImageBase']
        pe = self.pe_headers (base)
        opt = self.pe_optional (pe)
        file = self.pe_file (pe)
        sym_name = self.pe_parse_debug (pe)
        sections = self.pe_sections (opt, file, base)

        # For ELF and Mach-O-derived images...
        if self.offset_by_headers:
            base = base + opt['SizeOfHeaders']
        if sym_name != self.EINVAL:
            sym_name = sym_name.cast (self.ptype('CHAR8')).string ()
            sym_name_dbg = re.sub(r"\.dll$", ".debug", sym_name)
            macho = False
            if os.path.isdir(sym_name + '.dSYM'):
                sym_name += '.dSYM/Contents/Resources/DWARF/' + os.path.basename(sym_name)
                macho = True
            elif sym_name_dbg != sym_name and os.path.exists(sym_name_dbg):
                # TODO: implement .elf handling.
                sym_name = sym_name_dbg
            syms.append (self.get_sym_cmd (sym_name, long(orgbase), sections, macho, long(base)))

    #
    # Parses table EFI_DEBUG_IMAGE_INFO structures, builds
    # a list of add-symbol-file commands, and reloads debugger
    # symbols.
    #

    def parse_edii (self, edii, count):
        index = 0
        syms = []
        while index != count:
            entry = edii[index]
            if entry['ImageInfoType'].dereference () == 1:
                entry = entry['NormalImage']
                self.parse_image(entry['LoadedImageProtocolInstance'], syms)
            else:
                print ("Skipping unknown EFI_DEBUG_IMAGE_INFO (Type 0x%x)" % \
                        entry['ImageInfoType'].dereference ())
            index = index + 1
        gdb.execute ("symbol-file")
        print ("Loading new symbols...")
        for sym in syms:
            try:
                gdb.execute (sym)
            except (gdb.error) as err:
                print ('Failed: %s' % err)

    #
    # Parses EFI_DEBUG_IMAGE_INFO_TABLE_HEADER, in order to load
    # image symbols.
    #

    def parse_dh (self, dh):
        dh_t = self.ptype ('EFI_DEBUG_IMAGE_INFO_TABLE_HEADER')
        dh = dh.cast (dh_t)
        print ("DebugImageInfoTable @ 0x%x, 0x%x entries" % \
                (long (dh['EfiDebugImageInfoTable']), dh['TableSize']))
        if dh['UpdateStatus'] & self.DEBUG_IS_UPDATING:
            print ("EfiDebugImageInfoTable update in progress, retry later")
            return
        self.parse_edii (dh['EfiDebugImageInfoTable'], dh['TableSize'])

    #
    # Parses EFI_SYSTEM_TABLE, in order to load image symbols.
    #

    def parse_est (self, est):
        est_t = self.ptype ('EFI_SYSTEM_TABLE')
        est = est.cast (est_t)
        print ("Connected to %s (Rev. 0x%x)" % \
                (UefiMisc.parse_utf16 (est['FirmwareVendor']), \
                long (est['FirmwareRevision'])))
        print ("ConfigurationTable @ 0x%x, 0x%x entries" % \
                (long (est['ConfigurationTable']), est['NumberOfTableEntries']))

        dh = self.search_config(est['ConfigurationTable'],
                est['NumberOfTableEntries'], self.DEBUG_GUID)
        if dh == self.EINVAL:
            print ("No EFI_DEBUG_IMAGE_INFO_TABLE_HEADER")
            return
        self.parse_dh (dh)

    #
    # Usage information.
    #

    def usage (self):
        print ("Usage: reload-uefi [-o] [/path/to/GdbSyms.dll]")

    #
    # Handler for reload-uefi.
    #

    def invoke (self, arg, from_tty):
        args = arg.split(' ')
        try:
            opts, args = getopt.getopt(args, "o", ["offset-by-headers"])
        except (getopt.GetoptError) as err:
            self.usage ()
            return
        for opt, arg in opts:
            if opt == "-o":
                self.offset_by_headers = True

        if len(args) >= 1 and args[0] != '':
            gdb.execute ("symbol-file")
            gdb.execute ("symbol-file %s" % args[0])
        else:
            # FIXME: gdb.objfiles () loses files after symbol-file execution,
            # so we have to extract GdbSymbs.dll manually.
            lines = gdb.execute ("info files", to_string=True).split('\n')
            for line in lines:
                m = re.search("`([^']+)'", line)
                if m:
                    gdb.execute ("symbol-file")
                    gdb.execute ("symbol-file %s" % m.group(1))
                    break

        est = self.search_est ()
        if est == self.EINVAL:
            print ("No EFI_SYSTEM_TABLE...")
            return

        print ("EFI_SYSTEM_TABLE @ 0x%x" % est)
        self.parse_est (est)

class UefiStringPrinter:
    def __init__(self, val):
        self.val = val

    def to_string (self):
        if not self.val:
            return "NULL"
        return 'L"' + UefiMisc.parse_utf16(self.val) + '"'

class UefiEfiStatusPrinter:
    def __init__(self, val):
        self.val = val

    def to_string (self):
        return UefiMisc.parse_status(self.val, True)

class UefiReturnStatusPrinter:
    def __init__(self, val):
        self.val = val

    def to_string (self):
        return UefiMisc.parse_status(self.val, False)

class UefiGuidPrinter:
    def __init__(self, val):
        self.val = val

    def to_string (self):
        return UefiMisc.parse_guid(self.val)

def lookup_uefi_type (val):
    if str(val.type) == 'const CHAR16 *' or str(val.type) == 'CHAR16 *':
        return UefiStringPrinter(val)
    elif str(val.type) == 'EFI_STATUS':
        return UefiEfiStatusPrinter(val)
    elif str(val.type) == 'RETURN_STATUS':
        return UefiReturnStatusPrinter(val)
    elif str(val.type) == 'GUID' or str(val.type) == 'EFI_GUID':
        return UefiGuidPrinter(val)
    return None

ReloadUefi ()
gdb.pretty_printers.append (lookup_uefi_type)
