import re
from collections import defaultdict
from os import environ
from shutil import copy as shcopy
from string import printable, whitespace
from sys import argv, exc_info, stdout
from traceback import print_exc

from randomtools.scriptparser import Instruction, Parser
from randomtools.utils import (TextDecoder, cached_property, clached_property,
                               hexify, md5hash)

EVENT_POINTER_ADDRESS = 0x98000
VERSION = 0xff
OPTIMIZE = False

EXPECTED_CHECKSUM = '7c700360a46f54796802ca7c7bf499c5'


def rewrite_gameboy_header(filename, msg):
    DESTINATION_CODE_OFFSET = 0x14a
    TITLE_OFFSET = 0x134
    TITLE_LENGTH = 0x10
    assert len(msg) <= TITLE_LENGTH
    msg = msg.encode('ascii')
    while len(msg) < TITLE_LENGTH:
        msg += b'\x00'
    HEADER_RANGE = (0x134, 0x14d)
    VERSION_OFFSET = 0x14c
    HEADER_CHECKSUM_OFFSET = 0x14d
    ROM_CHECKSUM_OFFSET = 0x14e

    f = open(filename, 'r+b')
    f.seek(DESTINATION_CODE_OFFSET)
    f.write(b'\xab')
    f.seek(TITLE_OFFSET)
    #f.write(msg)
    f.seek(VERSION_OFFSET)
    f.write(int(VERSION).to_bytes(length=1, byteorder='big'))
    f.seek(HEADER_RANGE[0])
    header = f.read(HEADER_RANGE[1]-HEADER_RANGE[0])
    header_checksum = 0x8000
    for c in header:
        header_checksum -= (c + 1)
    header_checksum &= 0xff
    f.seek(HEADER_CHECKSUM_OFFSET)
    f.write(header_checksum.to_bytes(length=1, byteorder='big'))
    f.seek(ROM_CHECKSUM_OFFSET)
    f.write(b'\x00\x00')
    f.seek(0)
    rom_checksum = 0
    while True:
        c = f.read(1)
        if c == b'':
            break
        rom_checksum += ord(c)
    f.seek(ROM_CHECKSUM_OFFSET)
    f.write((rom_checksum & 0xffff).to_bytes(length=2, byteorder='big'))
    f.close()


def import_font(font_filename, filename, font_offset=0x74ba0,
                first_character=0x71):
    print('Importing font...')
    font_offset = font_offset - (first_character * 0x10)
    with open(font_filename, 'r+b') as f:
        with open(filename, 'r+b') as g:
            for i in range(first_character, 0x100):
                f.seek(i * 0x10)
                tile = f.read(0x10)
                if len(tile) != 0x10:
                    break
                if set(tile) <= {0} or set(tile) <= {0xff}:
                    continue
                offset = font_offset + (i*0x10)
                g.seek(offset)
                g.write(tile)


class GoeDecoder(TextDecoder):
    NULL_CHARACTER = None
    TABLE = {
        0x07:   '\n',
        0x18:   '　',
        0x71:   'あいうえおかきくけこさしすせそた'
                'ちつてとなにぬねのはひふへほまみ'
                'むめもやゆよらりるれろわをんぁぃ'
                'ぅぇぉっゃゅょがぎぐげござじずぜ'
                'ぞだぢづでどばびぶべぼぱぴぷぺぽ',

        0xc1:   'アイウエオカキクケコサシスセソタ'
                'チツテトナニヌネノハヒフヘホマミ'
                'ムメモヤユヨラリルレロワヲンァィ'
                'ゥェォッャュョガギグゲゴザジズ',

        0x7000: 'ゼ'
                'ゾダヂヅデドバビブベボパピプペポ',
        0x7011: 'ー０１２３４５６７８９。、？！＝',
        0x7021: '／×〜・．：＇％［］【】『』（）',
        0x7031: '💧♥★💀両段体技◯ＦＢＧ〝︒全単',
        0x7041: '自ＨＰⒽ♪♫丸⧅ⓁＡ',
        0x706e: '🞀🞃🞂',
        }

    WORDS = {
        0x03:   '<continue>',
        0x04:   '<close>',
        0x05:   '<blink>',
        0x06:   '<noblink>',
        0x0a:   '<pause>',
        0x0b:   '<unk0b>',
        0x0c:   '<unk0c>',
        0x0e:   '<item>',
        0x10:   '<unk10>',
        0x7061: '<human>',
        0x7062: '<beast>',
        0x7063: '<insect>',
        0x7064: '<fish>',
        0x7065: '<bird>',
        0x7066: '<plant>',
        0x7067: '<metal>',
        0x7068: '<ghost>',
        0x7069: '<fire>',
        0x706a: '<water>',
        0x706b: '<earth>',
        0x706c: '<wood>',
        0x706d: '<air>',
        }

    ALTS = {c: (ord(c)|0x80) for c in printable
            if ord(c) < 0x80 and c not in whitespace}
    ALTS[' '] = 0x18


