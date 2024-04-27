#!/usr/bin/python3

import influxdb
from influxdb import InfluxDBClient

import tibber

import time
import datetime
import calendar

tibber_token = "---api token---"
ql_timezone = "tz('Europe/Berlin')"
influxdb1host = "localhost"
influxdb1port = 8086


def getTibberHourlyPriceToday():

	tibber_account = tibber.Account(tibber_token)
	tibber_home = tibber_account.homes[0]
	tibber_sub = tibber_home.current_subscription
	price_data = tibber_sub.price_info
	#for prices in price_data.today:
	#	print(prices.starts_at, prices.total)
	cost_eur_kWh = [priceinfo.total for priceinfo in price_data.today]
	if len(cost_eur_kWh) != 24:
		print("Tibber API: unexpected non-24 length of Account::homes[0]::current_subscription::price_info::today->[%d items] = %s" % (len(cost_eur_kWh), str(cost_eur_kWh)))

	return cost_eur_kWh


def getOffgridHourlyOutput(db, year=2023, month=1, day=1):

	template_AC_W = "SELECT mean(value) FROM autogen.solar WHERE (topic::tag = 'solar/data/Steca_Load_W') "
	template_AC_W += "AND time >= '%s' and time < '%s' + 1d "
	template_AC_W += "GROUP BY time(1h) fill(0) " + ql_timezone

	datestr = '%d-%02d-%02d' % (year, month, day)
	q_AC_W = template_AC_W % (datestr, datestr)
	try:
		ac_load = db.query(q_AC_W)
		pts = list(ac_load.get_points())
	except influxdb1.exceptions.Influxdb1ClientError as cli_err:
		pts = [{'mean':0}]
		print(cli_err)
		return 0.0

	E_kWh = [1e-3*float(pt['mean']) if pt['mean'] is not None else 0 for pt in pts]

	return E_kWh


def getGridsupportHourlyOutput(db, year=2023, month=1, day=1):

	template_AC_W = "SELECT mean(value) FROM autogen.mqtt_consumer WHERE (topic::tag = 'ahoy/hm350night/ch0/P_AC') "
	template_AC_W += "AND time >= '%s' and time < '%s' + 1d "
	template_AC_W += "GROUP BY time(1h) fill(0) " + ql_timezone

	datestr = '%d-%02d-%02d' % (year, month, day)
	q_AC_W = template_AC_W % (datestr, datestr)
	try:
		ac_load = db.query(q_AC_W)
		pts = list(ac_load.get_points())
	except influxdb1.exceptions.Influxdb1ClientError as cli_err:
		pts = [{'mean':0}]
		print(cli_err)
		return 0.0

	E_kWh = [1e-3*float(pt['mean']) if pt['mean'] is not None else 0 for pt in pts]

	return E_kWh


def getBalkonsolarHourlyOutput(db, year=2023, month=1, day=1):

	template_AC_W = "SELECT mean(value) FROM autogen.mqtt_consumer WHERE (topic::tag = 'ahoy/hm350/ch0/P_AC') "
	template_AC_W += "AND time >= '%s' and time < '%s' + 1d "
	template_AC_W += "GROUP BY time(1h) fill(0) " + ql_timezone

	datestr = '%d-%02d-%02d' % (year, month, day)
	q_AC_W = template_AC_W % (datestr, datestr)
	try:
		ac_load = db.query(q_AC_W)
		pts = list(ac_load.get_points())
	except influxdb1.exceptions.Influxdb1ClientError as cli_err:
		pts = [{'mean':0}]
		print(cli_err)
		return 0.0

	E_kWh = [1e-3*float(pt['mean']) if pt['mean'] is not None else 0 for pt in pts]

	return E_kWh


def getHouseHourlyDraw(db, year=2023, month=1, day=1):

	template_AC_W = "SELECT mean(value) FROM autogen.local_tibber WHERE (topic::tag = 'local_tibber/power') "
	template_AC_W += "AND time >= '%s' and time < '%s' + 1d "
	template_AC_W += "GROUP BY time(1m) fill(0) " + ql_timezone

	datestr = '%d-%02d-%02d' % (year, month, day)
	q_AC_W = template_AC_W % (datestr, datestr)
	try:
		ac_load = db.query(q_AC_W)
		pts = list(ac_load.get_points())
	except influxdb1.exceptions.Influxdb1ClientError as cli_err:
		pts = [{'mean':0}]
		print(cli_err)
		return 0.0

	E_Wmin = [float(pt['mean']) if pt['mean'] is not None else 0 for pt in pts]
	E_Wmin_import = [E if E>0 else 0 for E in E_Wmin]
	E_Wmin_export = [-E if E<0 else 0 for E in E_Wmin]

	E_kWh_import = [0] * 24
	E_kWh_export = [0] * 24
	h = 0
	while h < 24:
		istart = h*60
		istop = min(istart + 60, len(E_Wmin_import))
		if istart >= len(E_Wmin_import):
			break
		E_kWh_import[h] = sum(E_Wmin_import[istart:istop]) / 60.0e3
		E_kWh_export[h] = sum(E_Wmin_export[istart:istop]) / 60.0e3
		h += 1

	return (E_kWh_import, E_kWh_export)


