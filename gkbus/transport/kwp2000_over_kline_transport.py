import logging
import time

from ..hardware.hardware_abc import HardwareABC, RawFrame
from .transport_abc import PacketDirection, RawPacket, TransportABC

logger = logging.getLogger(__name__)

class Kwp2000OverKLineTransport (TransportABC):
	def __init__ (self, hardware: HardwareABC, tx_id: int, rx_id: int) -> None:
		self.hardware: HardwareABC = hardware
		self.tx_id, self.rx_id = tx_id, rx_id
		self.short_header = False

	def set_short_header (self, enabled: bool) -> None:
		self.short_header = bool(enabled)

	def send_pdu (self, pdu: bytes) -> int:
		data = self.build_payload(pdu)

		bytes_written = self._write(data)
		self.buffer_push(RawPacket(direction=PacketDirection.OUTGOING, data=data, timestamp=int(time.time()*1000)))

		return bytes_written

	def read_pdu (self) -> bytes:
		if self.short_header:
			return self._read_pdu_short_header()

		frame = bytes()
		data = bytes()

		frame += self._read(4)

		counter = frame[0]
		tx_rx_id = frame[1:3]

		if (counter == 0x80): # more than 127 bytes incoming, counter overflowed. counter is gonna come after IDs
			counter = frame[3]+1
			logger.debug('More than 127 bytes incoming: {}'.format(counter))
		else:
			counter = counter-0x80
			data += frame[3:4] # frame[3] == python would automatically convert it to int. frame[3:3] == byte slice 

		data_and_checksum = self._read(counter)
		frame += data_and_checksum
		data += data_and_checksum[:-1] # last byte is the checksum

		self.buffer_push(RawPacket(direction=PacketDirection.INCOMING, data=frame, timestamp=int(time.time() * 1000)))

		return data


	def _read_pdu_short_header (self) -> bytes:
		first = self._read(1)

		if len(first) != 1:
			raise ValueError('Incomplete K-Line short-header frame')

		frame = first

		if first[0] == 0x00:
			length_byte = self._read(1)
			if len(length_byte) != 1:
				raise ValueError('Incomplete K-Line extended length')
			frame += length_byte
			data_length = length_byte[0]
		else:
			data_length = first[0]

		data_and_checksum = self._read(data_length + 1)
		frame += data_and_checksum

		if len(data_and_checksum) != data_length + 1:
			raise ValueError('Incomplete K-Line short-header payload')

		data = data_and_checksum[:-1]
		received_checksum = data_and_checksum[-1]
		expected_checksum = self.calculate_checksum(frame[:-1])

		if received_checksum != expected_checksum:
			raise ValueError(
				'K-Line checksum mismatch: received 0x{:02X}, expected 0x{:02X}'
				.format(received_checksum, expected_checksum)
			)

		self.buffer_push(
			RawPacket(
				direction=PacketDirection.INCOMING,
				data=frame,
				timestamp=int(time.time() * 1000)
			)
		)

		return data


	def _write (self, data: bytes) -> int:
		logger.debug('K-Line sending: {}'.format(' '.join([hex(x) for x in list(data)])))
		return self.hardware.write(RawFrame(identifier=0, data=data))

	def _read (self, length: int) -> bytes:
		logger.debug('K-Line trying to read {} bytes'.format(length))
		data = self.hardware.read(length).data
		logger.debug('K-Line success: {}'.format(' '.join([hex(x) for x in list(data)])))
		return data

	def init (self, payload: bytes) -> list[tuple[bytes, int, int]]:
		'''
		Bring up the socket if not opened already and initialize the K-Line by ISO14230. 
		'''
		if not self.hardware.is_open():
			self.hardware.open()

		init_payload = self.build_payload(payload)
		responses = []
		responses.append(self.hardware.iso14230_fast_init(init_payload, timing_offset_ms=0))
		# @todo: find out if there is some way to self-test and automatically measure the timing offset we should apply
		if responses[0][0][0:1] not in [b'\x00', b'\x81', b'\xC1']: # most often seen responses, depends on the adapter
			responses.append(self.hardware.iso14230_fast_init(init_payload, timing_offset_ms=-2))
			responses.append(self.hardware.iso14230_fast_init(init_payload, timing_offset_ms=2))

		return responses

	def calculate_checksum (self, payload: bytes) -> int:
		return sum(payload) & 0xFF

	def build_payload (self, data: bytes) -> bytes:
		data_length = len(data)

		if self.short_header:
			if data_length > 0xFF:
				raise ValueError(
					'K-Line short-header payload cannot exceed 255 bytes'
				)

			if data_length <= 0x7F:
				payload = bytes([data_length]) + data
			else:
				payload = bytes([0x00, data_length]) + data

			payload += self.calculate_checksum(payload).to_bytes(1, 'big')
			return payload

		if (data_length < 127):
			counter = 0x80 + data_length
		else:
			counter = 0x80
			data = bytes([data_length]) + data

		payload = bytes([counter, self.tx_id, self.rx_id]) 
		payload += data
		payload += self.calculate_checksum(payload).to_bytes(1, 'big')

		return payload