DECODER = GoeDecoder()


class GoeParser(Parser):
    SCRIPT_CONFIG = 'parser_config.yaml'
    FIRST_PARSER = None

    common_words = []

    def __init__(self, *args, **kwargs):
        self.locked_in_bytecode = b''
        self.locked_in_pointers = {}
        self.inline_string_counter = defaultdict(int)
        if 'page' in kwargs:
            self.page = kwargs['page']
            del(kwargs['page'])
        else:
            self.page = None
        if self.page == 0x1e:
            GoeParser.FIRST_PARSER = self
        return super().__init__(*args, **kwargs)

    @clached_property
    def common_word_scripts(self):
        pointers = EventPointer.ALL_POINTERS[:0x10]
        return [self.FIRST_PARSER.scripts[p.offset] for p in pointers]

    def update_format_length(self):
        self.format_length = 21
        self.address_length = 4

    def format_inline_text(self, bytecode):
        return DECODER.decode(bytecode)

    def compress_first_pass(self, bytecode):
        bytecode += b'\x70\x70'
        counter = 0
        prev = None
        compressed = b''
        for c in bytecode:
            c = c.to_bytes(length=1)
            if prev == b'\x70':
                compressed += prev
                compressed += c
                prev = None
                c = None
            elif c == prev:
                counter += 1
                continue
            elif counter >= 2 and prev == b'\x18':
                while counter > 0:
                    length = min(counter, 0xf+2)
                    counter -= length
                    assert length >= 2
                    compressed += (0x30+length-2).to_bytes(length=1)
                assert counter == 0
            elif counter >= 3:
                while counter > 0:
                    length = min(counter, 0xf+3)
                    counter -= length
                    assert length >= 3
                    compressed += (0x50+length-3).to_bytes(length=1)
                    compressed += prev
                assert counter == 0
            elif prev is not None:
                compressed += (prev * counter)
            prev = c
            counter = 1
        if prev is not None:
            compressed += (prev * counter)
        assert compressed.endswith(b'\x70\x70')
        compressed = compressed[:-2]
        return compressed

    def replace_inline_substring(self, inline, substring, replacement):
        while True:
            if substring not in inline:
                break
            for index in range(0, len(inline)):
                if index > 0 and inline[index-1] == 0x70:
                    continue
                if inline[index] != substring[0]:
                    continue
                y = inline[index:index+len(substring)]
                if y != substring:
                    continue
                x = inline[:index]
                z = inline[index+len(substring):]
                inline = x + replacement + z
                break
            else:
                break
        return inline

    def encode(self, text):
        inline_string = DECODER.encode(text)
        #compressed = self.compress_first_pass(inline_string)
        #self.inline_string_counter[compressed] += 1
        return inline_string

    def get_next_instruction(self, script, start_address=None, recurse=0):
        inst = super().get_next_instruction(script, start_address)
        if len(self.original_pointers) <= 1:
            return inst
        if inst is None:
            return None
        old_num_instructions = len(script.instructions)
        if inst.opcode == 0x30:
            script.instructions = script.instructions[:-1]
            length = inst.parameters['length'] + 2
            for _ in range(length):
                self.Instruction(script=script, opcode=0x18, parameters={})
        if inst.opcode == 0x40:
            script.instructions = script.instructions[:-1]
            other_script = self.common_word_scripts[inst.parameters['word']]
            for i in other_script.instructions:
                if i.opcode == 0:
                    break
                self.Instruction(script=script, opcode=i.opcode,
                                 parameters=dict(i.parameters))
        if inst.opcode == 0x50:
            script.instructions = script.instructions[:-1]
            length = inst.parameters['length'] + 3
            for _ in range(length):
                self.Instruction(
                        script=script, opcode=0x71,
                        parameters={'character':inst.parameters['character']})
        if inst.opcode == 0x60:
            if recurse > 0:
                return inst
            assert recurse == 0
            script.instructions = script.instructions[:-1]
            script_pointer = self.data.tell()
            address = inst.parameters['address']
            assert address & 0xc000 == 0x4000
            address &= 0x3fff
            self.data.seek(address)

            while True:
                self.get_next_instruction(script, recurse=recurse+1)
                prev = script.instructions[-1]
                assert prev.manifest['is_inline_text']
                length = self.data.tell() - address
                if length >= inst.parameters['length'] + 4:
                    assert length == inst.parameters['length'] + 4
                    break
            self.data.seek(script_pointer)

        if len(script.instructions) > old_num_instructions:
            for n, i in enumerate(script.instructions):
                if n < old_num_instructions-1:
                    continue
                i.start_address = 0xf000 + n
                i.end_address = i.start_address + 1
        inst = script.instructions[-1]
        return inst

    def count_inline_strings(self):
        self.inline_string_counter = defaultdict(int)
        for script in self.scripts.values():
            temp = []
            for i in script.instructions:
                if i.manifest['is_inline_text']:
                    temp.append(i.bytecode)
                else:
                    temp.append(None)
            bytestrings = []
            while temp:
                if not temp:
                    break
                if temp[0] is None:
                    temp = temp[1:]
                    continue
                if None not in temp:
                    s = b''.join(temp)
                    bytestrings.append(s)
                    break
                index = temp.index(None)
                s = b''.join(temp[:index])
                bytestrings.append(s)
                temp = temp[index:]
            for bytestring in bytestrings:
                self.inline_string_counter[bytestring] += 1

    def lock_in_inline(self, instructions):
        if not instructions:
            return
        done_index = 0
        MAX_LOOKBACK_LENGTH = 0xf + 4
        for index in range(len(instructions)):
            if index < done_index:
                continue
            best_lookback = b''
            best_common = b''
            best_repeat = b''
            index_length = {}
            if len(instructions)+1-index >= 3:
                for length in range(1, len(instructions)+1-index):
                    subinsts = instructions[index:index+length]
                    bytecode = b''.join(i.bytecode for i in subinsts)
                    index_length[bytecode] = length
                    if len(bytecode) < MAX_LOOKBACK_LENGTH and \
                            bytecode in self.locked_in_bytecode:
                        best_lookback = bytecode
                    if bytecode in GoeParser.common_words:
                        best_common = bytecode
                    if len(set(bytecode)) == 1 and len(bytecode) == 4:
                        best_repeat = bytecode
            lookback_score = len(best_lookback) - 3
            common_score = len(best_common) - 1
            test_repeat = self.compress_first_pass(best_repeat)
            repeat_score = len(best_repeat) - len(test_repeat)
            if max(lookback_score, common_score, repeat_score) <= 0:
                self.locked_in_bytecode += instructions[index].bytecode
                continue
            if repeat_score >= max(common_score, lookback_score):
                self.locked_in_bytecode += test_repeat
                done_index = index + index_length[best_repeat]
            elif common_score >= lookback_score:
                comdex = GoeParser.common_words.index(best_common)
                assert 0 <= comdex <= 0xf
                self.locked_in_bytecode += (0x40+comdex).to_bytes(length=1)
                done_index = index + index_length[best_common]
            else:
                lookback_index = self.locked_in_bytecode.index(best_lookback)
                lookback_index |= 0x4000
                lookback_index = lookback_index.to_bytes(length=2,
                                                         byteorder='little')
                length = len(best_lookback)-4
                opcode = (0x60+length).to_bytes(length=1)
                self.locked_in_bytecode += opcode + lookback_index
                done_index = index + index_length[best_lookback]

    def lock_in(self, pointer):
        script = self.scripts[pointer]
        script.pointer.repointer = len(self.locked_in_bytecode)
        if self.page == 0x1e and script in GoeParser.common_word_scripts:
            self.locked_in_pointers[pointer] = script.pointer.repointer
            self.locked_in_bytecode += script.bytecode
            return

        if OPTIMIZE and script.bytecode in self.locked_in_bytecode:
            script.pointer.repointer = \
                    self.locked_in_bytecode.index(script.bytecode)
            self.locked_in_pointers[pointer] = script.pointer.repointer
            return

        before = self.locked_in_bytecode
        inline = []
        for instruction in script.instructions:
            if instruction.manifest['is_inline_text']:
                inline.append(instruction)
                continue
            if inline:
                self.lock_in_inline(inline)
                inline = []
            self.locked_in_bytecode += instruction.bytecode
        self.lock_in_inline(inline)

        appendage = self.locked_in_bytecode[len(before):]
        if OPTIMIZE and appendage in before:
            self.locked_in_bytecode = before
            script.pointer.repointer = \
                    self.locked_in_bytecode.index(appendage)

        self.locked_in_pointers[pointer] = script.pointer.repointer


