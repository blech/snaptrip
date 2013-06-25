# -*- coding: utf-8 -*-
"""This module parses and generates contentlines as defined in RFC 2445
(iCalendar), but will probably work for other MIME types with similar syntax.
Eg. RFC 2426 (vCard)

It is stupid in the sense that it treats the content purely as strings. No type
conversion is attempted.
"""
from __future__ import absolute_import
import re
from .caselessdict import CaselessDict
from .parser_tools import (
    DEFAULT_ENCODING,
    SEQUENCE_TYPES,
    to_unicode,
    data_encode
)


def escape_char(text):
    """Format value according to iCalendar TEXT escaping rules.
    """
    assert isinstance(text, basestring)
    # NOTE: ORDER MATTERS!
    return text.replace('\N', '\n')\
               .replace('\\', '\\\\')\
               .replace(';', r'\;')\
               .replace(',', r'\,')\
               .replace('\r\n', r'\n')\
               .replace('\n', r'\n')


def unescape_char(text):
    assert isinstance(text, basestring)
    # NOTE: ORDER MATTERS!
    return text.replace(r'\N', r'\n')\
               .replace(r'\r\n', '\n')\
               .replace(r'\n', '\n')\
               .replace(r'\,', ',')\
               .replace(r'\;', ';')\
               .replace('\\\\', '\\')


def tzid_from_dt(dt):
    tzid = None
    if hasattr(dt.tzinfo, 'zone'):
        tzid = dt.tzinfo.zone  # pytz implementation
    elif hasattr(dt.tzinfo, 'tzname'):
        try:
            tzid = dt.tzinfo.tzname(dt)  # dateutil implementation
        except AttributeError:
            # No tzid available
            pass
    return tzid


def foldline(line, limit=75, fold_sep=u'\r\n '):
    """Make a string folded as defined in RFC5545
    Lines of text SHOULD NOT be longer than 75 octets, excluding the line
    break.  Long content lines SHOULD be split into a multiple line
    representations using a line "folding" technique.  That is, a long
    line can be split between any two characters by inserting a CRLF
    immediately followed by a single linear white-space character (i.e.,
    SPACE or HTAB).
    """
    assert isinstance(line, unicode)
    assert u'\n' not in line

    ret_line = u''
    byte_count = 0
    for char in line:
        char_byte_len = len(char.encode(DEFAULT_ENCODING))
        byte_count += char_byte_len
        if byte_count >= limit:
            ret_line += fold_sep
            byte_count = char_byte_len
        ret_line += char

    return ret_line


#################################################################
# Property parameter stuff

def param_value(value):
    """Returns a parameter value.
    """
    if isinstance(value, SEQUENCE_TYPES):
        return q_join(value)
    return dquote(value)


# Could be improved
NAME = re.compile('[\w-]+')
UNSAFE_CHAR = re.compile('[\x00-\x08\x0a-\x1f\x7F",:;]')
QUNSAFE_CHAR = re.compile('[\x00-\x08\x0a-\x1f\x7F"]')
FOLD = re.compile('(\r?\n)+[ \t]')
NEWLINE = re.compile(r'\r?\n')


def validate_token(name):
    match = NAME.findall(name)
    if len(match) == 1 and name == match[0]:
        return
    raise ValueError(name)


def validate_param_value(value, quoted=True):
    validator = QUNSAFE_CHAR if quoted else UNSAFE_CHAR
    if validator.findall(value):
        raise ValueError(value)


# chars presence of which in parameter value will be cause the value
# to be enclosed in double-quotes
QUOTABLE = re.compile("[,;: ’']")


def dquote(val):
    """Enclose parameter values containing [,;:] in double quotes.
    """
    # a double-quote character is forbidden to appear in a parameter value
    # so replace it with a single-quote character
    val = val.replace('"', "'")
    if QUOTABLE.search(val):
        return '"%s"' % val
    return val


# parsing helper
def q_split(st, sep=','):
    """Splits a string on char, taking double (q)uotes into considderation.
    """
    result = []
    cursor = 0
    length = len(st)
    inquote = 0
    for i in range(length):
        ch = st[i]
        if ch == '"':
            inquote = not inquote
        if not inquote and ch == sep:
            result.append(st[cursor:i])
            cursor = i + 1
        if i + 1 == length:
            result.append(st[cursor:])
    return result


def q_join(lst, sep=','):
    """Joins a list on sep, quoting strings with QUOTABLE chars.
    """
    return sep.join(dquote(itm) for itm in lst)


class Parameters(CaselessDict):
    """
    Parser and generator of Property parameter strings. It knows nothing of
    datatypes. Its main concern is textual structure.
    """

    def params(self):
        """
        in rfc2445 keys are called parameters, so this is to be consitent with
        the naming conventions
        """
        return self.keys()

