"""Binary (Protobuf) formatting utilities."""
from __future__ import absolute_import

import binascii
import numbers

import google.protobuf.message
from google.protobuf.internal.decoder import _DecodeVarint
from google.protobuf.internal import encoder

from openxc.formats.base import VehicleMessageStreamer
from openxc import openxc_pb2

class ProtobufStreamer(VehicleMessageStreamer):
    MAX_PROTOBUF_MESSAGE_LENGTH = 200

    def parse_next_message(self):
        message = None
        remainder = self.message_buffer
        message_data = ""

        # 1. decode a varint from the top of the stream
        # 2. using that as the length, if there's enough in the buffer, try and
        #       decode try and decode a VehicleMessage after the varint
        # 3. if it worked, great, we're oriented in the stream - continue
        # 4. if either couldn't be parsed, skip to the next byte and repeat
        while message is None and len(self.message_buffer) > 1:
            message_length, message_start = _DecodeVarint(self.message_buffer, 0)
            # sanity check to make sure we didn't parse some huge number that's
            # clearly not the length prefix
            if message_length > self.MAX_PROTOBUF_MESSAGE_LENGTH:
                self.message_buffer = self.message_buffer[1:]
                continue

            if message_start + message_length > len(self.message_buffer):
                break

            message_data = self.message_buffer[message_start:message_start +
                    message_length]
            remainder = self.message_buffer[message_start + message_length:]

            message = ProtobufFormatter.deserialize(message_data)
            if message is None:
                self.message_buffer = self.message_buffer[1:]

        self.message_buffer = remainder
        return message

    def serialize_for_stream(self, message):
        protobuf_message = ProtobufFormatter.serialize(message)
        delimiter = encoder._VarintBytes(len(protobuf_message))
        return delimiter + protobuf_message


