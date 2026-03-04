This repository contains translation tools for the Goemon GBC RPGs:
- Goemon 16 - Tengu-tou no Gyakushuu - The Tengu Gang Strikes Back
- Goemon 17 - Mononoke Douchuu Tobidase Nabe-Bugyou! - On the Way to Mononoke, Jump Out and be a Nabe Magistrate!

These tools can be used to extract event scripts from valid GBC ROMs with the following MD5 checksums:
- Goemon 16 - `18b2c4989209373c0cba9bc58075b2fd`
- Goemon 17 - `7c700360a46f54796802ca7c7bf499c5`

After extracting the event script, the script can be altered and then imported to create a modified ROM.

Example usage:
```
GOE_ROM=goe16.gbc GOE_EXPORT=script.16.export.txt python goe16.scripter.py
GOE_ROM=goe16.gbc GOE_IMPORT=script.16.import.txt python goe16.scripter.py
GOE_ROM=goe17.gbc GOE_EXPORT=script.17.export.txt python goe17.scripter.py
GOE_ROM=goe17.gbc GOE_IMPORT=script.17.import.txt GOE_FONT=mystical_ninja.font python goe17.scripter.py
```

Note that the scripters will not work without the included `randomtools` module.

Sample export script:
```
! SCRIPT 1f-01c-07c319
@319  # origin
  0319. 27:00                   # Unknown 27
  031b. 28:                     # Set speaker: Dog (Standard)
    speaker   = 11  # Dog
    alternate = 00  # Standard
    unknown   = 00
  031d. 1a:                     # Call script 1f-01d if condition
    script    = 001d
    condition = 001a
    page      = 01
  0322. 2b:b020                 # Play sound
  |ワン！ワン！<close>|
  032e. 00:                     # End event
```

Sample import script:
```
! SCRIPT 1f-01c-07c319
@319  # origin
  0319. 27:00                   # Unknown 27
  031b. 28:                     # Set speaker: Dog (Standard)
    speaker   = 11  # Dog
    alternate = 00  # Standard
    unknown   = 00
  031d. 1a:                     # Call script 1f-01d if condition
    script    = 001d
    condition = 001a
    page      = 01
  0322. 2b:b020                 # Play sound
  |Woof! Woof!<close>|
  032e. 00:                     # End event
```

The Goe17 scripter can take a custom font file, since the game does not have native support for roman characters. This font will overwrite the hiragana and katakana tables.
