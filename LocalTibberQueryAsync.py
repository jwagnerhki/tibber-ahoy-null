#!/usr/bin/python3
#
# Download a raw meter SML-format data frame as captured by Tibber Pulse,
# via the Tibber Bridge web interface.
#
# Does not use the remote API of Tibber, i.e., works even when the house
# internet connection drops out (provided that wifi stays on).
#
# Code assumes SML is from a Landis+Gyr E220 meter.
# For other meters, have to adjust two "offset = ..." below,
# by trial and error, or by some reverse engineering with https://github.com/volkszaehler/libsml
#
# Tibber readout assumes the web interface has been enabled on the Tibber Bridge.
# Steps to enable it are explained on other web sites.
# Steps essentially are essentially there:
#   1) configure Tibber Pulse normally via App, pair with Tibber
#   2) note down the typ. 8-letter password (XXXX-XXXX) found printed
#      on the Tibber Bridge device near its QR code label
#   3) power cycle the Pulse, wait till green light, power cycle again,
#      wait till blue light and then search for wireless network "Tibber Bridge"
#   4) connect to wifi network "Tibber Bridge", password as in (2)
#   5) open the Bridge's page http://10.133.70.1/params/, user 'admin', password as in (2)
#   6) find the entry called 'webserver_force_enable', change
#      the value to 'true' and Save it
#   7) find near the end fo the page 'Write settings to flash' or similar
#      and have the Bridge do that
#   8) change to http://10.133.70.1/console/ and enter 'reboot', or,
#      just manually power cycle the Bridge
#   9) after booting again the Bridge ought to be back on the
#      normal wifi network it was added to during (1)
#   10) figure out the local IP or address of your Bridge on
#      the normal wifi network make sure you can connect
#      to the Bridge at http://<bridge ip on your wifi>/params/
#
# The local Bridge Web interface provides only the raw data (SML frames)
# as read directly from the grid energy meter. The Bridge does not decode
# the content of the SML frame.
#


import aiohttp
import struct

class LocalTibberQueryAsync:

	def __init__(self, hostname, bridge_passwd):
		self.hostname = hostname
		self.auth = aiohttp.BasicAuth('admin', bridge_passwd)
		self.smlframe = None

	async def getMeterSMLFrame(self):
		url = 'http://%s/data.json?node_id=1' % (self.hostname)

		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
			async with client.get(url, auth=self.auth) as resp:
				if resp.status != 200:
					print ('HTTP Error %d while querying %s' % (resp.status, url))
					return None
				self.smlframe = await resp.read()
				return self.smlframe

		print ('LocalTibberQueryAsync: Unexpected HTTP connect error')

		return None

	def extractPowerReading(self, smlframe=None):
		"""
		Extract net active power reading from SML frame.
		The reading is a 32-bit Signed Int.

		One could in principle properly decode the entire SML frame using
		some library/package. However, it seems energy meters (or at least
		the Landis+Gyr E220) use a fixed SML frame format, no varying fields.

		Hence it suffices to "decode" just the 32-bit (4 byte) portion
		of the SML binary data that contains the power reading. The location
		likely depends on the meter model.
		"""

		offset = 12*16 + 4 + 8  # works for one type of Landis Gyr E220

		if not smlframe:
			smlframe = self.smlframe

		if smlframe and len(smlframe) >= (offset + 4):
			P_Watts = struct.unpack(">l", smlframe[offset:(offset+4)])[0]
			return P_Watts
		else:
			return 0


	def extractEnergyReading(self, smlframe=None):

		offset = 10*16 + 8 + 8  # works for one type of Landis Gyr E220

		if not smlframe:
			smlframe = self.smlframe

		if smlframe and len(smlframe) >= (offset + 8):
			E_Wh = float( struct.unpack(">Q", smlframe[offset:(offset+8)])[0] ) / 10
			return E_Wh
		else:
			return 0
