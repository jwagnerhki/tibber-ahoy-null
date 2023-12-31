#!/usr/bin/python3 -u
#
# Simple polling loop that
#  1) queries energy meter net power reading via local page of the Tibber Bridge,
#  2) queries the active power output of for now one single Hoymiles microinverter,
#  3) adjusts the non-persistent power limit of the Hoymiles microinverter by
#     3.1   reducing inverter output power if too much flows into the grid
#     3.2   increasing inverter output power to reduce draw from grid
#     3.3   keeping a minimum export flow into grid of 10 W (default)
#     3.4   adjustment steps are with granularity/hysteresis of 10 W (default)
#  4) different abs max inverter power limits are used depending on time of day
#  5) monitors microinverter DC input voltage and drops inverter output power to
#     near zero of DC voltage is too low (e.g. battery below some %charge level),
#     re-enables power control once DC returns to a good level (e.g. battery recharged)
#
#     For reference, voltage vs state of charge for 16-in-series LiFePo4 battery:
#     51.2V = 20% charged   52.0V = 40%   52.3V = 60%   53.1V = 80%
#
#     NB: A better method might be to query the battery management system (BMS),
#     they tend to keep track of battery SOC% based on energy (dis-)charge
#     over time - perhaps more accurate.
#

import asyncio
import aiohttp
import time, datetime
import requests
import subprocess
import sys

from AhoyDtuRESTAsync import AhoyDtuRESTAsync
from LocalTibberQueryAsync import LocalTibberQueryAsync
from LocalInfluxdbQueryAsync import LocalInfluxdbQueryAsync

## AhoyDTU device that is connected to the Hoymiles u-inverter
ahoydtu_host = "192.168.0.52"
ahoydtu_inverterId = 1            # cf. http://<ahoydtu_host>/api/inverter/list/ for list of connected inverters and their IDs

## Tibber Pulse/Bridge device
tibber_bridge_host = "192.168.0.14"
tibber_bridge_password = "XXXX-XXXX"  # code found printed on Tibber Bridge device, below QR tag

## Local Influxdb server that stores JK-BMS measurements incl. State-Of-Charge(%)
bms_db_host = "localhost"
bms_db_port = 8086
bms_db_database = "controllers"

## Remote MQTT with which to share Tibber power readings
mqtt_logger_host = "192.168.0.74"
mqtt_tibber_P_topic = "local_tibber/power"
mqtt_tibber_E_topic = "local_tibber/energy"

## Steca Solarix PLI-4800 AC input, controlled by a MyStrom wifi switch with a REST API
## with simple http get "http://[switch_ip]/relay?state=1" for AC ON, or state=0 for AC OFF
steca_ac_host = "192.168.0.44"

## Power control settings
# Power limits
inverter_day_max_power_W = 310    # Day time max power assist; Hoymiles HM-350, tested 350W, but inverter gets quite warm (>40C)
inverter_night_max_power_W = 310  # Night time max power assist
inverter_min_power_W = 5          # Minimum inverter output power
inverter_power_granularity_W = 5  # Minimum change of +- x Watt to apply, smaller changes are ignored and not sent to the inverter
settling_time_s = 10              # Approx. delay till DTU & Hoymiles have applied a requested power level change; esp8226 ~20sec, esp32 ~10sec
recheck_interval_s = 10           # Interval at which to query for new values

# Undervoltage shutdown/recovery
lfp_undervoltage = 51.3           # DC safety limit, turn off the inverter altogether then the input voltage drops to this level
lfp_recovery_voltage = 52.3       # DC recovery limit, restart inverter once undervoltage has cleared e.g. battery charged sufficiently
				  # Note, 16S LFP voltages approx.: 51.2V = 20%, 52.0 = 40%, 52.3 = 60%, 53.1 = 80% charged
lfp_min_SOC_percent = 20.0        # SOC safety limit, turn off inverter when remaining charge of battery drops to this level
lfp_recovery_SOC_percent = 30.0   # SOC recovery limit, restart after charged sufficiently _and_ lfp_recovery_voltage is met


def mqtt_submit(host, topic, value):

	cmd = ["/usr/bin/mosquitto_pub", "-h", host, "-t", topic, "-m", str(value)]

	if True:
		result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
		if len(result.stdout) > 1:
			print("  EXEC   ", " ".join(cmd))
			print("  STDOUT ", result.stdout)
	else:
		print("TODO ", " ".join(cmd))