class EventPointer:
    ALL_POINTERS = []
    ALL_POINTERS_BY_PAGE = defaultdict(list)
    PAGE_POINTER_CACHE = {}
    REVERSE_ASSOCIATIONS = defaultdict(set)

    def __init__(self, page, offset):
        self.page = page
        assert offset & 0xc000 == 0x4000
        self.offset = offset & 0x3fff
        self.original_offset = self.offset
        self.associated_script = None
        self.ALL_POINTERS.append(self)
        self.ALL_POINTERS_BY_PAGE[self.page].append(self)
        self.signature

    def __repr__(self):
        return f'<{self.file_offset:0>6x} ({self.page:0>2x})>'

    def __hash__(self):
        return self.signature.__hash__()

    @cached_property
    def signature(self):
        return f'{self.page:0>2x}-{self.page_index:0>3x}'

    @property
    def file_offset(self):
        assert 0 <= self.offset <= 0x3fff
        return (self.page << 14) | self.offset

    @property
    def bytestring(self):
        return bytes([self.page]) + (self.offset | 0x4000).to_bytes(
                length=2, byteorder='little')

    @classmethod
    def get_by_page(self, page):
        return self.ALL_POINTERS_BY_PAGE[page]

    @classmethod
    def get_pointer(self, pointer, page=None):
        if page is None:
            page = pointer >> 16
        pointers = [p for p in self.get_by_page(page)
                    if p.original_offset == pointer & 0x3fff]
        if len(pointers) == 1:
            return pointers[0]
        if len(pointers) >= 2:
            raise Exception(f'Ambiguous pointer: {page:0>2x}/{pointer:0>4x}')

    @classmethod
    def get_pointer_by_page_index(self, index, page):
        pointers = self.get_by_page(page)
        return pointers[index]

    @classmethod
    def associate(self, pointers, parser):
        scripts = parser.scripts.values()
        for p in pointers:
            candidates = [s for s in scripts
                          if s.pointer.old_pointer == p.offset]
            if len(candidates) >= 2:
                raise Exception(f'Ambiguous scripts: '
                                f'{p.page:0>2x}/{p.offset:0>4x}')
            assert len(candidates) == 1
            p.associated_script = candidates[0]
            assert p.associated_script.parser.page == p.page
            self.REVERSE_ASSOCIATIONS[p.associated_script].add(p)

    @property
    def page_index(self):
        return self.get_by_page(self.page).index(self)

    def set_pointer(self, pointer, page=None):
        if page is None:
            page = self.page
        if pointer > 0x3fff:
            assert (pointer >> 16) == page
            assert (pointer >> 14) & 0xb11 == 1
        self.offset = pointer & 0x3fff
        self.page = page


