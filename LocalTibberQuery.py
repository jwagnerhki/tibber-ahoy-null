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
# Steps to enable it are explained on other web sites,
# here a copy in brief:
#   1) configure your Tibber Pulse normally via App, pair with Tibber
#   2) note down the typ. 8-letter password (XXXX-XXXX) found printed
#      on the Tibber Bridge device near its QR code label
#   3) power cycle the Pulse, wait till a green light, power cycle again,
#      wait till blue light and then search for wireless network "Tibber Bridge"
#   4) connect to wifi network "Tibber Bridge", wifi password as in (2)
#   5) open the Bridge's page http://10.133.70.1/params/, user 'admin', password as in (2)
#   6) find the entry called 'webserver_force_enable',
#      change the value to 'true', then click the 'Save' button to store the setting
#   7) click the button 'Write settings to flash' or similar near the end of the page
#   8) open the page http://10.133.70.1/console/, enter 'reboot',
#      alternatively just manually power cycle the Bridge
#   9) after rebooting, the Bridge ought to be back on the
#      your normal wifi network that it was added to during step (1)
#   10) figure out the local IP or address of your Bridge on
#      the normal wifi network, then make sure you can connect
#      to the Bridge at http://<bridge ip on your wifi>/params/
#
# The local Bridge Web interface provides only the raw data (SML frames)
# as read directly from the grid energy meter. The Bridge does not decode
# the content of the SML frame.
#


import requests
import struct

class LocalTibberQuery:

	def __init__(self, hostname, bridge_passwd):
		self.hostname = hostname
		self.auth = requests.auth.HTTPBasicAuth('admin', bridge_passwd)
		self.smlframe = None

	def getMeterSMLFrame(self):
		url = 'http://%s/data.json?node_id=1' % (self.hostname)

		try:
			r = requests.get(url, auth=self.auth, timeout=5)
		except requests.ConnectionError as e:
			print(e)
			return None
		except requests.exceptions.ReadTimeout as e:
			print(e)
			return None

		if (r.status_code != 200):
			print ('HTTP Error %d while querying %s' % (r.status_code, url))
			return None

		self.smlframe = r.content

		return r.content


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
