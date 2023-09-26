#!/usr/bin/python3

from influxdb import InfluxDBClient
import time
import datetime
import calendar

dbhost = "localhost"
dbport = 8086


def getYieldOfDay(db, year=2023, month=1, day=1):

	t_grouping_sec = 20

	template_AC_W = "SELECT mean(value) FROM autogen.solar WHERE (topic::tag = 'solar/data/Steca_Load_W') "
	template_AC_W += "AND time >= '%s' and time < '%s' + 1d "
	template_AC_W += "GROUP BY time(%ds) fill(null)"

	datestr = '%d-%02d-%02d' % (year, month, day)
	q_AC_W = template_AC_W % (datestr, datestr, t_grouping_sec)
	# print(q_AC_W)

	try:
		ac_load = db.query(q_AC_W)
		pts = list(ac_load.get_points())
	except influxdb.exceptions.InfluxDBClientError as cli_err:
		pts = [{'mean':None}]
		print(cli_err)
		return 0.0

	vals = [pt['mean'] if  pt['mean'] is not None else 0 for pt in pts]

	E_Ws = sum(vals) * t_grouping_sec
	E_kWh = 1e-3 * E_Ws * (1 / 3600.0)

	if E_kWh > 0:
		print('%s  %.2f kWh' % (datestr, E_kWh))

	return E_kWh


def getYieldOfMonth(db, year=2023, month=1, start_day=1):

	E_kWh_sum = 0
	metered_days = 0
	unmetered_days = 0

	daysInMonth = calendar.monthrange(year,month)[1]

	for daynr in range(start_day, daysInMonth):
		# NB: loop ends at daynr = end_day|daysInMonth - 1, since Influx query covers daynr to daynr+1d

		E_kWh = getYieldOfDay(db, year, month, daynr)
		if E_kWh > 0:
			E_kWh_sum += E_kWh
			metered_days += 1
		else:
			unmetered_days += 1

	print('During %d-%02d the inverter was active on %d days, idle on %d days, total yield %.2f kWh' % (year, month, metered_days, unmetered_days, E_kWh_sum))

	return E_kWh_sum


def queryLatestTotal(db):

	query = "SELECT last(value) from derived where (topic = 'Steca_YieldTotal')"
	latest = db.query(query)

	pts = list(latest.get_points())
	if len(pts) <= 0:
		return {'last':0.0, 'time':'0'}

	vals = pts[-1]
	dtime = datetime.datetime.strptime(vals['time'], '%Y-%m-%dT%H:%M:%SZ')
	data = vals['last']

	return dtime, data


def writeLatestTotal(db, total_kWh):

	Tnow = datetime.datetime.utcnow()
	tstamp = Tnow.strftime('%Y-%m-%dT%H:%M:%SZ')

	datapoint = [{"measurement":"derived", "time":tstamp, "fields":{'topic':'Steca_YieldTotal', 'value':total_kWh}}]

	db.write_points(datapoint)



db = InfluxDBClient(dbhost, dbport, '', '', 'controllers')


E_timestamp, E_kWh = queryLatestTotal(db)
print('Latest reading  %.2f kWh  stored on UT %s' % (E_kWh, E_timestamp))

new_days = 0
next_timestamp = E_timestamp.date() + datetime.timedelta(days=1)

now = datetime.datetime.utcnow()
if now.hour >= 20:
	# Include data of "today" only if already close to midnight,
	# else postpone adding "todays" data until a later time
	ending_date = now.date()
else:
	ending_date = now.date() + datetime.timedelta(days=-1)

while next_timestamp <= ending_date:

	E_day_kWh = getYieldOfDay(db, next_timestamp.year, next_timestamp.month, next_timestamp.day)
	if E_day_kWh > 0:
		new_days += 1
		E_kWh += E_day_kWh

	next_timestamp = next_timestamp + datetime.timedelta(days=1)

if new_days > 0:

	print("Updated energy reading by %d new days for a total of %.2f kWh" % (new_days, E_kWh))

	writeLatestTotal(db, E_kWh)