def extract_event_pointers(filename):
    pointers = []
    with open(filename, 'r+b') as f:
        f.seek(EVENT_POINTER_ADDRESS)
        while True:
            page = ord(f.read(1))
            if page == 0xff:
                break
            offset = int.from_bytes(f.read(2), byteorder='little')
            assert offset & 0xc000 == 0x4000
            pointers.append(EventPointer(page, offset))
    return pointers


def write_event_pointers(filename, pointers):
    with open(filename, 'r+b') as f:
        f.seek(EVENT_POINTER_ADDRESS)
        for p in pointers:
            f.write(p.bytestring)


def extract_scripts(filename):
    print('Extracting scripts...')
    if not EventPointer.ALL_POINTERS:
        extract_event_pointers(filename)

    #scripts = {}
    for page in range(0x80):
        pointers = EventPointer.get_by_page(page)
        if not pointers:
            continue

        with open(filename, 'r+b') as f:
            f.seek(page << 14)
            data = f.read(0x4000)
        parser = GoeParser(GoeParser.SCRIPT_CONFIG, data,
                           [p.offset for p in pointers], page=page)
        EventPointer.associate(pointers, parser)
        #for i, s in enumerate(sorted(parser.scripts.values())):
        #    p = (s.pointer.old_pointer & 0x3fff) | (page << 14)
        #    identifier = (page, i, p)
        #    assert identifier not in scripts
        #    scripts[identifier] = s

    scripts = {}
    for ep in EventPointer.ALL_POINTERS:
        script = ep.associated_script
        scripts[ep.page, ep.page_index, ep.file_offset] = script

    return scripts


