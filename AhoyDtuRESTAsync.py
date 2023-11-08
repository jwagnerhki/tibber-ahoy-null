#!/usr/bin/python3 -u
#
# AhoyDTU REST API
#
#    http://<hostname of your AhoyDTU>/api/
#    http://ahoy.lan/api/inverter/list   - list of configured inverters
#    http://ahoy.lan/api/record/config   - power limits
#    http://ahoy.lan/api/record/live     - operating status in JSON 'inverter[]'
#
#    Under the live operating status fields, of interest are:
#      U_DC   - voltage from solar panel or battery as seen at input of inverter
#      P_AC   - output power to grid in Watt
#    Alas the values do not have any timestamp...
#
# Note: AhoyDTU firmware versions only up to 0.7.26.
# Later versions have removed half of the REST API,
# also cf https://github.com/lumapu/ahoy/issues/1185
#

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

		self.readings = {}
		self.last_update = datetime.datetime.utcnow()

	def run(self):

		self.runnable()


	def queryLoop(self):
		"""
		Inverter status polling loop - for debug purposes.
		TODO: modify so fill data into a Queue object shared with potential consumer
		"""

		while True:
			ir = self.getInverterReadings()
			if 'U_DC' in ir and 'P_AC' in ir:
				self.readings = ir
				self.last_update = datetime.datetime.utcnow()
				print()
				print(self.last_update)
				print('Input voltage: %6.2f V' % (ir['U_DC']))
				print('Output power : %6.2f W' % (ir['P_AC']))

			il = self.getActiveLimits()
			if 'active_PowerLimit' in il:
				print('Power limit  : %.2f%%' % (il['active_PowerLimit']))

			time.sleep(5)


	async def _getJSON(self, url):

		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
			async with client.get(url) as resp:
				if resp.status != 200:
					print ('HTTP Error %d while querying %s' % (resp.status, url))
					return None
				j = await resp.json()

				if not j:
					print("Unexpected reply on %s: %s - %s" % (url, str(r), str(j)))
					return None

				return j

		print('Unexpected _getJSON(%s) outcome, maybe could not connect' % (url))

		return None


	async def _getInverterJSON(self, url):

		j = await self._getJSON(url)
		if not j:
			return None

		if 'inverter' not in j:
			print("Unexpected reply on %s without 'inverter' field: %s" % (url, str(j)))
			return None

		try:
			inv = j['inverter'][self.inverter]
		except:
			print("Inverter list '%s' did not contain inverter nr %d" % (str(j['inverter']),self.inverter))
			inv = None

		return inv


	async def _getInverterJSONFields(self, url):

		fielddata = {}

		inv = await self._getInverterJSON(url)
		if not inv:
			return fielddata

		for element in inv:
			if 'val' in element:
				fielddata[element['fld']] = float(element['val'])
			else:
				print('DTU REST API unexpected returned element %s' % (str(element)))

		return fielddata


	async def getInverterReadings(self):

		url = 'http://%s/api/record/live' % (self.hostname)

		data = await self._getInverterJSONFields(url)

		return data


	async def getActiveLimits(self):

		url = 'http://%s/api/record/config' % (self.hostname)

		data = await self._getInverterJSONFields(url)

		return data

