#!/usr/bin/python3

import asyncio
from aioinflux import InfluxDBClient
from aioinflux import iterpoints

class LocalInfluxdbQueryAsync:

	def __init__(self, dbhost='localhost', dbport=8086, dbname='controllers'):
		self.dbclient = InfluxDBClient(host=dbhost, port=dbport, username='', password='', db=dbname, mode='async')


	def _getResultFloat(self, resultset):
		pts = list(iterpoints(resultset, lambda *x, meta: dict(zip(meta['columns'], x))))
		try:
			if len(pts) > 0:
				r = pts[-1]
			return float(r['last'])
		except:
			return -1

	async def queryFloat(self, qry):
		V = await self.dbclient.query(qry)
		return self._getResultFloat(V)


	async def getBatteryVoltage(self):
		qry = "SELECT last(value) FROM autogen.solar WHERE (topic::tag = 'solar/data/Battery_Voltage') and time >= now() - 5m fill(null)"
		return await self.queryFloat(qry)


	async def getBatteryPercentage(self):
		qry = "SELECT last(value) FROM autogen.solar WHERE (topic::tag = 'solar/data/Percent_Remain') and time >= now() - 5m fill(null)"
		return await self.queryFloat(qry)


if __name__ == '__main__':

	async def main():
		db = LocalInfluxdbQuery()
		out = await asyncio.gather(*[db.getBatteryVoltage(), db.getBatteryPercentage()])
		print('Battery Voltage: %.2f V' % (out[0]))
		print('Battery Charged: %.1f %%' % (out[1]))

	asyncio.run(main())