def export_scripts(scriptfile, romfile=None, scripts=None):
    if scripts is None:
        scripts = extract_scripts(romfile)

    unassociated_scripts = [s for s in scripts.values()
                            if not EventPointer.REVERSE_ASSOCIATIONS[s]]
    associated_scripts = [s for s in scripts.values()
                          if s not in unassociated_scripts]
    matches = defaultdict(set)
    for ua in unassociated_scripts:
        try:
            best_match = max(s for s in associated_scripts
                             if s.pointer < us.pointer)
        except ValueError:
            import pdb; pdb.set_trace()
        matches[best_match].add(ua)

    with open(scriptfile, 'w+') as f:
        for pointer in EventPointer.ALL_POINTERS:
            page = pointer.page
            i = pointer.page_index
            p = pointer.file_offset
            script = pointer.associated_script
            f.write(f'! SCRIPT {page:0>2x}-{i:0>3x}-{p:0>6x}\n')
            f.write(f'{script}\n\n')
            for ua in matches[script]:
                f.write(f'{ua}\n\n')


def build_common_word_list(all_parsers):
    ALLOWED_BANKS = {0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23}
    TARGET_LIST_SIZE = 0x10
    first_parser = min(all_parsers, key=lambda p: p.page)
    assert first_parser.page == 0x1e
    parsers = {p for p in all_parsers if p.page in ALLOWED_BANKS}
    chosen = set()

    while True:
        if len(chosen) >= TARGET_LIST_SIZE:
            break
        stdout.write(f'{TARGET_LIST_SIZE-len(chosen)} ')
        stdout.flush()
        chosen = sorted(chosen, key=lambda c: (-len(c), c))
        substring_bank_tracker = {}
        for parser in parsers:
            for inline, count in parser.inline_string_counter.items():
                original_inline = inline
                for c in chosen:
                    if inline in c:
                        inline = b''
                    if c not in inline:
                        continue
                    inline = first_parser.replace_inline_substring(
                        inline, c, b'\x70\x70')
                if len(inline) < 2:
                    continue
                done_substrings = set()
                for index in range(0, len(inline)-1):
                    if index > 0 and inline[index-1] == 0x70:
                        if index == 1 or inline[index-2] != 0x70:
                            continue
                    for length in range(2, len(inline)+1-index):
                        if inline[index+length-1] == 0x70:
                            continue
                        substring = inline[index:index+length]
                        if b'\x70\x70' in substring:
                            continue
                        if substring in done_substrings:
                            continue
                        done_substrings.add(substring)
                        assert len(substring) == length
                        assert substring[-1] != 0x70
                        if substring not in substring_bank_tracker:
                            substring_bank_tracker[substring] = \
                                    defaultdict(int)
                        substring_bank_tracker[substring][parser.page] += count

        scores = {}
        for substring in substring_bank_tracker:
            counts = sorted(substring_bank_tracker[substring].values())
            while len(counts) < len(ALLOWED_BANKS):
                counts.insert(0, 0)
            median_count = counts[len(counts)>>1]
            #scores[substring] = (len(substring)-1) * count
            if median_count > 0:
                score1 = median_count * (len(substring)-1)
                score2 = sum(counts) * (len(substring)-1)
                scores[substring] = (-score1, -score2)

        scored = sorted(scores, key=lambda s: (scores[s], s))
        for s in scored:
            choose_it = True
            for c in chosen:
                if s in c:
                    choose_it = False
            if choose_it:
                chosen.append(s)
                break
    stdout.write('\n')
    stdout.flush()

    scores = defaultdict(int)
    for parser in parsers:
        for c in sorted(chosen):
            for inline, count in parser.inline_string_counter.items():
                cc = inline.count(c)
                scores[c] += cc * count * (len(c)-1)

    chosen = sorted(chosen, key=lambda c: (-len(c), -scores[c], c))

    common_words = []
    assert first_parser.page == 0x1e
    scripts = GoeParser.common_word_scripts
    for c, script in zip(chosen, scripts):
        common_words.append(c)
        decoded = DECODER.decode(c)
        decoded = decoded.replace('\n', '|\n|')
        script_text = (f'@{script.pointer.old_pointer:x}\n'
                       f'|{decoded}|\n'
                       f'0000. 00:\n')
        first_parser.import_script(script_text)
    GoeParser.common_words = common_words


