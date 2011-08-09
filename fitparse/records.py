#
# Copyright (c) 2011, David Cooper <dave@kupesoft.com>
# All rights reserved.
#
# Dedicated to Kate Lacey
#
# Permission to use, copy, modify, and/or distribute this software
# for any purpose with or without fee is hereby granted, provided
# that the above copyright notice, the above dedication, and this
# permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHORS DISCLAIMS ALL
# WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL
# THE AUTHORS BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR
# CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
# NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#


from collections import namedtuple
import datetime
import math
import os


RECORD_HEADER_NORMAL = 0
RECORD_HEADER_COMPRESSED_TS = 1

MESSAGE_DEFINITION = 1
MESSAGE_DATA = 0

LITTLE_ENDIAN = 0
BIG_ENDIAN = 1


class RecordHeader(namedtuple('RecordHeader',
    ('type', 'message_type', 'local_message_type', 'seconds_offset'))):
    # type -- one of RECORD_HEADER_NORMAL, RECORD_HEADER_COMPRESSED_TS
    # message_type -- one of MESSAGE_DEFINITION, MESSAGE_DATA
    # local_message_type -- a number
    #    * for a definition message, the key to store in FitFile().global_messages
    #    * for a data message, the key to look up the associated definition
    # seconds_offset -- for RECORD_HEADER_COMPRESSED_TS, offset in seconds
    # NOTE: Though named similarly, none of these map to the namedtuples below
    pass


class FieldTypeBase(namedtuple('FieldTypeBase', ('num', 'name', 'invalid', 'struct_fmt', 'is_variable_size'))):
    # Yields a singleton if called with just a num
    _instances = {}

    def __new__(cls, num, *args, **kwargs):
        instance = FieldTypeBase._instances.get(num)
        if instance:
            return instance

        instance = super(FieldTypeBase, cls).__new__(cls, num, *args, **kwargs)
        FieldTypeBase._instances[num] = instance
        return instance

    def get_struct_fmt(self, size):
        if self.is_variable_size:
            return self.struct_fmt % size
        else:
            return self.struct_fmt

    def convert(self, raw_data):
        if self.name == 'string':
            raw_data = raw_data.rstrip('\x00')

        if callable(self.invalid):
            if self.invalid(raw_data):
                return None
        else:
            if raw_data == self.invalid:
                return None
        return raw_data

    @property
    def base(self):
        return self


class FieldType(namedtuple('FieldType', ('name', 'base', 'converter'))):
    # Higher level fields as defined in Profile.xls
    #
    # converter is a dict or a func. If type is uint*z, then converter should
    # look through the value as a bit array and return all found values
    _instances = {}

    def __new__(cls, name, *args, **kwargs):
        instance = FieldType._instances.get(name)
        if instance:
            return instance

        instance = super(FieldType, cls).__new__(cls, name, *args, **kwargs)
        FieldType._instances[name] = instance
        return instance

    @property
    def get_struct_fmt(self):
        return self.base.get_struct_fmt

    def convert(self, raw_data):
        if self.base.convert(raw_data) is None:
            return None
        elif isinstance(self.converter, dict):
            #if self.base.name in ('uint8z', 'uint16z', 'uint32z'):
            #    XXX -- handle this condition, ie return a list of properties
            return self.converter.get(raw_data, raw_data)
        elif callable(self.converter):
            return self.converter(raw_data)
        else:
            return raw_data


class Field(namedtuple('Field', ('name', 'type', 'units', 'scale', 'offset'))):
    # A name, type, units, scale, offset
    pass


class DynamicField(namedtuple('DynamicField', ('name', 'type', 'units', 'scale', 'offset', 'possibilities'))):
    # A name, type, units, scale, offset
    # TODO: Describe format of possiblities
    pass


class AllocatedField(namedtuple('AllocatedField', ('field', 'size'))):
    # A field along with its size

    @property
    def name(self):
        return self.field.name

    @property
    def type(self):
        return self.field.type