def send_JSON(host, json):

	cmd = ["/usr/bin/curl", "-i", "-v", "-H", "Accept:application/json", "-H", "Content-Type:application/json", "-X", "POST"]
	cmd += ["--data", json, "http://%s/api/ctrl" % (host)]

	if True:
		result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
		print("  EXEC   ", " ".join(cmd))
		print("  STDOUT ", result.stdout)
	else:
		print("TODO ", " ".join(cmd))


def command_new_power(host, invId, P_Watt):

	json = '{"id":%u,"cmd":"limit_nonpersistent_absolute","val":%u}' % (int(invId), int(P_Watt))

	send_JSON(host, json)


def command_power_state(host, invId, powerEnabled=True):
	'''Turn the inverter power production on or off'''

	if powerEnabled:
		json = '{"id":%u,"cmd":"power","val":%u}' % (int(invId), 1)
	else:
		json = '{"id":%u,"cmd":"power","val":%u}' % (int(invId), 0)

	send_JSON(host, json)


async def query_steca_mystrom_on(host):

	ac_input_on = False
	url = 'http://%s/report' % (host)

	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
			async with client.get(url) as resp:
				if resp.status != 200:
					print ('Failed to query %s' % (url))
					return ac_input_on
				j = await resp.json()
				ac_input_on = (j['relay'] == True)
				return ac_input_on

	except Exception as e:
		print('Unexpected result of querying %s - exception: %s' % (url, str(e)))

	return ac_input_on