# TODO?
# Later, when I get more time... need to finish this off now. The last major
# thing missing.
#   def _encode(self, name, value, cond=1):
#       # internal, for conditional convertion of values.
#       if cond:
#           klass = types_factory.for_property(name)
#           return klass(value)
#       return value
#
#   def add(self, name, value, encode=0):
#       "Add a parameter value and optionally encode it."
#       if encode:
#           value = self._encode(name, value, encode)
#       self[name] = value
#
#   def decoded(self, name):
#       "returns a decoded value, or list of same"

    def __repr__(self):
        return 'Parameters(%s)' % data_encode(self)

    def to_ical(self):
        result = []
        items = self.items()
        items.sort()  # To make doctests work
        for key, value in items:
            value = param_value(value)
            if isinstance(value, unicode):
                value = value.encode(DEFAULT_ENCODING)
            # CaselessDict keys are always unicode
            result.append('%s=%s' % (key.upper().encode('utf-8'), value))
        return ';'.join(result)

    @classmethod
    def from_ical(cls, st, strict=False):
        "Parses the parameter format from ical text format"

        # parse into strings
        result = cls()
        for param in q_split(st, ';'):
            try:
                key, val = q_split(param, '=')
                validate_token(key)
                # Property parameter values that are not in quoted
                # strings are case insensitive.
                vals = []
                for v in q_split(val, ','):
                    if v.startswith('"') and v.endswith('"'):
                        v = v.strip('"')
                        validate_param_value(v, quoted=True)
                        vals.append(v)
                    else:
                        validate_param_value(v, quoted=False)
                        if strict:
                            vals.append(v.upper())
                        else:
                            vals.append(v)
                if not vals:
                    result[key] = val
                else:
                    if len(vals) == 1:
                        result[key] = vals[0]
                    else:
                        result[key] = vals
            except ValueError as exc:
                raise ValueError('%r is not a valid parameter string: %s'
                                 % (param, exc))
        return result


def escape_string(val):
    # '%{:02X}'.format(i)
    return val.replace(r'\,', '%2C').replace(r'\:', '%3A')\
              .replace(r'\;', '%3B').replace(r'\\', '%5C')


def unsescape_string(val):
    return val.replace('%2C', ',').replace('%3A', ':')\
              .replace('%3B', ';').replace('%5C', '\\')


#########################################
# parsing and generation of content lines

class Contentline(unicode):
    """A content line is basically a string that can be folded and parsed into
    parts.

    """
    def __new__(cls, value, strict=False, encoding=DEFAULT_ENCODING):
        value = to_unicode(value, encoding=encoding)
        assert u'\n' not in value, ('Content line can not contain unescaped '
                                    'new line characters.')
        self = super(Contentline, cls).__new__(cls, value)
        self.strict = strict
        return self

    @classmethod
    def from_parts(cls, name, params, values):
        """Turn a parts into a content line.
        """
        assert isinstance(params, Parameters)
        if hasattr(values, 'to_ical'):
            values = values.to_ical()
        else:
            values = vText(values).to_ical()
        # elif isinstance(values, basestring):
        #    values = escape_char(values)

        # TODO: after unicode only, remove this
        # Convert back to unicode, after to_ical encoded it.
        name = to_unicode(name)
        values = to_unicode(values)
        if params:
            params = to_unicode(params.to_ical())
            return cls(u'%s;%s:%s' % (name, params, values))
        return cls(u'%s:%s' % (name, values))

    def parts(self):
        """Split the content line up into (name, parameters, values) parts.
        """
        try:
            st = escape_string(self)
            name_split = None
            value_split = None
            in_quotes = False
            for i, ch in enumerate(st):
                if not in_quotes:
                    if ch in ':;' and not name_split:
                        name_split = i
                    if ch == ':' and not value_split:
                        value_split = i
                if ch == '"':
                    in_quotes = not in_quotes
            name = unsescape_string(st[:name_split])
            if not name:
                raise ValueError('Key name is required')
            validate_token(name)
            if name_split + 1 == value_split:
                raise ValueError('Invalid content line')
            params = Parameters.from_ical(st[name_split + 1: value_split],
                                          strict=self.strict)
            params = Parameters(
                (unsescape_string(key), unsescape_string(value))
                for key, value in params.iteritems()
            )
            values = unsescape_string(st[value_split + 1:])
            return (name, params, values)
        except ValueError as exc:
            raise ValueError("Content line could not be parsed into parts: %r:"
                             " %s" % (self, exc))

    @classmethod
    def from_ical(cls, ical, strict=False):
        """Unfold the content lines in an iCalendar into long content lines.
        """
        ical = to_unicode(ical)
        # a fold is carriage return followed by either a space or a tab
        return cls(FOLD.sub('', ical), strict=strict)

    def to_ical(self):
        """Long content lines are folded so they are less than 75 characters.
        wide.
        """
        return foldline(self).encode(DEFAULT_ENCODING)


class Contentlines(list):
    """I assume that iCalendar files generally are a few kilobytes in size.
    Then this should be efficient. for Huge files, an iterator should probably
    be used instead.
    """
    def to_ical(self):
        """Simply join self.
        """
        return '\r\n'.join(line.to_ical() for line in self if line) + '\r\n'

    @classmethod
    def from_ical(cls, st):
        """Parses a string into content lines.
        """
        try:
            # a fold is carriage return followed by either a space or a tab
            unfolded = FOLD.sub('', st)
            lines = cls(Contentline(line) for
                        line in unfolded.splitlines() if line)
            lines.append('')  # '\r\n' at the end of every content line
            return lines
        except:
            raise ValueError('Expected StringType with content lines')


# XXX: what kind of hack is this? import depends to be at end
from .prop import vText