class BoundField(namedtuple('BoundField', ('data', 'raw_data', 'field'))):
    # Convert data
    def __new__(cls, raw_data, field):
        data = field.type.convert(raw_data)
        return super(BoundField, cls).__new__(cls, data, raw_data, field)

    @property
    def name(self):
        return self.field.name

    @property
    def type(self):
        return self.field.type

    def items(self):
        return self.name, self.data


class MessageType(namedtuple('MessageType', ('num', 'name', 'fields'))):
    _instances = {}

    def __new__(cls, num, *args, **kwargs):
        instance = MessageType._instances.get(num)
        if instance:
            return instance

        try:
            instance = super(MessageType, cls).__new__(cls, num, *args, **kwargs)
        except TypeError:
            # Don't store unknown field types in _instances.
            # this would be a potential memory leak in a long-running parser
            return super(MessageType, cls).__new__(cls, num, 'unknown', None)

        MessageType._instances[num] = instance
        return instance


class DefinitionRecord(namedtuple('DefinitionRecord', ('header', 'type', 'arch', 'fields'))):
    # arch -- Little endian or big endian
    # fields -- list of AllocatedFields
    # type -- MessageType

    @property
    def name(self):
        return self.type.name

    @property
    def num(self):
        return self.type.num


class DataRecord(namedtuple('DataRecord', ('header', 'definition', 'fields'))):
    # fields -- list of BoundFields

    @property
    def name(self):
        return self.definition.name

    @property
    def type(self):
        return self.definition.type

    @property
    def num(self):
        return self.definition.num

    def iteritems(self):
        return (f.items() for f in self.fields)

    def get(self, field_name):
        for field in self.fields:
            if field.name == field_name:
                return field.data
        return None


# Definitions from FIT SDK 1.2

FieldTypeBase(0, 'enum', 0xFF, 'B', False)
FieldTypeBase(1, 'sint8', 0x7F, 'b', False)
FieldTypeBase(2, 'uint8', 0xFF, 'B', False)
FieldTypeBase(3, 'sint16', 0x7FFF, 'h', False)
FieldTypeBase(4, 'uint16', 0xFFFF, 'H', False)
FieldTypeBase(5, 'sint32', 0x7FFFFFFF, 'i', False)
FieldTypeBase(6, 'uint32', 0xFFFFFFFF, 'I', False)
FieldTypeBase(7, 'string', lambda x: all([ord(c) == '\x00' for c in x]), '%ds', True)
FieldTypeBase(8, 'float32', math.isnan, 'f', False)
FieldTypeBase(9, 'float64', math.isnan, 'd', False)
FieldTypeBase(10, 'uint8z', 0, 'B', False)
FieldTypeBase(11, 'uint16z', 0, 'H', False)
FieldTypeBase(12, 'uint32z', 0, 'I', False)
FieldTypeBase(13, 'byte', lambda x: all([ord(c) == '\xFF' for c in x]), '%ds', True)


# Conversion functions for FieldTypes

# XXX -- need to handle UTC/timezones
_convert_local_date_time = lambda x: datetime.datetime.fromtimestamp(631065600 + x)
_convert_date_time = lambda x: datetime.datetime.fromtimestamp(631065600 + x)
_convert_bool = lambda x: bool(x)


# XXX -- untested
# see FitSDK1_2.zip:c/examples/decode/decode.c lines 121-150 for an example
def _convert_record_compressed_speed_distance(raw_data):
    first, second, third = (ord(b) for b in raw_data)
    speed = first + (second & 0b1111)
    distance = (third << 4) + ((second & 0b11110000) >> 4)
    return speed / 100. / 1000. * 60. * 60., distance / 16.


# XXX -- we do this so ipython doesn't throw an error on __file__.
try:
    execfile('profile.def')
except IOError:
    execfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profile.def'))