# FILE: Stores top level logic to unwrap blobs from a snapshot file and parse them

from struct import unpack

from .constants import kAppAOTSymbols, kAppJITMagic, kAppSnapshotPageSize
from .core import Snapshot

has_elftools = False
try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    has_elftools = True
except ImportError as e:
    pass


def parse_elf_snapshot(fname, **kwargs):
    ''' Open and parse an ELF (executable) AppAOT snapshot. Note that the reported
        offsets are virtual addresses, not physical ones. Returns isolate snapshot.
        NOTE: This method requires pyelftools '''
    log = lambda n, x: print(x) if kwargs.get('print_level', 4) >= n else None
    if not has_elftools:
        raise Exception('pyelftools not found, install it to use this method')

    # Open file, obtain symbols
    f = ELFFile(open(fname, 'rb'))
    sections = list(f.iter_sections())
    tables = [ s for s in sections if isinstance(s, SymbolTableSection) ]
    symbols = { sym.name: sym.entry for table in tables for sym in table.iter_symbols() }

    # Extract blobs
    blobs, offsets = [], []
    for s in kAppAOTSymbols:
        s = symbols[s]
        section = next(S for S in sections if 0 <= s.st_value - S['sh_addr'] < S.data_size)
        blob = section.data()[(s.st_value - section['sh_addr']):][:s.st_size]
        assert len(blob) == s.st_size
        blobs.append(blob), offsets.append(s.st_value)

    # Parse VM snapshot, then isolate snapshot
    log(3, '------- PARSING VM SNAPSHOT --------\n')
    base = Snapshot(data=blobs[0], data_offset=offsets[0],
                    instructions=blobs[1], instructions_offset=offsets[1],
                    vm=True, **kwargs).parse()
    log(3, '\n------- PARSING ISOLATE SNAPSHOT --------\n')

    res = Snapshot(data=blobs[2], data_offset=offsets[2],
                    instructions=blobs[3], instructions_offset=offsets[3],
                    base=base, **kwargs).parse()

    archs = { 'EM_386': 'ia32', 'EM_X86_64': 'x64', 'EM_ARM': 'arm', 'EM_AARCH64': 'arm64' }
    if archs.get(f['e_machine']) != res.arch.split('-')[0] or (f.elfclass == 64) != res.is_64:
        log(1, 'WARN: ELF arch ({}) and/or class ({}) not matching snapshot'.format(f['e_machine'], f.elfclass))
    return res

def parse_appjit_snapshot(fname, base=None, **kwargs):
    ''' Open and parse an AppJIT snapshot file. Returns isolate snapshot. '''
    log = lambda n, x: print(x) if kwargs.get('print_level', 3) >= n else None

    # Read header, check magic
    f = open(fname, 'rb')
    magic = unpack('<Q', f.read(8))[0]
    if magic != kAppJITMagic:
        log(1, "WARN: Magic not matching, got 0x{:016x}".format(magic))
    lengths = unpack('<qqqq', f.read(4 * 8))

    # Extract blobs
    blobs, offsets = [], []
    for length in lengths:
        f.seek( ((f.tell() - 1) // kAppSnapshotPageSize + 1) * kAppSnapshotPageSize )
        offsets.append(f.tell())
        blobs.append(f.read(length))

    # Parse VM snapshot if present, then isolate snapshot
    if blobs[0]:
        log(3, '\n------- PARSING VM SNAPSHOT --------\n')
        base = Snapshot(data=blobs[0], data_offset=offsets[0],
                        instructions=blobs[1], instructions_offset=offsets[1],
                        vm=True, **kwargs).parse()
    else:
        log(3, 'No base snapshot, skipping base snapshot parsing...')
        assert not lengths[1]

    log(3, '\n------- PARSING ISOLATE SNAPSHOT --------\n')
    return Snapshot(data=blobs[2], data_offset=offsets[2],
                    instructions=blobs[3], instructions_offset=offsets[3],
                    base=base, **kwargs).parse()