def import_scripts(scriptfile, romfile, outfile=None, scripts=None):
    TEXT_MATCHER = re.compile(r'^[^|]*\|([^|]+)\|')
    BRACKET_MATCHER = re.compile('<[^>]+>')
    if outfile is None:
        a = '.'.join(romfile.split('.')[:-1])
        if not a.strip():
            a = romfile
        b = '.'.join(scriptfile.split('.')[:-1])
        if not b.strip():
            b = scriptfile
        outfile = f'{a}.{b}.gbc'

    letters = set(GoeDecoder.ALTS.keys())

    assert romfile != outfile
    shcopy(romfile, outfile)

    if scripts is None:
        scripts = extract_scripts(outfile)

    temp = {}
    for (page, i, p) in scripts:
        assert (page, i) not in temp
        temp[page, i] = scripts[page, i, p]
    scripts = temp

    script_texts = defaultdict(str)
    active_script, identifier = None, None
    with open(scriptfile) as f:
        for line in f:
            if not line.strip():
                continue
            match = TEXT_MATCHER.match(line)
            if match:
                text = match.group(1)
                bmatches = BRACKET_MATCHER.findall(text)
                if bmatches:
                    for bmatch in bmatches:
                        text = text.replace(bmatch, '')
                if len(text) > 12 and letters & set(text):
                    print(f'Warning: Script {identifier} exceeds '
                          f'12-character line limit.')
            if line.startswith('! SCRIPT '):
                _, _, identifier = line.strip().split(' ')
                page, i, p = identifier.split('-')
                page = int(page, 0x10)
                i = int(i, 0x10)
                p = int(p, 0x10)
                if (page, i) not in scripts:
                    import pdb; pdb.set_trace()
                    raise Exception(f'Invalid script: {identifier}')
                active_script = scripts[(page, i)]
                assert active_script.parser.page == page
                continue
            else:
                script_texts[active_script] += line

    all_pointers = [p.file_offset for p in EventPointer.ALL_POINTERS]

    print(f'Importing scripts...')
    for script, text in script_texts.items():
        script.parser.import_script(text)
    print(f'Analyzing word usage...')
    parsers = {script.parser for script in scripts.values()}
    for parser in parsers:
        parser.count_inline_strings()
    build_common_word_list(parsers)

    page_sizes = {}
    all_scripts = set()
    for parser in sorted(parsers, key=lambda p: p.page):
        print(f'Compressing text (page {parser.page:0>2X})...')
        for p, script in sorted(parser.scripts.items()):
            all_scripts.add(script)
            parser.lock_in(p)
        with open(outfile, 'r+b') as f:
            f.seek(parser.page * 0x4000)
            old_data = f.read(0x4000)
            last_byte = old_data[-1]
            if last_byte in (0, 0xff):
                while old_data[-1] == last_byte:
                    old_data = old_data[:-1]

            f.seek(parser.page * 0x4000)
            new_data = parser.locked_in_bytecode
            page_sizes[parser.page] = (len(old_data), len(new_data))
            if len(new_data) < 0x4000:
                new_data += b'\xff' * (0x4000-len(new_data))
                assert len(new_data) == 0x4000
            if len(new_data) <= 0x4000:
                f.write(new_data)

    print('Final page usage:')
    for page, (old, new) in page_sizes.items():
        print(f'  {page:0>2X}: {old:0>4x} -> {new:0>4x}')
    for page, (old, new) in page_sizes.items():
        if new > 0x4000:
            raise Exception(f'Not enough space - page {page:0>2X}')

    #all_pointers = [p.file_offset for p in EventPointer.ALL_POINTERS]
    #assert all_pointers == sorted(all_pointers)
    for ep in EventPointer.ALL_POINTERS:
        script = ep.associated_script
        ep.offset = script.pointer.repointer
        assert 0 <= ep.offset <= 0x3fff
    write_event_pointers(outfile, EventPointer.ALL_POINTERS)

    return outfile


