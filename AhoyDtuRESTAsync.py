#!/usr/bin/python3 -u
#
# AhoyDTU REST API
#
#    http://<hostname of your AhoyDTU>/api/
#    http://<ahoydtu>/api/inverter/list    - list of configured inverters and their Serial#
#    http://<ahoydtu>/api/index            - reachability and 'cur_pwr' of the above inverters
#    http://<ahoydtu>/api/live             - measurement point names and units of ch0 (AC) and ch1..n (PV)
#    http://<ahoydtu>/api/inverter/id/<nr> - measurement point values (AC and PV(s)), active power limit 'power_limit_read'
#
# Note: AhoyDTU firmware versions up to 0.7.26 had http://<ahoydtu>/api/record/live
# which had measurement point names, values, units. This was deprecated in later
# versions of the Ahoy REST API, see https://github.com/lumapu/ahoy/issues/1185
#
# Now measurement names and units are read once at creation of AhoyDtuREST().
# Live values are read from /api/inverter/id/<nr> and parsed.
# There is a field 'ts_last_success' which contains the Unix timestamp. Todo: use it?
#

import requests

import asyncio
import aiohttp

import threading
import time, datetime
import json

class AhoyDtuRESTAsync(threading.Thread):

	def __init__(self, host, inverter=0):

		threading.Thread.__init__(self)
		self.hostname = str(host)
		self.inverter = int(inverter)
		self.runnable = self.queryLoop
		self.daemon = True

		self.max_chan = 1 + 8  # todo: from http://<ahoydtu>/api/inverter/list JSON get max(inverter[]['channels']) + 1
		self.AC_CHAN = 0

		self.readings = {}
		self.last_update = datetime.datetime.utcnow()

		url = 'http://%s/api/live' % (self.hostname)
		j = self._getJSON(url)

		self.field_names = [[]] * self.max_chan
		self.field_units = [[]] * self.max_chan
		self.field_names[0] = j['ch0_fld_names']
		self.field_units[0] = j['ch0_fld_units']
		for n in range(1, self.max_chan):
			self.field_names[n] = j['fld_names']
			self.field_units[n] = j['fld_units']


	def run(self):

		self.runnable()


	async def queryLoop(self):
		"""
		Inverter status polling loop - for debug purposes.
		"""
		while True:
			invdata = await self.readInverterData()
			plimit = self.getActiveLimit(invdata)
			print('== Inverter %d - power limit %d Watt ==' % (self.inverter, plimit))
			print('Updated     %s' % (str(self.last_update)))
			print('YieldTotal  %s' % (self.getChannelMeasurement(invdata, 'YieldTotal', self.AC_CHAN)))
			print('YieldDay    %s' % (self.getChannelMeasurement(invdata, 'YieldDay', self.AC_CHAN)))
			for ch in range(len(invdata['ch'])):
				self.getChannelMeasurements(invdata, ch, True)
			await asyncio.sleep(5)


	def _getJSON(self, url):

		try:
			r = requests.get(url, timeout=5)
		except requests.ConnectionError as e:
			print(e)
			return None
		except requests.exceptions.ReadTimeout as e:
			print(e)
			return None

		if (r.status_code != 200):
			print ('HTTP Error %d while querying %s' % (r.status_code, url))
			return None

		try:
			j = r.json()
		except json.decoder.JSONDecodeError as e:
			print ('JSON response decode error: %s' % (str(e)))
			return None

		if not j:
			print("Unexpected reply on %s: %s - %s" % (url, str(r), str(j)))
			return None

		return j


	async def _getJSON_async(self, url):

		try:
			nokeepalive = aiohttp.TCPConnector(force_close=True)
			async with aiohttp.ClientSession(connector=nokeepalive, timeout=aiohttp.ClientTimeout(total=2)) as client:
				async with client.get(url) as resp:
					if resp.status != 200:
						print ('HTTP Error %d while querying %s' % (resp.status, url))
						return None
					j = await resp.json()

					if not j:
						print("Unexpected reply on %s: %s - %s" % (url, str(r), str(j)))
						return None

					return j
		except aiohttp.ServerDisconnectedError:
			print('Unexpected _getJSON(%s) outcome - server disconnected' % (url))
			return None
		except Exception as e:
			print('Unexpected _getJSON(%s) outcome - exception: %s' % (url, str(e)))
			return None

		print('Unexpected _getJSON(%s) outcome, maybe could not connect' % (url))

		return None


	async def readInverterData(self):

		url = 'http://%s/api/inverter/id/%d' % (self.hostname, self.inverter)
		j = await self._getJSON_async(url)
		if not j:
			return None

		self.last_update = self.getDataTimestamp(j)

		return j


	def getDataTimestamp(self, invdata):

		unixtime = float(invdata['ts_last_success'])
		dtime = datetime.datetime.fromtimestamp(unixtime)

		return dtime


	def getChannelMeasurements(self, invdata, channel=0, verbose=False):

		if channel < 0 or channel > len(invdata['ch']):
			return None

		if verbose:
			print("Channel %d '%s'" % (channel, invdata['ch_name'][channel]))
			for chfld in range (len(invdata['ch'][channel])):
				print('    ', self.field_names[channel][chfld], invdata['ch'][channel][chfld], self.field_units[channel][chfld])

		m = dict(zip(self.field_names[channel], invdata['ch'][channel]))
		return m


	def getChannelMeasurement(self, invdata, measurement_name, channel=0, verbose=False):

		try:
			i = self.field_names[channel].index(measurement_name)
			return invdata['ch'][channel][i]
		except:
			return None


	def getActiveLimit(self, invdata):

		if 'power_limit_read' in invdata:
			return float(invdata['power_limit_read'])
		return 0


if __name__ == '__main__':

	async def main():
		dtu = AhoyDtuRESTAsync('192.168.0.52', inverter=1)
		await dtu.queryLoop()

	asyncio.run(main())
