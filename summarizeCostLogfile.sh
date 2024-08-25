#!/bin/bash

logfile=~/log/solar-cost-yield.log

echo ""
echo -n "From "
head -1 $logfile | cut -f1 -d" " -z
echo -n " to "
tail -1 $logfile | cut -f1 -d" " -z
echo ""
echo ""

echo -n "Not billed (self-consumed): € "
cut -f7 -d" " $logfile | paste -sd+ | bc
echo -n "Billed i.e. grid imported:  € "
cut -f3 -d" " $logfile | paste -sd+ | bc
echo -n "Donated i.e. exported free: € "
cut -f11 -d" " $logfile | paste -sd+ | bc
echo ""