def scripter_main():
    romfile = None
    if len(argv) > 1:
        romfile = argv[1]

    envs = {
        'GOE_EXPORT': None,
        'GOE_IMPORT': None,
        'GOE_FONT': None,
        'GOE_ROM': None,
        'GOE_OUTPUT': None,
        }
    for key in envs:
        if key in environ:
            envs[key] = environ[key]

    if envs['GOE_ROM']:
        romfile = envs['GOE_ROM']

    if not any(envs.values()):
        print('Select one:\n'
              ' 1. Export game script\n'
              ' 2. Import game script')
        x = input('Input 1 or 2: ')
        x = x.strip()
        if x not in ('1', '2'):
            exit(0)
        if romfile is None:
            envs['GOE_ROM'] = input('Input rom file name: ').strip()
            romfile = envs['GOE_ROM']
        if x == '1':
            envs['GOE_EXPORT'] = f"{envs['GOE_ROM']}.export.txt"
        if x == '2':
            envs['GOE_IMPORT'] = input('Input script file name: ').strip()
            x2 = input('Input font file name (or leave blank): ').strip()
            if x2:
                envs['GOE_FONT'] = x2

    checksum = md5hash(romfile)
    if checksum != EXPECTED_CHECKSUM:
        print(f'WARNING: ROM does not mach expected MD5 checksum.\n'
              f'  Expected - {EXPECTED_CHECKSUM}\n'
              f'  This ROM - {checksum}')

    if envs['GOE_EXPORT']:
        exfile = envs['GOE_EXPORT']
        export_scripts(exfile, romfile=romfile)

    outfile = envs['GOE_OUTPUT']
    if envs['GOE_IMPORT']:
        imfile = envs['GOE_IMPORT']
        outfile = import_scripts(imfile, romfile=romfile, outfile=outfile)

    if envs['GOE_FONT']:
        fontfile = envs['GOE_FONT']
        if outfile is None:
            a = '.'.join(romfile.split('.')[:-1])
            if not a.strip():
                a = romfile
            b = '.'.join(fontfile.split('.')[:-1])
            if not b.strip():
                b = fontfile
            outfile = f'{a}.{b}.gbc'
            shcopy(romfile, outfile)
        import_font(fontfile, outfile)

    if outfile is not None:
        rewrite_gameboy_header(outfile, 'GOE17-MOD')


if __name__ == '__main__':
    try:
        scripter_main()
        print('Completed successfully.')
    except Exception:
        print_exc()
        print('ERROR:', exc_info()[1])

    if 'GOE_IMPORT' not in environ and 'GOE_EXPORT' not in environ:
        input('Press Enter to close this program. ')