async def controlLoop():

	dtu = AhoyDtuRESTAsync(ahoydtu_host, inverter=ahoydtu_inverterId)
	meter = LocalTibberQueryAsync(tibber_bridge_host, tibber_bridge_password)
	bms = LocalInfluxdbQueryAsync(bms_db_host, bms_db_port, bms_db_database)

	T = datetime.datetime.utcnow()
	dtu_T, meter_T, prev_adjust_T = T, T, T
	dtu_P, meter_P, meter_E = 0, 0, 0

	hitUndervoltage = False
	dynamic_max_power_W = inverter_day_max_power_W

	# Make sure the inverter is on
	command_power_state(ahoydtu_host, ahoydtu_inverterId, powerEnabled=True)
	#sys.exit(0)

	# Power control loop
	while True:

		# Grab new data
		T = datetime.datetime.utcnow()
		Tloc = datetime.datetime.now()

		if Tloc.hour >= 8 and Tloc.hour <= 18:
			dynamic_max_power_W = inverter_day_max_power_W
		else:
			dynamic_max_power_W = inverter_night_max_power_W

		#timing0 = time.perf_counter()
		[invdata,gridsml,bmsVolt,bmsSOC,stecaCharge] = await asyncio.gather(*[dtu.getInverterReadings(),
			meter.getMeterSMLFrame(),
			bms.getBatteryVoltage(), bms.getBatteryPercentage(),
			query_steca_mystrom_on(steca_ac_host)
		])
		#dtiming = time.perf_counter() - timing0
		#print('Network wait time (ms):', 1e3*dtiming) # approx 150ms..250ms, vs non-async ~600ms

		print()
		print('Local time       : %s' % (str(Tloc)))

		print('Steca AC In      : %s' % ('ON' if stecaCharge else 'off'))

		if 'U_DC' in invdata and 'P_AC' in invdata and float(invdata['U_DC']) > 0:
			print('DC input voltage : %.2f V_dc' % (invdata['U_DC']))
			print('AC output power  : %.2f W_rms of max %d W' % (invdata['P_AC'], dynamic_max_power_W))
			dtu_T = T
			dtu_P = invdata['P_AC']
			dtu_V = float(invdata['U_DC'])
		else:
			dtu_V, dtu_P = 0.0, 0.0

		if bmsVolt > 0:
			print('Battery voltage  : %.2f V per BMS' % (bmsVolt))
		if bmsSOC > 0 or True:
			print('Battery remain   : %.0f %%' % (bmsSOC))


		if gridsml and len(gridsml) > 0:
			meter_T = T
			meter_P = meter.extractPowerReading(gridsml)
			meter_E = meter.extractEnergyReading(gridsml)
			print("Grid power       : %+d Watt" % (meter_P))
			print("Grid energy      : %.2f kWh" % (meter_E/1000))

			# Helper: share the grid meter reading over MQTT, since no
			# dedicated program does any querying and logging (for now)
			if mqtt_logger_host is not None:
				mqtt_submit(mqtt_logger_host, mqtt_tibber_P_topic, meter_P)
				mqtt_submit(mqtt_logger_host, mqtt_tibber_E_topic, int(meter_E))


		# Stop microinverter if Steca Solarix hybrid inverter AC-IN was
		# switched on (outside of this script) to charge battery esp.
		# at night during a minimal electricity cost hour (Tibber); no point
		# in microinverter feeding house via Solarix-internal battery charger...
		if stecaCharge:  # and ('P_AC' in invdata and float(invdata['P_AC']) > 0):
			print("Command power    : OFF due to Steca Solarix hybrid inverter charging battery from AC In")
			command_power_state(ahoydtu_host, ahoydtu_inverterId, powerEnabled=False)
			time.sleep(settling_time_s)
			continue

		# Check battery undervoltage & low charge remaining, and recovery from it
		if 'U_DC' in invdata and dtu_V > 0:
			#if dtu_V <= lfp_undervoltage:
			if dtu_V <= lfp_undervoltage or bmsSOC <= lfp_min_SOC_percent:
				hitUndervoltage = True
			elif dtu_V >= lfp_recovery_voltage and bmsSOC >= lfp_recovery_SOC_percent and not stecaCharge:
				hitUndervoltage = False

		# During undervoltage, shut down the u-inverter power production,
		# turn back on only after undervoltage condition has cleared
		if hitUndervoltage and 'P_AC' in invdata and float(invdata['P_AC']) > 0:
			print("Command power    : OFF due low battery, wait till %.2f V and %.0f %% charge" % (lfp_recovery_voltage,lfp_min_SOC_percent))
			command_power_state(ahoydtu_host, ahoydtu_inverterId, powerEnabled=False)
			time.sleep(settling_time_s)
			continue
		elif (not hitUndervoltage) and 'P_AC' in invdata and float(invdata['P_AC']) <= 0 and not stecaCharge:
			print("Command power    : ON due to recovery from earlier DC undervoltage or AC-Charge Priority")
			command_power_state(ahoydtu_host, ahoydtu_inverterId, powerEnabled=True)
			time.sleep(settling_time_s)
			continue


		# When DTU and Grid values are "fresh enough", inspect them,
		# and adjust inverter output power to get near zero energy export
		if abs((dtu_T - meter_T).total_seconds()) < recheck_interval_s/2:
			new_P = dtu_P + meter_P
			new_P = (new_P // inverter_power_granularity_W) * inverter_power_granularity_W
			new_P = new_P + inverter_power_granularity_W  # always feed some extra
			new_P = min(new_P, dynamic_max_power_W)
			new_P = max(new_P, inverter_min_power_W)

			#if hitUndervoltage:
			#	new_P = inverter_power_granularity_W
			#	print("DC Undervoltage  : fixing output to %d Watt until recovery" % (new_P))

			pdiff = new_P - dtu_P

			if abs(pdiff) > 2*inverter_power_granularity_W:
				# Large load change: slowly assist, or quickly back off
				if hitUndervoltage:
					print("Command power    : stay OFF due to DC undervoltage")
				elif (T - prev_adjust_T).total_seconds() > settling_time_s or pdiff < 0:
					print("Command power    : %d Watt" % (new_P))
					command_new_power(ahoydtu_host, ahoydtu_inverterId, new_P)
					prev_adjust_T = T
				else:
					print("Future cmd power : %d Watt" % (new_P))
		else:
			print('Not enough recent data in this interval, skipping adjustments')

		# Pause until the next iteration
		tsleep = recheck_interval_s - (datetime.datetime.utcnow() - T).seconds
		if tsleep > 0:
			print("Re-checking after: %d sec" % (tsleep))
			time.sleep(tsleep)


if __name__ == '__main__':

	while True:
		try:
			asyncio.run(controlLoop())
		except Exception as e:
			print('Main program ran into an exception: %s' % (str(e)))
			print('Plowing on, anyway...')
