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

import time, datetime
import subprocess

from AhoyDtuREST import AhoyDtuREST
from LocalTibberQuery import LocalTibberQuery

tibber_bridge_host = "192.168.0.14"
tibber_bridge_password = "XXXX-XXXX"  # code found printed on Tibber Bridge device, below QR tag

mqtt_logger_host = "192.168.0.74"
mqtt_tibber_P_topic = "local_tibber/power"
mqtt_tibber_E_topic = "local_tibber/energy"

ahoydtu_host = "192.168.0.52"
ahoydtu_inverterId = 1            # cf. http://<ahoydtu_host>/api/inverter/list/ for list of connected inverters and their IDs

inverter_day_max_power_W = 330    # Hoymiles HM-350, but also, consider max battery kWh (TODO: battery voltage limit to shut down inverter early!)
                                  # Tested: can set 355W, but then inverter gets quite warm (40C)
inverter_night_max_power_W = 180  # Night time reduced max power assist cap
inverter_min_power_W = 10         # Minimum inverter output power to always maintain while DC voltage input level is good
inverter_power_granularity_W = 5  # Minimum change of +- x Watt to apply, smaller changes are ignored and not sent to the inverter

settling_time_s = 10              # Approx. delay till DTU & Hoymiles have applied a requested power level change; esp8226 ~20sec, esp32 ~10sec

lfp_undervoltage = 51.4           # DC safety limit, reduce inverter output power to minimum when DC input voltage drops to this level
lfp_recovery_voltage = 53.2       # DC recovery limit, restart operating after undervoltage has cleared e.g. battery charged sufficiently




def mqtt_submit(host, topic, P_Watt):

	cmd = ["/usr/bin/mosquitto_pub", "-h", host, "-t", topic, "-m", str(P_Watt)]

	if True:
		result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
		if len(result.stdout) > 1:
			print("  EXEC   ", " ".join(cmd))
			print("  STDOUT ", result.stdout)
	else:
		print("TODO ", " ".join(cmd))



def command_new_power(host, invId, P_Watt):

	json = '{"id":%u,"cmd":"limit_nonpersistent_absolute","val":%u}' % (int(invId), int(P_Watt))
	cmd = ["/usr/bin/curl", "-i", "-v", "-H", "Accept:application/json", "-H", "Content-Type:application/json", "-X", "POST"]
	cmd += ["--data", json, "http://%s/api/ctrl" % (host)]

	if True:
		result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
		print("  EXEC   ", " ".join(cmd))
		print("  STDOUT ", result.stdout)
	else:
		print("TODO ", " ".join(cmd))



dtu = AhoyDtuREST(ahoydtu_host, inverter=ahoydtu_inverterId)
meter = LocalTibberQuery(tibber_bridge_host, tibber_bridge_password)

T = datetime.datetime.utcnow()
dtu_T, meter_T, prev_adjust_T = T, T, T
dtu_P, meter_P = 0, 0

hitUndervoltage = False
dynamic_max_power_W = inverter_day_max_power_W

while True:

	print()

	T = datetime.datetime.utcnow()
	Tloc = datetime.datetime.now()

	if Tloc.hour >= 8 and Tloc.hour <= 18:
		dynamic_max_power_W = inverter_day_max_power_W
	else:
		dynamic_max_power_W = inverter_night_max_power_W

	invpwr = dtu.getInverterReadings()
	gridsml = meter.getMeterSMLFrame()

	print('Local time       : ', Tloc)

	if 'U_DC' in invpwr and 'P_AC' in invpwr and float(invpwr['U_DC']) > 0:
		print('DC input voltage : %6.2f V_dc' % (invpwr['U_DC']))
		print('AC output power  : %6.2f W_rms of max %d W' % (invpwr['P_AC'], dynamic_max_power_W))
		dtu_T = T
		dtu_P = invpwr['P_AC']

		if invpwr['U_DC'] <= lfp_undervoltage:
			hitUndervoltage = True
		elif invpwr['U_DC'] >= lfp_recovery_voltage:
			hitUndervoltage = False

	if gridsml and len(gridsml) > 0:
		pwr = meter.extractPowerReading(gridsml)
		print("Grid power       : %+d Watt" % (pwr))
		meter_T = T
		meter_P = pwr

		mqtt_submit(mqtt_logger_host, mqtt_tibber_P_topic, pwr)

	# When DTU and Grid values are "fresh enough", inspect them.
	if abs((dtu_T - meter_T).total_seconds()) < 5:
		new_P = dtu_P + meter_P
		new_P = (new_P // inverter_power_granularity_W) * inverter_power_granularity_W
		new_P = new_P + inverter_power_granularity_W  # always feed some extra
		new_P = min(new_P, dynamic_max_power_W)
		new_P = max(new_P, inverter_min_power_W)

		if hitUndervoltage:
			new_P = inverter_power_granularity_W
			print("DC Undervoltage  : fixing output to %d Watt until recovery" % (new_P))

		pdiff = new_P - dtu_P

		if abs(pdiff) > 2*inverter_power_granularity_W:
			# Large load change: slowly assist, or quickly back off
			if (T - prev_adjust_T).total_seconds() > settling_time_s or pdiff < 0:
				print("Command power    : %d Watt" % (new_P))
				command_new_power(ahoydtu_host, ahoydtu_inverterId, new_P)
				prev_adjust_T = T
			else:
				print("Future cmd power : %d Watt" % (new_P))

	time.sleep(2)
