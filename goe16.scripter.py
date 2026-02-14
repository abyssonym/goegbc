from os import environ
from shutil import copy
from sys import argv

from randomtools.scriptparser import Parser
from randomtools.unpacker import Unpacker
from randomtools.utils import TextDecoder
from randomtools.utils import fake_yaml as yaml
from randomtools.utils import hexify, md5hash

DIALOGUE_FORMAT_FILENAME = 'goe16.struct_dialogue.yaml'
EXPECTED_CHECKSUM = '18b2c4989209373c0cba9bc58075b2fd'


class GGGBCDecoder(TextDecoder):
    CODEPOINT_LENGTH = 1
    NULL_CHARACTER = None

    TABLE = {
        0x00: '　',
        0x01: 'あいうえおかきくけこさしすせそ'
              'たちつてとなにぬねのはひふへほ',
        0x1f: 'ま',
        0x20: '０１２３４５６７８９',
        0x2a: 'れろわをん',
        0x2f: 'ぁぃぅぇぉ',
        0x34: 'っゃゅょ',
        0x38: 'がぎぐげござじずぜぞだぢづでど'
              'ばびぶべぼぱぴぷぺぽ',
        0x51: 'アイウエオカキクケコサシスセソ'
              'タチツテトナニヌネノハヒフヘホ'
              'マミムメモヤユヨラリルレロワヲン',
        0x7f: 'ァィゥェォ',
        0x84: 'ッャュョ',
        0x88: 'ガギグゲゴザジズゼゾダヂヅデド'
              'バビブベボパピプペポ',
        0xa1: '＞／？、。ー！「」・',
        0xab: 'みむめもやゆよらりる',
        0xb5: 'ＡＢＣＤＥＦＧＨＩＪＫＬＭ'
              'ＮＯＰＱＲＳＴＵＶＷＸＹＺ',
        0xd0: '金両',
        0xd2: '◯═≫',
        0xd5: '●━▶',
        0xd8: 'ⅬⅤ',
        0xda: '♂♀',
        0xdc: '①⑥⑧',
        0xdf: '𝅘𝅥𝅮',
        0xcf: '丸',
        0xe0: '❤％',
        0xfe:   '\n',
        }

    ALTS = {
        ' ': '　',
        '0123456789': '０１２３４５６７８９',
        '>/?,.-![]*': '＞／？、。ー！「」・',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            'ＡＢＣＤＥＦＧＨＩＪＫＬＭ'
            'ＮＯＰＱＲＳＴＵＶＷＸＹＺ',
        'abcdefghijklmnopqrstuvwxyz':
            'ＡＢＣＤＥＦＧＨＩＪＫＬＭ'
            'ＮＯＰＱＲＳＴＵＶＷＸＹＺ',
        '%': '％',
        }

    WORDS = {
        0xf1: '<pause-short>',
        0xf5: '<pause-medium>',
        0xf6: '<pause-long>',
        0xf7: '<choice>',
        0xf9: '<silent>',
        #0xf80c: '<player>',
        }


DECODER = GGGBCDecoder()

UNKNOWN_OPCODES = sorted(set(range(0xda, 0xf0)) -
                         set(DECODER.FORWARD_TABLE.keys()))


class GGGBCParser(Parser):
    SCRIPT_CONFIG = 'goe16.parser_config.yaml'

    def format_inline_text(self, bytecode):
        test = DECODER.encode(DECODER.decode(bytecode))
        return DECODER.decode(bytecode)

    def encode(self, text):
        return DECODER.encode(text)


def get_dialogue(filename, address):
    page = address >> 14
    page_address = page << 14
    page_offset = address & 0x3fff

    with open(DIALOGUE_FORMAT_FILENAME) as f:
        config = yaml.safe_load(f.read())

    with open(filename, 'r+b') as f:
        f.seek(page_address)
        data = f.read(0x4000)

    config['main_pointers']['start'] = page_offset
    u = Unpacker(config)

    u.set_packed(data)
    unpacked = u.unpack()

    #test_opcodes = UNKNOWN_OPCODES[:10]
    parser = GGGBCParser(GGGBCParser.SCRIPT_CONFIG, data,
                         unpacked['main_pointers'])

    s = f'! SCRIPTS {address:0>6x}\n{parser.pretty}'
    return s


def import_script(romfile, scriptfile):
    script_texts = {}
    address, script_text = None, None
    with open(scriptfile) as f:
        for line in f:
            if line.strip().startswith('! SCRIPTS'):
                if script_text is not None:
                    script_texts[address] = script_text
                _, _, address = line.strip().split()
                address = int(address, 0x10)
                script_text = ''
                continue
            script_text += line
    script_texts[address] = script_text

    with open(DIALOGUE_FORMAT_FILENAME) as f:
        config = yaml.safe_load(f.read())

    for address, script_text in script_texts.items():
        page = address >> 14
        page_address = page << 14
        page_offset = address & 0x3fff

        with open(romfile, 'r+b') as f:
            f.seek(page_address)
            data = f.read(0x4000)

        config['main_pointers']['start'] = page_offset
        u = Unpacker(config)
        u.set_packed(data)
        unpacked = u.unpack()

        parser = GGGBCParser(GGGBCParser.SCRIPT_CONFIG, data,
                             unpacked['main_pointers'])
        #print(f'! SCRIPTS {address:0>6x}\n{parser.pretty}\n')
        parser.import_script(script_text)
        bytecode = parser.dump_all_scripts()

        new_pointers = []
        new_data = {}
        lowest = min(unpacked['main_pointers'])
        for pointer in unpacked['main_pointers']:
            assert int(pointer) in parser.scripts
            script = parser.scripts[int(pointer)]
            new_pointer = script.pointer.repointer
            pointer.pointer = lowest + new_pointer
            new_pointers.append(pointer)
            new_data[pointer] = script.bytecode
        unpacked['main_pointers'] = new_pointers
        unpacked['main_data'] = new_data

        u2 = Unpacker(config)
        u2.set_unpacked(unpacked)
        verify = u2.repack()
        start = u2.get_address('@main_pointers')
        finish = u2.get_address('@@main_data')
        data = verify[start:finish]

        with open(romfile, 'r+b') as f:
            f.seek(address)
            f.write(data)


def export_script(romfile, outfile):
    POINTERS = [
        0x03520c,
        0x035501,
        0x035881,
        0x0358eb,
        0x035b7f,
        0x060025,
        0x0601e1,
        0x062bf1,
        0x065b7c,
        0x0669a3,
        0x068025,
        0x068d75,
        0x069930,
        0x07c035,
        0x07d5a7,
        0x07eae1,
        0x07f247,
        ]

    with open(outfile, 'w+') as f:
        for pointer in POINTERS:
            s = get_dialogue(romfile, pointer)
            f.write(s + '\n\n')


if __name__ == '__main__':
    infile = argv[1]
    if len(argv) > 2:
        outfile = argv[2]
    else:
        outfile = infile.split('.')
        outfile.insert(-1, 'modified')
        outfile = '.'.join(outfile)

    checksum = md5hash(infile)
    if checksum != EXPECTED_CHECKSUM:
        print(f'WARNING: ROM does not mach expected MD5 checksum.\n'
              f'  Expected - {EXPECTED_CHECKSUM}\n'
              f'  This ROM - {checksum}')

    if 'SCRIPT_EXPORT' in environ:
        export_script(infile, environ['SCRIPT_EXPORT'])
    if 'SCRIPT_IMPORT' in environ:
        copy(infile, outfile)
        import_script(outfile, environ['SCRIPT_IMPORT'])