class ProtobufFormatter(object):
    @classmethod
    def deserialize(cls, data):
        message = openxc_pb2.VehicleMessage()
        try:
            message.ParseFromString(data)
        except google.protobuf.message.DecodeError as e:
            pass
        except UnicodeDecodeError as e:
            LOG.warn("Unable to parse protobuf: %s", e)
        else:
            return cls._protobuf_to_dict(message)

    @classmethod
    def serialize(cls, data):
        return cls._dict_to_protobuf(data).SerializeToString()

    @classmethod
    def _command_string_to_protobuf(self, command_name):
        if command_name == "version":
            return openxc_pb2.ControlCommand.VERSION
        elif command_name == "device_id":
            return openxc_pb2.ControlCommand.DEVICE_ID
        elif command_name == "diagnostic_request":
            return openxc_pb2.ControlCommand.DIAGNOSTIC
        elif command_name == "passthrough":
            return openxc_pb2.ControlCommand.PASSTHROUGH
        elif command_name == "af_bypass":
            return openxc_pb2.ControlCommand.ACCEPTANCE_FILTER_BYPASS
        elif command_name == "payload_format":
            return openxc_pb2.ControlCommand.PAYLOAD_FORMAT

    @classmethod
    def _dict_to_protobuf(cls, data):
        message = openxc_pb2.VehicleMessage()
        if 'command' in data:
            command_name = data['command']
            message.type = openxc_pb2.VehicleMessage.CONTROL_COMMAND
            message.control_command.type = cls._command_string_to_protobuf(command_name)
            if message.control_command.type == openxc_pb2.ControlCommand.PASSTHROUGH:
                message.control_command.passthrough_mode_request.bus = data['bus']
                message.control_command.passthrough_mode_request.enabled = data['enabled']
            elif message.control_command.type == openxc_pb2.ControlCommand.ACCEPTANCE_FILTER_BYPASS:
                message.control_command.acceptance_filter_bypass_command.bus = data['bus']
                message.control_command.acceptance_filter_bypass_command.bypass = data['bypass']
            elif message.control_command.type == openxc_pb2.ControlCommand.PAYLOAD_FORMAT:
                if data['format'] == "json":
                    message.control_command.payload_format_command.format = openxc_pb2.PayloadFormatCommand.JSON
                elif data['format'] == "protobuf":
                    message.control_command.payload_format_command.format = openxc_pb2.PayloadFormatCommand.PROTOBUF
            elif message.control_command.type == openxc_pb2.ControlCommand.DIAGNOSTIC:
                request_command = message.control_command.diagnostic_request
                action = data['action']
                if action == "add":
                    request_command.action = openxc_pb2.DiagnosticControlCommand.ADD
                elif action == "cancel":
                    request_command.action = openxc_pb2.DiagnosticControlCommand.CANCEL
                request = request_command.request
                request_data = data['request']
                request.bus = request_data['bus']
                request.message_id = request_data['id']
                request.mode = request_data['mode']
                if 'frequency' in request_data:
                    request.frequency = request_data['frequency']
                if 'name' in request_data:
                    request.name = request_data['name']
                if 'multiple_responses' in request_data:
                    request.multiple_responses = request_data['multiple_responses']
                if 'pid' in request_data:
                    request.pid = request_data['pid']
                if 'payload' in request_data:
                    request.payload = binascii.unhexlify(request_data['payload'].split('0x')[1])
        elif 'command_response' in data:
            message.type = openxc_pb2.VehicleMessage.COMMAND_RESPONSE
            message.command_response.type = cls._command_string_to_protobuf(data['command_response'])
            if 'message' in data:
                message.command_response.message = data['message']
            message.command_response.status = data['status']
        elif 'id' in data and 'data' in data:
            message.type = openxc_pb2.VehicleMessage.RAW
            if 'bus' in data:
                message.raw_message.bus = data['bus']
            message.raw_message.message_id = data['id']
            message.raw_message.data = binascii.unhexlify(data['data'].split('0x')[1])
        elif 'id' in data and 'bus' in data and 'mode' in data:
            message.type = openxc_pb2.VehicleMessage.DIAGNOSTIC
            response = message.diagnostic_response
            response.bus = data['bus']
            response.message_id = data['id']
            response.mode = data['mode']
            if 'pid' in data:
                response.pid = data['pid']
            if 'success' in data:
                response.success = data['success']
            if 'negative_response_code' in data:
                response.negative_response_code = data['negative_response_code']
            if 'value' in data:
                response.value = data['value']
            if 'payload' in data:
                response.payload = binascii.unhexlify(data['payload'].split('0x')[1])
        elif 'name' in data and 'value' in data:
            message.type = openxc_pb2.VehicleMessage.TRANSLATED
            message.translated_message.name = data['name']
            value = data['value']
            if isinstance(value, bool):
                message.translated_message.type = openxc_pb2.TranslatedMessage.BOOL
                message.translated_message.value.type = openxc_pb2.DynamicField.BOOL
                message.translated_message.value.boolean_value = value
            elif isinstance(value, str):
                message.translated_message.type = openxc_pb2.TranslatedMessage.STRING
                message.translated_message.value.type = openxc_pb2.DynamicField.STRING
                message.translated_message.value.string_value = value
            elif isinstance(value, numbers.Number):
                message.translated_message.type = openxc_pb2.TranslatedMessage.NUM
                message.translated_message.value.type = openxc_pb2.DynamicField.NUM
                message.translated_message.value.numeric_value = value

            if 'event' in data:
                event = data['event']
                # TODO holy repeated code, batman. this will be easier to DRY
                # when https://github.com/openxc/openxc-message-format/issues/19
                # is resolved
                if isinstance(event, bool):
                    message.translated_message.type = openxc_pb2.TranslatedMessage.EVENTED_BOOL
                    message.translated_message.event.type = openxc_pb2.DynamicField.BOOL
                    message.translated_message.event.boolean_value = event
                elif isinstance(event, str):
                    message.translated_message.type = openxc_pb2.TranslatedMessage.EVENTED_STRING
                    message.translated_message.event.type = openxc_pb2.DynamicField.STRING
                    message.translated_message.event.string_value = event
                elif isinstance(event, numbers.Number):
                    message.translated_message.type = openxc_pb2.TranslatedMessage.EVENTED_NUM
                    message.translated_message.event.type = openxc_pb2.DynamicField.NUM
                    message.translated_message.event.numeric_value = event
        return message

    @classmethod
    def _protobuf_to_dict(cls, message):
        parsed_message = {}
        if message is not None:
            if message.type == message.RAW and message.HasField('raw_message'):
                raw_message = message.raw_message
                if raw_message.HasField('bus'):
                    parsed_message['bus'] = raw_message.bus
                if raw_message.HasField('message_id'):
                    parsed_message['id'] = raw_message.message_id
                if raw_message.HasField('data'):
                    parsed_message['data'] = "0x%s" % binascii.hexlify(raw_message.data)
            elif message.type == message.DIAGNOSTIC:
                diagnostic_message = message.diagnostic_response
                if diagnostic_message.HasField('bus'):
                    parsed_message['bus'] = diagnostic_message.bus
                if diagnostic_message.HasField('message_id'):
                    parsed_message['id'] = diagnostic_message.message_id
                if diagnostic_message.HasField('mode'):
                    parsed_message['mode'] = diagnostic_message.mode
                if diagnostic_message.HasField('pid'):
                    parsed_message['pid'] = diagnostic_message.pid
                if diagnostic_message.HasField('success'):
                    parsed_message['success'] = diagnostic_message.success
                if diagnostic_message.HasField('value'):
                    parsed_message['value'] = diagnostic_message.value
                if diagnostic_message.HasField('negative_response_code'):
                    parsed_message['negative_response_code'] = diagnostic_message.negative_response_code
                if diagnostic_message.HasField('payload'):
                    parsed_message['payload'] = "0x%s" % binascii.hexlify(diagnostic_message.payload)
            elif message.type == message.TRANSLATED:
                translated_message = message.translated_message
                parsed_message['name'] = translated_message.name
                if translated_message.HasField('event'):
                    event = translated_message.event
                    if event.HasField('numeric_value'):
                        parsed_message['event'] = event.numeric_value
                    elif event.HasField('boolean_value'):
                        parsed_message['event'] = event.boolean_value
                    elif event.HasField('string_value'):
                        parsed_message['event'] = event.string_value

                if translated_message.HasField('value'):
                    value = translated_message.value
                    if value.HasField('numeric_value'):
                        parsed_message['value'] = value.numeric_value
                    elif value.HasField('boolean_value'):
                        parsed_message['value'] = value.boolean_value
                    elif value.HasField('string_value'):
                        parsed_message['value'] = value.string_value
                    else:
                        parsed_message = None
                else:
                    parsed_message = None
            elif message.type == message.CONTROL_COMMAND:
                command = message.control_command
                if command.type == openxc_pb2.ControlCommand.VERSION:
                    parsed_message['command'] = "version"
                elif command.type == openxc_pb2.ControlCommand.DEVICE_ID:
                    parsed_message['command'] = "device_id"
                elif command.type == openxc_pb2.ControlCommand.DIAGNOSTIC:
                    parsed_message['command'] = "diagnostic_request"
                    parsed_message['request'] = {}
                    action = command.diagnostic_request.action
                    if action == openxc_pb2.DiagnosticControlCommand.ADD:
                        parsed_message['action'] = "add"
                    elif action == openxc_pb2.DiagnosticControlCommand.CANCEL:
                        parsed_message['action'] = "cancel"

                    request = command.diagnostic_request.request
                    parsed_message['request']['id'] = request.message_id
                    parsed_message['request']['bus'] = request.bus
                    parsed_message['request']['mode'] = request.mode

                    if request.HasField('frequency'):
                        parsed_message['request']['frequency'] = request.frequency
                    if request.HasField('name'):
                        parsed_message['request']['name'] = request.name
                    if request.HasField('multiple_responses'):
                        parsed_message['request']['multiple_responses'] = request.multiple_responses
                    if request.HasField('pid'):
                        parsed_message['request']['pid'] = request.pid
                    if request.HasField('payload'):
                        parsed_message['request']['payload'] = "0x%s" % binascii.hexlify(request.payload)
                elif command.type == openxc_pb2.ControlCommand.PASSTHROUGH:
                    parsed_message['command'] = "passthrough"
                    parsed_message['bus'] = command.passthrough_mode_request.bus
                    parsed_message['enabled'] = command.passthrough_mode_request.enabled
                elif command.type == openxc_pb2.ControlCommand.ACCEPTANCE_FILTER_BYPASS:
                    parsed_message['command'] = "af_bypass"
                    parsed_message['bus'] = command.acceptance_filter_bypass_command.bus
                    parsed_message['bypass'] = command.acceptance_filter_bypass_command.bypass
                elif command.type == openxc_pb2.ControlCommand.PAYLOAD_FORMAT:
                    parsed_message['command'] = "payload_format"
                    if command.payload_format_command.format == openxc_pb2.PayloadFormatCommand.JSON:
                        parsed_message['format'] = "json"
                    elif command.payload_format_command.format == openxc_pb2.PayloadFormatCommand.PROTOBUF:
                        parsed_message['format'] = "protobuf"
            elif message.type == message.COMMAND_RESPONSE:
                response = message.command_response
                if response.type == openxc_pb2.ControlCommand.VERSION:
                    parsed_message['command_response'] = "version"
                elif response.type == openxc_pb2.ControlCommand.DEVICE_ID:
                    parsed_message['command_response'] = "device_id"
                elif response.type == openxc_pb2.ControlCommand.DIAGNOSTIC:
                    parsed_message['command_response'] = "diagnostic_request"
                elif response.type == openxc_pb2.ControlCommand.PASSTHROUGH:
                    parsed_message['command_response'] = "passthrough"
                elif response.type == openxc_pb2.ControlCommand.PAYLOAD_FORMAT:
                    parsed_message['command_response'] = "payload_format"

                parsed_message['status'] = response.status
                if response.HasField('message'):
                    parsed_message['message'] = response.message
            else:
                parsed_message = None
        return parsed_message