def floatlistStr(floats):
	return ' '.join(['%.2f' % f for f in floats])


def dotProduct(a, b):
	if len(a) != len(b):
		print("Error: non-identical vector lenghts, a=%s b=%s" % (str(a),str(b)))
		return 0
	return sum(ab[0] * ab[1] for ab in zip(a, b))


def writeEndOfDayData(db, imported_kWh, imported_cost, selfconsumed_kWh, selfconsumed_costsaved):
	Tnow = datetime.datetime.now()
	Tnow_ut = datetime.datetime.utcnow()
	tstamp = Tnow_ut.strftime('%Y-%m-%dT%H:%M:%SZ')

	datapoints = [{"measurement":"derived", "time":tstamp, "fields":{'topic':'imported_today_kWh', 'value':imported_kWh}}]
	datapoints += [{"measurement":"derived", "time":tstamp, "fields":{'topic':'imported_today_cost', 'value':imported_cost}}]
	datapoints += [{"measurement":"derived", "time":tstamp, "fields":{'topic':'selfconsumed_today_kWh', 'value':selfconsumed_kWh}}]
	datapoints += [{"measurement":"derived", "time":tstamp, "fields":{'topic':'selfconsumed_today_cost', 'value':selfconsumed_costsaved}}]

	if Tnow.hour < 23:
		print('DEBUG: not actually writing values, not after 23:00 yet')
		print(datapoints)
	else:
		print(datapoints)
		#db.write_points(datapoints)



db_steca = InfluxDBClient(influxdb1host, influxdb1port, '', '', 'controllers')
db_hoymiles = InfluxDBClient(influxdb1host, influxdb1port, '', '', 'hoymiles350')
db_tibber = InfluxDBClient(influxdb1host, influxdb1port, '', '', 'sensors')

now = datetime.datetime.now()

offgrid_hourlyE = getOffgridHourlyOutput(db_steca, now.year, now.month, now.day)
ongrid_hourlyE = getBalkonsolarHourlyOutput(db_hoymiles, now.year, now.month, now.day)
gridsupport_hourlyE = getGridsupportHourlyOutput(db_hoymiles, now.year, now.month, now.day)
(house_hourlyE_import, house_hourlyE_export) = getHouseHourlyDraw(db_tibber, now.year, now.month, now.day)

tibber_price_hourly = getTibberHourlyPriceToday()

saved_offgrid = dotProduct(tibber_price_hourly, offgrid_hourlyE)
saved_ongrid = dotProduct(tibber_price_hourly, ongrid_hourlyE)
saved_gridsupport = dotProduct(tibber_price_hourly, gridsupport_hourlyE)
saved_total = saved_offgrid + saved_ongrid + saved_gridsupport
lost_export = dotProduct(tibber_price_hourly, house_hourlyE_export)
cost_import = dotProduct(tibber_price_hourly, house_hourlyE_import)

total_self_consumption = sum(offgrid_hourlyE) + sum(ongrid_hourlyE) + sum(gridsupport_hourlyE)
total_imported = sum(house_hourlyE_import)

autarcy = 100.0 * total_self_consumption / (total_self_consumption + total_imported)

print("Off-grid Output     : %.2f kWh, %.2f €" % (sum(offgrid_hourlyE), saved_offgrid))
print("On-grid Output      : %.2f kWh, %.2f €" % (sum(ongrid_hourlyE), saved_ongrid))
print("Grid Support Output : %.2f kWh, %.2f €" % (sum(gridsupport_hourlyE), saved_gridsupport))
print("Generated Consumed  : %.2f kWh, %.2f €" % (total_self_consumption, saved_total))
print("Grid Export (lost)  : %.2f kWh, %.2f €" % (sum(house_hourlyE_export), lost_export))
print("Grid Import (paid)  : %.2f kWh, %.2f €" % (sum(house_hourlyE_import), cost_import))
print("------------------------------------------")
print("Cost %.2f €  Saved %.2f €  Missed %.2f €" % (cost_import, saved_total, lost_export))
print("Autarcy %.0f %%" % (autarcy))

writeEndOfDayData(db_steca, total_imported, cost_import, total_self_consumption, saved_total)

