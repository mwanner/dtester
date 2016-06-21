# utils.py
#
# Copyright (c) 2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

def parseArgs(rest, errLogFunc):
    """ Parse python args in their repr() representation, supporting mainly
        strings and decimal numbers.
    """
    in_single_string = False
    in_double_string = False
    in_number = False
    in_backslash = False
    in_bl_hex_char = False
    hex_char = ""
    token = ""
    args = []
    for char in rest:
        if in_bl_hex_char:
            assert char in "0123456789" or char in "abcdef"
            hex_char += char
            if len(hex_char) == 2:
                token += "\\x" + hex_char
                hex_char = ""
                in_bl_hex_char = False
        elif char == "'" and not in_double_string and not in_number:
            if not in_single_string:
                in_single_string = True
            elif in_backslash:
                token += "'"
                in_backslash = False
            else:
                args.append(token)
                in_single_string = False
                token = ""
        elif char == '"' and not in_single_string and not in_number:
            if not in_double_string:
                in_double_string = True
            elif in_backslash:
                token += '"'
                in_backslash = False
            else:
                args.append(token)
                in_double_string = False
                token = ""
        elif char == "\\" and not in_backslash:
            if in_single_string or in_double_string:
                in_backslash = True
            else:
                errLogFunc("WARNING: invalid position for backslash, ignored!")
        elif char in "-.0123456789" and not in_backslash:
            if in_number or in_single_string or in_double_string:
                token += char
            else:
                token += char
                in_number = True
        else:
            if in_backslash:
                if char == "n":
                    token += "\n"
                elif char == "r":
                    token += "\r"
                elif char == "t":
                    token += "\t"
                elif char == "x":
                    in_hex_char = True
                elif char == "\\":
                    token += "\\"
                else:
                    errLogFunc("WARNING: unknown escape character: '%s'"
                               % repr(char))
                in_backslash = False
            elif in_single_string or in_double_string:
                token += char
            elif in_number and char in ".0123456789+-e":
                token += char
            else:
                if char in " \n\r\t":
                    if in_number:
                        if "." in token:
                            args.append(float(token))
                        else:
                            args.append(int(token))
                    token = ""
                    in_number = False
                else:
                    errLogFunc("invalid char outside of token: '%s' in: %s" % (repr(char), rest))

    if in_number:
        if "." in token or 'e' in token:
            args.append(float(token))
        else:
            args.append(int(token))
    elif in_single_string or in_double_string:
        errLogFunc("unterminated string at end of line: %s" % repr(token))
        args.append(token)

    return args


